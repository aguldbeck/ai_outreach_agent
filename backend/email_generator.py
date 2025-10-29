# email_generator.py
import os, random, json
from openai import OpenAI

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

def load_weclick_config(config_name: str = "weclick") -> dict:
    path = os.path.join("configs", f"{config_name}.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def compose_email(row: dict, profile: dict, config_name: str = "weclick") -> dict:
    cfg = load_weclick_config(config_name)
    name = row.get("name") or "there"
    company = row.get("company") or ""
    title = row.get("job_title") or row.get("title") or ""
    posts = profile.get("posts", []) or []
    headline = profile.get("headline", "")
    about = profile.get("about", "")

    # Build small context: pick up to one post
    post_snip = posts[0] if posts else ""
    proof = random.choice(cfg["case_studies"])

    prompt = f"""
You are a top-tier DTC retention copywriter.

Write a 120–150 word cold email to {name} ({title}) at {company}.
Reference their LinkedIn context below when relevant (one natural reference max).

LinkedIn Headline: {headline}
About: {about}
Recent Post: {post_snip}

WeClick positioning:
{cfg["positioning"]}

Use exactly ONE proof point:
- {proof}

Tone: {cfg["tone"]}

CTA: {cfg["cta_primary"]} (secondary acceptable: {cfg["cta_secondary"]})

Return as:
Subject: <subject>
Body: <body>
"""

    # Fallback if no API key: return a deterministic stub
    if not _client:
        subj = f"Quick retention idea for {company}"
        body = (
            f"Hi {name},\n\n"
            f"Saw your work at {company}. Based on your profile, there's likely unused CLV upside "
            f"in lifecycle flows and segmentation.\n\n{cfg['positioning']}\n\n"
            f"Recent win: {proof}\n\n"
            f"If helpful, I can run a {cfg['cta_primary']}. —Alex\n"
        )
        return {"subject": subj, "body": body}

    try:
        resp = _client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8
        )
        text = resp.choices[0].message.content
        parts = text.split("Body:")
        subject = parts[0].replace("Subject:", "").strip() if len(parts) > 1 else "Quick idea"
        body = parts[1].strip() if len(parts) > 1 else text.strip()
        return {"subject": subject, "body": body}
    except Exception as e:
        print(f"[Stage3] OpenAI error: {e}")
        return {"subject": "Quick idea", "body": "Fallback body due to API error."}