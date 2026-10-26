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

# Documented community API (https://github.com/bundesAPI/jobsuche-api) with its public client key.
# Search moved to /pc/v6 in 2026 (the old /pc/v4/jobs route now answers 403 "No match found")
# and renamed its fields; job details are still served by /pc/v4.
BA_BASE = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service"
BA_HEADERS = {"X-API-Key": "jobboerse-jobsuche"}


def iter_searches(cfg: dict):
    """(bucket, term, only_sources). Arbeitsagentur-only terms come last."""
    for bucket, terms in cfg["searches"].items():
        for term in terms:
            yield bucket, term, None
    ba = cfg.get("arbeitsagentur", {})
    if ba.get("enabled"):
        for term in ba.get("extra_searches", []):
            yield "arbeitsagentur", term, ["arbeitsagentur"]
    if cfg.get("company_boards"):
        yield "startups", "startup career pages", ["company_boards"]
    if cfg.get("berlinstartupjobs", True):
        yield "startups", "Berlin Startup Jobs feed", ["berlinstartupjobs"]


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


def _arbeitsagentur(cfg: dict, term: str, skip_urls: set = frozenset()) -> pd.DataFrame:
    ba = cfg.get("arbeitsagentur", {})
    # its own window: daily postings per search term are few, so look back further (default 7 days);
    # jobs already on the board are skipped before the extra details request
    days = ba.get("days") or max(1, round(cfg["hours_old"] / 24))
    r = requests.get(
        f"{BA_BASE}/pc/v6/jobs",
        params={"was": term, "wo": ba.get("location", "Deutschland"), "veroeffentlichtseit": days,
                "size": min(ba.get("size", cfg["results_per_search"]), 100), "page": 1},
        headers=BA_HEADERS, timeout=30,
    )
    r.raise_for_status()
    rows = []
    for j in r.json().get("ergebnisliste", []):
        ref = j.get("referenznummer")
        if not ref or f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{ref}" in skip_urls:
            continue
        desc, external = ", ".join(j.get("alleBerufe") or []), None
        if ba.get("fetch_details", True):
            try:
                enc = base64.b64encode(ref.encode()).decode()
                d = requests.get(f"{BA_BASE}/pc/v4/jobdetails/{enc}", headers=BA_HEADERS, timeout=30)
                d.raise_for_status()
                detail = d.json()
                desc = _text(detail.get("stellenangebotsBeschreibung")) or desc
                external = detail.get("externeURL")
            except Exception as e:
                logger.debug(f"BA details failed for {ref}: {e}")
        place = (j.get("stellenlokationen") or [{}])[0].get("adresse", {})
        rows.append({
            "title": j.get("stellenangebotsTitel"),
            "company": j.get("firma"),
            "location": place.get("ort"),  # e.g. "Augsburg, Bayern"
            "site": "arbeitsagentur",
            "date_posted": (j.get("veroeffentlichungszeitraum") or {}).get("von") or j.get("datumErsteVeroeffentlichung"),
            "job_url": f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{ref}",
            "job_url_direct": external,
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
    # links were relative until 2026, now absolute; accept both
    "stepstone": ("https://www.stepstone.de/jobs/{slug}",
                  r'href="(?:https://www\.stepstone\.de)?(/stellenangebote--[^"#]+)"', "https://www.stepstone.de"),
    "xing": ("https://www.xing.com/jobs/search?keywords={q}", r'href="(/jobs/[a-z0-9-]+-\d{6,}[^"#]*)"', "https://www.xing.com"),
    "fraunhofer": ("https://jobs.fraunhofer.de/search/?q={q}", r'href="(/job/[^"#]+)"', "https://jobs.fraunhofer.de"),
    "jobware": ("https://www.jobware.de/jobsuche?jw_jobname={q}", r'href="(/job/[^"#]+)"', "https://www.jobware.de"),
}


def _utf8(resp: requests.Response) -> requests.Response:
    # requests assumes ISO-8859-1 for text/html without a charset header; these sites send UTF-8,
    # so "Köster" would become "KÃ¶ster"
    if (resp.encoding or "").lower() in ("iso-8859-1", "latin-1"):
        resp.encoding = "utf-8"
    return resp


def _html_board(cfg: dict, name: str, term: str) -> pd.DataFrame:
    """Best-effort: read the search page, then each posting's schema.org JobPosting JSON-LD."""
    tmpl, pattern, prefix = HTML_BOARDS[name]
    slug = re.sub(r"[^a-z0-9]+", "-", term.lower()).strip("-")
    r = _utf8(requests.get(tmpl.format(slug=slug, q=quote_plus(term)), headers=WEB_HEADERS, timeout=30))
    r.raise_for_status()
    links = list(dict.fromkeys(html.unescape(l) for l in re.findall(pattern, r.text)))
    rows = []
    for link in links[: cfg.get("html_board_max_jobs", 15)]:
        url = prefix + link
        time.sleep(1)
        try:
            p = _utf8(requests.get(url, headers=WEB_HEADERS, timeout=30))
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


# ---------- startup career pages (public applicant-tracking-system feeds) ----------
# Many startups post Werkstudent/intern roles only on their own career page, which is usually served
# by an ATS with an official public JSON/XML feed. Each feed lists ALL of a company's jobs, so only
# student-looking titles in Germany (or remote) are kept before the LLM sees them.
STUDENT_TITLE = re.compile(
    r"werkstudent|working student|studentische|hiwi|intern\b|internship|praktik|pflichtpraktikum|"
    r"praxissemester|thesis|abschlussarbeit|masterarbeit|bachelorarbeit|\bstudent\b", re.I)
GERMANY = re.compile(
    r"german|deutschland|\bde\b|berlin|m[uü]nchen|munich|hamburg|k[oö]ln|cologne|frankfurt|stuttgart|"
    r"d[uü]sseldorf|leipzig|dresden|hannover|n[uü]rnberg|nuremberg|karlsruhe|bremen|essen|dortmund|"
    r"bonn|mannheim|heidelberg|aachen|potsdam|ottobrunn|walldorf|remote", re.I)
ATS_TIMEOUT = 30


def _ats_greenhouse(slug):
    r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true", timeout=ATS_TIMEOUT)
    r.raise_for_status()
    for j in r.json().get("jobs", []):
        yield j["title"], (j.get("location") or {}).get("name", ""), j["absolute_url"], html.unescape(j.get("content", ""))


def _ats_ashby(slug):
    r = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", timeout=ATS_TIMEOUT)
    r.raise_for_status()
    for j in r.json().get("jobs", []):
        if j.get("isListed") is False:
            continue
        country = ((j.get("address") or {}).get("postalAddress") or {}).get("addressCountry", "")
        where = " ".join(x for x in (j.get("location"), country, "remote" if j.get("isRemote") else "") if x)
        yield j["title"], where, j["jobUrl"], j.get("descriptionPlain") or ""


def _ats_lever(slug):
    r = requests.get(f"https://api.lever.co/v0/postings/{slug}?mode=json", timeout=ATS_TIMEOUT)
    r.raise_for_status()
    for j in r.json():
        where = f"{(j.get('categories') or {}).get('location', '')} {j.get('country', '')}"
        yield j["text"], where, j["hostedUrl"], j.get("descriptionPlain") or ""


def _ats_personio(slug):
    r = requests.get(f"https://{slug}.jobs.personio.de/xml", timeout=ATS_TIMEOUT)
    r.raise_for_status()
    for pos in re.findall(r"<position>(.*?)</position>", r.text, re.S):
        tag = lambda t: html.unescape((re.search(rf"<{t}>(.*?)</{t}>", pos, re.S) or [None, ""])[1]).strip()
        yield (tag("name"), tag("office"), f"https://{slug}.jobs.personio.de/job/{tag('id')}",
               _text(" ".join(re.findall(r"<value>(.*?)</value>", pos, re.S))))


ATS = {"greenhouse": _ats_greenhouse, "ashby": _ats_ashby, "lever": _ats_lever, "personio": _ats_personio}


def _company_boards(cfg: dict, skip_urls: set = frozenset()) -> pd.DataFrame:
    rows, failed = [], []
    for b in cfg.get("company_boards", []):
        try:
            for title, where, url, desc in ATS[b["ats"]](b["slug"]):
                if url in skip_urls or not STUDENT_TITLE.search(title or ""):
                    continue
                if where and not GERMANY.search(where):
                    continue
                rows.append({
                    "title": html.unescape(title), "company": b["company"], "location": where,
                    "site": f"careers:{b['ats']}",
                    # career pages keep roles open for months and their publish dates would expire them
                    # at once; use the date found (an open role is simply found again after expiry)
                    "date_posted": None,
                    "job_url": url, "job_url_direct": url, "description": _text(desc),
                })
        except Exception as e:
            failed.append(f"{b['company']} ({e.__class__.__name__})")
        time.sleep(0.5)
    if failed:
        logger.warning(f"[company_boards] skipped: {', '.join(failed)}")
    return pd.DataFrame(rows)


def _berlinstartupjobs(cfg: dict) -> pd.DataFrame:
    """Official RSS feed of the engineering category. Mostly full-time roles; the LLM drops those."""
    r = requests.get("https://berlinstartupjobs.com/engineering/feed/", headers=WEB_HEADERS, timeout=30)
    r.raise_for_status()  # 403 = they refuse automated access right now: skipped, not worked around
    rows = []
    for item in re.findall(r"<item>(.*?)</item>", r.text, re.S):
        tag = lambda t: html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", (re.search(rf"<{t}>(.*?)</{t}>", item, re.S) or [None, ""])[1])).strip()
        title = tag("title")  # "Role // Company"
        role, _, company = title.partition(" // ")
        rows.append({
            "title": role or title, "company": company or None, "location": "Berlin", "site": "berlinstartupjobs",
            "date_posted": pd.to_datetime(tag("pubDate"), errors="coerce").date().isoformat() if tag("pubDate") else None,
            "job_url": tag("link"), "job_url_direct": None, "description": _text(tag("description")),
        })
    return pd.DataFrame(rows)


def scrape_term(cfg: dict, bucket: str, term: str, only: list[str] | None = None,
                skip_urls: set = frozenset()) -> pd.DataFrame:
    """Run every configured source for one term (or just the sources in `only`).
    A failing source is logged and skipped. `skip_urls`: known jobs, so sources that need an
    extra request per job (Arbeitsagentur details) can skip them early."""
    frames = []
    sources = {}
    if cfg.get("sites"):
        sources["jobspy"] = lambda: _jobspy(cfg, term, cfg["sites"])
    if cfg.get("google", True):
        sources["google"] = lambda: _jobspy(
            cfg, term, ["google"], google_search_term=f"{term} jobs in {cfg['location']} since yesterday")
    if cfg.get("arbeitsagentur", {}).get("enabled", False):
        sources["arbeitsagentur"] = lambda: _arbeitsagentur(cfg, term, skip_urls)
    for board in cfg.get("extra_sites", []):
        if board == "arbeitnow":
            sources[board] = lambda: _arbeitnow(cfg, term)
        elif board in HTML_BOARDS:
            sources[board] = lambda b=board: _html_board(cfg, b, term)
        else:
            logger.warning(f"unknown extra site '{board}'")
    if only:
        sources = {k: v for k, v in sources.items() if k in only}
        # term-independent sources: run once per scrape, only when asked for explicitly
        if "company_boards" in only and cfg.get("company_boards"):
            sources["company_boards"] = lambda: _company_boards(cfg, skip_urls)
        if "berlinstartupjobs" in only:
            sources["berlinstartupjobs"] = lambda: _berlinstartupjobs(cfg)

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
