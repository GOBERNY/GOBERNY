"""
Temporary helper (not part of the pipeline) to run fetch_data.fetch_all() on a slice of
TICKERS, so the fetch can be split across multiple shorter bash calls without editing
fetch_data.py itself. Safe to delete after use.
"""
import sys
import fetch_data

start = int(sys.argv[1])
end = int(sys.argv[2])

items = list(fetch_data.TICKERS.items())
subset = dict(items[start:end])
fetch_data.TICKERS = subset

for name, (status, detail) in fetch_data.fetch_all().items():
    print(f"{name:6s} {status:5s} {detail}")
