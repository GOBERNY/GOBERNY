"""
Full daily pipeline: fetch data -> backtest (with train/test holdout + cost assumption) ->
validate -> archive -> render report. Run this single script to regenerate everything.
Used both for manual runs and by the scheduled task, so behavior stays identical either way.
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
from fetch_data import TICKERS, fetch_all
import fetch_fundamentals
import fetch_options

MIN_HISTORY_BARS_WARNING = 500  # flag tickers with materially shorter history (e.g. recent spinoffs like SNDK)
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
    print("1/7 fetching data...")
    fetch_status = fetch_all()
    failed = {}
    for name, (status, detail) in fetch_status.items():
        print(f"  {name:6s} {status:5s} {detail}")
        if status == "FAIL":
            failed[name] = detail

    print("2/7 fetching fundamentals + analyst targets...")
    fundamentals = {}
    fundamentals_failed = {}
    for name, (status, detail, fdata) in fetch_fundamentals.fetch_all().items():
        if status == "OK":
            fundamentals[name] = fdata
        else:
            fundamentals_failed[name] = detail
    print(f"  {len(fundamentals)} OK, {len(fundamentals_failed)} failed"
          + (f" ({list(fundamentals_failed.keys())})" if fundamentals_failed else ""))
    # Fundamentals are best-effort/supplementary - a failure here never blocks a ticker's
    # technical backtest, it just means that ticker's card shows no valuation/analyst block.

    print("3/7 fetching options positioning (call/put wall, gamma exposure)...")
    spot_prices = {}
    for name in TICKERS:
        path = f"data/{name}.csv"
        if name not in failed and os.path.exists(path):
            _df = pd.read_csv(path, index_col=0, parse_dates=True)
            if len(_df):
                spot_prices[name] = float(_df.Close.iloc[-1])
    options_data = {}
    options_skipped = 0
    for name, (status, detail, odata) in fetch_options.fetch_all(spot_prices).items():
        if status == "OK":
            options_data[name] = odata
        else:
            options_skipped += 1
    with open("options.json", "w", encoding="utf-8") as f:
        json.dump(options_data, f, ensure_ascii=False, indent=2)
    print(f"  {len(options_data)} OK, {options_skipped} skipped (no US options chain - e.g. BTC/KRX names - or fetch error)")
    # Best-effort/supplementary just like fundamentals - a ticker with no options chain
    # (crypto, KRX-listed names) just gets fewer inputs into its combined score below,
    # never blocks the technical backtest itself.

    print("4/7 running backtests...")
    all_results = {}
    for name in TICKERS:
        if name in failed:
            continue
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

    print("5/7 validating...")
    problems = validate_all(all_results)
    if problems:
        print("  VALIDATION WARNINGS FOUND:")
        for t, ws in problems.items():
            for w in ws:
                print(f"    [{t}] {w}")
    else:
        print("  OK - no consistency issues found.")

    meta = {
        # 서버 시계가 UTC인 환경(GitHub Actions 등)에서 돌아도 "생성 시각"이 항상
        # 한국시간(KST) 기준으로 찍히게 명시 - 안 그러면 9시간 밀려서 표시된다.
        "generated_at": datetime.datetime.now(KST).isoformat(timespec="seconds"),
        "failed_tickers": failed,
        "fundamentals_failed_tickers": fundamentals_failed,
        "validation_warnings": problems,
    }

    print("6/7 saving results + archive...")
    payload = {"meta": meta, "tickers": all_results}
    with open("backtest_results.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=_json_default)

    today = datetime.datetime.now(KST).date().isoformat()
    archive_dir = f"archive/{today}"
    os.makedirs(archive_dir, exist_ok=True)
    shutil.copy("backtest_results.json", f"{archive_dir}/backtest_results.json")

    print("7/7 rendering report...")
    import subprocess
    subprocess.run(["python3", "generate_report_v2.py"], check=True)
    shutil.copy("report.html", f"{archive_dir}/report.html")
    if os.path.exists("index.html"):
        shutil.copy("index.html", f"{archive_dir}/index.html")

    print(f"\nDone. {len(all_results)} tickers OK, {len(failed)} failed: {list(failed.keys())}")
    return payload


if __name__ == "__main__":
    run()
