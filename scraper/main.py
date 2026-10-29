"""Daily pipeline: expire old jobs, then for each search term:
scrape -> skip already-seen -> title rules -> classify -> filter -> save (Postgres + CSV backup).

Outputs (in output_dir, a backup of what goes to the database):
  jobs_YYYY-MM-DD.csv  today's new, categorised jobs
  all_jobs.csv         running history
"""
import argparse
from datetime import date
from pathlib import Path
import logging
import re
import time

import pandas as pd
import yaml

from dotenv import load_dotenv

from classify import Classifier
from scrape import dedupe, iter_searches, scrape_term
from db import delete_expired, load_seen, save_jobs

BASE = Path(__file__).parent
COLUMNS = [
    "date_found", "category", "seniority", "field", "german_required", "work_mode", "title",
    "company", "location", "city", "site", "date_posted", "job_url", "job_url_direct",
    "stack", "hours_per_week", "summary", "search_term", "classified_by", "description",
]
load_dotenv(BASE.parent / ".env")  # GEMINI_API_KEY


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hours-old", type=int,
                        help="only jobs posted within this many hours (overrides config.yaml for this run)")
    parser.add_argument("--only", metavar="TEXT",
                        help="only run search terms containing TEXT (case-insensitive), e.g. --only thesis")
    parser.add_argument("--sources", metavar="LIST",
                        help="only these sources, comma-separated, e.g. --sources stepstone,xing "
                             "(names: jobspy, google, arbeitsagentur, extra_sites entries, company_boards, "
                             "berlinstartupjobs)")
    args = parser.parse_args()

    cfg = yaml.safe_load((BASE / "config.yaml").read_text(encoding="utf-8"))
    if args.hours_old:
        cfg["hours_old"] = args.hours_old
    out_dir = BASE / cfg["output_dir"]
    out_dir.mkdir(exist_ok=True)
    all_path = out_dir / "all_jobs.csv"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(out_dir / "run.log", encoding="utf-8"),
            logging.StreamHandler()
        ]
    )
    logger = logging.getLogger("main")

    logger.info(f"Starting job scraper pipeline (jobs from the last {cfg['hours_old']}h)...")

    try:
        removed = delete_expired(cfg.get("expire_days", 20))
        logger.info(f"Expired {removed} jobs older than {cfg.get('expire_days', 20)} days")
    except Exception as e:
        logger.warning(f"Could not expire old jobs: {e}")

    today_path = out_dir / f"jobs_{date.today().isoformat()}.csv"
    for path in (all_path, today_path):
        _rotate_if_old_format(path)
    clf = Classifier(cfg)
    reject = [re.compile(p, re.I) for p in cfg.get("reject_title_patterns", [])]

    # Already-known jobs: history + today's file (dedupe also on title|company)
    seen_urls, seen_keys = set(), set()
    for path in (all_path, today_path):
        if path.exists():
            old = pd.read_csv(path, usecols=["job_url", "title", "company"])
            seen_urls |= set(old["job_url"])
            seen_keys |= set(_key(old))
    try:  # the database is the full history; the CSVs may be partial
        old = load_seen()
        seen_urls |= set(old["job_url"])
        seen_keys |= set(_key(old))
    except Exception as e:
        logger.warning(f"Could not read seen jobs from DB, using CSVs only: {e}")
    logger.info(f"{len(seen_urls)} known jobs will be skipped")

    total = 0
    searches = [(b, t, o) for b, t, o in iter_searches(cfg)
                if not args.only or args.only.lower() in f"{b} {t}".lower()]
    if args.sources:
        wanted = [s.strip() for s in args.sources.split(",") if s.strip()]
        searches = [(b, t, [s for s in (o or wanted) if s in wanted]) for b, t, o in searches]
        searches = [(b, t, o) for b, t, o in searches if o]
    logger.info(f"{len(searches)} search terms")
    for bucket, term, only in searches:
        logger.info(f"Searching: {bucket:16s} | term: {term}")
        try:
            df = scrape_term(cfg, bucket, term, only=only, skip_urls=seen_urls)
            if df.empty:
                continue
            df = df[~df["job_url"].isin(seen_urls)]
            df = df[~_key(df).isin(seen_keys)]
            df = dedupe(df)
            if df.empty:
                logger.info("nothing new for this term")
                continue

            bad = df["title"].fillna("").map(lambda t: any(p.search(t) for p in reject))
            if bad.any():
                logger.info(f"hard-rejected {int(bad.sum())} by title rules: {df.loc[bad, 'title'].head(5).tolist()}")
                seen_urls |= set(df.loc[bad, "job_url"])  # don't reconsider them in later searches
                seen_keys |= set(_key(df[bad]))
                df = df[~bad].reset_index(drop=True)  # labels are concatenated by position
            if df.empty:
                continue

            t0 = time.monotonic()
            labels = clf.classify_many(
                [(r.title, r.company, r.location, r.description) for r in df.itertuples()]
            )
            logger.info(f"classified {len(df)} jobs in {time.monotonic() - t0:.0f}s ({clf.stats})")
            df = pd.concat([df, pd.DataFrame(labels)], axis=1)
            df["date_found"] = date.today().isoformat()
            seen_urls |= set(df["job_url"])
            seen_keys |= set(_key(df))

            drop = {
                "category": df["category"].isin(cfg.get("drop_categories", [])),
                "seniority": df["seniority"].isin(cfg.get("drop_seniority", [])),
                # non-tech roles; keyword-fallback rows have no real field, so don't judge them by it
                "field": df["field"].isin(cfg.get("drop_fields", [])) & (df["classified_by"] != "keyword"),
            }
            dropped = drop["category"] | drop["seniority"] | drop["field"]
            if dropped.any():
                why = ", ".join(f"{k} {int(v.sum())}" for k, v in drop.items() if v.any())
                logger.info(f"dropped {int(dropped.sum())} ({why}; categories: "
                            f"{df.loc[dropped, 'category'].value_counts().to_dict()})")
            df = df[~dropped].reindex(columns=COLUMNS)
            # Saved immediately: a crash or rate limit later never loses finished searches
            for path in (today_path, all_path):
                df.to_csv(path, mode="a", header=not path.exists(), index=False, encoding="utf-8-sig")
            try:
                save_jobs(df)
            except Exception as e:
                logger.error(f"DB save failed for '{term}' (CSV still written): {e}")
            total += len(df)
            logger.info(f"saved {len(df)} jobs from '{term}' (run total {total})")
        except Exception as e:
            logger.error(f"Search '{term}' failed, continuing: {e}")
        time.sleep(cfg.get("sleep_between_searches", 5))

    logger.info(f"Pipeline finished: {total} new jobs -> {today_path}")


def _rotate_if_old_format(path: Path):
    """The CSV columns changed with the profile-free classifier; appending new rows under the old
    header would misalign them, so an old-format file is renamed and a fresh one started."""
    if not path.exists():
        return
    header = path.open(encoding="utf-8-sig").readline().strip().split(",")
    if header != COLUMNS:
        path.rename(path.with_name(f"{path.stem}.old-format{path.suffix}"))


def _key(df: pd.DataFrame) -> pd.Series:
    return df["title"].fillna("").str.lower().str.strip() + "|" + df["company"].fillna("").str.lower().str.strip()


if __name__ == "__main__":
    main()
