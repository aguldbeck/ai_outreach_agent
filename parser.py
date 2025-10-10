import pandas as pd
from io import BytesIO

REQUIRED_FIELDS = [
    "first_name", "last_name", "role_title", "company_name"
]

ALL_FIELDS = [
    "first_name", "last_name", "full_name", "email",
    "role_title", "company_name", "company_industry", "company_size",
    "company_website", "company_location", "linkedin_url", "notes"
]

def read_input_file(file):
    """Reads CSV or Excel file and returns a DataFrame."""
    filename = file.filename.lower()
    if filename.endswith(".csv"):
        df = pd.read_csv(file.file)
    elif filename.endswith((".xls", ".xlsx")):
        df = pd.read_excel(BytesIO(file.file.read()))
    else:
        raise ValueError("Unsupported file type. Upload .csv or .xlsx.")
    return df

def validate_columns(df):
    """Ensures all required columns exist."""
    cols = [c.strip().lower() for c in df.columns]
    missing = [c for c in REQUIRED_FIELDS if c not in cols]
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")
    # Add any missing optional columns as blank
    for col in ALL_FIELDS:
        if col not in df.columns:
            df[col] = None
    return df