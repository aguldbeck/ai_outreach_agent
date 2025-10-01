import os, json, pandas as pd

def run_enrichment(input_csv, config_name, output_csv):
    # Load input CSV
    df = pd.read_csv(input_csv)

    # Resolve config path based on name
    config_path = os.path.join("configs", f"{config_name}.json")
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config_data = json.load(f)

    # For now, just enrich with dummy data for demonstration
    df["enriched_field"] = f"Processed with config: {config_name}"

    # Save output
    df.to_csv(output_csv, index=False)
    return output_csv
