"""Temporary helper: replicate run_daily_pipeline.py step 3 (options fetch) standalone."""
import json, os
import pandas as pd
import fetch_options
from fetch_data import TICKERS

spot_prices = {}
for name in TICKERS:
    path = f"data/{name}.csv"
    if os.path.exists(path):
        _df = pd.read_csv(path, index_col=0, parse_dates=True)
        if len(_df):
            spot_prices[name] = float(_df.Close.iloc[-1])

options_data = {}
skipped = 0
for name, (status, detail, odata) in fetch_options.fetch_all(spot_prices).items():
    if status == "OK":
        options_data[name] = odata
    else:
        skipped += 1
with open("options.json", "w", encoding="utf-8") as f:
    json.dump(options_data, f, ensure_ascii=False, indent=2)
print(f"  {len(options_data)} OK, {skipped} skipped")
