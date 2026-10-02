"""
Fetch a simple options-positioning snapshot per ticker via yfinance's option chain, saved
to options.json. Run once daily alongside fetch_data.py / fetch_fundamentals.py (called by
run_daily_pipeline.py). Purely additive - feeds the "종합의견" combined score in
combine_opinion.py, does not touch backtest_engine.py's 45-strategy engine.

Deliberately simple, NOT full dealer-positioning modeling:
  - call_wall / put_wall: strike with the largest GAMMA EXPOSURE (open interest x Black-Scholes
    gamma, not raw open interest) among calls / puts, at the expiration closest to ~30 calendar
    days out (skips 0DTE/weekly noise where OI is thin and often just a handful of stale
    contracts). Switched from raw-OI-max to gamma-weighted on 2026-08-28: raw OI is easily
    dominated by cheap, dead, deep-OTM strikes that accumulate huge contract counts over time
    (e.g. lotto puts far below spot) but carry ~0 gamma and therefore ~0 actual dealer-hedging
    relevance; gamma weighting concentrates the wall near the money, matching how gamma
    exposure-by-strike charts on sites like unusualwhales define support/resistance walls. If
    every contract on one side has invalid/missing IV (gamma exposure sums to exactly 0), falls
    back to the old raw-OI-max strike for that side rather than returning a meaningless pick.
  - net_gex: sum of (call gamma x call OI) - (put gamma x put OI), each x spot^2 x 0.01 x 100
    (standard contract multiplier), using Black-Scholes gamma from each contract's own
    implied vol. This is the common simplified "gamma exposure" proxy used across retail
    options-flow sites - NOT verified real dealer positioning, just a heuristic. Positive =
    historically associated with pinning/lower realized vol; negative = higher realized
    vol / larger swings. Informational only - NOT used in options_score (see below). (Reuses the
    same per-strike gamma exposure values computed for call_wall/put_wall above.)
  - options_score (-100..+100): equal-weight average of two sub-signals, per 2026-08-25
    decision (see below for why the other 3 metrics were deliberately left out):
      (a) wall position: where spot sits between put_wall and call_wall (breakout above
          call_wall = +100, breakdown below put_wall = -100, linear in between).
      (b) put/call OI ratio score: (1 - put_call_oi_ratio) * 100, clamped to [-100, 100] -
          ratio of 1.0 (equal put/call OI) = neutral (0), more puts = bearish-leaning
          (negative), more calls = bullish-leaning (positive).
  - max_pain: the strike where option WRITERS' total payout is smallest (standard "max pain"
    calc: for each candidate strike, sum call-holder intrinsic value below it + put-holder
    intrinsic value above it, weighted by OI; the minimizing strike is max pain). Price often
    drifts toward this level as expiration nears - informational only, not scored.
  - iv_skew_pts: (OTM put IV at ~90% of spot) - (OTM call IV at ~110% of spot), in vol points.
    Positive = puts pricier than calls (downside-hedging demand / fear), negative = calls
    pricier (upside speculation demand).

net_gex, max_pain, and iv_skew_pts are informational only (shown in the 옵션포지셔닝 detail
card) - they deliberately do NOT feed into options_score or the combined 종합의견, per
2026-08-25 discussion: their directionality is ambiguous/context-dependent (e.g. high put OI
can reflect bearish bets, defensive hedging by longs, OR a contrarian-bullish "too much fear"
setup; put-skewed IV is the structural norm for most equities most of the time, not
necessarily an unusual directional tell without a historical baseline to compare against), and
none of the three have been backtested for predictive value, unlike the other combined-opinion
components. put_call_oi_ratio's directionality is just as debatable in theory, but was kept in
the score at the user's explicit request alongside the wall-position signal. Many tickers have
NO US options chain via Yahoo Finance (crypto, KRX-listed Korean stocks like 삼성전자/SK하이닉스)
- those simply get options_available: false and are excluded from the combined score for that
ticker (weights renormalize over whatever's available), same best-effort pattern as
fetch_fundamentals.py.
"""
import datetime
import json
import math
import time

import yfinance as yf

from fetch_data import TICKERS

TARGET_DAYS_OUT = 30  # aim for the expiration closest to ~1 month out
MIN_DAYS_OUT = 14     # avoid 0DTE/weekly noise entirely if a further-out date exists


