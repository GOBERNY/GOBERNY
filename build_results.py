"""
One-off helper for this scheduled run: replicates steps 3-5 of run_daily_pipeline.py
(backtest + save + validate) WITHOUT re-fetching data/fundamentals, since those were
already freshly fetched in separate steps this run. Does not touch backtest_engine.py,
fetch_data.py, or generate_report_v2.py logic - just calls them.
"""
import datetime
import json
import os
import shutil
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from backtest_engine import analyze_ticker, validate_all
from combine_opinion import compute_final_opinion, apply_final_opinion_to_chart, compute_composite_signal_recency
from fetch_data import TICKERS

MIN_HISTORY_BARS_WARNING = 500
KST = ZoneInfo("Asia/Seoul")


def _json_default(o):
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return str(o)


def run():
    with open("fundamentals.json", "r", encoding="utf-8") as f:
        fundamentals = json.load(f)

    options_data = {}
    if os.path.exists("options.json"):
        with open("options.json", "r", encoding="utf-8") as f:
            options_data = json.load(f)

    failed = {}
    all_results = {}
    for name in TICKERS:
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

    problems = validate_all(all_results)
    if problems:
        print("VALIDATION WARNINGS FOUND:")
        for t, ws in problems.items():
            for w in ws:
                print(f"  [{t}] {w}")
    else:
        print("OK - no consistency issues found.")

    meta = {
        # GitHub Actions 등 서버 시계는 UTC라서, 시간대 지정 없이 now()를 찍으면
        # 리포트에 "생성 시각"이 9시간 밀려서 어제 시각처럼 표시되는 버그가 있었다 -
        # 항상 한국시간(KST)으로 명시해서 어느 서버에서 돌든 동일하게 나오게 한다.
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
    return payload


if __name__ == "__main__":
    run()
