"""Daily pipeline: for each search term: scrape -> skip already-seen -> classify -> append to CSVs.

Outputs (in output_dir):
  jobs_YYYY-MM-DD.csv  today's new, categorised jobs
  all_jobs.csv         running history of everything (used by the frontend)
"""
from datetime import date
from pathlib import Path
import logging
import re
import time

import pandas as pd
import yaml
from tqdm import tqdm

from classify import Classifier
from scrape import dedupe, iter_searches, scrape_term

BASE = Path(__file__).parent
COLUMNS = [
    "date_found", "category", "field", "relevance", "german_required", "title", "company",
    "location", "site", "date_posted", "job_url", "job_url_direct", "reason", "search_term",
]


def main():
    cfg = yaml.safe_load((BASE / "config.yaml").read_text(encoding="utf-8"))
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

    logger.info("Starting job scraper pipeline...")

    today_path = out_dir / f"jobs_{date.today().isoformat()}.csv"
    clf = Classifier(cfg)
    reject = [re.compile(p, re.I) for p in cfg.get("reject_title_patterns", [])]

    # Already-known jobs: history + today's file (dedupe also on title|company)
    seen_urls, seen_keys = set(), set()
    for path in (all_path, today_path):
        if path.exists():
            old = pd.read_csv(path, usecols=["job_url", "title", "company"])
            seen_urls |= set(old["job_url"])
            seen_keys |= set(_key(old))

    total = 0
    for bucket, term in iter_searches(cfg):
        logger.info(f"Searching: {bucket:16s} | term: {term}")
        try:
            df = scrape_term(cfg, bucket, term)
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

            labels = [
                clf.classify(r.title, r.company, r.location, r.description)
                for r in tqdm(df.itertuples(), total=len(df), desc=f"classify '{term}'")
            ]
            df = pd.concat([df, pd.DataFrame(labels)], axis=1)
            df["date_found"] = date.today().isoformat()
            seen_urls |= set(df["job_url"])
            seen_keys |= set(_key(df))

            df = df[~df["category"].isin(cfg.get("drop_categories", []))]
            df = df.reindex(columns=COLUMNS).sort_values("relevance", ascending=False)
            # Saved immediately: a crash or rate limit later never loses finished searches
            for path in (today_path, all_path):
                df.to_csv(path, mode="a", header=not path.exists(), index=False, encoding="utf-8-sig")
            total += len(df)
            logger.info(f"saved {len(df)} jobs from '{term}' (run total {total})")
        except Exception as e:
            logger.error(f"Search '{term}' failed, continuing: {e}")
        time.sleep(cfg.get("sleep_between_searches", 5))

    logger.info(f"Pipeline finished: {total} new jobs -> {today_path}")


def _key(df: pd.DataFrame) -> pd.Series:
    return df["title"].fillna("").str.lower().str.strip() + "|" + df["company"].fillna("").str.lower().str.strip()


if __name__ == "__main__":
    main()
