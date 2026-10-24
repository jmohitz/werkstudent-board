"""Scraping layer: one function per search term, so the pipeline can classify + save after every search."""
import base64
import html
import json
import logging
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote_plus

import pandas as pd
import requests
from jobspy import scrape_jobs

logger = logging.getLogger("scrape")

BA_BASE = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4"
BA_HEADERS = {"X-API-Key": "jobboerse-jobsuche"}  # public key used by the official Jobsuche site/app


def iter_searches(cfg: dict):
    for bucket, terms in cfg["searches"].items():
        for term in terms:
            yield bucket, term


def _jobspy(cfg: dict, term: str, sites: list[str], **extra) -> pd.DataFrame:
    return scrape_jobs(
        site_name=sites,
        search_term=term,
        location=cfg["location"],
        results_wanted=cfg["results_per_search"],
        hours_old=cfg["hours_old"],
        country_indeed=cfg["country_indeed"],
        linkedin_fetch_description=cfg.get("linkedin_fetch_description", False),
        **extra,
    )


def _arbeitsagentur(cfg: dict, term: str) -> pd.DataFrame:
    ba = cfg.get("arbeitsagentur", {})
    days = max(1, round(cfg["hours_old"] / 24))
    r = requests.get(
        f"{BA_BASE}/jobs",
        params={"was": term, "wo": ba.get("location", "Deutschland"), "veroeffentlichtseit": days,
                "size": cfg["results_per_search"], "page": 1},
        headers=BA_HEADERS, timeout=30,
    )
    r.raise_for_status()
    rows = []
    for j in r.json().get("stellenangebote", []):
        refnr = j.get("refnr")
        if not refnr:
            continue
        desc = j.get("beruf", "")
        if ba.get("fetch_details", True):
            try:
                enc = base64.b64encode(refnr.encode()).decode()
                d = requests.get(f"{BA_BASE}/jobdetails/{enc}", headers=BA_HEADERS, timeout=30)
                d.raise_for_status()
                desc = d.json().get("stellenbeschreibung") or desc
            except Exception as e:
                logger.debug(f"BA details failed for {refnr}: {e}")
        ort = j.get("arbeitsort", {})
        rows.append({
            "title": j.get("titel"),
            "company": j.get("arbeitgeber"),
            "location": ", ".join(x for x in (ort.get("ort"), ort.get("region")) if x),
            "site": "arbeitsagentur",
            "date_posted": j.get("aktuelleVeroeffentlichungsdatum"),
            "job_url": f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}",
            "job_url_direct": j.get("externeUrl"),
            "description": desc,
        })
    return pd.DataFrame(rows)


# ---------- extra German job boards ----------
WEB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}


