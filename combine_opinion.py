"""
Combines the three (or four, when options data is available) independent signal blocks a
ticker card shows - 지표분석(indicator mix), 추세상태(trend vote), 백테스트예측(top-5
strategy vote), and 옵션 포지셔닝(gamma/call-put wall, when the ticker has a US options
chain) - into ONE headline verdict (종합의견), instead of letting the backtest vote alone
decide the card's 매수/매도 label like before.

Deliberately simple by request: equal weight across whichever of the 4 blocks are actually
available for a given ticker (weights renormalize - e.g. 3-way 33/33/33 for BTC/KRX names
with no options chain, 4-way 25/25/25/25 otherwise), each converted to a -100..+100 score,
averaged, then thresholded against a symmetric band around 0 for 매수/매도/관망.

This does NOT replace or touch the existing per-signal "신뢰도 낮음" caution already shown
inside the 백테스트예측 section (that one flags when THAT SPECIFIC strategy's own historical
accuracy is weak, or its open position is stale/underwater) - that stays exactly as-is. This
module only decides the card's overall label/sort/color at the top level.
"""

BAND = 30.0  # |combined_score| below this -> 관망(신뢰도 낮음); tune here if it feels too strict/loose


def _indicator_score(record):
    buy_pct = record.get("buy_ratio_pct")
    sell_pct = record.get("sell_ratio_pct")
    if buy_pct is None or sell_pct is None:
        return None
    return buy_pct - sell_pct


def _trend_score(record):
    ts = record.get("trend_status") or {}
    total = ts.get("total_votes")
    up = ts.get("up_votes")
    if not total:
        return None
    return ((up / total) - 0.5) * 200


def _backtest_score(record):
    vote_total = record.get("top_n_vote_total")
    vote_buy = record.get("top_n_vote_buy")
    if not vote_total:
        return None
    return ((vote_buy / vote_total) - 0.5) * 200


def _options_score(options_record):
    if not options_record:
        return None
    return options_record.get("options_score")


LABELS = {
    "indicator": "지표분석",
    "trend": "추세상태",
    "backtest": "백테스트예측",
    "options": "옵션포지셔닝",
}


def compute_final_opinion(record, options_record=None, band=BAND):
    """record: one ticker's entry as assembled by build_results.py/run_daily_pipeline.py
    (needs buy_ratio_pct/sell_ratio_pct, trend_status, top_n_vote_buy/top_n_vote_total).
    options_record: that ticker's entry from options.json, or None if not optionable.
    Returns a dict to store as record["final_opinion"], or None if nothing was scorable."""
    raw = {
        "indicator": _indicator_score(record),
        "trend": _trend_score(record),
        "backtest": _backtest_score(record),
        "options": _options_score(options_record),
    }
    scores = {k: v for k, v in raw.items() if v is not None}
    if not scores:
        return None
    combined = sum(scores.values()) / len(scores)
    if combined >= band:
        label = "매수"
    elif combined <= -band:
        label = "매도"
    else:
        label = "관망"
    weight_pct = round(100 / len(scores), 1)
    return {
        "combined_score": round(combined, 1),
        "band": band,
        "label": label,
        "components": {
            LABELS[k]: {"score": round(v, 1), "weight_pct": weight_pct}
            for k, v in scores.items()
        },
        "missing": [LABELS[k] for k, v in raw.items() if v is None],
    }


def compute_composite_signal_recency(chart_data, final_opinion, last_date):
    """How long the 종합의견(final_opinion) badge has been showing its CURRENT label, for
    display next to that badge on the index/검색 page - previously that spot reused
    top_strategy.last_signal_bars_ago (one reference strategy's own signal recency), which
    could legitimately be a different, older or newer date than when the actual 4-block
    composite score crossed into its current label. That mismatch is confusing on the same
    row (badge says "just turned 매수", the neighboring text says "4 days ago") even though
    both are individually correct - they used to just be answering two different questions.

    Reconstructed from the same 3-of-4-block approximation used for chart arrows (see
    backtest_engine._composite_chart_data) - 옵션포지셔닝 has no historical series, so: if
    today's real final_opinion label matches what that 3-block approximation already says for
    today, trust the approximation's run-length. If options tipped today's real verdict away
    from what the 3-block approximation predicted, the most honest answer is "as of today"
    (bars_ago=0) - there's no historical options series to say how many prior days that would
    also have held true for."""
    if not chart_data or not final_opinion:
        return None
    label = final_opinion.get("label")
    approx_label = chart_data.get("approx_current_label")
    if approx_label is not None and approx_label == label:
        return {
            "date": chart_data.get("approx_signal_date"),
            "bars_ago": chart_data.get("approx_signal_bars_ago"),
        }
    return {"date": last_date, "bars_ago": 0}


def apply_final_opinion_to_chart(chart_data, final_opinion, last_close, last_date):
    """chart_data's markers approximate the 종합의견 history using only the 3 blocks that
    have a historical time series (see backtest_engine._composite_chart_data) - 옵션포지셔닝
    has no history, so the approximation can occasionally disagree with the REAL, options-
    inclusive final_opinion on the very last bar. This corrects just that last bar in place
    so the chart's most recent arrow always matches the 종합의견 badge shown on the same
    card exactly, even on days options tilt the real verdict a different way than the
    3-block proxy alone would. Historical (non-last-bar) markers are left as approximations -
    intentionally not "corrected" since there's nothing to correct them against."""
    if not chart_data or not final_opinion:
        return
    label = final_opinion.get("label")
    if label not in ("매수", "매도"):
        return  # 관망 has no marker type - leave whatever historical state was last as-is
    marker_type = "buy" if label == "매수" else "sell"
    markers = chart_data.get("markers") or []
    if markers and markers[-1]["date"] == last_date:
        markers[-1]["type"] = marker_type
    else:
        implied_state = markers[-1]["type"] if markers else None
        if implied_state != marker_type:
            markers.append({"date": last_date, "price": round(float(last_close), 2), "type": marker_type})
