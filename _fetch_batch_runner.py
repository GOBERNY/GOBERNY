"""Temporary helper (not part of the engine) to run fetch_data.fetch_all() on a
subset of TICKERS so a single call stays under the remote shell's timeout.
Does not modify fetch_data.py - just monkeypatches the module-level dict at
runtime before calling the unmodified fetch_all().
Usage: python3 _fetch_batch_runner.py NAME1,NAME2,NAME3
"""
import sys
import fetch_data

names = sys.argv[1].split(",")
subset = {k: fetch_data.TICKERS[k] for k in names if k in fetch_data.TICKERS}
missing = [k for k in names if k not in fetch_data.TICKERS]
if missing:
    print("WARN unknown ticker keys:", missing)
fetch_data.TICKERS = subset
for name, (status, detail) in fetch_data.fetch_all().items():
    print(f"{name:12s} {status:5s} {detail}")