def _text(s: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _arbeitnow(cfg: dict, term: str) -> pd.DataFrame:
    """Free public JSON API (https://www.arbeitnow.com/api/job-board-api)."""
    r = requests.get("https://www.arbeitnow.com/api/job-board-api", params={"search": term},
                     headers=WEB_HEADERS, timeout=30)
    r.raise_for_status()
    rows = []
    for j in r.json().get("data", [])[: cfg["results_per_search"]]:
        rows.append({
            "title": j.get("title"), "company": j.get("company_name"),
            "location": j.get("location"), "site": "arbeitnow",
            "date_posted": datetime.fromtimestamp(j["created_at"], timezone.utc).date().isoformat()
            if j.get("created_at") else None,
            "job_url": j.get("url"), "job_url_direct": None, "description": _text(j.get("description")),
        })
    return pd.DataFrame(rows)


def _jobposting(page: str) -> dict | None:
    for m in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', page, re.S):
        try:
            data = json.loads(m)
        except ValueError:
            continue
        for item in (data if isinstance(data, list) else [data]):
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                return item
    return None


def _microdata(page: str) -> dict | None:
    """SAP SuccessFactors career sites (e.g. Fraunhofer) use schema.org microdata, not JSON-LD."""
    def grab(prop: str, attr: bool = False) -> str | None:
        pat = rf'itemprop="{prop}"[^>]*?content="([^"]*)"' if attr else rf'itemprop="{prop}"[^>]*>(.*?)</(?:span|div)>'
        m = re.search(pat, page, re.S)
        return m.group(1) if m else None
    title = grab("title")
    if not title:
        return None
    desc = re.search(r'itemprop="description".*?<span class="jobdescription">(.*?)</span>\s*</span>', page, re.S)
    posted = grab("datePosted", attr=True) or ""
    return {
        "title": title,
        "description": desc.group(1) if desc else (grab("description") or ""),
        "hiringOrganization": {"name": grab("hiringOrganization", attr=True)},
        "jobLocation": {"address": {"addressLocality": grab("addressLocality", attr=True) or grab("addressLocality")}},
        "datePosted": "",
    }


# name -> (listing URL template, regex for posting links, URL prefix for relative links)
HTML_BOARDS = {
    "stepstone": ("https://www.stepstone.de/jobs/{slug}", r'href="(/stellenangebote--[^"#]+)"', "https://www.stepstone.de"),
    "xing": ("https://www.xing.com/jobs/search?keywords={q}", r'href="(/jobs/[a-z0-9-]+-\d{6,}[^"#]*)"', "https://www.xing.com"),
    "fraunhofer": ("https://jobs.fraunhofer.de/search/?q={q}", r'href="(/job/[^"#]+)"', "https://jobs.fraunhofer.de"),
    "jobware": ("https://www.jobware.de/jobsuche?jw_jobname={q}", r'href="(/job/[^"#]+)"', "https://www.jobware.de"),
}


def _html_board(cfg: dict, name: str, term: str) -> pd.DataFrame:
    """Best-effort: read the search page, then each posting's schema.org JobPosting JSON-LD."""
    tmpl, pattern, prefix = HTML_BOARDS[name]
    slug = re.sub(r"[^a-z0-9]+", "-", term.lower()).strip("-")
    r = requests.get(tmpl.format(slug=slug, q=quote_plus(term)), headers=WEB_HEADERS, timeout=30)
    r.raise_for_status()
    links = list(dict.fromkeys(html.unescape(l) for l in re.findall(pattern, r.text)))
    rows = []
    for link in links[: cfg.get("html_board_max_jobs", 15)]:
        url = prefix + link
        time.sleep(1)
        try:
            p = requests.get(url, headers=WEB_HEADERS, timeout=30)
            p.raise_for_status()
        except Exception as e:
            logger.debug(f"[{name}] detail failed {url}: {e}")
            continue
        jp = _jobposting(p.text) or _microdata(p.text)
        if not jp:
            continue
        org = jp.get("hiringOrganization") or {}
        loc = jp.get("jobLocation") or {}
        loc = loc[0] if isinstance(loc, list) and loc else loc
        addr = (loc or {}).get("address", {}) if isinstance(loc, dict) else {}
        rows.append({
            "title": _text(jp.get("title")), "company": org.get("name") if isinstance(org, dict) else None,
            "location": (addr.get("addressLocality") if isinstance(addr, dict) else None)
            or (link.split("/job/")[1].split("-")[0] if name == "fraunhofer" and "/job/" in link else None),
            "site": name, "date_posted": (jp.get("datePosted") or "")[:10] or None,
            "job_url": url, "job_url_direct": None, "description": _text(jp.get("description")),
        })
    return pd.DataFrame(rows)


def scrape_term(cfg: dict, bucket: str, term: str) -> pd.DataFrame:
    """Run every configured source for one term. A failing source is logged and skipped."""
    frames = []
    sources = {}
    if cfg.get("sites"):
        sources["jobspy"] = lambda: _jobspy(cfg, term, cfg["sites"])
    if cfg.get("google", True):
        sources["google"] = lambda: _jobspy(
            cfg, term, ["google"], google_search_term=f"{term} jobs in {cfg['location']} since yesterday")
    if cfg.get("arbeitsagentur", {}).get("enabled", False):
        sources["arbeitsagentur"] = lambda: _arbeitsagentur(cfg, term)
    for board in cfg.get("extra_sites", []):
        if board == "arbeitnow":
            sources[board] = lambda: _arbeitnow(cfg, term)
        elif board in HTML_BOARDS:
            sources[board] = lambda b=board: _html_board(cfg, b, term)
        else:
            logger.warning(f"unknown extra site '{board}'")

    for name, fn in sources.items():
        try:
            df = fn()
        except Exception as e:
            logger.error(f"[{name}] failed for '{term}': {e}")
            continue
        if df is not None and not df.empty:
            logger.info(f"[{name}] {len(df)} results for '{term}'")
            frames.append(df)
        else:
            logger.info(f"[{name}] no results for '{term}'")

    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df["search_bucket"] = bucket
    df["search_term"] = term
    return df


def dedupe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.drop_duplicates(subset=["job_url"])
    # Same job often appears on several sites -> dedupe on title + company
    key = (
        df["title"].fillna("").str.lower().str.strip()
        + "|"
        + df["company"].fillna("").str.lower().str.strip()
    )
    return df.loc[~key.duplicated()].reset_index(drop=True)
