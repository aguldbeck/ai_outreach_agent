# linkedin_enricher.py
import time, random, requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}

def find_linkedin_profile(name: str, company: str = "") -> str | None:
    if not name:
        return None
    # DuckDuckGo HTML endpoint (no JS)
    q = f'{name} {company} site:linkedin.com/in OR site:linkedin.com/pub'
    url = f"https://duckduckgo.com/html/?q={requests.utils.quote(q)}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a.result__a[href]"):
            href = a["href"]
            if "linkedin.com/in" in href or "linkedin.com/pub" in href:
                return href
        return None
    except Exception as e:
        print(f"[Stage1] DuckDuckGo error ({name}, {company}): {e}")
        return None
    finally:
        time.sleep(random.uniform(1.8, 3.2))  # polite delay