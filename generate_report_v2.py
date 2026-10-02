import json, math, re
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

with open("backtest_results.json", encoding="utf-8") as f:
    payload = json.load(f)

meta = payload.get("meta", {})
data = payload.get("tickers", payload)  # fall back to flat structure for older files
failed_tickers = meta.get("failed_tickers", {})

TICKER_LABELS = {
    "NVDA": "엔비디아", "MU": "마이크론", "SOXX": "필라델피아 반도체 ETF",
    "TSLA": "테슬라", "IONQ": "아이온큐", "NVTS": "나비타스 세미컨덕터",
    "SNDK": "샌디스크", "PLTR": "팔란티어", "RKLB": "로켓랩", "BTC": "비트코인",
    "QCOM": "퀄컴", "COHR": "코히런트", "AMD": "AMD", "INTC": "인텔", "MRVL": "마벨 테크놀로지",
    "ORCL": "오라클", "SMCI": "슈퍼마이크로컴퓨터",
    "POET": "포엣 테크놀로지스", "CIFR": "사이퍼 마이닝", "CRWV": "코어위브",
    "RGTI": "리게티 컴퓨팅", "QBTS": "디웨이브 퀀텀",
    "ACHR": "아처 에비에이션", "JOBY": "조비 에비에이션", "RCAT": "레드캣 홀딩스",
    "ARBE": "아르베 로보틱스", "RR": "리치테크 로보틱스", "SERV": "서브 로보틱스",
    "DXYZ": "데스티니 테크100", "MP": "MP 머티리얼즈",
    "OPEN": "오픈도어 테크놀로지스", "TEM": "템퍼스AI", "RXRX": "리커전 파마슈티컬스",
    "RZLV": "리졸브AI", "SATL": "새틀로직", "SES": "SES AI", "SMR": "뉴스케일파워",
    "AAPL": "애플", "MSFT": "마이크로소프트", "GOOGL": "알파벳(구글)", "AMZN": "아마존", "META": "메타플랫폼스",
    "AVGO": "브로드컴", "CRM": "세일즈포스", "ADBE": "어도비", "NFLX": "넷플릭스",
    "SPY": "S&P500 ETF", "XLV": "헬스케어 섹터 ETF", "XLB": "소재 섹터 ETF",
    "XLY": "임의소비재 섹터 ETF", "XLF": "금융 섹터 ETF", "XLRE": "리츠 섹터 ETF",
    "XLI": "산업재 섹터 ETF", "XLP": "필수소비재 섹터 ETF", "XLK": "기술 섹터 ETF",
    "XLU": "유틸리티 섹터 ETF", "XLC": "커뮤니케이션 섹터 ETF", "XLE": "에너지 섹터 ETF",
    "TSM": "TSMC", "ASML": "ASML", "AMAT": "어플라이드 머티리얼즈",
    "JPM": "JP모건", "V": "비자", "UNH": "유나이티드헬스", "WMT": "월마트", "XOM": "엑슨모빌",
    "CRWD": "크라우드스트라이크",
    "COIN": "코인베이스", "MSTR": "스트래티지(마이크로스트래티지)",
    "QQQ": "나스닥100 ETF", "DIA": "다우존스 ETF", "IWM": "러셀2000(소형주) ETF",
}

# Sector groupings for the report grid - with 70+ tickers a flat 매수/매도 sort alone made
# the page impossible to browse, so cards are now grouped under sector headings (still
# 매수-first sorted WITHIN each sector). Any ticker not listed here falls into "기타" at the
# end automatically, so adding a new ticker without updating this list doesn't break anything.
SECTOR_GROUPS = [
    ("반도체 (수요기업)", ["NVDA", "MU", "SOXX", "NVTS", "SNDK", "QCOM", "COHR", "AMD", "INTC", "MRVL", "SMCI"]),
    ("반도체 공급망 (파운드리·장비)", ["TSM", "ASML", "AMAT"]),
    ("빅테크 · 소프트웨어", ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "AVGO", "ORCL", "CRM", "ADBE", "NFLX", "CRWD", "PLTR"]),
    ("AI 인프라 · 데이터센터", ["POET", "CIFR", "CRWV"]),
    ("양자컴퓨터", ["IONQ", "RGTI", "QBTS"]),
    ("드론 택시 (eVTOL)", ["ACHR", "JOBY", "RCAT"]),
    ("휴머노이드 로봇", ["ARBE", "RR", "SERV"]),
    ("우주 · 자원 · 성장주", ["RKLB", "DXYZ", "MP", "OPEN", "TEM", "RXRX", "RZLV", "SATL", "SES", "SMR"]),
    ("테슬라 · EV", ["TSLA"]),
    ("금융 · 헬스케어 · 소비재 · 에너지 블루칩", ["JPM", "V", "UNH", "WMT", "XOM"]),
    ("크립토 & 연계주", ["BTC", "COIN", "MSTR"]),
    ("섹터 ETF", ["XLV", "XLB", "XLY", "XLF", "XLRE", "XLI", "XLP", "XLK", "XLU", "XLC", "XLE"]),
    ("지수 ETF", ["SPY", "QQQ", "DIA", "IWM"]),
]

# Korean market convention: red = up/매수, blue = down/매도
UP_COLOR = "#e0293f"
DOWN_COLOR = "#3366ff"

def needle_point(pct, cx=100, cy=100, r=72):
    angle_deg = 180 - (pct / 100 * 180)
    rad = math.radians(angle_deg)
    return cx + r * math.cos(rad), cy - r * math.sin(rad)

def arc_point(pct, cx=100, cy=100, r=80):
    """Same angle mapping as needle_point but for a point ON the gauge arc itself
    (r=80 matches the arc path radius) - used to build the 3 colored zone segments."""
    angle_deg = 180 - (pct / 100 * 180)
    rad = math.radians(angle_deg)
    return cx + r * math.cos(rad), cy - r * math.sin(rad)

def fmt_pct(v, digits=1, signed=True):
    if v is None: return "N/A"
    sign = "+" if (signed and v > 0) else ""
    return f"{sign}{v:.{digits}f}%"

def fmt_num(v):
    return f"{v:,.2f}"

def fmt_market_cap(v):
    """USD market cap -> 조/억달러 단위 (한국 투자자에게 익숙한 단위 표기)."""
    if v is None: return "N/A"
    if v >= 1e12: return f"{v/1e12:.2f}조달러"
    if v >= 1e8: return f"{v/1e8:.0f}억달러"
    return f"{v:,.0f}달러"

def fmt_ratio(v, digits=1):
    if v is None: return "N/A"
    return f"{v:.{digits}f}배"

RECOMMENDATION_KO = {
    "strong_buy": "강력매수", "buy": "매수", "hold": "보유",
    "sell": "매도", "strong_sell": "강력매도", "underperform": "매도",
    "outperform": "매수",
}

def fmt_recommendation(v):
    if not v: return "N/A"
    return RECOMMENDATION_KO.get(v, v)

