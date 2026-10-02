"""
Lightweight web-share version of the report, built from the SAME backtest_results.json
as generate_report_v2.py - no charts/tooltips/top5 table, just the essentials per ticker
(opinion, trend badge, key plan numbers). This exists purely because the full report.html
(inline SVG charts x72 tickers) is far too large to push through a chat-based publish tool
in one shot; the full report.html on the desktop is untouched and still has everything.
Publish target: Send (send.co) via CreateSite/EditSite, called separately after this script.
"""
import json
import datetime

with open("backtest_results.json", encoding="utf-8") as f:
    payload = json.load(f)

meta = payload.get("meta", {})
data = payload.get("tickers", payload)

UP_COLOR = "#e0293f"
DOWN_COLOR = "#3366ff"
WATCH_COLOR = "#92400e"

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


def fmt_pct(v, digits=1, signed=True):
    if v is None:
        return "N/A"
    sign = "+" if (signed and v > 0) else ""
    return f"{sign}{v:.{digits}f}%"


def fmt_num(v):
    if v is None:
        return "—"
    return f"{v:,.2f}"


rows = []
for ticker, d in data.items():
    top = d.get("top_strategy", {}) or {}
    opinion = d.get("opinion")
    accuracy = d.get("signal_accuracy_pct")
    open_ret_now = top.get("open_trade_return_pct")
    open_watch_now = top.get("open_watch_return_pct")
    low_confidence = (
        (accuracy is not None and accuracy <= 50)
        or (top.get("current_state") == "매수보유" and open_ret_now is not None and open_ret_now < -10)
        or (top.get("current_state") == "관망" and open_watch_now is not None and open_watch_now > 10)
    )
    category = "watch" if low_confidence else ("buy" if opinion == "매수" else "sell")
    op_color = {"buy": UP_COLOR, "sell": DOWN_COLOR, "watch": WATCH_COLOR}[category]
    op_label = {"buy": "매수", "sell": "매도", "watch": "관망"}[category]
    bars_ago = top.get("last_signal_bars_ago")

    ts = d.get("trend_status") or {}
    trend_up = ts.get("overall") == "up"
    trend_label = ("▲ 상승추세 유지" if trend_up else "▼ 상승추세 이탈") if ts else ""
    trend_color = UP_COLOR if trend_up else DOWN_COLOR
    trend_votes = f"{ts.get('up_votes')}/{ts.get('total_votes')}" if ts else ""

    plan_html = ""
    tp = d.get("trade_plan")
    wp = d.get("watch_plan")
    if opinion == "매수" and tp:
        items = [("매수타점", fmt_num(tp.get("entry_price")))]
        if tp.get("stop_price") is not None:
            items.append(("손절가", fmt_num(tp["stop_price"])))
        if tp.get("target1_price") is not None:
            items.append((f"1차목표({tp.get('target1_horizon_days')}일)", fmt_num(tp["target1_price"])))
        if tp.get("target2_price") is not None:
            items.append(("2차목표", fmt_num(tp["target2_price"])))
        plan_html = " · ".join(f"{lbl} {val}" for lbl, val in items)
    elif opinion == "매도" and wp:
        items = []
        if wp.get("support1_price") is not None:
            items.append(("1차지지", fmt_num(wp["support1_price"])))
        if wp.get("support2_price") is not None:
            items.append(("2차지지", fmt_num(wp["support2_price"])))
        if wp.get("wait_days_median") is not None:
            items.append(("평균관망", f"{wp['wait_days_median']:.0f}거래일"))
        plan_html = " · ".join(f"{lbl} {val}" for lbl, val in items)

    rows.append({
        "ticker": ticker,
        "label": TICKER_LABELS.get(ticker, ticker),
        "price": fmt_num(d.get("last_close")),
        "last_date": d.get("last_date", ""),
        "category": category,
        "op_label": op_label,
        "op_color": op_color,
        "bars_ago": bars_ago,
        "top_name": top.get("name", ""),
        "accuracy": fmt_pct(accuracy, 0, False) if accuracy is not None else "N/A",
        "trend_label": trend_label,
        "trend_color": trend_color,
        "trend_votes": trend_votes,
        "plan_html": plan_html,
    })

rows.sort(key=lambda r: (r["bars_ago"] is None, r["bars_ago"] if r["bars_ago"] is not None else 0))

cat_counts = {"buy": 0, "sell": 0, "watch": 0}
for r in rows:
    cat_counts[r["category"]] += 1

card_rows_html = []
for r in rows:
    trend_chip = (
        f'<span class="trend-chip" style="color:{r["trend_color"]}">{r["trend_label"]} ({r["trend_votes"]})</span>'
        if r["trend_label"] else ""
    )
    sig_txt = f'{r["bars_ago"]}거래일 전 신호' if r["bars_ago"] is not None else ""
    plan_line = f'<div class="plan-line">{r["plan_html"]}</div>' if r["plan_html"] else ""
    card_rows_html.append(f"""
      <div class="card" data-ticker="{r['ticker']}" data-label="{r['label']}" data-category="{r['category']}">
        <div class="card-top">
          <div class="card-name"><span class="tkr">{r['ticker']}</span><span class="lbl">{r['label']}</span></div>
          <div class="card-price">{r['price']}<span class="pdate">{r['last_date']}</span></div>
        </div>
        <div class="card-mid">
          <span class="op-chip" style="background:{r['op_color']}1a;color:{r['op_color']}">{r['op_label']}</span>
          {trend_chip}
          <span class="acc-txt">신호적중 {r['accuracy']}</span>
          <span class="sig-txt">{sig_txt}</span>
        </div>
        {plan_line}
        <div class="card-strategy">대표전략: {r['top_name']}</div>
      </div>""")

