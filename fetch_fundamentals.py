"""
Fetch a fundamental/valuation snapshot + analyst consensus target price for the tracked
tickers via yfinance's `.info`, saved to fundamentals.json. Run once daily alongside
fetch_data.py as part of the pipeline (run_daily_pipeline.py calls this automatically).

Best-effort by design: yfinance's `.info` dict is inconsistent across ticker types (ETFs
have no PER/PBR/analyst targets, crypto has almost nothing, some equities lack revenue
growth), so every field is read with .get() and left as None if missing rather than
raising - the report renders "N/A" for anything not present instead of failing the whole
ticker. A single ticker's fetch failing (network error, delisted, etc.) is recorded as
FAIL and skipped, same pattern as fetch_data.py, so one bad symbol never blocks the rest.
"""
import time
import json

import yfinance as yf

from fetch_data import TICKERS

# Fields pulled straight from yfinance .info - see
# https://github.com/ranaroussi/yfinance for the (undocumented, best-effort) key names.
FIELDS = [
    "trailingPE", "forwardPE", "priceToBook", "marketCap",
    "revenueGrowth", "targetMeanPrice", "targetHighPrice", "targetLowPrice",
    "targetMedianPrice", "numberOfAnalystOpinions", "recommendationKey",
]


def _fetch_one(symbol, retries=2, delay_sec=0.5, backoff_sec=3.0):
    last_err = None
    for attempt in range(retries + 1):
        try:
            info = yf.Ticker(symbol).get_info()
            time.sleep(delay_sec)
            if not info:
                return None, "empty info response"
            return {f: info.get(f) for f in FIELDS}, None
        except Exception as e:
            last_err = e
            time.sleep(backoff_sec)
    return None, str(last_err)


def fetch_all():
    """Returns {name: (status, detail, data_or_None)}."""
    results = {}
    for name, symbol in TICKERS.items():
        data, err = _fetch_one(symbol)
        if err is not None:
            results[name] = ("FAIL", err, None)
        else:
            results[name] = ("OK", "", data)
    return results


if __name__ == "__main__":
    out = {}
    fail_count = 0
    for name, (status, detail, data) in fetch_all().items():
        print(f"{name:6s} {status:5s} {detail}")
        if data is not None:
            out[name] = data
        else:
            fail_count += 1
    with open("fundamentals.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\nSaved fundamentals.json: {len(out)} OK, {fail_count} failed")
