"""
Temporary helper (not part of the pipeline) to run the build_results.py per-ticker
analysis on a slice of TICKERS, so it can be split across multiple shorter bash calls
without editing build_results.py itself. Writes partial results to _partial_build/.
Safe to delete after use.
"""
import json
import os
import sys

import numpy as np
import pandas as pd

from backtest_engine import analyze_ticker
from combine_opinion import compute_final_opinion, apply_final_opinion_to_chart, compute_composite_signal_recency
from fetch_data import TICKERS

MIN_HISTORY_BARS_WARNING = 500

start = int(sys.argv[1])
end = int(sys.argv[2])

names = list(TICKERS.keys())[start:end]

with open("fundamentals.json", "r", encoding="utf-8") as f:
    fundamentals = json.load(f)

options_data = {}
if os.path.exists("options.json"):
    with open("options.json", "r", encoding="utf-8") as f:
        options_data = json.load(f)

os.makedirs("_partial_build", exist_ok=True)

failed = {}
all_results = {}
for name in names:
    path = f"data/{name}.csv"
    if not os.path.exists(path):
        failed[name] = "data file missing after fetch"
        continue
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    if len(df) < 130:
        failed[name] = f"only {len(df)} bars available (need >=130) - too little history to analyze yet"
        continue
    try:
        res = analyze_ticker(df, min_bars=130)
    except Exception as e:
        failed[name] = f"analyze error: {e}"
        continue
    all_results[name] = {
        "last_close": float(df.Close.iloc[-1]),
        "last_date": str(df.index[-1].date()),
        "num_bars": len(df),
        "short_history_warning": len(df) < MIN_HISTORY_BARS_WARNING,
        "top_strategy": res["top_strategy"],
        "trend_status": res["trend_status"],
        "chart_data": res["chart_data"],
        "signal_track_record": res.get("signal_track_record", []),
        "fundamentals": fundamentals.get(name),
        "top_n_vote_buy": res["top_n_vote_buy"],
        "top_n_vote_total": res["top_n_vote_total"],
        "buy_hold_count": res["buy_hold_count"],
        "sell_count": res["sell_count"],
        "total_strategies": res["total_strategies"],
        "buy_ratio_pct": res["buy_ratio_pct"],
        "sell_ratio_pct": res["sell_ratio_pct"],
        "opinion": res["opinion"],
        "horizon_days": res["horizon_days"],
        "signal_accuracy_pct": res["signal_accuracy_pct"],
        "signal_accuracy_n": res["signal_accuracy_n"],
        "expected_return_pct": res["expected_return_pct"],
        "trade_plan": res["trade_plan"],
        "watch_plan": res["watch_plan"],
        "cost_pct_assumed": res["cost_pct_assumed"],
        "train_frac": res["train_frac"],
        "oos_holds_up": res["oos_holds_up"],
        "thin_fallback": res["thin_fallback"],
        "fallback_reason": res["fallback_reason"],
        "min_trades_for_ranking": res["min_trades_for_ranking"],
        "min_recent_trades": res["min_recent_trades"],
        "all_results": res["all_results"],
    }
    opt_rec = options_data.get(name)
    all_results[name]["options"] = opt_rec
    all_results[name]["final_opinion"] = compute_final_opinion(all_results[name], opt_rec)
    fo = all_results[name]["final_opinion"]
    apply_final_opinion_to_chart(all_results[name]["chart_data"], fo, all_results[name]["last_close"], all_results[name]["last_date"])
    all_results[name]["composite_signal_recency"] = compute_composite_signal_recency(
        all_results[name]["chart_data"], fo, all_results[name]["last_date"]
    )
    fo_label = fo["label"] if fo else "N/A"
    print(f"  {name:6s} opinion={res['opinion']:4s} final={fo_label:4s} top={res['top_strategy']['name']}")


def _json_default(o):
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return str(o)


with open(f"_partial_build/{start}_{end}.json", "w", encoding="utf-8") as f:
    json.dump({"results": all_results, "failed": failed}, f, ensure_ascii=False, default=_json_default)

print(f"chunk {start}:{end} done - {len(all_results)} ok, {len(failed)} failed")
