# linkedin_scraper.py
import re, requests

JINA_PROXY_PREFIX = "https://r.jina.ai/http://"

def fetch_profile_text(linkedin_url: str) -> str:
    # Fetch a readable text snapshot via Jina proxy (public content only)
    if not linkedin_url:
        return ""
    proxied = JINA_PROXY_PREFIX + linkedin_url.lstrip("http://").lstrip("https://")
    try:
        r = requests.get(proxied, timeout=12)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"[Stage2] Fetch proxy failed for {linkedin_url}: {e}")
        return ""

def extract_profile_structured(text: str) -> dict:
    """
    Extremely simple heuristics. We keep it robust & cheap:
    - headline: first line with a dash or ' at ' pattern
    - about: first paragraph near 'About' or 'Summary'
    - posts: first 3 lines that look like activity/post excerpts
    """
    if not text:
        return {"headline": "", "about": "", "posts": []}

    # Normalize newlines
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    joined = "\n".join(lines)

    # Headline heuristic
    headline = ""
    for ln in lines[:40]:
        if " at " in ln or " — " in ln or " – " in ln:
            headline = ln
            break

    # About/Summary heuristic
    about = ""
    m = re.search(r"(About|Summary)\s*\n+(.{120,800})", joined, re.IGNORECASE | re.DOTALL)
    if m:
        about = m.group(2).split("\n\n")[0].strip()

    # Posts heuristic: lines with enough length & not headers, grab first 3
    post_candidates = [ln for ln in lines if len(ln) > 60 and not re.match(r"^(About|Experience|Education|Activity|Posts)\b", ln, re.I)]
    posts = post_candidates[:3]

    return {
        "headline": headline[:200],
        "about": about[:800],
        "posts": [p[:300] for p in posts]
    }

def scrape_profile(linkedin_url: str) -> dict:
    text = fetch_profile_text(linkedin_url)
    return extract_profile_structured(text)