def _bs_gamma(spot, strike, iv, t_years):
    if spot <= 0 or strike <= 0 or iv <= 0 or t_years <= 0:
        return 0.0
    try:
        d1 = (math.log(spot / strike) + 0.5 * iv * iv * t_years) / (iv * math.sqrt(t_years))
        return math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi) / (spot * iv * math.sqrt(t_years))
    except (ValueError, ZeroDivisionError):
        return 0.0


def _max_pain(calls, puts):
    """Strike minimizing total intrinsic-value payout to option holders (= cost to writers)."""
    strikes = sorted(set(calls["strike"]).union(set(puts["strike"])))
    if not strikes:
        return None
    best_strike, best_pain = None, None
    for k in strikes:
        call_payout = ((k - calls["strike"]).clip(lower=0) * calls["openInterest"]).sum()
        put_payout = ((puts["strike"] - k).clip(lower=0) * puts["openInterest"]).sum()
        total = call_payout + put_payout
        if best_pain is None or total < best_pain:
            best_pain, best_strike = total, k
    return float(best_strike) if best_strike is not None else None


def _iv_skew_pts(calls, puts, spot):
    """(OTM put IV near -10%) - (OTM call IV near +10%), in vol points (e.g. 3.2 = 3.2%p)."""
    if calls.empty or puts.empty or spot <= 0:
        return None
    call_target, put_target = spot * 1.10, spot * 0.90
    call_row = calls.iloc[(calls["strike"] - call_target).abs().argsort()[:1]]
    put_row = puts.iloc[(puts["strike"] - put_target).abs().argsort()[:1]]
    call_iv = float(call_row["impliedVolatility"].iloc[0]) if len(call_row) else None
    put_iv = float(put_row["impliedVolatility"].iloc[0]) if len(put_row) else None
    if call_iv is None or put_iv is None or not (0 < call_iv < 5) or not (0 < put_iv < 5):
        return None
    return (put_iv - call_iv) * 100


def _pick_expiration(expirations, today):
    if not expirations:
        return None
    dated = []
    for e in expirations:
        try:
            dated.append((e, (datetime.date.fromisoformat(e) - today).days))
        except ValueError:
            continue
    candidates = [d for d in dated if d[1] >= MIN_DAYS_OUT] or dated
    if not candidates:
        return None
    return min(candidates, key=lambda d: abs(d[1] - TARGET_DAYS_OUT))


