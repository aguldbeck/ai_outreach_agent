from bs4 import BeautifulSoup
import re

def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def html_to_text(html: str, max_chars: int = 4000) -> str:
    soup = BeautifulSoup(html, "html.parser")
    bits = []
    for tag in soup.find_all(["h1","h2","h3","p","li"]):
        t = tag.get_text(" ", strip=True)
        if t:
            bits.append(t)
    return clean_text(" ".join(bits))[:max_chars]
# redeploy