generated_at = meta.get("generated_at", datetime.datetime.now().isoformat(timespec="seconds"))

html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>고버니 트레이딩 센터 - 요약 리포트</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, "Pretendard", "Malgun Gothic", sans-serif; background: #f1f5f9; margin: 0; padding: 20px 14px 60px; color: #0f172a; }}
  .wrap {{ max-width: 720px; margin: 0 auto; }}
  h1 {{ font-size: 19px; margin: 0 0 4px; }}
  .sub {{ font-size: 12px; color: #64748b; margin: 0 0 14px; }}
  .note {{ font-size: 11.5px; color: #92400e; background: #fffbeb; border: 1px solid #fde68a; border-radius: 10px; padding: 10px 14px; margin-bottom: 14px; line-height: 1.6; }}
  .filter-row {{ display: flex; gap: 8px; margin-bottom: 10px; }}
  .filter-btn {{ flex: 1; font-family: inherit; font-size: 12.5px; font-weight: 700; cursor: pointer; border-radius: 9px; padding: 8px 0; border: 1px solid #e2e8f0; background: #fff; color: #64748b; }}
  .filter-btn.active.f-buy {{ background: #fef2f2; border-color: {UP_COLOR}; color: {UP_COLOR}; }}
  .filter-btn.active.f-sell {{ background: #eff4ff; border-color: {DOWN_COLOR}; color: {DOWN_COLOR}; }}
  .filter-btn.active.f-watch {{ background: #fffbeb; border-color: {WATCH_COLOR}; color: {WATCH_COLOR}; }}
  input#q {{ font-family: inherit; font-size: 14px; padding: 9px 12px; border-radius: 10px; border: 1px solid #cbd5e1; width: 100%; outline: none; margin-bottom: 10px; }}
  .count {{ font-size: 11.5px; color: #64748b; margin-bottom: 8px; display: block; }}
  .card {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 14px; padding: 12px 14px; margin-bottom: 8px; }}
  .card-top {{ display: flex; justify-content: space-between; align-items: baseline; }}
  .card-name .tkr {{ font-size: 14.5px; font-weight: 800; }}
  .card-name .lbl {{ font-size: 11px; color: #64748b; margin-left: 6px; }}
  .card-price {{ font-size: 13px; font-weight: 700; text-align: right; }}
  .pdate {{ display: block; font-size: 9.5px; color: #94a3b8; font-weight: 400; }}
  .card-mid {{ display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: center; margin-top: 6px; }}
  .op-chip {{ font-size: 11.5px; font-weight: 800; border-radius: 8px; padding: 3px 8px; }}
  .trend-chip {{ font-size: 10.5px; font-weight: 700; }}
  .acc-txt, .sig-txt {{ font-size: 10.5px; color: #94a3b8; }}
  .plan-line {{ font-size: 11px; color: #334155; margin-top: 6px; line-height: 1.6; }}
  .card-strategy {{ font-size: 10px; color: #94a3b8; margin-top: 4px; }}
  .footer-note {{ font-size: 11px; color: #92400e; background: #fffbeb; border: 1px solid #fde68a; border-radius: 10px; padding: 10px 14px; margin-top: 16px; line-height: 1.6; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>고버니 트레이딩 센터 — 요약 리포트</h1>
  <div class="sub">{len(rows)}개 종목 · 생성: {generated_at}</div>
  <div class="note">⚠ 이 페이지는 차트·지표상세·상위5전략표를 뺀 요약 버전이에요. 전체 상세(차트·추세 3지표·상위5전략)는 로컬 report.html에서 확인하세요.</div>
  <input type="text" id="q" placeholder="종목 검색 (예: NVDA, 엔비디아)" oninput="filterRows()">
  <div class="filter-row">
    <button type="button" class="filter-btn f-buy" data-cat="buy" onclick="selectCat('buy')">▲ 매수 ({cat_counts['buy']})</button>
    <button type="button" class="filter-btn f-sell" data-cat="sell" onclick="selectCat('sell')">▼ 매도 ({cat_counts['sell']})</button>
    <button type="button" class="filter-btn f-watch" data-cat="watch" onclick="selectCat('watch')">◆ 관망 ({cat_counts['watch']})</button>
  </div>
  <span id="count" class="count"></span>
  <div id="list">{''.join(card_rows_html)}</div>
  <div class="footer-note">⚠ 투자 권유가 아니라 과거 데이터 기반 참고자료예요. 최종 투자 판단과 책임은 본인에게 있어요.</div>
</div>
<script>
  var activeCat = null;
  function selectCat(cat) {{
    activeCat = (activeCat === cat) ? null : cat;
    document.querySelectorAll('.filter-btn').forEach(function(b) {{ b.classList.toggle('active', b.dataset.cat === activeCat); }});
    filterRows();
  }}
  function filterRows() {{
    var q = document.getElementById('q').value.trim().toLowerCase();
    var cards = document.querySelectorAll('#list .card');
    var visible = 0;
    cards.forEach(function(c) {{
      var hay = ((c.dataset.ticker||'') + ' ' + (c.dataset.label||'')).toLowerCase();
      var textMatch = q === '' || hay.indexOf(q) !== -1;
      var catMatch = activeCat === null || c.dataset.category === activeCat;
      var match = textMatch && catMatch;
      c.style.display = match ? '' : 'none';
      if (match) visible++;
    }});
    document.getElementById('count').textContent = visible + '개 종목 표시 중';
  }}
  filterRows();
</script>
</body>
</html>"""

with open("report_share.html", "w", encoding="utf-8") as f:
    f.write(html)

print(f"report_share.html written, {len(html)} chars, {len(rows)} tickers")