def _fetch_one(symbol, spot, retries=2, delay_sec=0.5, backoff_sec=3.0):
    last_err = None
    for attempt in range(retries + 1):
        try:
            t = yf.Ticker(symbol)
            expirations = t.options
            picked = _pick_expiration(expirations, datetime.date.today())
            if not picked:
                return None, "no options chain (not optionable)"
            exp, days_out = picked
            chain = t.option_chain(exp)
            calls = chain.calls[(chain.calls.openInterest.fillna(0) > 0)].copy()
            puts = chain.puts[(chain.puts.openInterest.fillna(0) > 0)].copy()
            time.sleep(delay_sec)
            if calls.empty and puts.empty:
                return None, "options chain has zero open interest"

            t_years = max(days_out, 1) / 365.0

            def _gamma_exposure_col(df):
                # Per-contract dollar gamma exposure = OI x Black-Scholes gamma x spot^2 x 0.01
                # x 100 (contract multiplier). Always >= 0 (magnitude) - net_gex below is the
                # one that nets calls against puts with a sign.
                exposures = []
                for _, row in df.iterrows():
                    iv = row.get("impliedVolatility") or 0.0
                    g = _bs_gamma(spot, row["strike"], iv, t_years) if 0 < iv < 5 else 0.0
                    exposures.append(g * row["openInterest"] * 100 * spot * spot * 0.01)
                return exposures

            calls["gamma_exposure"] = _gamma_exposure_col(calls)
            puts["gamma_exposure"] = _gamma_exposure_col(puts)
            call_gex_total = float(calls["gamma_exposure"].sum())
            put_gex_total = float(puts["gamma_exposure"].sum())
            net_gex = call_gex_total - put_gex_total

            # Wall = strike with the largest gamma exposure, not raw OI - raw OI is easily
            # dominated by cheap, dead, deep-OTM strikes with ~0 actual gamma/hedging
            # relevance. Falls back to raw-OI-max if every contract on that side has
            # missing/invalid IV (gamma exposure all zero), so a bad-data ticker still gets
            # a wall instead of an arbitrary tie-broken pick.
            if not calls.empty and call_gex_total > 0:
                call_wall = float(calls.loc[calls["gamma_exposure"].idxmax(), "strike"])
            elif not calls.empty:
                call_wall = float(calls.loc[calls["openInterest"].idxmax(), "strike"])
            else:
                call_wall = None

            if not puts.empty and put_gex_total > 0:
                put_wall = float(puts.loc[puts["gamma_exposure"].idxmax(), "strike"])
            elif not puts.empty:
                put_wall = float(puts.loc[puts["openInterest"].idxmax(), "strike"])
            else:
                put_wall = None

            if call_wall is not None and put_wall is not None and call_wall > put_wall:
                range_pos = (spot - put_wall) / (call_wall - put_wall)
                range_pos = max(0.0, min(1.0, range_pos))
                base = (range_pos - 0.5) * 200
            else:
                base = 0.0
            if call_wall is not None and spot > call_wall:
                base = 100.0
            if put_wall is not None and spot < put_wall:
                base = -100.0

            call_oi_total = float(calls["openInterest"].sum())
            put_oi_total = float(puts["openInterest"].sum())
            pcr = (put_oi_total / call_oi_total) if call_oi_total > 0 else None
            pcr_bias = None
            pcr_score = None
            if pcr is not None:
                pcr_bias = "풋 우위 (방어적)" if pcr > 1.0 else ("콜 우위 (공격적)" if pcr < 0.7 else "중립")
                # 1.0 (put OI == call OI) = neutral; more puts = negative, more calls = positive.
                pcr_score = max(-100.0, min(100.0, (1.0 - pcr) * 100))

            # 2026-08-25: options_score = equal-weight avg of wall-position(base) and
            # put/call-ratio(pcr_score) only. net_gex no longer damps/amplifies the score -
            # it's informational-only now (see module docstring for why).
            options_score = base if pcr_score is None else (base + pcr_score) / 2.0
            options_score = max(-100.0, min(100.0, options_score))

            mp = _max_pain(calls, puts)
            skew = _iv_skew_pts(calls, puts, spot)
            skew_bias = None
            if skew is not None:
                skew_bias = "풋 스큐 (하방헤지 수요)" if skew > 2 else ("콜 스큐 (상방베팅 수요)" if skew < -2 else "중립")

            return {
                "expiration": exp,
                "days_out": days_out,
                "spot_at_fetch": spot,
                "call_wall": call_wall,
                "put_wall": put_wall,
                "net_gex": net_gex,
                "net_gex_bias": "안정(핀닝 성향)" if net_gex >= 0 else "변동성 확대 위험",
                "options_score": round(options_score, 1),
                "put_call_oi_ratio": round(pcr, 2) if pcr is not None else None,
                "put_call_oi_ratio_bias": pcr_bias,
                "max_pain": mp,
                "iv_skew_pts": round(skew, 1) if skew is not None else None,
                "iv_skew_bias": skew_bias,
            }, None
        except Exception as e:
            last_err = e
            time.sleep(backoff_sec)
    return None, str(last_err)


def fetch_all(spot_prices):
    """spot_prices: {name: last_close}. Returns {name: (status, detail, data_or_None)}."""
    results = {}
    for name, symbol in TICKERS.items():
        spot = spot_prices.get(name)
        if not spot:
            results[name] = ("FAIL", "no spot price available", None)
            continue
        data, err = _fetch_one(symbol, spot)
        if err is not None:
            results[name] = ("FAIL", err, None)
        else:
            results[name] = ("OK", "", data)
    return results


if __name__ == "__main__":
    import pandas as pd
    import os

    spot_prices = {}
    for name in TICKERS:
        path = f"data/{name}.csv"
        if os.path.exists(path):
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            if len(df):
                spot_prices[name] = float(df.Close.iloc[-1])

    out = {}
    ok_count = 0
    fail_count = 0
    for name, (status, detail, data) in fetch_all(spot_prices).items():
        print(f"{name:8s} {status:5s} {detail}")
        if data is not None:
            out[name] = data
            ok_count += 1
        else:
            fail_count += 1
    with open("options.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\nSaved options.json: {ok_count} OK, {fail_count} skipped/failed (no options chain, e.g. BTC/KRX names)")
