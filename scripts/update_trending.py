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
    r = session.get(url, headers=headers, params=params, timeout=15)
    r.raise_for_status()
    return r.json().get("items", [])

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
    # Match headings like: # Lets connect, ## Lets connect, ### Let's connect etc.
    # Accepts "lets" or "let's" (case-insensitive)
    header_re = re.compile(r"(^\s*#{1,6}\s*let(?:'|’)?s\s+connect\s*$)", flags=re.I | re.M)
    m = header_re.search(readme_text)
    if m:
        insert_pos = m.end()
        # If the block markers already exist elsewhere, first remove them to avoid duplicates
        if "<!-- TRENDING_START -->" in readme_text and "<!-- TRENDING_END -->" in readme_text:
            readme_text = re.sub(r"<!-- TRENDING_START -->.*?<!-- TRENDING_END -->", "", readme_text, flags=re.S)
        # Insert block after the heading with two newlines
        return readme_text[:insert_pos] + "\n\n" + block + readme_text[insert_pos:]
    else:
        # Fallback: replace existing markers or append to end
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

def main():
    days = int(os.environ.get("TREND_DAYS", "7"))
    count = int(os.environ.get("RESULTS", "20"))
    language = os.environ.get("LANGUAGE") or None

    since = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).date().isoformat()
    q = build_query(since, language)
    session = requests_session()

    try:
        items = fetch_top_repos(session, q, per_page=count)
    except requests.HTTPError as e:
        print("GitHub API error:", e, file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print("Unexpected error:", e, file=sys.stderr)
        sys.exit(1)

    block = make_block(items, count, since)
    update_readme(block)
    print("README updated with trending repositories.")

if __name__ == "__main__":
    main()
