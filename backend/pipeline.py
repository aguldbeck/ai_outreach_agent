# pipeline.py
"""
High-level orchestrator for AI Outreach Agent.
Runs LinkedIn enrichment, scraping, summarization, and email generation.

Called from server.py -> process_job().
"""

import os
import pandas as pd
from typing import Dict, Any, List

from parser import read_input_file
from linkedin_enricher import enrich_profiles
from linkedin_scraper import scrape_profiles
from summarizer import summarize_profiles
from email_generator import generate_emails


def run_pipeline(input_path: str, job_id: str, output_dir: str = "outputs") -> str:
    """
    Orchestrates the full outreach workflow.
    Returns the path to the generated output file.
    """
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"processed_{os.path.basename(input_path)}")

    try:
        # Step 1: Parse input leads
        leads = read_input_file(input_path)
        if not leads:
            raise ValueError("No leads found in input file.")
        print(f"[Job {job_id}] Parsed {len(leads)} leads")

        # Step 2: Enrich with LinkedIn profile URLs
        enriched = enrich_profiles(leads)
        print(f"[Job {job_id}] Enriched {len(enriched)} profiles with LinkedIn URLs")

        # Step 3: Scrape recent posts and profile summaries
        scraped = scrape_profiles(enriched)
        print(f"[Job {job_id}] Scraped {len(scraped)} profiles with posts/headlines")

        # Step 4: Summarize insights (optional but helpful for context)
        summarized = summarize_profiles(scraped)
        print(f"[Job {job_id}] Summarized {len(summarized)} profiles")

        # Step 5: Generate personalized outreach emails
        emails = generate_emails(summarized)
        print(f"[Job {job_id}] Generated {len(emails)} emails")

        # Step 6: Write structured output to Excel
        df = pd.DataFrame(emails)

        # Expand list fields (like posts) into separate columns for clarity
        if "posts" in df.columns:
            df["post_1"] = df["posts"].apply(lambda p: p[0]["snippet"] if isinstance(p, list) and len(p) > 0 else "")
            df["post_2"] = df["posts"].apply(lambda p: p[1]["snippet"] if isinstance(p, list) and len(p) > 1 else "")
            df["post_3"] = df["posts"].apply(lambda p: p[2]["snippet"] if isinstance(p, list) and len(p) > 2 else "")
            df.drop(columns=["posts"], inplace=True, errors="ignore")

        df.to_excel(output_path, index=False)
        print(f"[Job {job_id}] Saved output to {output_path}")

        return output_path

    except Exception as e:
        print(f"[ERROR] Job {job_id} failed: {e}")
        raise


if __name__ == "__main__":
    # Manual test
    test_path = "TestList.xlsx"
    run_pipeline(test_path, job_id="local-test")