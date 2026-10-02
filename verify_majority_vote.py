"""
One-off analysis (not part of the daily pipeline): does a day-by-day majority vote across
the top-5 strategies actually produce overlapping buy/sell regimes, and is that majority
signal's forward-return accuracy better than just following the single #1 strategy alone?

For each ticker:
  1. Re-rank the 45 strategies by train_return_pct (same selection as the report's top-5).
  2. Walk each of the top-5 strategies' own single-position state machine across the FULL
     history to get a day-by-day "holding or not" series.
  3. Sum those 5 series into a 0-5 "votes currently long" count per day.
  4. A majority-buy REGIME is any run of consecutive days with votes>=3; majority-sell is
     any run with votes<=2. Count regimes + their lengths to confirm they exist/overlap.
  5. At the first day of each majority-buy regime (a "majority buy signal"), and each
     majority-sell regime start, measure the 10-day forward return - same methodology as
     the single-strategy accuracy stat already in the report - and compare accuracy% to
     the single #1-ranked strategy's own buy/sell forward accuracy.
"""
import pandas as pd
from backtest_engine import (
    build_strategies, run_backtest, run_backtest_holdout, DEFAULT_COST_PCT,
    _median, _forward_signal_stats,
)

TICKERS = ["NVDA", "MU", "SOXX", "TSLA", "IONQ", "NVTS", "SNDK", "PLTR", "RKLB", "BTC"]
MIN_BARS = 130
HORIZON = 10
TOP_N = 5


def position_state_series(df, signal_fn, min_bars=MIN_BARS):
    """0/1 series: 1 on every day the strategy is actually holding a position (after
    entering on a buy signal, until the matching sell signal), 0 otherwise. Pre-min_bars
    days are 0 (indicators not valid yet)."""
    sig = signal_fn(df).fillna(0)
    n = len(df)
    state = [0] * n
    position = 0
    for i in range(min_bars, n):
        s = sig.iloc[i]
        if position == 0 and s == 1:
            position = 1
        elif position == 1 and s == -1:
            position = 0
        state[i] = position
    return state


def regimes(votes, min_bars, threshold_buy=3):
    """Collapse the day-by-day vote series into contiguous majority-buy / majority-sell
    regimes (runs), skipping the pre-min_bars warmup. Returns list of (kind, start_i, end_i, length)."""
    out = []
    n = len(votes)
    i = min_bars
    while i < n:
        kind = "buy" if votes[i] >= threshold_buy else "sell"
        j = i
        while j < n and (votes[j] >= threshold_buy) == (kind == "buy"):
            j += 1
        out.append((kind, i, j - 1, j - i))
        i = j
    return out


def forward_stats_at(df, event_idxs, want_direction, horizon=HORIZON):
    close = df.Close
    n = len(df)
    rets, hits = [], 0
    for i in event_idxs:
        if i + horizon >= n:
            continue
        p0, p1 = close.iloc[i], close.iloc[i + horizon]
        ret = (p1 - p0) / p0 * 100
        rets.append(ret)
        if (want_direction == 1 and ret > 0) or (want_direction == -1 and ret < 0):
            hits += 1
    k = len(rets)
    if k == 0:
        return None, None, 0
    med = round(_median(rets), 2)
    acc = round(hits / k * 100, 1)
    return med, acc, k


print(f"{'TICKER':6s} {'#buy regimes':>12s} {'#sell regimes':>13s} {'avg buy len':>11s} {'avg sell len':>12s} | "
      f"{'top1 buy acc':>12s} {'vote buy acc':>12s} | {'top1 sell acc':>13s} {'vote sell acc':>13s}")

for ticker in TICKERS:
    df = pd.read_csv(f"data/{ticker}.csv", index_col=0, parse_dates=True)
    strategies = build_strategies()
    results = []
    for name, category, fn in strategies:
        try:
            r = run_backtest(df, fn, min_bars=MIN_BARS, cost_pct=DEFAULT_COST_PCT)
            r["name"], r["category"], r["fn"] = name, category, fn
            r.update(run_backtest_holdout(df, fn, min_bars=MIN_BARS, cost_pct=DEFAULT_COST_PCT))
            results.append(r)
        except Exception:
            pass

    ranked = sorted([r for r in results if r["train_num_trades"] >= 3], key=lambda r: r["train_return_pct"], reverse=True)
    top5 = ranked[:TOP_N]
    top1 = ranked[0]

    state_series = [position_state_series(df, r["fn"]) for r in top5]
    votes = [sum(s[i] for s in state_series) for i in range(len(df))]

    regs = regimes(votes, MIN_BARS, threshold_buy=3)
    buy_regs = [r for r in regs if r[0] == "buy"]
    sell_regs = [r for r in regs if r[0] == "sell"]
    avg_buy_len = round(sum(r[3] for r in buy_regs) / len(buy_regs), 1) if buy_regs else None
    avg_sell_len = round(sum(r[3] for r in sell_regs) / len(sell_regs), 1) if sell_regs else None

    buy_event_idxs = [r[1] for r in buy_regs]   # first day of each majority-buy regime
    sell_event_idxs = [r[1] for r in sell_regs]  # first day of each majority-sell regime

    vote_buy_med, vote_buy_acc, vote_buy_n = forward_stats_at(df, buy_event_idxs, 1)
    vote_sell_med, vote_sell_acc, vote_sell_n = forward_stats_at(df, sell_event_idxs, -1)

    top1_sig_name = top1["name"]
    top1_buy_acc = top1.get("buy_forward_accuracy_pct")
    top1_buy_n = top1.get("buy_forward_n")
    top1_sell_acc = top1.get("sell_forward_accuracy_pct")
    top1_sell_n = top1.get("sell_forward_n")

    print(f"{ticker:6s} {len(buy_regs):>12d} {len(sell_regs):>13d} {str(avg_buy_len):>11s} {str(avg_sell_len):>12s} | "
          f"{str(top1_buy_acc)+'%('+str(top1_buy_n)+')':>12s} {str(vote_buy_acc)+'%('+str(vote_buy_n)+')':>12s} | "
          f"{str(top1_sell_acc)+'%('+str(top1_sell_n)+')':>13s} {str(vote_sell_acc)+'%('+str(vote_sell_n)+')':>13s}")
