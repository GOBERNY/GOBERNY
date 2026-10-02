"""
Temporary helper (not part of the pipeline) to merge the partial results written by
_chunk_build.py into backtest_results.json, replicating the tail end of build_results.py
(validate_all, meta, save, archive) exactly. Safe to delete after use.
"""
import datetime
import glob
import json
import os
import shutil
from zoneinfo import ZoneInfo

import numpy as np

from backtest_engine import validate_all
from fetch_data import TICKERS

KST = ZoneInfo("Asia/Seoul")


def _json_default(o):
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return str(o)


all_results = {}
failed = {}
for path in sorted(glob.glob("_partial_build/*.json")):
    with open(path, "r", encoding="utf-8") as f:
        chunk = json.load(f)
    all_results.update(chunk["results"])
    failed.update(chunk["failed"])

# sanity: every ticker accounted for
missing = [t for t in TICKERS if t not in all_results and t not in failed]
if missing:
    raise SystemExit(f"ERROR: tickers missing from all chunks: {missing}")

problems = validate_all(all_results)
if problems:
    print("VALIDATION WARNINGS FOUND:")
    for t, ws in problems.items():
        for w in ws:
            print(f"  [{t}] {w}")
else:
    print("OK - no consistency issues found.")

meta = {
    "generated_at": datetime.datetime.now(KST).isoformat(timespec="seconds"),
    "failed_tickers": failed,
    "fundamentals_failed_tickers": {},
    "validation_warnings": problems,
}

payload = {"meta": meta, "tickers": all_results}
with open("backtest_results.json", "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2, default=_json_default)

today = datetime.datetime.now(KST).date().isoformat()
archive_dir = f"archive/{today}"
os.makedirs(archive_dir, exist_ok=True)
shutil.copy("backtest_results.json", f"{archive_dir}/backtest_results.json")

print(f"\nDone. {len(all_results)} tickers OK, {len(failed)} failed: {list(failed.keys())}")
