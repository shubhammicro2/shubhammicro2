#!/usr/bin/env python3
import os
import sys
import datetime
import re
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
if not GITHUB_TOKEN:
    print("GITHUB_TOKEN not found in environment", file=sys.stderr)
    sys.exit(1)

def requests_session(retries=3, backoff=1):
    s = requests.Session()
    retry = Retry(total=retries, backoff_factor=backoff, status_forcelist=(429,500,502,503,504))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s

def build_query(since, language=None):
    q = f"created:>{since}+fork:false"
    if language:
        q += f"+language:{language}"
    return q

def fetch_top_repos(session, q, per_page):
    url = "https://api.github.com/search/repositories"
    params = {"q": q, "sort": "stars", "order": "desc", "per_page": per_page}
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "update-trending-script"
    }
    print(f"DEBUG: Requesting {url} params={params}", file=sys.stderr)
    r = session.get(url, headers=headers, params=params, timeout=20)
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        print("GitHub API error:", e, file=sys.stderr)
        print("Response status:", r.status_code, "body:", r.text, file=sys.stderr)
        raise
    data = r.json()
    items = data.get("items", [])
    print(f"DEBUG: fetched {len(items)} items (total_count={data.get('total_count')})", file=sys.stderr)
    if len(items) > 0:
        first = items[0]
        print("DEBUG: first repo:", first.get("full_name"), first.get("html_url"), "stars:", first.get("stargazers_count"), file=sys.stderr)
    return items

def make_block(items, count, since):
    lines = []
    lines.append("<!-- TRENDING_START -->")
    lines.append(f"### Top {count} trending GitHub repositories (created since {since})")
    lines.append("")
    for repo in items:
        full = repo.get("full_name")
        html = repo.get("html_url")
        desc = repo.get("description") or ""
        stars = repo.get("stargazers_count", 0)
        desc = desc.replace("\n", " ").strip()
        lines.append(f"- [{full}]({html}) — {desc} ⭐ {stars}")
    lines.append("<!-- TRENDING_END -->")
    return "\n".join(lines) + "\n"

def insert_after_heading(readme_text, block):
    header_re = re.compile(r"(^\s*#{1,6}\s*let(?:'|’)?s\s+connect\s*$)", flags=re.I | re.M)
    m = header_re.search(readme_text)
    if m:
        insert_pos = m.end()
        if "<!-- TRENDING_START -->" in readme_text and "<!-- TRENDING_END -->" in readme_text:
            readme_text = re.sub(r"<!-- TRENDING_START -->.*?<!-- TRENDING_END -->", "", readme_text, flags=re.S)
        return readme_text[:insert_pos] + "\n\n" + block + readme_text[insert_pos:]
    else:
        if "<!-- TRENDING_START -->" in readme_text and "<!-- TRENDING_END -->" in readme_text:
            return re.sub(r"<!-- TRENDING_START -->.*?<!-- TRENDING_END -->", block, readme_text, flags=re.S)
        else:
            return readme_text.rstrip() + "\n\n" + block

def update_readme(block, path="README.md"):
    if os.path.exists(path):
        text = open(path, "r", encoding="utf-8").read()
        new = insert_after_heading(text, block)
    else:
        new = block
    with open(path, "w", encoding="utf-8") as f:
        f.write(new)

def try_windows(session, base_days, count, language):
    # Attempt sequence: base_days -> 30 -> 90 -> 365 as last resort
    windows = [base_days]
    if base_days not in (30, 90, 365):
        windows += [30, 90, 365]
    tried = []
    for days in windows:
        since = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).date().isoformat()
        q = build_query(since, language)
        print(f"DEBUG: trying window days={days}, since={since}", file=sys.stderr)
        items = fetch_top_repos(session, q, per_page=count)
        tried.append((days, len(items), since))
        if items:
            return items, tried, since
    return [], tried, None

def main():
    base_days = int(os.environ.get("TREND_DAYS", "7"))
    count = int(os.environ.get("RESULTS", "20"))
    language = os.environ.get("LANGUAGE") or None

    session = requests_session()

    try:
        items, tried, since = try_windows(session, base_days, count, language)
    except Exception as e:
        print("ERROR fetching repos:", e, file=sys.stderr)
        sys.exit(1)

    for days, n, s in tried:
        print(f"DEBUG: tried window {days} days -> fetched {n} items (since={s})", file=sys.stderr)

    if not items:
        # Last-resort: search a broader timeframe (365 days) but still safe
        fallback_since = (datetime.datetime.utcnow() - datetime.timedelta(days=365)).date().isoformat()
        q = build_query(fallback_since, language)
        print(f"DEBUG: fallback to 365-day window since={fallback_since}", file=sys.stderr)
        try:
            items = fetch_top_repos(session, q, per_page=count)
        except Exception as e:
            print("ERROR fallback fetch:", e, file=sys.stderr)
            sys.exit(1)
        print(f"DEBUG: fallback fetched {len(items)} items", file=sys.stderr)
        since = fallback_since

    if not items:
        print("No items fetched from GitHub Search API after all attempts; aborting README update.", file=sys.stderr)
        sys.exit(0)

    block = make_block(items, count, since)
    update_readme(block)
    print("README updated with trending repositories.")

if __name__ == "__main__":
    main()
