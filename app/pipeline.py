# app/pipeline.py
import os
import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ---------- Stage 1: Enrichment ----------
def enrich_stage1(input_csv: str, output_csv: str, config: str = "weclick"):
    """
    Add/prepare LinkedIn URL leads. Stub builds a DDG query if linkedin_url is missing.
    You can replace with your working DDG→LinkedIn resolver.
    """
    df = pd.read_csv(input_csv)
    if "linkedin_url" not in df.columns:
        df["linkedin_url"] = ""

    def mk_ddg_query(row):
        name = str(row.get("name", "")).strip()
        company = str(row.get("company", "")).strip()
        if row.get("linkedin_url"): return row["linkedin_url"]
        if name or company:
            return f'DDG: "{name} {company}" site:linkedin.com/in'
        return ""
    df["linkedin_url"] = df.apply(mk_ddg_query, axis=1)
    df.to_csv(output_csv, index=False)
    return output_csv

# ---------- Stage 2: Scraping ----------
def scrape_stage2(input_csv: str, output_csv: str):
    """
    Stub: pretend to fetch profile + last 3 posts. Replace with your DDG snapshot parser.
    """
    df = pd.read_csv(input_csv)
    if "latest_posts" not in df.columns:
        df["latest_posts"] = ""
    # placeholder content (you'll replace with real scrape)
    df["latest_posts"] = df["linkedin_url"].apply(
        lambda u: "Post A · Post B · Post C" if isinstance(u, str) and u else ""
    )
    df.to_csv(output_csv, index=False)
    return output_csv

# ---------- Stage 3: Email Generation (OpenAI) ----------
WCLICK_POSITIONING = """WeClick helps 7–9 figure DTC brands scale profitably using email, SMS, and retention strategies that go beyond generic discounts. We focus on driving customer lifetime value through deep segmentation, personalized lifecycle flows, and data-led execution across Klaviyo and complementary tools."""

CASE_STUDIES = [
    "CoverFX: High-converting campaigns, retention-focused flows, and AOV growth via cross-sells.",
    "DTC Beauty Brand: $91 LTV increase in 12 months through strategic email/SMS.",
    "Jewelry Brand: Reduced 42% returns using email-driven post-purchase automation.",
    "Health Supplement Brand: 67.12% repeat purchase rate through bundling and smart flows.",
]

def generate_stage3(input_csv: str, output_csv: str):
    df = pd.read_csv(input_csv)
    emails = []
    for _, row in df.iterrows():
        name    = row.get("name", "there")
        company = row.get("company", "your brand")
        posts   = row.get("latest_posts", "")

        prompt = f"""
Write a confident, conversational, 150–180 word cold email to a DTC decision maker.

Prospect: {name} at {company}
Recent posts (if any): {posts}

Positioning:
{WCLICK_POSITIONING}

Include exactly one short case study from:
- {CASE_STUDIES[0]}
- {CASE_STUDIES[1]}
- {CASE_STUDIES[2]}
- {CASE_STUDIES[3]}

CTA: End with “DM me for a FREE Klaviyo/Omnisend audit”.

Tone: strategic operator-level, value-focused, practical.
Avoid hype; reference posts if relevant.
"""

        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=250,
            )
            text = resp.choices[0].message.content.strip()
        except Exception as e:
            text = f"[OpenAI error] {e}"

        emails.append(text)

    df["email_copy"] = emails
    df.to_csv(output_csv, index=False)
    return output_csv