def build_track_record_svg(track_record, width=640, height=140):
    """Line chart of the rolling (trailing-10-signal) hit-rate for the reference strategy's
    own signal type over time - see backtest_engine._signal_track_record. Same visual
    language (SVG, gridlines, date ticks) as build_chart_svg for consistency."""
    if not track_record or len(track_record) < 2:
        return ""
    accs = [p["accuracy_pct"] for p in track_record]
    dates = [p["date"] for p in track_record]
    n = len(accs)
    pad_left, pad_right, pad_top, pad_bottom = 10, 44, 14, 24
    lo, hi = 0, 100
    def xy(i, v):
        x = pad_left + (width - pad_left - pad_right) * i / (n - 1)
        y = height - pad_bottom - (height - pad_top - pad_bottom) * (v - lo) / (hi - lo)
        return x, y
    pts = [xy(i, v) for i, v in enumerate(accs)]
    path_d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    last_x, last_y = pts[-1]
    line_color = UP_COLOR if accs[-1] >= 50 else DOWN_COLOR

    _, y50 = xy(0, 50)
    grid_svg = (
        f'<line x1="{pad_left}" y1="{y50:.1f}" x2="{width-pad_right}" y2="{y50:.1f}" '
        f'stroke="#eef1f5" stroke-width="1" stroke-dasharray="3,3"/>'
        f'<text x="{width-pad_right+8:.1f}" y="{y50:.1f}" text-anchor="start" '
        f'dominant-baseline="middle" class="chart-axis-label">50%</text>'
    )

    date_svgs = []
    tick_idxs = sorted(set([0, n // 2, n - 1]))
    for idx in tick_idxs:
        tx, _ = xy(idx, accs[idx])
        anchor = "start" if idx == 0 else ("end" if idx == n - 1 else "middle")
        date_svgs.append(f'<text x="{tx:.1f}" y="{height - 6}" text-anchor="{anchor}" class="chart-axis-label">{dates[idx]}</text>')

    return f'''<svg viewBox="0 0 {width} {height}" class="mini-chart">
      {grid_svg}
      <path d="{path_d}" fill="none" stroke="{line_color}" stroke-width="2"/>
      <circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="4" fill="{line_color}"/>
      {''.join(date_svgs)}
    </svg>'''

def build_chart_svg(chart_data, width=640, height=260):
    """Chart of the last ~1yr close prices with ▲/▼ markers at the buy/sell
    signals the reference strategy actually fired in that window, plus price
    gridlines on the right and date ticks along the bottom."""
    if not chart_data:
        return ""
    prices = chart_data.get("prices") or []
    dates = chart_data.get("dates") or []
    markers = chart_data.get("markers") or []
    if len(prices) < 2:
        return ""
    lo, hi = min(prices), max(prices)
    mid = (lo + hi) / 2
    span = (hi - lo) or 1
    n = len(prices)
    # extra right room for price labels, extra bottom room for date labels
    pad_left, pad_right, pad_top, pad_bottom = 10, 58, 14, 26
    def xy(i, p):
        x = pad_left + (width - pad_left - pad_right) * i / (n - 1)
        y = height - pad_bottom - (height - pad_top - pad_bottom) * (p - lo) / span
        return x, y
    pts = [xy(i, p) for i, p in enumerate(prices)]
    path_d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    date_index = {d: i for i, d in enumerate(dates)}
    marker_svgs = []
    for m in markers:
        idx = date_index.get(m["date"])
        if idx is None:
            continue
        x, y = xy(idx, m["price"])
        if m["type"] == "buy":
            marker_svgs.append(f'<polygon points="{x:.1f},{y+6:.1f} {x-6:.1f},{y+18:.1f} {x+6:.1f},{y+18:.1f}" fill="{UP_COLOR}"/>')
        else:
            marker_svgs.append(f'<polygon points="{x:.1f},{y-6:.1f} {x-6:.1f},{y-18:.1f} {x+6:.1f},{y-18:.1f}" fill="{DOWN_COLOR}"/>')

    # price gridlines: high / mid / low, with the price value labeled on the right
    plot_x0, plot_x1 = pad_left, width - pad_right
    grid_svgs = []
    for p_val in (hi, mid, lo):
        _, gy = xy(0, p_val)
        grid_svgs.append(f'<line x1="{plot_x0}" y1="{gy:.1f}" x2="{plot_x1}" y2="{gy:.1f}" stroke="#eef1f5" stroke-width="1"/>')
        grid_svgs.append(f'<text x="{plot_x1 + 8:.1f}" y="{gy:.1f}" text-anchor="start" dominant-baseline="middle" class="chart-axis-label">{fmt_num(p_val)}</text>')

    # date ticks: first, ~1/3, ~2/3, last (anchor the edge ticks inward so labels don't clip)
    date_svgs = []
    tick_idxs = sorted(set([0, n // 3, (2 * n) // 3, n - 1]))
    for idx in tick_idxs:
        tx, _ = xy(idx, prices[idx])
        anchor = "start" if idx == 0 else ("end" if idx == n - 1 else "middle")
        date_svgs.append(f'<text x="{tx:.1f}" y="{height - 6}" text-anchor="{anchor}" class="chart-axis-label">{dates[idx]}</text>')

    return f'''<svg viewBox="0 0 {width} {height}" class="mini-chart">
      {''.join(grid_svgs)}
      <path d="{path_d}" fill="none" stroke="#94a3b8" stroke-width="2"/>
      {''.join(marker_svgs)}
      {''.join(date_svgs)}
    </svg>'''

# 지표분석/추세상태/백테스트예측/(있으면)옵션포지셔닝 4개를 동일 가중으로 합친 종합의견
# 기준으로 정렬/분류해요 - 백테스트예측(45개 전략 중 상위 5개 다수결) 하나에만 기대던 이전
# 방식 대신, 종목 하나를 여러 각도에서 본 합의를 "지금 볼 만한 종목" 판단 기준으로 써요.
# final_opinion이 없는(모든 구성요소가 다 빠진, 사실상 없는) 극히 드문 케이스만 예전 방식으로 폴백.
def _final_label(d):
    fo = d.get("final_opinion")
    return fo["label"] if fo else d["opinion"]

# 매수 종목을 앞쪽에, 매도 종목을 뒤쪽에, 관망은 그 사이에 정렬 - "지금 볼 만한 종목"이 먼저 보이도록.
_SORT_RANK = {"매수": 0, "관망": 1, "매도": 2}
ordered_items = sorted(data.items(), key=lambda kv: _SORT_RANK.get(_final_label(kv[1]), 1))

card_html_by_ticker = {}
ticker_category = {}  # ticker -> "buy"/"sell"/"watch", used by index.html's 매수/매도/관망 filter
for ticker, d in ordered_items:
    label = TICKER_LABELS.get(ticker, ticker)
    top = d["top_strategy"]
    buy_pct = d["buy_ratio_pct"]
    sell_pct = d["sell_ratio_pct"]
    active_n = d.get("total_strategies", 45)
    buy_hold_n = d.get("buy_hold_count", 0)
    sell_n = d.get("sell_count", 0)

    opinion = d["opinion"]
    vote_buy = d.get("top_n_vote_buy", 0)
    vote_total = d.get("top_n_vote_total", 0)
    horizon = d.get("horizon_days", 10)
    accuracy = d["signal_accuracy_pct"]
    accuracy_n = d.get("signal_accuracy_n", 0)
    exp_ret = d["expected_return_pct"]
    # "투자의견" only reflects whether the top strategy currently holds a position -
    # it is NOT the same as "this signal is reliable right now". When this specific
    # signal's own historical accuracy is <=50% (a coin flip or worse), showing a
    # bold, fully-saturated opinion chip is misleading, so we mute the color and
    # add an explicit caution line instead of a confident recommendation.
    low_confidence = accuracy is not None and accuracy <= 50
    # A strategy can pass every eligibility bar (enough total trades, enough recent trades)
    # and still be sitting on a big unrealized loss RIGHT NOW simply because price moved hard
    # against its currently-held position since the last signal fired, with no exit signal
    # yet. That's a live, quantifiable red flag - not "this signal type is historically
    # unreliable" (that's what `accuracy` already covers) but "this specific open position is
    # underwater today" - so it gets the same muted/low-confidence treatment.
    UNDERWATER_THRESHOLD_PCT = -10
    open_ret_now = top.get("open_trade_return_pct")
    is_underwater = (top.get("current_state") == "매수보유" and open_ret_now is not None and open_ret_now < UNDERWATER_THRESHOLD_PCT)
    # Mirror case for 관망(watching): the strategy sold and price has since rallied hard with
    # no buy-back signal - "매도" doesn't mean the sell was validated, just that nothing has
    # flipped it back yet. Missing a big rally while sitting in cash is just as live a red
    # flag as holding through a big drawdown.
    MISSED_RALLY_THRESHOLD_PCT = 10
    open_watch_now = top.get("open_watch_return_pct")
    is_missed_rally = (top.get("current_state") == "관망" and open_watch_now is not None and open_watch_now > MISSED_RALLY_THRESHOLD_PCT)
    low_confidence = low_confidence or is_underwater or is_missed_rally
    opinion_color = "#94a3b8" if low_confidence else (UP_COLOR if opinion == "매수" else DOWN_COLOR)
    # low_confidence는 "백테스트예측" 섹션 자체의 개별 신호 신뢰도 캐주션(그대로 유지)이고,
    # 카드 상단 분류/정렬/index.html 검색필터는 아래 종합의견(4개 요소 합산) 기준으로 갈려요 -
    # 이 둘은 서로 다른 질문에 답하는 별개 장치예요.
    final_opinion = d.get("final_opinion")
    final_label = final_opinion["label"] if final_opinion else opinion
    _fv_color = {"매수": UP_COLOR, "매도": DOWN_COLOR, "관망": "#94a3b8"}[final_label]
    _fv_icon = {"매수": "▲", "매도": "▼", "관망": "-"}[final_label]
    ticker_category[ticker] = {"매수": "buy", "매도": "sell", "관망": "watch"}.get(final_label, "watch")
    sig_bars_ago = top.get("last_signal_bars_ago")
    sig_date = top.get("last_signal_date")
    nx, ny = needle_point(accuracy if accuracy is not None else 50)
    trade_plan = d.get("trade_plan")
    watch_plan = d.get("watch_plan")
    oos_holds_up = d.get("oos_holds_up")
    test_ret = top.get("test_return_pct")
    test_n = top.get("test_num_trades", 0)

    # Same eligibility cascade as analyze_ticker() in backtest_engine.py, so this table always
    # matches the strategies that actually drove top_strategy/opinion/chart - previously this
    # re-derived a separate, looser filter here and could show a different "top 5" than the one
    # behind the rest of the card. Mirrors, in priority order: non-oscillator + enough total
    # trades + enough recent trades + not a stale open position -> relax recency -> relax
    # staleness -> relax oscillator exclusion -> relax trade count entirely.
    _min_tr = d.get("min_trades_for_ranking", 10)
    _min_recent = d.get("min_recent_trades", 2)

    def _stale(r):
        if r.get("current_state") == "매수보유" and r.get("open_trade_return_pct") is not None:
            return r["open_trade_return_pct"] < UNDERWATER_THRESHOLD_PCT
        if r.get("current_state") == "관망" and r.get("open_watch_return_pct") is not None:
            return r["open_watch_return_pct"] > MISSED_RALLY_THRESHOLD_PCT
        return False

    def _osc(r):
        return r.get("category") == "오실레이터"

    _all = [r for r in d["all_results"] if "error" not in r]
    _eligible_rows = [r for r in _all if not _osc(r) and r.get("num_trades", 0) >= _min_tr and r.get("recent_num_trades", 0) >= _min_recent and not _stale(r)]
    if not _eligible_rows:
        _eligible_rows = [r for r in _all if not _osc(r) and r.get("num_trades", 0) >= _min_tr and not _stale(r)]
    if not _eligible_rows:
        _eligible_rows = [r for r in _all if not _osc(r) and r.get("num_trades", 0) >= _min_tr]
    if not _eligible_rows:
        _eligible_rows = [r for r in _all if r.get("num_trades", 0) >= _min_tr]
    if not _eligible_rows:
        _eligible_rows = _all
    ranked = sorted(_eligible_rows, key=lambda r: r["train_return_pct"], reverse=True)[:5]
    top5_rows = "".join(f"""
        <tr>
          <td class="rank">{i+1}</td>
          <td class="sname">{r['name']}<span class="scat">{r['category']}</span></td>
          <td class="state {'buy' if r['current_state']=='매수보유' else ''}">{r['current_state']}</td>
          <td class="num {'pos' if r['train_return_pct']>=0 else 'neg'}">{fmt_pct(r['train_return_pct'])}</td>
          <td class="num {'pos' if (r.get('test_return_pct') or 0)>=0 else 'neg'}">{fmt_pct(r['test_return_pct']) if r.get('test_return_pct') is not None else 'N/A'}</td>
          <td class="num">{fmt_pct(r['win_rate'],0,False) if r['win_rate'] is not None else 'N/A'}</td>
          <td class="num">{r['num_trades']}회</td>
        </tr>""" for i, r in enumerate(ranked))

    trade_plan_html = ""
    if opinion == "매수" and trade_plan:
        tp = trade_plan
        rows = [("매수타점", tp["entry_price"], "지금 가격 기준 (신호가 이미 켜져 있어요)", None)]
        if tp.get("stop_price") is not None:
            rows.append(("손절가", tp["stop_price"], f"이 전략 손실거래 중앙값 {fmt_pct(tp['stop_pct'])} 적용 (표본 {tp['num_losses_sample']}건)", "neg"))
        else:
            rows.append(("손절가", None, f"손실거래 표본 부족(표본 {tp['num_losses_sample']}건) — 표시 안 함", "neg"))
        if tp.get("target1_price") is not None:
            rows.append((f"1차 목표가({tp['target1_horizon_days']}일)", tp["target1_price"], f"이 전략 기대수익률({fmt_pct(exp_ret)}) 반영가", "pos"))
        else:
            rows.append((f"1차 목표가({tp['target1_horizon_days']}일)", None, "단기(10일) 적중률이 낮아 표시 안 함 — 아래 주의문 참고", "pos"))
        hold_days = tp.get("target2_median_hold_days")
        hold_days_txt = f", 평균 도달까지 {hold_days:.0f}거래일" if hold_days is not None else ""
        target2_label = f"2차 목표가(평균 {hold_days:.0f}거래일)" if hold_days is not None else "2차 목표가(기간 불명)"
        if tp.get("target2_price") is not None:
            rows.append((target2_label, tp["target2_price"], f"이 전략 승리거래 중앙값 {fmt_pct(tp['target2_pct'])} 적용 (표본 {tp['num_wins_sample']}건{hold_days_txt})", "pos"))
        else:
            rows.append((target2_label, None, f"승리거래 표본 부족(표본 {tp['num_wins_sample']}건) — 표시 안 함", "pos"))

        row_html = "".join(f"""
          <div class="plan-row">
            <div class="plan-row-main">
              <div class="plan-label">{label}</div>
              <div class="plan-val {cls or ''}">{fmt_num(val) if val is not None else '—'}</div>
            </div>
            <div class="plan-note">{note}</div>
          </div>""" for label, val, note, cls in rows)

        rr_html = f'<div class="plan-rr">위험 대비 보상비(R/R) <b>{tp["risk_reward"]}</b> — 손절폭 1에 대한 2차 목표 기대이익 배수</div>' if tp.get("risk_reward") is not None else ""
        # 2차 목표가 라벨 자체에 "(평균 N거래일)"이 이미 붙어있어 기간을 명시하므로,
        # 아래 별도 경고문(1차 목표가 생략 사유 + 기간 재설명)은 중복이라 제거했다.
        weak_note = ""

        trade_plan_html = f"""
      <div class="block">
        <div class="card-title-row">
          <span class="card-title">매매 플랜</span>
          <span class="info-dot" title="이 전략이 과거 이 종목에서 실제로 냈던 승리/손실 거래의 중앙값 수익률을 그대로 현재가에 적용한 값이에요. 별도의 리스크 관리 공식이 아닙니다.">?</span>
        </div>
        <div class="card-sub">과거 거래 기록 기반 참고용 매매 플랜이에요 (매도 의견 종목은 표시하지 않아요)</div>
        <div class="plan-box">
          {row_html}
        </div>
        {rr_html}
        {weak_note}
      </div>"""

    watch_plan_html = ""
    if opinion == "매도" and watch_plan:
        wp = watch_plan
        wrows = []
        if wp.get("support1_price") is not None:
            wrows.append(("1차 지지선", wp["support1_price"], f"과거 매도신호 이후 저점 중앙값 {fmt_pct(wp['support1_pct'])} (표본 {wp['n_cycles']}건)", "neg"))
        else:
            wrows.append(("1차 지지선", None, f"완결된 매도→매수 사이클 표본 부족(표본 {wp['n_cycles']}건) — 표시 안 함", "neg"))
        if wp.get("support2_price") is not None:
            wrows.append(("2차 지지선", wp["support2_price"], f"더 깊었던 하위 25% 저점 기준 {fmt_pct(wp['support2_pct'])} (표본 {wp['n_cycles']}건)", "neg"))
        else:
            wrows.append(("2차 지지선", None, f"표본 부족(표본 {wp['n_cycles']}건) — 표시 안 함", "neg"))
        if wp.get("wait_days_median") is not None:
            wrows.append(("평균 관망기간", f"{wp['wait_days_median']:.1f}거래일", f"과거 매도신호 이후 다음 매수신호까지 걸린 기간의 중앙값 (표본 {wp['n_cycles']}건)", None))
        else:
            wrows.append(("평균 관망기간", None, f"표본 부족(표본 {wp['n_cycles']}건) — 표시 안 함", None))

        wrow_html = "".join(f"""
          <div class="plan-row">
            <div class="plan-row-main">
              <div class="plan-label">{label}</div>
              <div class="plan-val {cls or ''}">{(fmt_num(val) if isinstance(val, float) else val) if val is not None else '—'}</div>
            </div>
            <div class="plan-note">{note}</div>
          </div>""" for label, val, note, cls in wrows)

        low_sample_note = '<div class="plan-warn">⚠ 이 전략은 이 종목에서 완결된 매도→매수 사이클 표본이 적어(2건 미만) 지지선/관망기간을 계산할 수 없었어요.</div>' if wp["n_cycles"] < 2 else ""

        watch_plan_html = f"""
      <div class="block">
        <div class="card-title-row">
          <span class="card-title">관망 플랜</span>
          <span class="info-dot" title="이 전략이 과거 이 종목에서 매도 신호를 낸 뒤, 실제로 다음 매수 신호가 나오기까지 가격이 얼마나 더 내려갔고 며칠이 걸렸는지의 통계예요. 반등 시점을 예측하는 것이 아닙니다.">?</span>
        </div>
        <div class="card-sub">매도 신호 이후 실제 저점·소요기간 통계예요 (정확한 반등 시점 예측이 아니에요)</div>
        <div class="plan-box">
          {wrow_html}
        </div>
        {low_sample_note}
      </div>"""

    # 밸류에이션 & 애널리스트 컨센서스 - 기술적 신호와 무관한 기본적 지표 스냅샷. ETF/암호화폐는
    # 대부분 필드가 없어 카드 전체를 생략하고, 개별주는 있는 필드만 보여준다 (없는 필드는 N/A).
    fund = d.get("fundamentals") or {}
    has_valuation = any(fund.get(k) is not None for k in ("trailingPE", "priceToBook", "marketCap", "revenueGrowth"))
    has_target = fund.get("targetMeanPrice") is not None
    valuation_html = ""
    if has_valuation or has_target:
        per = fmt_ratio(fund.get("trailingPE"), 1)
        pbr = fmt_ratio(fund.get("priceToBook"), 2)
        mcap = fmt_market_cap(fund.get("marketCap"))
        rev_growth = fmt_pct(fund.get("revenueGrowth") * 100) if fund.get("revenueGrowth") is not None else "N/A"
        valuation_stats_html = f"""
          <div class="stat"><div class="stat-val">{per}</div><div class="stat-label">PER</div></div>
          <div class="stat"><div class="stat-val">{pbr}</div><div class="stat-label">PBR</div></div>
          <div class="stat"><div class="stat-val">{mcap}</div><div class="stat-label">시가총액</div></div>
          <div class="stat"><div class="stat-val">{rev_growth}</div><div class="stat-label">매출성장률(YoY)</div></div>"""

        target_html = ""
        if has_target:
            tmean = fund.get("targetMeanPrice")
            thigh = fund.get("targetHighPrice")
            tlow = fund.get("targetLowPrice")
            n_analysts = fund.get("numberOfAnalystOpinions")
            rec = fmt_recommendation(fund.get("recommendationKey"))
            gap_pct = (tmean - d["last_close"]) / d["last_close"] * 100 if d["last_close"] else None
            gap_cls = "pos" if (gap_pct or 0) >= 0 else "neg"
            analyst_n_txt = f" · 애널리스트 {n_analysts}명" if n_analysts else ""
            target_html = f"""
        <div class="plan-box" style="margin-top:12px;">
          <div class="plan-row analyst-row">
            <div class="plan-row-main">
              <div class="plan-label">애널리스트 목표주가</div>
              <div class="plan-val {gap_cls}">{fmt_num(tmean)}</div>
            </div>
            <div class="plan-note">현재가 대비 {fmt_pct(gap_pct) if gap_pct is not None else 'N/A'} · 최고 {fmt_num(thigh) if thigh is not None else 'N/A'} · 최저 {fmt_num(tlow) if tlow is not None else 'N/A'}{analyst_n_txt}</div>
          </div>
          <div class="plan-row analyst-row">
            <div class="plan-row-main">
              <div class="plan-label">애널리스트 투자의견</div>
              <div class="plan-val">{rec}</div>
            </div>
            <div class="plan-note">Yahoo Finance 애널리스트 컨센서스 (실시간 아님, 참고용)</div>
          </div>
        </div>"""

        valuation_html = f"""
      <div class="block">
        <div class="card-title-row">
          <span class="card-title">밸류에이션 &amp; 애널리스트 컨센서스</span>
          <span class="info-dot" title="기술적 백테스트와 무관한 기본적 지표예요. Yahoo Finance 제공 데이터 기준이며 지연·결측이 있을 수 있어요. ETF·암호화폐는 해당 항목이 대부분 N/A예요.">?</span>
        </div>
        <div class="card-sub">기술적 신호와 별개로 참고할 기본적 지표예요</div>
        <div class="stat-row" style="grid-template-columns: repeat(4, 1fr);">{valuation_stats_html}</div>
        {target_html}
      </div>"""

    # 시그널 신뢰도 추이 - 근거 전략의 방향(매수/매도)이 신호가 날 때마다 직전 10회 기준으로
    # 얼마나 맞았는지 시간순 추이. 위 게이지의 단일 숫자(상위 5개 합산)와는 표본이 달라 값이
    # 일치하지 않을 수 있음을 info-dot에서 명시.
    track_record = d.get("signal_track_record") or []
    track_svg = build_track_record_svg(track_record)
    track_html = ""
    if track_svg:
        latest_acc = track_record[-1]["accuracy_pct"]
        latest_n = track_record[-1]["n"]
        track_html = f"""
      <div class="block detail-extra">
        <div class="card-title-row">
          <span class="card-title">시그널 신뢰도 추이</span>
          <span class="info-dot" title="근거 전략의 {opinion} 신호가 발생할 때마다, 그 시점 기준 직전 최대 10회 신호의 적중률을 시간순으로 표시했어요. 위 게이지 숫자는 상위 5개 전략 합산 중앙값이라 표본이 달라 이 값과 다를 수 있어요.">?</span>
        </div>
        <div class="card-sub">이 전략의 {opinion} 신호가 최근 발생할 때마다 직전 최대 10회 적중률이 어떻게 변해왔는지예요</div>
        <div class="chart-wrap">{track_svg}</div>
        <div class="chart-foot">
          <span class="chart-date">최근 신호 기준 (표본 {latest_n}회)</span>
          <span class="chart-price">{latest_acc:.0f}%</span>
        </div>
      </div>"""

    # 추세 상태: 45개 백테스트 전략과 별개로 상시 켜져 있는 구조적 추세 판정 - 이동평균
    # 정배열/역배열, ADX/DMI 방향, Parabolic SAR 전환 3개 지표의 다수결이에요. 제목+배지는
    # 한 줄로 항상 보이고, 근거가 된 보조지표 3개 상세만 detail-extra로 숨겨서 검색으로
    # 종목 하나를 열었을 때만 (같은 블록 안에서, 지표분석과 나란히) 펼쳐져요.
    trend_block_html = ""
    ts = d.get("trend_status")
    if ts:
        ts_up = ts["overall"] == "up"
        ts_color = UP_COLOR if ts_up else DOWN_COLOR
        ts_icon = "▲" if ts_up else "▼"
        ts_label = "상승추세 유지" if ts_up else "상승추세 이탈"

        def _trend_item(label_txt, val_txt, is_up):
            c = UP_COLOR if is_up else DOWN_COLOR
            arrow = "▲" if is_up else "▼"
            return f"""
            <div class="trend-item">
              <div class="trend-item-label">{label_txt}</div>
              <div class="trend-item-val" style="color:{c}">{arrow} {val_txt}</div>
            </div>"""

        ma_up = ts["ma_vote"] == "up"
        adx_up = ts["adx_vote"] == "up"
        sar_up = ts["sar_vote"] == "up"
        trend_items_html = (
            _trend_item(
                f"이동평균({ts['ma_fast']}/{ts['ma_slow']})",
                f"{'정배열' if ma_up else '역배열'} ({fmt_num(ts['ma_fast_value'])} / {fmt_num(ts['ma_slow_value'])})",
                ma_up,
            )
            + _trend_item("ADX/DMI", f"+DI {ts['plus_di']} · -DI {ts['minus_di']} (ADX {ts['adx_value']})", adx_up)
            + _trend_item("Parabolic SAR", f"{'상승 전환 중' if sar_up else '하락 전환 중'} (SAR {fmt_num(ts['sar_value'])})", sar_up)
        )

        trend_block_html = f"""
      <div class="block">
        <div class="card-title-row">
          <span class="card-title">추세상태</span>
          <span class="info-dot" title="45개 백테스트 전략과 별개로, 상시 켜져 있는 추세 판정이에요. 이동평균({ts['ma_fast']}/{ts['ma_slow']}) 정배열, ADX/DMI 방향, Parabolic SAR 전환 3개 지표 중 2개 이상이 가리키는 방향으로 판정해요. 근거가 된 지표 3개는 종목 검색으로 열면 볼 수 있어요.">?</span>
          <span class="trend-chip" style="background:{ts_color}1a;color:{ts_color}">{ts_icon} {ts_label} <span class="trend-votes">({ts['up_votes']}/{ts['total_votes']} 지표 일치)</span></span>
        </div>
        <div class="trend-detail-grid detail-extra">{trend_items_html}
        </div>
      </div>"""

    # 옵션포지셔닝: 콜월/풋월(감마 익스포저 최대 행사가 - 2026-08-28부터 단순 OI 최대값에서
    # 변경, 아래 opt-item 설명·info-dot 참고) 대비 현재가 위치 + 풋/콜 비율을
    # 이용한 간단한 강세/약세 판정 - 이 4개(콜월/풋월/풋콜비율/현재가위치)만 점수 계산과
    # 화면 표시 둘 다에 쓰고, 넷감마·맥스페인·IV 스큐는 2026-08-25 사용자 요청으로 점수뿐
    # 아니라 카드 표시에서도 완전히 뺐어요(fetch_options.py는 계속 계산/저장은 하지만
    # 여기서 안 읽어요 - 나중에 다시 필요하면 opt.get("net_gex") 등으로 꺼내 쓸 수 있어요).
    # 추세상태와 같은 패턴으로, 배지는 항상 보이고 상세 수치는 detail-extra로 숨겨서
    # 검색으로 종목 하나를 열었을 때만 펼쳐져요.
    # 미국 옵션시장에 상장 안 된 종목(BTC, 삼성전자, SK하이닉스 등)은 이 블록 자체가 없어요.
    options_block_html = ""
    opt = d.get("options")
    if opt:
        opt_score = None
        if final_opinion:
            comp = final_opinion["components"].get("옵션포지셔닝")
            opt_score = comp["score"] if comp else None
        opt_up = (opt_score if opt_score is not None else 0) >= 0
        opt_color = UP_COLOR if opt_up else DOWN_COLOR
        opt_icon = "▲" if opt_up else "▼"
        opt_label = "옵션 강세" if opt_up else "옵션 약세"
        spot = d["last_close"]
        call_wall = opt.get("call_wall")
        put_wall = opt.get("put_wall")

        # 옵션 초보도 이해할 수 있게, 라벨을 크고 진하게 + 무엇을 뜻하는지 설명 한 줄을 항상
        # 붙여요 (호버해야만 보이는 info-dot 툴팁만으론 부족하다는 피드백 반영).
        def _opt_item(label_txt, desc_txt, val_txt, is_up):
            c = UP_COLOR if is_up else DOWN_COLOR
            arrow = "▲" if is_up else "▼"
            return f"""
            <div class="opt-item">
              <div class="opt-item-top">
                <div class="opt-item-label">{label_txt}</div>
                <div class="opt-item-val" style="color:{c}">{arrow} {val_txt}</div>
              </div>
              <div class="opt-item-desc">{desc_txt}</div>
            </div>"""

        pcr = opt.get("put_call_oi_ratio")
        pcr_bias = opt.get("put_call_oi_ratio_bias")
        pcr_html = _opt_item(
            "풋/콜 비율",
            "1보다 크면 하락 방어(풋) 수요 우위, 낮으면 상승 베팅(콜) 수요 우위예요.",
            f"{pcr:.2f} · {pcr_bias}" if pcr is not None else "N/A",
            pcr <= 1.0,
        ) if pcr is not None else ""

        _wall_pos_txt = "정상범위"
        if call_wall is not None and spot > call_wall:
            _wall_pos_txt = "콜월 돌파"
        elif put_wall is not None and spot < put_wall:
            _wall_pos_txt = "풋월 이탈"
        # 콜월/풋월 화살표는 "가격이 이 벽을 어느 방향으로 벗어났는지"가 아니라 "현재 이 벽
        # 기준으로 강세/약세 신호인지"를 색으로 표시해요 - 콜월 돌파(저항 상향 돌파)는 강세,
        # 풋월 이탈(지지 하향 이탈)은 약세로, 옵션포지셔닝 점수 계산 로직과 방향을 맞췄어요.
        options_items_html = (
            _opt_item(
                "콜월 (저항선)",
                "콜 감마 익스포저(미결제약정 x 감마)가 가장 큰 가격대 — 뚫고 오르면 상승 압력이 붙어요.",
                f"{fmt_num(call_wall) if call_wall is not None else 'N/A'} — 현재가 대비 {fmt_pct((call_wall/spot-1)*100) if call_wall else 'N/A'}",
                spot > (call_wall or spot),
            )
            + _opt_item(
                "풋월 (지지선)",
                "풋 감마 익스포저(미결제약정 x 감마)가 가장 큰 가격대 — 하향 이탈하면 하락 압력이 붙어요.",
                f"{fmt_num(put_wall) if put_wall is not None else 'N/A'} — 현재가 대비 {fmt_pct((put_wall/spot-1)*100) if put_wall else 'N/A'}",
                spot > (put_wall or spot),
            )
            + pcr_html
            + _opt_item(
                "현재가 위치 · 만기",
                "만기가 가까울수록 콜월·풋월의 영향력이 커지는 경향이 있어요.",
                f"{_wall_pos_txt} · {opt.get('expiration', 'N/A')} ({opt.get('days_out', '?')}일 남음)",
                _wall_pos_txt != "풋월 이탈",
            )
        )

        options_block_html = f"""
      <div class="block">
        <div class="card-title-row">
          <span class="card-title">옵션포지셔닝</span>
          <span class="info-dot" title="미국 옵션시장에 상장된 종목만 표시돼요. 만기 약 30일짜리 옵션체인에서 콜/풋 감마 익스포저(미결제약정 x 블랙숄즈 감마)가 가장 큰 행사가를 각각 콜월(저항)·풋월(지지)로 보고(단순 미결제약정 최대값은 감마가 거의 0인 죽은 딥아웃오브더머니 행사가에 왜곡되기 쉬워 2026-08-28부터 감마 가중 방식으로 변경), 현재가가 그 구간 어디에 있는지(콜월 돌파=+100, 풋월 이탈=-100, 그 사이는 위치 비율)와 풋/콜 OI 비율(1.0=중립, 풋 많을수록 약세, 콜 많을수록 강세)을 동일 가중으로 평균해 점수를 매기는 단순 휴리스틱이지 실제 딜러 포지션 분석이 아니에요.">?</span>
          <span class="trend-chip" style="background:{opt_color}1a;color:{opt_color}">{opt_icon} {opt_label}{f' ({opt_score:+.0f}점)' if opt_score is not None else ''}</span>
        </div>
        <div class="trend-detail-grid detail-extra">{options_items_html}
        </div>
      </div>"""

    chart_svg = build_chart_svg(d.get("chart_data"))
    _test_ret = top.get("test_return_pct")
    _test_n = top.get("test_num_trades", 0) or 0
    _stale_unavoidable = d.get("fallback_reason") == "stale_open_position_unavoidable"
    _stale_prefix = "이 종목은 지금 상태가 멀쩡한 전략이 하나도 없어서 부득이하게 이 전략을 대표전략으로 썼어요. " if _stale_unavoidable else ""
    chart_warn = ""
    if is_underwater:
        chart_warn = f'<div class="plan-warn">⚠ {_stale_prefix}이 전략은 지금 보유 중인 포지션이 진입가 대비 {fmt_pct(open_ret_now)} 손실 상태예요 — 마지막 매수 신호({sig_bars_ago}거래일 전, {top.get("last_signal_date")}) 이후 가격이 불리하게 움직였는데도 아직 매도 신호가 안 나왔어요. 위 매수 의견을 그대로 믿지 마세요.</div>'
    elif is_missed_rally:
        chart_warn = f'<div class="plan-warn">⚠ {_stale_prefix}이 전략은 매도 이후 가격이 {fmt_pct(open_watch_now)} 올랐는데도 아직 매수(재진입) 신호가 안 나왔어요 — 마지막 매도 신호({sig_bars_ago}거래일 전, {top.get("last_signal_date")}) 이후 상승분을 놓치고 있는 상태예요. 위 매도 의견을 그대로 믿지 마세요.</div>'
    elif d.get("thin_fallback") and d.get("fallback_reason") == "no_recent_activity":
        min_recent = d.get("min_recent_trades", 2)
        chart_warn = f'<div class="plan-warn">⚠ 이 종목은 최근 1년간 {min_recent}회 이상 거래한 전략이 하나도 없어서, 최근 활동이 뜸한 전략을 대표전략으로 썼어요 — 마지막 화살표 이후 가격이 많이 움직였어도 그 사이엔 아무 신호가 없었다는 뜻이에요. 아래 상태를 그대로 믿지 말고 참고만 하세요.</div>'
    elif d.get("thin_fallback") and d.get("fallback_reason") == "oscillator_unavoidable":
        chart_warn = f'<div class="plan-warn">⚠ 이 종목은 과매수/과매도 구간에서 미리 매매하는 오실레이터 계열 지표({top["name"]})만 기준을 통과해서, 부득이하게 이를 대표전략으로 썼어요 — 추세를 끝까지 타지 않고 중간에 선반영해서 매매하는 방식이라 차트상 타이밍이 다소 이르게/늦게 보일 수 있어요.</div>'
    elif d.get("thin_fallback"):
        min_tr = d.get("min_trades_for_ranking", 10)
        chart_warn = f'<div class="plan-warn">⚠ 이 종목은 최근 3년간 {min_tr}회 이상 거래한 전략이 하나도 없어서, 기준에 못 미치는 전략(매매 {top.get("num_trades", "N/A")}회)을 어쩔 수 없이 대표전략으로 썼어요 — 표본이 매우 적어 신뢰하기 어려워요.</div>'
    elif _test_n == 0:
        chart_warn = '<div class="plan-warn">⚠ 이 종목의 대표 전략은 최근 검증구간(약 25%)에서 한 번도 매매하지 않았어요 — 최근 신뢰도를 검증하기엔 표본이 부족해요.</div>'
    elif _test_ret is not None and _test_ret < 0:
        chart_warn = f'<div class="plan-warn">⚠ 이 종목의 대표 전략은 최근 검증구간에서 {fmt_pct(_test_ret)} 손실을 냈어요 — 최근엔 학습구간만큼 예측력이 좋지 않았어요.</div>'
    chart_html = f"""
      <div class="block">
        <div class="card-title-row">
          <span class="card-title">가격 차트 (최근 1년)</span>
          <span class="info-dot" title="지표분석·추세상태·백테스트예측(옵션포지셔닝은 과거 데이터가 없어 제외) 3가지를 합쳐 종합의견이 매수/매도로 바뀐 시점을 최근 1년 구간에 근사적으로 표시했어요. 가장 최근(오늘) 화살표만은 옵션포지셔닝까지 포함한 실제 종합의견과 항상 일치해요.">?</span>
        </div>
        <div class="card-sub">▲ 매수전환 &nbsp; ▼ 매도전환 (종합의견 기준, 과거는 근사치)</div>
        <div class="chart-wrap">{chart_svg}</div>
        <div class="chart-foot">
          <span class="chart-date">{d['last_date']} 종가</span>
          <span class="chart-price">{fmt_num(d['last_close'])}</span>
        </div>
        {chart_warn}
      </div>""" if chart_svg else ""

    # 종합의견 게이지 - 예전엔 여기가 "백테스트예측" 하나만의 과거 적중률 게이지를 재활용한
    # 자리였는데, 종합의견은 지표분석/추세상태/백테스트예측/옵션포지셔닝 4개를 합친 값이라
    # 데이터가 안 맞았어요 (사용자 피드백 반영). 이제는 실제 종합점수(-100~+100)를 매도/관망/매수
    # 3개 구간으로 색칠한 반원 게이지에 그대로 표시해요 - 바늘 위치 = 실제 종합점수.
    if final_opinion:
        _fv_pct = max(0.0, min(100.0, (final_opinion["combined_score"] + 100) / 2))
        _band_pct = max(0.0, min(100.0, (100 - final_opinion["band"]) / 2))  # 매도/관망 경계 (점수 -band)
        _band_pct_hi = 100 - _band_pct  # 관망/매수 경계 (점수 +band, 대칭)
        _zone_lo_x, _zone_lo_y = arc_point(_band_pct)
        _zone_hi_x, _zone_hi_y = arc_point(_band_pct_hi)
        _gauge_nx, _gauge_ny = needle_point(_fv_pct)
        predict_box_html = f"""
          <div class="gauge-wrap">
            <svg viewBox="0 0 200 110" class="gauge">
              <path d="M 20,100 A 80,80 0 0 1 {_zone_lo_x:.1f},{_zone_lo_y:.1f}" fill="none" stroke="{DOWN_COLOR}" stroke-width="14" stroke-linecap="round"/>
              <path d="M {_zone_lo_x:.1f},{_zone_lo_y:.1f} A 80,80 0 0 1 {_zone_hi_x:.1f},{_zone_hi_y:.1f}" fill="none" stroke="#cbd5e1" stroke-width="14"/>
              <path d="M {_zone_hi_x:.1f},{_zone_hi_y:.1f} A 80,80 0 0 1 180,100" fill="none" stroke="{UP_COLOR}" stroke-width="14" stroke-linecap="round"/>
              <line x1="100" y1="100" x2="{_gauge_nx:.1f}" y2="{_gauge_ny:.1f}" stroke="#1e293b" stroke-width="3" stroke-linecap="round"/>
              <circle cx="100" cy="100" r="6" fill="#1e293b"/>
            </svg>
            <div class="gauge-caption">종합점수 <b style="color:{_fv_color}">{final_opinion['combined_score']:+.0f}</b>점 <span class="gauge-n">(매도 ≤-{final_opinion['band']:.0f} · 관망 · 매수 ≥+{final_opinion['band']:.0f})</span></div>
          </div>

          <div class="opinion-chip" style="background:{_fv_color}1a;color:{_fv_color}">종합의견 &nbsp;<b>{final_label}</b></div>
        """
    else:
        predict_box_html = '<div class="card-sub">종합의견을 계산할 데이터가 부족해요.</div>'

    # 종합의견: 지표분석/추세상태/백테스트예측/(있으면)옵션포지셔닝 4개를 동일 가중으로 합산한
    # 카드 상단 헤드라인 판정. 개별 섹션(위 지표분석·추세상태·백테스트예측)은 각자 그대로 남아있고,
    # 이건 그 4개를 한 번에 보여주는 요약일 뿐 - 근거는 아래로 스크롤해서 직접 확인 가능해요.
    final_verdict_html = ""
    if final_opinion:
        _comp_rows = ""
        for _cname, _cval in final_opinion["components"].items():
            _cscore = _cval["score"]
            _cw = _cval["weight_pct"]
            _cbarcolor = UP_COLOR if _cscore > 0 else (DOWN_COLOR if _cscore < 0 else "#94a3b8")
            _cpos = max(0.0, min(100.0, (_cscore + 100) / 2))
            _comp_rows += f"""
            <div class="fv-comp-row">
              <div class="fv-comp-label">{_cname} <span class="fv-comp-weight">({_cw:.0f}%)</span></div>
              <div class="fv-comp-bar"><div class="fv-comp-bar-fill" style="left:{_cpos:.1f}%;background:{_cbarcolor}"></div><div class="fv-comp-bar-mid"></div></div>
              <div class="fv-comp-score" style="color:{_cbarcolor}">{_cscore:+.0f}</div>
            </div>"""
        _missing_note = ""
        if final_opinion["missing"]:
            _missing_note = f'<div class="fv-missing-note">데이터 없어 제외됨: {", ".join(final_opinion["missing"])} (해당 항목 제외하고 나머지를 동일 가중 재계산했어요)</div>'
        # 왼쪽: 기존 "백테스트 예측" 게이지(적중률 반원 게이지 + 투자의견 칩 + 신호 발생 시점) -
        # 보기 좋다고 해서 그대로 재사용, 자리만 종합의견 왼쪽으로 옮겼어요. 오른쪽: 4개 요소
        # 합산 점수 막대 목록. 좁은 화면(그리드 여러 카드 모드)에서는 위/아래로 쌓여요.
        final_verdict_html = f"""
      <div class="wide-row">
      <div class="block final-verdict-block" style="border:2px solid {_fv_color}66;background:#fdf8ee;box-shadow:0 1px 3px rgba(0,0,0,0.06)">
        <div class="card-title-row">
          <span class="card-title">종합의견</span>
          <span class="info-dot" title="지표분석(45개 중 활성 전략 매수/매도 비율), 추세상태(MA/ADX-DMI/SAR 다수결), 백테스트예측(상위 5개 전략 다수결), 옵션포지셔닝(콜월/풋월 대비 현재가 위치 + 감마 익스포저, 미국 옵션시장 상장 종목만) - 이 4개(옵션 데이터 없으면 3개)를 각각 -100~+100점으로 환산해 동일 가중 평균한 뒤, 종합점수가 +{final_opinion['band']:.0f} 이상이면 매수, -{final_opinion['band']:.0f} 이하면 매도, 그 사이는 관망으로 판정해요. 간단한 규칙 기반 합산이지 AI 예측이 아니에요.">?</span>
          <span class="final-verdict-chip" style="background:{_fv_color}1a;color:{_fv_color}">{_fv_icon} {final_label} <span class="fv-score">(종합점수 {final_opinion['combined_score']:+.0f})</span></span>
        </div>
        <div class="fv-layout">
          <div class="fv-left">{predict_box_html}</div>
          <div class="fv-right">
            <div class="fv-comp-list">{_comp_rows}</div>
            {_missing_note}
          </div>
        </div>
      </div>
      </div>"""

    card_html_by_ticker[ticker] = (f"""
    <div class="ticker-card" id="ticker-{ticker}" data-ticker="{ticker}" data-label="{label}">
      <div class="section-head">
        <div class="ticker">{ticker}<span class="label">{label}</span>{'<span class="short-history-badge">표본 짧음 (' + str(d.get('num_bars', 0)) + '봉)</span>' if d.get('short_history_warning') else ''}</div>
        {f'<div class="price-block"><div class="price">{fmt_num(d["last_close"])}</div><div class="pricedate">{d["last_date"]} 종가</div></div>' if not chart_svg else ''}
      </div>
      {chart_html}

      {final_verdict_html}

      <div class="wide-row row-indicator-trend">
      <div class="block">
        <div class="card-title-row">
          <span class="card-title">지표분석</span>
          <span class="info-dot" title="45개 매매전략 중 최근 3년간 10회 이상, 그리고 최근 1년 내에도 2회 이상 거래한 전략만 모아, 지금 몇 개가 매수/매도 포지션인지 보여줘요. 참고용 분포이며, 바로 위 종합의견은 이 값을 포함한 4개 요소를 합산한 값이에요.">?</span>
          <span class="inline-signal-summary">
            <span style="color:{UP_COLOR}">▲ 매수 {buy_pct:.1f}%</span>
            <span style="color:{DOWN_COLOR}">▼ 매도 {sell_pct:.1f}%</span>
          </span>
        </div>
        <div class="indicator-bar"><div class="indicator-bar-seg buy" style="width:{buy_pct}%"></div><div class="indicator-bar-seg sell" style="width:{sell_pct}%"></div></div>
        <div class="indicator-bar-legend">
          <span><i class="dot buy"></i>매수 {buy_hold_n}건</span>
          <span><i class="dot sell"></i>매도 {sell_n}건</span>
          <span class="indicator-bar-total">총 {active_n}개 전략 기준</span>
        </div>
        <div class="card-sub" style="margin-top:12px">검증된 45개 전략 중 최근 충분히 거래된 {active_n}개의 현재 포지션 분포예요 (참고용 — 바로 위 종합의견의 구성요소 중 하나예요)</div>
      </div>
      {trend_block_html}
      </div>

      <div class="wide-row row-top5-track">
      <div class="block">
        <div class="card-title-row">
          <span class="card-title">백테스트 예측</span>
          <span class="info-dot" title="별도 AI 모델이 아니라, 학습구간 수익률 상위 5개 전략(위 지표분석과 동일하게 충분히 거래된 전략만 후보)의 현재 포지션을 다수결로 모으고, 그 중 의견이 일치하는 전략들의 과거 매매 통계를 중앙값으로 계산한 값이에요. 위 지표분석은 그 후보군 전체의 매수/매도 비율이라 표본 크기가 달라 숫자는 다를 수 있지만, 같은 전략 풀을 기준으로 해요.">?</span>
          <span class="trend-chip" style="background:{opinion_color}1a;color:{opinion_color}">{'▲' if opinion=='매수' else '▼'} {opinion}{' (신뢰도 낮음)' if low_confidence else ''}</span>
        </div>
        <div class="card-sub">상위 5개 전략 중 <b style="color:{opinion_color}">{vote_buy if opinion=='매수' else vote_total-vote_buy}/{vote_total}개</b>가 <b style="color:{opinion_color}">'{opinion}'</b> 상태 — 다수결로 낸 의견이에요 (위 지표분석과 같은 전략 풀 기준, 표본 크기 차이로 비율은 다를 수 있어요)</div>
        <div class="top5-scroll">
        <table class="top5">
          <thead><tr><th>순위</th><th>전략</th><th>현재상태</th><th>학습수익률</th><th>검증수익률</th><th>승률</th><th>매매</th></tr></thead>
          <tbody>{top5_rows}</tbody>
        </table>
        </div>
      </div>
      {options_block_html if options_block_html else track_html}
      </div>

      <div class="wide-row row-track-plan">
      {track_html if options_block_html else ''}
      {trade_plan_html}
      {watch_plan_html}
      </div>
      <div class="detail-extra">
        {valuation_html}
      </div>
    </div>
    """)

# Assemble the final grid: cards grouped under sector headings (each ticker-card div is
# grid-column-spanned to sit as a full-width divider), sorted 매수-first within each sector.
# Any ticker not covered by SECTOR_GROUPS lands in an auto "기타" bucket at the end so a
# forgotten classification never silently drops a ticker from the report.
classified = set()
sector_sections_html = []
nav_links_html = []
_sector_idx = 0
for sector_name, tickers_in_sector in SECTOR_GROUPS:
    present = [t for t in tickers_in_sector if t in card_html_by_ticker]
    if not present:
        continue
    present.sort(key=lambda t: _SORT_RANK.get(_final_label(data[t]), 1))
    classified.update(present)
    # index-based id, not slugified from the (Korean) sector name - a regex slug of Korean
    # text collapses to empty/duplicate ids (Korean chars all match "non a-zA-Z0-9"), which
    # broke both the nav links and made two different sectors share one anchor.
    anchor_id = f"sector-{_sector_idx}"
    _sector_idx += 1
    nav_links_html.append(f'<a href="#{anchor_id}" class="sector-nav-link">{sector_name} <span class="sector-nav-count">{len(present)}</span></a>')
    cards = "".join(card_html_by_ticker[t] for t in present)
    sector_sections_html.append(f'<div class="sector-heading" id="{anchor_id}">{sector_name} <span class="sector-count">{len(present)}개</span></div>{cards}')

leftover = [t for t, _ in ordered_items if t not in classified]
if leftover:
    anchor_id = f"sector-{_sector_idx}"
    nav_links_html.append(f'<a href="#{anchor_id}" class="sector-nav-link">기타 <span class="sector-nav-count">{len(leftover)}</span></a>')
    cards = "".join(card_html_by_ticker[t] for t in leftover)
    sector_sections_html.append(f'<div class="sector-heading" id="{anchor_id}">기타 <span class="sector-count">{len(leftover)}개</span></div>{cards}')

sections = sector_sections_html
sector_nav_html = "".join(nav_links_html)

if meta.get("generated_at"):
    _gen_dt = datetime.fromisoformat(meta["generated_at"])
    # generated_at 은 KST로 기록되게 고쳤지만(build_results.py/run_daily_pipeline.py),
    # 예전 아카이브 데이터처럼 타임존 정보가 없는 naive 값이 섞여 들어와도 안전하게
    # "이미 KST 벽시계 시각"으로 취급 - UTC로 잘못 재해석해서 9시간 밀리는 일이 없게 한다.
    if _gen_dt.tzinfo is None:
        now = _gen_dt.strftime("%Y-%m-%d %H:%M")
    else:
        now = _gen_dt.astimezone(KST).strftime("%Y-%m-%d %H:%M")
else:
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")

fail_banner_html = ""
if failed_tickers:
    fail_list = ", ".join(f"{t}({reason})" for t, reason in failed_tickers.items())
    fail_banner_html = f"""
  <div class="fail-banner">
    ⚠ 오늘 데이터를 못 가져온 종목이 있어요: {fail_list} — 이 종목들은 리포트에서 빠졌습니다.
  </div>"""

html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>고버니 트레이딩 센터 핵심 종목 지표분석</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, "Pretendard", "Malgun Gothic", sans-serif;
    background: #f1f5f9; margin: 0; padding: 28px 20px; color: #0f172a;
  }}
  .header {{ max-width: 1240px; margin: 0 auto 20px; }}
  .brand-row {{ display: flex; align-items: center; gap: 14px; margin-bottom: 8px; }}
  .brand-badge {{
    width: 44px; height: 44px; border-radius: 12px; flex-shrink: 0;
    background: linear-gradient(135deg, #1e293b 0%, #0f172a 55%, {UP_COLOR} 130%);
    color: #fff; font-size: 20px; font-weight: 800; display: flex; align-items: center;
    justify-content: center; letter-spacing: -0.5px; box-shadow: 0 2px 8px rgba(15,23,42,0.25);
  }}
  .brand-text {{ display: flex; flex-direction: column; gap: 2px; }}
  .brand-wordmark {{ font-size: 10.5px; font-weight: 800; color: #64748b; letter-spacing: 2.5px; }}
  .header h1 {{ font-size: 23px; margin: 0; font-weight: 800; letter-spacing: -0.2px; }}
  .brand-accent {{ color: {UP_COLOR}; }}
  .header .sub {{ color: #64748b; font-size: 12.5px; }}
  .back-link {{
    display: inline-flex; align-items: center; gap: 5px; margin-top: 12px; font-size: 12px;
    font-weight: 700; color: #4f46e5; text-decoration: none; background: #eef2ff;
    border-radius: 8px; padding: 6px 12px;
  }}
  .disclaimer {{
    max-width: 1240px; margin: 0 auto 22px; background: #fffbeb; border: 1px solid #fde68a;
    border-radius: 10px; padding: 10px 16px; font-size: 12px; color: #92400e; line-height: 1.6; cursor: help;
  }}
  .disclaimer-more {{ color: #b45309; font-size: 10.5px; }}
  .fail-banner {{
    max-width: 1240px; margin: 0 auto 14px; background: #fef2f2; border: 1px solid #fecaca;
    border-radius: 10px; padding: 10px 16px; font-size: 12px; color: #991b1b; line-height: 1.6;
  }}
  .short-history-badge {{
    display: inline-block; font-size: 10px; font-weight: 700; color: #92400e; background: #fef3c7;
    border-radius: 6px; padding: 2px 7px; margin-left: 8px; vertical-align: middle;
  }}
  .grid {{
    max-width: 1240px; margin: 0 auto; display: grid;
    grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 18px; align-items: start;
  }}
  .sector-heading {{
    grid-column: 1 / -1; scroll-margin-top: 14px;
    font-size: 15px; font-weight: 800; color: #0f172a;
    padding: 10px 4px 4px; margin-top: 6px; border-bottom: 2px solid #0f172a;
    display: flex; align-items: baseline; gap: 8px;
  }}
  .grid > .sector-heading:first-child {{ margin-top: 0; }}
  .sector-count {{ font-size: 11.5px; font-weight: 600; color: #94a3b8; }}
  .sector-nav {{
    max-width: 1240px; margin: 0 auto 16px; display: flex; flex-wrap: wrap; gap: 6px;
  }}
  .sector-nav-link {{
    font-size: 11.5px; font-weight: 700; color: #334155; background: #fff;
    border: 1px solid #e2e8f0; border-radius: 8px; padding: 5px 10px; text-decoration: none;
  }}
  .sector-nav-link:hover {{ border-color: {UP_COLOR}; color: {UP_COLOR}; }}
  .sector-nav-count {{ color: #94a3b8; font-weight: 600; }}

  .ticker-card {{
    background: #fff; border: 1px solid #e2e8f0; border-radius: 18px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05); overflow: hidden;
  }}
  .section-head {{
    display: flex; justify-content: space-between; align-items: flex-end;
    padding: 16px 18px; background: #0f172a; color: #fff;
  }}
  .ticker {{ font-size: 19px; font-weight: 800; }}
  .ticker .label {{ font-size: 11.5px; font-weight: 500; color: #cbd5e1; margin-left: 8px; }}
  .price-block {{ text-align: right; }}
  .price {{ font-size: 15px; font-weight: 700; }}
  .pricedate {{ font-size: 10.5px; color: #94a3b8; }}
  .chart-foot {{
    display: flex; justify-content: space-between; align-items: baseline;
    margin-top: 8px; padding-top: 10px; border-top: 1px dashed #e2e8f0;
  }}
  .chart-foot .chart-date {{ font-size: 12px; color: #94a3b8; }}
  .chart-foot .chart-price {{ font-size: 22px; font-weight: 800; color: #0f172a; }}

  .block {{ padding: 16px 18px 18px; border-top: 1px solid #eef1f5; }}
  .ticker-card .block:first-of-type {{ border-top: none; }}
  .indicator-bar {{
    display: flex; height: 10px; border-radius: 6px; overflow: hidden;
    margin-top: 24px; background: #f1f5f9;
  }}
  .indicator-bar-seg.buy {{ background: {UP_COLOR}; }}
  .indicator-bar-seg.sell {{ background: {DOWN_COLOR}; }}
  .indicator-bar-legend {{
    display: flex; align-items: center; gap: 14px; margin-top: 10px;
    font-size: 11.5px; color: #475569;
  }}
  .indicator-bar-legend .dot {{
    display: inline-block; width: 8px; height: 8px; border-radius: 50%;
    margin-right: 5px; vertical-align: middle;
  }}
  .indicator-bar-legend .dot.buy {{ background: {UP_COLOR}; }}
  .indicator-bar-legend .dot.sell {{ background: {DOWN_COLOR}; }}
  .indicator-bar-legend .indicator-bar-total {{ margin-left: auto; color: #94a3b8; }}
  .trend-chip {{
    display: inline-block; font-size: 13px; font-weight: 700; border-radius: 10px;
    padding: 5px 10px; margin-left: auto; white-space: nowrap;
  }}
  .trend-votes {{ font-size: 10.5px; font-weight: 500; opacity: 0.75; }}
  /* 항상 세로 1칸 - 3칸으로 나누면 값 텍스트("역배열 (70.13 / 90.55)" 등)가 좁은 칸 안에서
     줄바꿈되어 지저분해지므로, 각 항목이 컨테이너 전체 폭을 써서 한 줄에 들어가게 한다. */
  .trend-detail-grid {{
    display: grid; grid-template-columns: 1fr;
    gap: 8px; margin-top: 10px;
  }}
  .trend-item {{ background: #f8fafc; border-radius: 10px; padding: 8px 10px; display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }}
  .trend-item-label {{ font-size: 10.5px; color: #94a3b8; white-space: nowrap; }}
  .trend-item-val {{ font-size: 12px; font-weight: 700; white-space: nowrap; text-align: right; }}
  /* 옵션포지셔닝 전용 - 초보자도 보게 라벨을 크고 진하게, 설명 문장을 항상 붙여요 */
  /* 2026-08-25: 옵션포지셔닝이 백테스트예측 옆으로 옮겨가면서, 다른 detail 항목(추세상태 등)과
     글자 크기를 맞췄어요 - 예전엔 "옵션 초보 배려"로 일부러 더 크고 굵게 했었는데, 이제
     다른 블록들과 나란히 붙다 보니 그것만 튀어 보여서 통일했어요. */
  .opt-item {{ background: #f8fafc; border-radius: 10px; padding: 8px 10px; }}
  .opt-item-top {{ display: flex; align-items: baseline; justify-content: space-between; gap: 10px; flex-wrap: wrap; }}
  .opt-item-label {{ font-size: 10.5px; color: #94a3b8; white-space: nowrap; }}
  .opt-item-val {{ font-size: 12px; font-weight: 700; white-space: nowrap; text-align: right; }}
  .opt-item-desc {{ font-size: 10.5px; color: #94a3b8; margin-top: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .final-verdict-block {{ border-radius: 14px; border: 1.5px solid #eef1f5; padding: 14px 16px 16px; }}
  .final-verdict-chip {{
    display: inline-flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 700;
    border-radius: 10px; padding: 5px 10px; margin-left: auto; white-space: nowrap;
  }}
  .fv-score {{ font-size: 10.5px; font-weight: 500; opacity: 0.75; }}
  .fv-layout {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 22px; margin-top: 14px; align-items: start; }}
  .fv-left {{ border-right: 1px dashed #e2e8f0; padding-right: 22px; }}
  .fv-right {{ min-width: 0; display: flex; flex-direction: column; justify-content: center; }}
  @media (max-width: 480px) {{ .fv-left {{ border-right: none; border-bottom: 1px dashed #e2e8f0; padding-right: 0; padding-bottom: 14px; }} }}
  .fv-comp-list {{ display: flex; flex-direction: column; gap: 22px; }}
  .fv-comp-row {{ display: grid; grid-template-columns: 140px 1fr 56px; align-items: center; gap: 14px; }}
  .fv-comp-label {{ font-size: 14.5px; font-weight: 600; color: #475569; white-space: nowrap; }}
  .fv-comp-weight {{ color: #94a3b8; font-weight: 500; }}
  .fv-comp-bar {{ position: relative; height: 11px; border-radius: 6px; background: #eef1f5; }}
  .fv-comp-bar-fill {{ position: absolute; top: 0; bottom: 0; width: 5px; border-radius: 3px; transform: translateX(-50%); }}
  .fv-comp-bar-mid {{ position: absolute; left: 50%; top: -3px; bottom: -3px; width: 1px; background: #cbd5e1; }}
  .fv-comp-score {{ font-size: 16px; font-weight: 800; text-align: right; }}
  .fv-missing-note {{ margin-top: 12px; font-size: 11px; color: #94a3b8; }}
  .wide-row {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 16px; padding: 16px 18px 18px; border-top: 1px solid #eef1f5;
  }}
  .wide-row .block {{
    border-top: none; border: 1px solid #eef1f5; border-radius: 14px; padding: 14px 16px 16px;
  }}
  /* 지표분석(짧은 텍스트) vs 추세상태 상세(3개 항목) - 검색으로 카드 1개만 볼 때(폭이
     넓을 때)만 내용량에 맞춰 2칸으로 나누고, 그리드에서 여러 카드가 나란히 있을 때는
     카드 자체 폭이 좁으므로 항상 1칸(세로쌓기)으로 둔다 - 뷰포트 폭이 아니라 카드가
     속한 모드(#ticker-grid.single-view)로 판단해야 여러 열 그리드에서 깨지지 않는다. */
  /* grid + align-items:start만으로는 두 블록 높이가 안 맞을 때 짧은 쪽 박스가 여전히
     행 높이만큼 늘어나 보이는 경우가 있어, 아예 flex로 바꿔 각 박스가 자기 내용
     높이만큼만 차지하도록 확실히 고정한다(align-self로 다시 늘어날 여지를 없앰). */
  #ticker-grid.single-view .wide-row.row-indicator-trend {{ display: flex; flex-wrap: wrap; align-items: flex-start; }}
  #ticker-grid.single-view .wide-row.row-indicator-trend > .block {{
    flex: 1 1 0; align-self: flex-start; height: auto; min-width: 260px;
  }}
  /* 전체결과 상위 5개 전략 + 시그널 신뢰도 추이 - 검색(단일 카드) 모드에서만 반반씩
     나란히 배치한다. 그리드 모드에서는 추이 블록이 detail-extra라 애초에 숨어있으므로
     상위 5개 전략 블록이 항상 그대로 한 줄 전체를 차지한다. */
  #ticker-grid.single-view .wide-row.row-top5-track {{ grid-template-columns: 1fr 1fr; align-items: start; }}
  #ticker-grid.single-view .wide-row.row-top5-track .block {{ align-self: start; }}
  /* 2026-08-25: 옵션 있는 종목은 옵션포지셔닝이 위 row-top5-track의 오른쪽 칸을 차지하니,
     시그널 신뢰도 추이는 매매/관망 플랜과 반반씩 나눠 아래 줄에 배치한다(검색/단일 카드
     모드에서만 - 그리드 모드에서는 추이 블록이 detail-extra라 숨어있어 매매/관망 플랜만
     그대로 한 줄을 차지한다). */
  #ticker-grid.single-view .wide-row.row-track-plan {{ grid-template-columns: 1fr 1fr; align-items: start; }}
  #ticker-grid.single-view .wide-row.row-track-plan .block {{ align-self: start; }}
  .card-title-row {{ display: flex; align-items: center; gap: 6px; }}
  .card-title {{ font-size: 14.5px; font-weight: 800; }}
  .info-dot {{
    width: 15px; height: 15px; border-radius: 50%; background: #e2e8f0; color: #64748b;
    font-size: 10px; display: inline-flex; align-items: center; justify-content: center; cursor: help;
  }}
  .card-sub {{ font-size: 11.5px; color: #94a3b8; margin: 5px 0 12px; }}
  .inline-signal-summary {{
    margin-left: auto; display: flex; gap: 12px; font-size: 15px; font-weight: 800; white-space: nowrap;
  }}
  .detail-extra {{ display: none; }}
  .detail-extra.show {{ display: block; }}
  .trend-detail-grid.detail-extra.show {{ display: grid; margin-top: 10px; }}

  .tabs {{ display: flex; gap: 8px; margin-bottom: 14px; }}
  .tab {{ font-size: 12px; font-weight: 600; padding: 6px 12px; border-radius: 8px; background: #f1f5f9; color: #94a3b8; }}
  .tab.active {{ background: #eef2ff; color: #4f46e5; }}

  .summary-label {{ font-size: 13px; font-weight: 800; margin-bottom: 8px; }}
  .summary-sentence {{ font-size: 13px; line-height: 1.6; color: #334155; margin-bottom: 14px; }}
  .signal-row {{
    display: flex; align-items: center; gap: 8px; padding: 10px 14px; border-radius: 12px; margin-bottom: 8px;
  }}
  .signal-row.buy {{ background: #fdecee; }}
  .signal-row.sell {{ background: #eaf0ff; }}
  .signal-icon {{ font-size: 11px; }}
  .signal-row.buy .signal-icon {{ color: {UP_COLOR}; }}
  .signal-row.sell .signal-icon {{ color: {DOWN_COLOR}; }}
  .signal-label {{ font-size: 13px; font-weight: 600; color: #334155; }}
  .signal-pct {{ margin-left: auto; font-size: 16px; font-weight: 800; }}

  .predict-box {{ }}
  .predict-head {{ display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }}
  .ticker-badge {{ font-size: 10.5px; font-weight: 800; background: #0f172a; color: #fff; border-radius: 6px; padding: 3px 7px; }}
  .predict-title {{ font-size: 12.5px; font-weight: 700; color: #64748b; }}
  .predict-sentence {{ font-size: 13px; line-height: 1.6; margin-bottom: 6px; }}
  .confidence-warn {{ font-size: 11px; color: #92400e; background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; padding: 8px 10px; margin-bottom: 10px; line-height: 1.5; }}
  .signal-since {{ font-size: 11px; color: #475569; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 8px 10px; margin-bottom: 10px; line-height: 1.5; }}

  .chart-wrap {{ text-align: center; }}
  .mini-chart {{ width: 100%; max-width: 900px; height: auto; }}
  .chart-axis-label {{ font-size: 11px; fill: #94a3b8; font-family: inherit; }}

  .gauge-wrap {{ text-align: center; margin: 6px 0 4px; }}
  .gauge {{ width: 200px; max-width: 100%; }}
  .gauge-caption {{ font-size: 11.5px; color: #64748b; margin-top: -6px; font-weight: 600; }}
  .gauge-n {{ font-weight: 400; color: #94a3b8; }}

  .opinion-chip {{ text-align: center; font-size: 17px; font-weight: 700; border-radius: 10px; padding: 8px; margin: 10px 0 14px; }}

  .stat-row {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; padding-top: 12px; border-top: 1px dashed #e2e8f0; }}
  .stat {{ text-align: center; }}
  .stat-val {{ font-size: 13.5px; font-weight: 800; }}
  .stat-val.pos {{ color: {UP_COLOR}; }}
  .stat-val.neg {{ color: {DOWN_COLOR}; }}
  .stat-label {{ font-size: 10px; color: #94a3b8; margin-top: 3px; }}
  .predict-footnote {{ font-size: 10px; color: #94a3b8; text-align: center; margin-top: 12px; line-height: 1.5; }}

  .plan-box {{ display: flex; flex-direction: column; gap: 8px; }}
  .plan-row {{ padding: 8px 10px; background: #f8fafc; border-radius: 10px; }}
  .plan-row-main {{ display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }}
  .plan-label {{ font-size: 11.5px; font-weight: 700; color: #475569; white-space: nowrap; }}
  .plan-val {{ font-size: 13px; font-weight: 800; text-align: right; }}
  .plan-val.pos {{ color: {UP_COLOR}; }}
  .plan-val.neg {{ color: {DOWN_COLOR}; }}
  .plan-note {{ font-size: 10px; color: #94a3b8; line-height: 1.4; margin-top: 4px; }}
  .plan-row.analyst-row .plan-label {{ font-size: 13.5px; font-weight: 800; color: #1e293b; }}
  .plan-row.analyst-row .plan-val {{ font-size: 17px; font-weight: 800; }}
  .plan-rr {{ font-size: 11.5px; color: #475569; margin-top: 10px; text-align: center; }}
  .plan-warn {{ font-size: 11px; color: #92400e; background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; padding: 8px 10px; margin-top: 10px; line-height: 1.5; }}

  /* 순위·전략·현재상태는 항상 보이게 왼쪽에 고정(sticky)해두고, 학습/검증수익률·승률·매매
     4개 숫자 열만 옆으로 드래그해서 보게 한다. table-layout:fixed + 명시적 폭 합계로 테이블
     전체 너비를 고정해야 sticky left 오프셋이 실제 열 경계와 정확히 맞아서, 좁은 화면에서
     내용에 따라 열 폭이 늘어나 sticky 열이 다음 열 글씨를 가리는 문제가 생기지 않는다. */
  .top5-scroll {{ overflow-x: auto; -webkit-overflow-scrolling: touch; }}
  table.top5 {{ table-layout: fixed; width: 452px; border-collapse: collapse; font-size: 11.2px; }}
  table.top5 th {{ text-align: left; color: #94a3b8; font-weight: 600; padding: 4px 6px; border-bottom: 1px solid #e2e8f0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  table.top5 td {{ padding: 6px 6px; border-bottom: 1px solid #f1f5f9; vertical-align: middle; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  table.top5 td.sname {{ white-space: normal; word-break: keep-all; overflow: visible; }}
  table.top5 th:nth-child(1), table.top5 td:nth-child(1) {{
    position: sticky; left: 0; width: 22px; background: #fff; z-index: 1;
  }}
  table.top5 th:nth-child(2), table.top5 td:nth-child(2) {{
    position: sticky; left: 22px; width: 116px; background: #fff; z-index: 1;
    box-shadow: 3px 0 6px -3px rgba(15,23,42,0.12);
  }}
  table.top5 th:nth-child(3), table.top5 td:nth-child(3) {{ width: 58px; }}
  table.top5 th:nth-child(4), table.top5 td:nth-child(4) {{ width: 76px; }}
  table.top5 th:nth-child(5), table.top5 td:nth-child(5) {{ width: 76px; }}
  table.top5 th:nth-child(6), table.top5 td:nth-child(6) {{ width: 52px; }}
  table.top5 th:nth-child(7), table.top5 td:nth-child(7) {{ width: 52px; }}
  /* 검색(단일 카드) 모드는 상위 5개 전략이 시그널 신뢰도 추이와 반반씩 나눠 갖더라도
     카드 자체 폭이 넓어서 여전히 여유가 있으므로, 드래그용 좁은 고정폭·sticky 대신
     칸 폭 전체(100%)를 퍼센트로 나눠 쓰고 전략명도 굳이 줄바꿈시키지 않는다.
     그리드(전체보기) 모드는 위 기본 규칙을 그대로 써서 손대지 않는다. */
  #ticker-grid.single-view table.top5 {{ width: 100%; }}
  #ticker-grid.single-view table.top5 th, #ticker-grid.single-view table.top5 td {{
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }}
  #ticker-grid.single-view table.top5 td.sname {{ white-space: nowrap; }}
  #ticker-grid.single-view table.top5 th:nth-child(1), #ticker-grid.single-view table.top5 td:nth-child(1) {{
    position: static; width: 7%;
  }}
  #ticker-grid.single-view table.top5 th:nth-child(2), #ticker-grid.single-view table.top5 td:nth-child(2) {{
    position: static; width: 30%; box-shadow: none;
  }}
  #ticker-grid.single-view table.top5 th:nth-child(3), #ticker-grid.single-view table.top5 td:nth-child(3) {{ width: 15%; }}
  #ticker-grid.single-view table.top5 th:nth-child(4), #ticker-grid.single-view table.top5 td:nth-child(4) {{ width: 16%; }}
  #ticker-grid.single-view table.top5 th:nth-child(5), #ticker-grid.single-view table.top5 td:nth-child(5) {{ width: 16%; }}
  #ticker-grid.single-view table.top5 th:nth-child(6), #ticker-grid.single-view table.top5 td:nth-child(6) {{ width: 8%; }}
  #ticker-grid.single-view table.top5 th:nth-child(7), #ticker-grid.single-view table.top5 td:nth-child(7) {{ width: 8%; }}
  td.rank {{ color: #94a3b8; font-weight: 700; }}
  td.sname {{ font-weight: 600; }}
  .scat {{ display: block; font-size: 9.5px; font-weight: 400; color: #94a3b8; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  td.num.pos {{ color: {UP_COLOR}; font-weight: 600; }}
  td.num.neg {{ color: {DOWN_COLOR}; font-weight: 600; }}
  td.state {{ font-size: 10.5px; color: #64748b; text-align: right; }}
  td.state.buy {{ color: {UP_COLOR}; font-weight: 700; }}
</style>
</head>
<body>
  <div class="header">
    <div class="brand-row">
      <div class="brand-badge">G</div>
      <div class="brand-text">
        <div class="brand-wordmark">GOBEONI TRADING CENTER</div>
        <h1>고버니 트레이딩 센터 <span class="brand-accent">핵심 종목 지표분석</span></h1>
      </div>
    </div>
    <div class="sub">생성 시각: {now} · 데이터: Yahoo Finance 일봉(최근 3년, ~750봉) · 지표 1개 = 전략 1개 방식으로 45개 구성 · 왕복거래비용 0.2% 가정 · 학습/검증구간 분리 적용</div>
    <a class="back-link" href="index.html">← 종목 검색 / 사용설명서로 돌아가기</a>
    <a class="back-link" href="#" id="show-all-link" style="display:none;margin-left:8px;">전체 {len(ordered_items)}개 종목 보기</a>
  </div>
  {fail_banner_html}
  <div class="disclaimer" title="45개 전략은 실제 지표분석 서비스에서 확인된 지표 목록(43개 확인, Ultimate Oscillator·PPO·PVO 3개는 미확인 추가)을 최대한 따라 구성했고, 매수/매도 기준값은 표준 교과서적 정의를 썼어요. 순위는 학습구간(최근 75%) 수익률로 매기고, 검증구간(최근 25%, 표에서 뽑히지 않은 기간)에서도 성과가 유지되는지 별도로 확인해요 - 과최적화(45개 중 우연히 하나가 맞은 경우)를 걸러내기 위한 장치예요. 모든 수익률에는 왕복 거래비용 0.2%(수수료+슬리피지 가정치)가 이미 차감돼 있어요.">
    ⚠ 45개 전략을 학습구간으로 순위 매기고 검증구간에서 재확인한 결과예요 (거래비용 0.2% 반영, 투자 권유 아님). 매매 횟수·승률이 적으면 신뢰도가 낮을 수 있어요. <span class="disclaimer-more">(자세히 보려면 마우스를 올려보세요)</span>
  </div>
  <div class="sector-nav" id="sector-nav">{sector_nav_html}</div>
  <div class="grid" id="ticker-grid">
    {''.join(sections)}
  </div>
  <script>
    // Deep-link from index.html search (report.html#ticker-NVDA) shows ONLY that
    // ticker's card, not the whole grid - a search result should feel like "here's
    // your ticker", not "here's everything, scrolled roughly near your ticker".
    (function() {{
      function applyHashFilter() {{
        var hash = decodeURIComponent(window.location.hash || '');
        var cards = document.querySelectorAll('#ticker-grid .ticker-card');
        var headings = document.querySelectorAll('#ticker-grid .sector-heading');
        var nav = document.getElementById('sector-nav');
        var showAllLink = document.getElementById('show-all-link');
        if (hash.indexOf('#ticker-') === 0) {{
          var targetId = hash.slice(1);
          var found = false;
          cards.forEach(function(card) {{
            var match = card.id === targetId;
            card.style.display = match ? '' : 'none';
            // 밸류에이션/애널리스트 컨센서스/시그널 신뢰도 추이·추세상태 상세는 평소
            // 그리드에선 카드가 너무 길어지니 숨겨두고, 검색으로 특정 종목 하나만 볼 때만
            // 펼친다 (카드 하나에 detail-extra가 여러 개일 수 있어 all로 순회).
            var extras = card.querySelectorAll('.detail-extra');
            extras.forEach(function(extra) {{ extra.classList.toggle('show', match); }});
            if (match) found = true;
          }});
          if (found) {{
            headings.forEach(function(h) {{ h.style.display = 'none'; }});
            if (nav) nav.style.display = 'none';
            showAllLink.style.display = 'inline-flex';
            // 검색으로 카드 1개만 볼 땐 카드 폭이 거의 뷰포트 전체라 지표분석/추세상태
            // 상세를 2칸으로 나란히 보여줄 여유가 있다 - 그리드(여러 카드) 모드에서는
            // 카드 폭이 훨씬 좁아지므로 이 클래스가 없을 때는 항상 1칸(세로쌓기)로 둔다.
            document.getElementById('ticker-grid').classList.add('single-view');
            return;
          }}
        }}
        // no hash, or hash didn't match any card: show everything (but keep detail-extra
        // collapsed - it's search-only, not part of normal grid browsing)
        document.getElementById('ticker-grid').classList.remove('single-view');
        cards.forEach(function(card) {{
          card.style.display = '';
          var extras = card.querySelectorAll('.detail-extra');
          extras.forEach(function(extra) {{ extra.classList.remove('show'); }});
        }});
        headings.forEach(function(h) {{ h.style.display = ''; }});
        if (nav) nav.style.display = '';
        showAllLink.style.display = 'none';
      }}
      document.getElementById('show-all-link').addEventListener('click', function(e) {{
        e.preventDefault();
        history.replaceState(null, '', window.location.pathname);
        applyHashFilter();
      }});
      window.addEventListener('hashchange', applyHashFilter);
      applyHashFilter();
    }})();
  </script>
</body>
</html>"""

with open("report.html", "w", encoding="utf-8") as f:
    f.write(html)

print("report.html written,", len(html), "bytes")

# ---------------------------------------------------------------------------
# index.html: usage manual + lightweight ticker search. Deliberately contains
# NO per-ticker analysis (chart/plan/top-5 table) - just enough to find a
# ticker and jump to its full card in report.html via #ticker-{TICKER} anchor.
# ---------------------------------------------------------------------------
CATEGORY_LABELS = {"buy": "매수", "sell": "매도", "watch": "관망"}
CATEGORY_COLORS = {"buy": UP_COLOR, "sell": DOWN_COLOR, "watch": "#92400e"}

# 검색 목록 정렬: 대표전략(top_strategy) 기준 마지막 신호가 가장 최근(거래일수 적음)인 종목이
# 위로 오도록 - 신호 자체가 없는 극히 드문 케이스는 맨 뒤로 보낸다.
def _signal_recency_key(item):
    _, d = item
    bars_ago = (d.get("composite_signal_recency") or {}).get("bars_ago")
    return (bars_ago is None, bars_ago if bars_ago is not None else 0)

search_ordered_items = sorted(ordered_items, key=_signal_recency_key)

search_rows = []
for ticker, d in search_ordered_items:
    label = TICKER_LABELS.get(ticker, ticker)
    opinion = d["opinion"]
    category = ticker_category.get(ticker, "buy" if opinion == "매수" else "sell")
    op_color = CATEGORY_COLORS[category]
    op_label = CATEGORY_LABELS[category]
    bars_ago = (d.get("composite_signal_recency") or {}).get("bars_ago")
    sig_txt = f"{bars_ago}거래일 전" if bars_ago is not None else ""
    search_rows.append(f"""
      <a class="result-row" href="report.html#ticker-{ticker}" data-ticker="{ticker}" data-label="{label}" data-category="{category}">
        <div class="result-main">
          <span class="result-ticker">{ticker}</span>
          <span class="result-label">{label}</span>
        </div>
        <div class="result-side">
          <span class="result-signal">{sig_txt}</span>
          <span class="result-price">{fmt_num(d['last_close'])}</span>
          <span class="result-opinion" style="color:{op_color}">{op_label}</span>
        </div>
      </a>""")

index_html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>고버니 트레이딩 센터 - 사용설명서 & 종목 검색</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, "Pretendard", "Malgun Gothic", sans-serif;
    background: #f1f5f9; margin: 0; padding: 28px 12px; color: #0f172a;
  }}
  .wrap {{ max-width: 760px; margin: 0 auto; }}
  .brand-row {{ display: flex; align-items: center; gap: 14px; margin-bottom: 8px; }}
  .brand-badge {{
    width: 44px; height: 44px; border-radius: 12px; flex-shrink: 0;
    background: linear-gradient(135deg, #1e293b 0%, #0f172a 55%, {UP_COLOR} 130%);
    color: #fff; font-size: 20px; font-weight: 800; display: flex; align-items: center;
    justify-content: center; letter-spacing: -0.5px; box-shadow: 0 2px 8px rgba(15,23,42,0.25);
  }}
  .brand-text {{ display: flex; flex-direction: column; gap: 2px; }}
  .brand-wordmark {{ font-size: 10.5px; font-weight: 800; color: #64748b; letter-spacing: 2.5px; }}
  h1 {{ font-size: 21px; margin: 0; font-weight: 800; letter-spacing: -0.2px; }}
  .accent {{ color: {UP_COLOR}; }}
  .sub {{ color: #64748b; font-size: 12.5px; margin: 10px 0 20px; line-height: 1.6; }}

  .card {{
    background: #fff; border: 1px solid #e2e8f0; border-radius: 16px;
    padding: 16px 18px; margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.04);
  }}
  .card-num {{
    display: inline-flex; align-items: center; justify-content: center;
    width: 22px; height: 22px; border-radius: 7px; background: #0f172a; color: #fff;
    font-size: 12px; font-weight: 800; margin-right: 8px;
  }}
  .card h2 {{ font-size: 14.5px; margin: 0 0 8px; display: flex; align-items: center; }}
  .card p, .card li {{ font-size: 12.8px; line-height: 1.7; color: #334155; margin: 4px 0; }}
  .card ul {{ margin: 6px 0 0; padding-left: 18px; }}
  .tag {{ display: inline-block; font-size: 11px; font-weight: 700; border-radius: 6px; padding: 1px 7px; }}
  .tag.up {{ background: #fef2f2; color: {UP_COLOR}; }}
  .tag.down {{ background: #eff4ff; color: {DOWN_COLOR}; }}
  .tag.warn {{ background: #fffbeb; color: #92400e; }}
  .example {{
    background: #f8fafc; border: 1px dashed #cbd5e1; border-radius: 10px;
    padding: 8px 12px; margin-top: 8px; font-size: 12px; color: #475569; line-height: 1.6;
  }}
  .footer-note {{
    background: #fffbeb; border: 1px solid #fde68a;
    border-radius: 10px; padding: 12px 16px; font-size: 11.5px; color: #92400e; line-height: 1.7;
    margin-bottom: 24px;
  }}

  .search-block {{
    background: #fff; border: 1px solid #e2e8f0; border-radius: 16px;
    padding: 18px 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); margin-bottom: 22px;
  }}
  .manual-heading {{ font-size: 13.5px; font-weight: 800; color: #64748b; margin: 4px 0 10px; }}
  .search-block h2 {{ font-size: 21px; margin: 0 0 4px; font-weight: 800; }}
  .search-block .hint {{ font-size: 17px; color: #94a3b8; margin: 0 0 12px; }}
  .search-input {{
    font-family: inherit; font-size: 23px; padding: 14px 14px; border-radius: 10px;
    border: 1px solid #cbd5e1; width: 100%; outline: none; margin-bottom: 6px;
  }}
  .search-input:focus {{ border-color: {UP_COLOR}; }}
  .category-filter {{ display: flex; gap: 6px; margin-bottom: 10px; }}
  .category-btn {{
    flex: 1; font-family: inherit; font-size: 21px; font-weight: 700; cursor: pointer;
    border-radius: 9px; padding: 13px 0; border: 1px solid #e2e8f0; background: #fff; color: #64748b;
  }}
  .category-btn.cat-all.active {{ background: #f1f5f9; border-color: #334155; color: #0f172a; }}
  .category-btn.cat-buy.active {{ background: #fef2f2; border-color: {UP_COLOR}; color: {UP_COLOR}; }}
  .category-btn.cat-sell.active {{ background: #eff4ff; border-color: {DOWN_COLOR}; color: {DOWN_COLOR}; }}
  .category-btn.cat-watch.active {{ background: #fffbeb; border-color: #92400e; color: #92400e; }}
  .search-count {{ font-size: 16.5px; color: #64748b; font-weight: 600; display: block; margin-bottom: 10px; }}
  .result-row {{
    display: flex; align-items: center; justify-content: space-between; gap: 10px;
    padding: 12px 14px; border-radius: 12px; background: #f8fafc; margin-bottom: 8px;
    text-decoration: none; color: inherit; border: 1px solid transparent;
  }}
  .result-row:hover {{ border-color: {UP_COLOR}; background: #fdecee0d; }}
  .result-main {{ display: flex; align-items: baseline; gap: 8px; }}
  .result-ticker {{ font-size: 19px; font-weight: 800; }}
  .result-label {{ font-size: 16.5px; color: #64748b; }}
  .result-side {{ display: flex; align-items: center; gap: 10px; }}
  .result-signal {{ font-size: 15.5px; color: #94a3b8; white-space: nowrap; }}
  .result-price {{ font-size: 17.5px; font-weight: 600; color: #475569; }}
  .result-opinion {{ font-size: 17.5px; font-weight: 800; }}
  .no-results {{ font-size: 17.5px; color: #94a3b8; text-align: center; padding: 14px; display: none; }}
  .search-prompt {{ font-size: 17.5px; color: #94a3b8; text-align: center; padding: 14px; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="brand-row">
    <div class="brand-badge">G</div>
    <div class="brand-text">
      <div class="brand-wordmark">GOBEONI TRADING CENTER</div>
      <h1>사용설명서 & <span class="accent">종목 검색</span></h1>
    </div>
  </div>
  <div class="sub">45개 매매전략 백테스트 · 구조적 추세 판정 · 옵션시장 감마 포지셔닝 · 밸류에이션을 한 장에 통합한 멀티팩터 분석 리포트. 티커나 종목명을 입력해서 바로 분석 페이지로 이동하세요.</div>

  <div class="search-block">
    <h2>🔍 종목 검색</h2>
    <div class="hint">종목명이나 티커를 입력하면 해당 종목의 상세 분석 페이지로 이동해요.</div>
    <input type="text" id="ticker-search" class="search-input" placeholder="종목 검색 (예: NVDA, 엔비디아)" oninput="filterResults()" onkeydown="handleSearchKeydown(event)" autofocus>
    <div class="category-filter">
      <button type="button" class="category-btn cat-all" data-category="all" onclick="selectCategory('all')">전체보기</button>
      <button type="button" class="category-btn cat-buy" data-category="buy" onclick="selectCategory('buy')">▲ 매수</button>
      <button type="button" class="category-btn cat-sell" data-category="sell" onclick="selectCategory('sell')">▼ 매도</button>
      <button type="button" class="category-btn cat-watch" data-category="watch" onclick="selectCategory('watch')">◆ 관망</button>
    </div>
    <span id="search-result-count" class="search-count"></span>
    <div id="search-prompt" class="search-prompt">찾으실 종목을 입력해 보세요 (예: NVDA, 엔비디아)</div>
    <div id="result-list">{''.join(search_rows)}</div>
    <div id="no-results" class="no-results">일치하는 종목이 없어요.</div>
  </div>

  <div class="manual-heading">📖 사용설명서</div>

  <div class="card">
    <h2><span class="card-num">1</span>이게 뭔가요?</h2>
    <p>유료 리서치 터미널이 제공하는 지표분석·AI예측 서비스를 참고해, <b>가격 데이터부터 옵션체인·펀더멘털까지 서로 다른 성격의 데이터를 한 종목에 동시에 적용</b>하도록 직접 설계한 멀티팩터 분석 엔진이에요. 매일 장 마감 후 추적 종목 전체를 자동으로 재계산해요.</p>
    <ul>
      <li><b>① 전략 백테스트 레이어</b> — 45개 매매전략을 최근 3년치 일봉에 전수 시뮬레이션. 왕복거래비용 0.2%를 물리고, 학습/검증 구간을 분리한 <b>워크포워드 검증</b>으로 과최적화를 걸러내요. 거래 표본이 부족한 전략은 애초에 순위에서 배제해요.</li>
      <li><b>② 구조적 추세 레이어</b> — 전략 성적과 무관하게 항상 작동하는 레짐 판정. 이동평균 정배열(20/50), ADX/DMI 방향성, Parabolic SAR 전환을 <b>다수결</b>로 묶어 추세 자체가 살아있는지 확인해요.</li>
      <li><b>③ 옵션 포지셔닝 레이어</b> — 만기 30일 옵션체인에서 <b>미결제약정 × 블랙숄즈 감마</b>로 감마 익스포저를 계산해 콜월(저항)·풋월(지지)을 잡고, 풋/콜 비율로 시장 참여자의 실제 자금 포지션 방향을 읽어요. 차트만 보는 분석이 절대 볼 수 없는 레이어예요.</li>
      <li><b>④ 밸류에이션 레이어</b> — PER·PBR·시가총액과 애널리스트 컨센서스 목표주가를 붙여, 기술적 신호가 가격 수준 자체와 모순되지 않는지 대조해요.</li>
    </ul>
    <p>네 레이어를 각각 -100~+100점으로 정규화해 동일 가중 합산한 결과가 카드 맨 위의 <b>종합의견</b>이에요. 한 레이어가 틀려도 나머지 세 개가 견제하도록 만든 구조이고, 블랙박스가 아니라 <b>모든 근거 수치를 종목 페이지에서 전부 열어볼 수 있어요.</b></p>
  </div>

  <div class="card">
    <h2><span class="card-num">2</span>학습구간 vs 검증구간</h2>
    <p>3년 데이터를 앞 75%(<b>학습구간</b>)로 1등 전략을 뽑고, 뒤 25%(<b>검증구간</b> — 뽑을 때 안 본 데이터)에서 그 전략이 진짜 통하는지 재확인해요. <b>검증수익률</b>이 낮아도 플러스면 오히려 신뢰할 만한 신호고, 학습수익률만 화려하고 검증수익률이 마이너스면 우연히 맞았을 가능성이 커요 — 검증수익률을 더 믿으세요.</p>
  </div>

  <div class="card">
    <h2><span class="card-num">3</span>종합의견 (최종 매수/매도/관망)</h2>
    <ul>
      <li>카드 맨 위 <span class="tag up">매수</span>/<span class="tag down">매도</span>/<span class="tag warn">관망</span> 배지와 위 검색창의 필터는 전부 <b>종합의견</b> 기준이에요 — 아래 4가지를 각각 -100~+100점으로 환산해 동일 가중으로 평균한 값이에요: <b>지표분석</b>(45개 중 활성 전략 매수/매도 비율), <b>추세상태</b>(이동평균·ADX/DMI·SAR 다수결), <b>백테스트예측</b>(상위 5개 전략 다수결), <b>옵션포지셔닝</b>(미국 옵션시장 상장 종목만).</li>
      <li>종합점수가 +30 이상이면 매수, -30 이하면 매도, 그 사이는 관망으로 판정해요. 옵션 데이터가 없는 종목(BTC, 삼성전자·SK하이닉스 등 국내상장)은 나머지 3개만으로 동일 가중 재계산해요.</li>
      <li>종목 하나를 검색으로 열면 게이지 바늘이 이 종합점수 위치를, 오른쪽엔 4개 항목이 각각 얼마씩 기여했는지 막대로 보여줘요. 간단한 규칙 기반 합산이지 AI 예측이 아니에요.</li>
    </ul>
  </div>

  <div class="card">
    <h2><span class="card-num">4</span>지표분석 & 백테스트예측</h2>
    <ul>
      <li><b>지표분석</b>: 45개 매매전략 중 최근 3년 10회 + 최근 1년 2회 이상 거래한 전략만 모아, 지금 몇 개가 매수/매도 포지션인지 보여주는 분포예요.</li>
      <li><b>백테스트예측</b>(전체결과 상위 5개 전략 표): 학습구간 수익률 상위 5개 전략의 현재 포지션 다수결이에요. 오실레이터 계열 지표(RSI·스토캐스틱 등)는 타이밍이 어색해 보일 수 있어 대표전략에서 제외해요. 이 표 옆의 <span class="tag up">매수</span>/<span class="tag down">매도</span> 칩은 위 종합의견과 다를 수 있어요 — 이건 백테스트예측 하나만의 다수결이라서예요.</li>
      <li>대표전략의 과거 적중률이 50% 이하이거나 진입가 대비 -10% 손실 중 / +10% 상승을 놓친 상태면, 종목 카드 안 "백테스트예측" 게이지 자리에 <span class="tag warn">신뢰도 낮음</span> 표시가 붙어요 — 이건 종합의견의 관망과는 다른, 그 대표전략 하나에 대한 개별 경고예요.</li>
    </ul>
  </div>

  <div class="card">
    <h2><span class="card-num">5</span>추세상태 & 옵션포지셔닝</h2>
    <ul>
      <li><b>추세상태</b>: 45개 백테스트 전략과는 완전히 별개로, 항상 켜져 있는 구조적 추세 판정이에요. 이동평균(20/50) 정배열·역배열, ADX/DMI 방향, Parabolic SAR 전환 — 이 3개 지표 중 2개 이상이 가리키는 쪽으로 "상승추세 유지" 또는 "상승추세 이탈"을 판정해요. 근거 지표 3개 실제 수치는 종목 하나를 검색으로 열면 나와요.</li>
      <li><b>옵션포지셔닝</b>: 만기 약 30일짜리 옵션체인에서 콜/풋 감마 익스포저(미결제약정 x 블랙숄즈 감마)가 가장 큰 행사가를 각각 콜월(저항)·풋월(지지)로 보고(2026-08-28부터 감마 가중 방식 — 단순 미결제약정 최대값은 감마가 거의 0인 죽은 딥아웃오브더머니 행사가에 왜곡되기 쉬워 변경했어요), 현재가가 그 구간 어디에 있는지(콜월 돌파=+100, 풋월 이탈=-100)와 풋/콜 OI 비율(1.0=중립, 풋 많을수록 약세, 콜 많을수록 강세)을 동일 가중으로 평균해 판정하는 단순 휴리스틱이지 실제 딜러 포지션 분석이 아니에요. 넷감마·맥스페인·IV 스큐는 옵션포지셔닝 상세 카드에 참고용으로만 표시하고 점수엔 반영하지 않아요(방향성이 애매하고 백테스트 검증이 안 돼서 제외). 미국 옵션시장에 상장 안 된 종목(BTC, 국내상장 종목 등)은 이 항목 자체가 없어요.</li>
    </ul>
  </div>

  <div class="card">
    <h2><span class="card-num">6</span>플랜 & 참고정보</h2>
    <ul>
      <li><b>매매 플랜</b>: 백테스트예측(상위 5개 전략 다수결)이 매수일 때만 나와요 — 과거 실제 승/패 거래 기록 기반 진입가·손절가·1·2차 목표가. 카드 맨 위 종합의견이 관망/매도여도, 백테스트예측 하나가 매수면 이 플랜은 뜰 수 있어요.</li>
      <li><b>관망 플랜</b>: 백테스트예측이 매도일 때 나와요 — 과거 매도 이후 실제 하락폭·소요기간 통계예요. 반등 시점 예측은 아니에요.</li>
      <li><b>밸류에이션·애널리스트 컨센서스·시그널 신뢰도 추이</b>: PER·PBR·시가총액·애널리스트 목표주가 등 참고 정보예요. 목록에선 숨겨져 있고, 검색으로 종목 하나를 열면 카드 맨 아래에 나와요.</li>
    </ul>
  </div>

  <div class="footer-note">
    ⚠ 이 리포트는 투자 권유가 아니라 과거 데이터 기반 참고자료예요. 왕복거래비용 0.2%를 가정했고, 매매 횟수·표본이 적은 종목은 신뢰도가 떨어질 수 있어요. 옵션포지셔닝은 단순 휴리스틱이에요. 최종 투자 판단과 책임은 본인에게 있어요.
  </div>
</div>
<script>
  var activeCategory = null; // 'buy' | 'sell' | 'watch' | null

  function selectCategory(cat) {{
    activeCategory = (activeCategory === cat) ? null : cat;
    document.querySelectorAll('.category-btn').forEach(function(btn) {{
      btn.classList.toggle('active', btn.dataset.category === activeCategory);
    }});
    filterResults();
  }}

  function filterResults() {{
    var q = document.getElementById('ticker-search').value.trim().toLowerCase();
    var rows = document.querySelectorAll('#result-list .result-row');
    var hasFilter = (q !== '' || activeCategory !== null);
    var visible = 0;
    rows.forEach(function(row) {{
      var hay = ((row.dataset.ticker || '') + ' ' + (row.dataset.label || '')).toLowerCase();
      var textMatch = q === '' || hay.indexOf(q) !== -1;
      var catMatch = activeCategory === null || activeCategory === 'all' || row.dataset.category === activeCategory;
      var match = hasFilter && textMatch && catMatch;
      row.style.display = match ? '' : 'none';
      if (match) visible++;
    }});
    document.getElementById('search-result-count').textContent = hasFilter ? (visible + '개 종목 표시 중') : '';
    document.getElementById('search-prompt').style.display = hasFilter ? 'none' : 'block';
    document.getElementById('no-results').style.display = (visible === 0 && hasFilter) ? 'block' : 'none';
  }}
  function handleSearchKeydown(e) {{
    if (e.key !== 'Enter') return;
    var visibleRows = Array.prototype.filter.call(
      document.querySelectorAll('#result-list .result-row'),
      function(row) {{ return row.style.display !== 'none'; }}
    );
    if (visibleRows.length > 0) {{
      window.location.href = visibleRows[0].getAttribute('href');
    }}
  }}
  filterResults();
</script>
</body>
</html>"""

with open("index.html", "w", encoding="utf-8") as f:
    f.write(index_html)

print("index.html written,", len(index_html), "bytes")
