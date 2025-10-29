# parser.py
from __future__ import annotations

import os
from typing import List, Dict, Any
import pandas as pd


REQUIRED_COLUMNS = [
    # minimally expected; extras are allowed
    "name",            # e.g., "Alex Guldbeck"
    "company",         # e.g., "Lovable"
    "title",           # e.g., "Founder"
    "linkedin_url",    # optional but helpful
    "domain",          # company domain, e.g., "lovable.app"
    "notes",           # optional freeform notes
]

def validate_columns(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Input file missing required columns: {missing}. "
                         f"Present: {list(df.columns)}")

def read_input_file(input_path: str) -> List[Dict[str, Any]]:
    """
    Read the Excel/CSV uploaded by the user, validate columns,
    and return a list of row dicts for downstream steps.
    """
    if not os.path.isabs(input_path):
        # Always operate on absolute paths
        input_path = os.path.abspath(input_path)

    # Support .xlsx and .csv
    lower = input_path.lower()
    if lower.endswith(".xlsx") or lower.endswith(".xlsm"):
        df = pd.read_excel(input_path)
    elif lower.endswith(".csv"):
        df = pd.read_csv(input_path)
    else:
        raise ValueError("Unsupported input format. Please upload .xlsx or .csv")

    # Normalize columns (lowercase + underscores)
    df.columns = [str(c).strip().lower() for c in df.columns]

    # If some required columns are missing but we can infer them, do it
    # (kept simple; fail fast otherwise)
    validate_columns(df)

    # Fill NaNs to safe defaults
    df = df.fillna("")

    rows: List[Dict[str, Any]] = df.to_dict(orient="records")

    # Add an id per row (stable index-based)
    for i, r in enumerate(rows, start=1):
        r.setdefault("row_id", i)

    return rows