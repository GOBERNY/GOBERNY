"""고버니 트렌드 엔진 — 지표견(Lazy Alpha) 스타일 신호를 일봉 데이터로 재현."""
import json, math
import numpy as np, pandas as pd


def load(path='data.txt'):
    out = {}
    for blk in open(path).read().split('#')[1:]:
        h, b = blk.split('\n', 1)
        rows = [r.split(',') for r in b.strip().split(';')]
        df = pd.DataFrame(rows, columns=['d', 'o', 'h', 'l', 'c', 'v'])
        df['date'] = pd.to_datetime('20' + df.d, format='%Y%m%d')
        for k in 'ohlcv':
            df[k] = df[k].astype(float)
        out[h.strip()] = df[['date', 'o', 'h', 'l', 'c', 'v']].reset_index(drop=True)
    return out

DP = 2
def ema(s, n): return s.ewm(span=n, adjust=False).mean()
def wilder(s, n): return s.ewm(alpha=1 / n, adjust=False).mean()

def indicators(df):
    c, h, l, v = df.c, df.h, df.l, df.v
    for n in (8, 14, 21, 55):
        df[f'e{n}'] = ema(c, n)
    for n in (50, 100, 150, 200):
        df[f's{n}'] = c.rolling(n).mean()
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    df['atr'] = wilder(tr, 14)
    mid = c.rolling(20).mean(); sd = c.rolling(20).std(ddof=0)
    df['bbU'], df['bbL'], df['bbM'] = mid + 2 * sd, mid - 2 * sd, mid
    e20 = ema(c, 20); a20 = wilder(tr, 20)
    df['kcU'], df['kcL'] = e20 + 1.5 * a20, e20 - 1.5 * a20
    df['sq'] = (df.bbU < df.kcU) & (df.bbL > df.kcL)
    d = c.diff()
    rs = wilder(d.clip(lower=0), 14) / wilder((-d).clip(lower=0), 14)
    df['rsi'] = 100 - 100 / (1 + rs)
    macd = ema(c, 12) - ema(c, 26)
    df['hist'] = macd - ema(macd, 9)
    up = h.diff(); dn = -l.diff()
    pdm = np.where((up > dn) & (up > 0), up, 0.0); mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    atr14 = wilder(tr, 14)
    pdi = 100 * wilder(pd.Series(pdm), 14) / atr14; mdi = 100 * wilder(pd.Series(mdm), 14) / atr14
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi)
    df['adx'], df['pdi'], df['mdi'] = wilder(dx, 14), pdi, mdi
    df['vr'] = v / v.rolling(50, min_periods=20).mean()
    df['vr20'] = v / v.rolling(20, min_periods=10).mean()
    df['atrRel'] = df.atr / df.atr.rolling(50, min_periods=20).mean()
    return df

def pivots(df, k=5):
    hs, ls = [], []
    H, L = df.h.values, df.l.values
    for i in range(k, len(df) - k):
        if H[i] == H[i - k:i + k + 1].max() and (not hs or hs[-1] < i - 1): hs.append(i)
        if L[i] == L[i - k:i + k + 1].min() and (not ls or ls[-1] < i - 1): ls.append(i)
    return hs, ls

def fitline(idx, vals):
    if len(idx) < 2: return None
    m, b = np.polyfit(idx, vals, 1)
    return m, b

def classify(mh, ml, atr):
    sh, sl = mh / atr, ml / atr
    f = 0.012
    if sh > f and sl > f: return 'up_channel', '상승 채널'
    if sh < -f and sl < -f: return 'dn_channel', '하락 채널'
    if sh < -f and sl > f: return 'sym_tri', '대칭 삼각형'
    if abs(sh) <= f and sl > f: return 'asc_tri', '상승 삼각형'
    if sh < -f and abs(sl) <= f: return 'desc_tri', '하강 삼각형'
    if abs(sh) <= f and abs(sl) <= f: return 'box', '박스권'
    return None, None

def run(sym, df, bench=None):
    df = indicators(df)
    n = len(df); K = 5
    O, H, L, C, V = (df[k].values for k in 'ohlcv')
    A = df.atr.values
    hs, ls = pivots(df, K)
    ev = []  # events

    def add(i, code, text, cat, pos, color, desc, shape=None, extra=None):
        e = dict(i=i, code=code, text=text, cat=cat, pos=pos, color=color, desc=desc,
                 shape=shape or ('arrowUp' if pos == 'belowBar' else 'arrowDown'))
        if extra: e.update(extra)
        ev.append(e)

    GREEN, RED, BLUE, AMBER, VIOLET, GREY = '#1f9d6a', '#d6455d', '#2f6fde', '#d98a1c', '#8a4fd8', '#7b8794'
    state, entry, stop, tp1, tp2, lvl, ei = '관찰', None, None, None, None, None, None
    pyr, f8, f14, f21, hitTP1, hitTP2 = 0, False, False, False, False, False
    cool = {}
    def ok(key, i, gap):
        if i - cool.get(key, -999) >= gap:
            cool[key] = i; return True
        return False
    setup_lvl, vcp_key = None, None
    peg = None
    msell_i = None
    pat_done = set(); w_done = set()
    trail = []

    start = 60
    for i in range(start, n):
        a = A[i]
        hc = [p for p in hs if p <= i - K and p >= i - 90]
        lc = [p for p in ls if p <= i - K and p >= i - 90]
        # --- 응축 / 스퀴즈 해제
        if i >= 6 and not df['sq'].iat[i] and df['sq'].iloc[i - 6:i].sum() >= 5 and ok('sqf', i, 8):
            up = df['hist'].iat[i] > 0
            add(i, 'sqfire', '응축 해제 ↑' if up else '응축 해제 ↓', 'squeeze',
                'belowBar' if up else 'aboveBar', AMBER,
                '볼린저밴드가 켈트너채널 안에 갇혀 있던 응축 구간(드래곤볼)이 끝나고 변동성이 터지는 첫 봉입니다. 방향은 MACD 히스토그램 부호로 판정합니다.')
        # --- resistance level: highest confirmed pivot high in last 45 bars
        # 막혀 있던 고점 = 가장 최근에 확정된 피벗 고점 (60봉 이내)
        level = H[hc[-1]] if hc and hc[-1] >= i - 60 else None
        # --- VCP
        if len(hc) >= 3 and len(lc) >= 3 and C[i] > df.e55.iat[i]:
            depths = []
            for p in hc[-4:]:
                after = [q for q in lc if q > p]
                if after:
                    q = after[0]; depths.append((H[p] - L[q]) / H[p])
            if len(depths) >= 3:
                d1, d2, d3 = depths[-3:]
                key = tuple(hc[-3:])
                if d1 > d2 > d3 and d3 < 0.6 * d1 and key != vcp_key:
                    vcp_key = key
                    add(i, 'vcp', 'VCP 형성', 'setup', 'belowBar', AMBER,
                        f'최근 세 번의 눌림 깊이가 {d1*100:.1f}% → {d2*100:.1f}% → {d3*100:.1f}%로 줄었습니다. 매도 물량이 마르며 변동성이 수축하는 미너비니식 VCP 구조입니다.', 'circle')
        # --- setup forming
        if state == '관찰' and level and level * 0.95 <= C[i] < level and C[i] > df.e55.iat[i] \
                and (df['sq'].iloc[max(0, i - 5):i + 1].any() or df.atrRel.iat[i] < 0.85) and setup_lvl != level:
            setup_lvl = level
            add(i, 'setup', '셋업 형성 중', 'setup', 'belowBar', AMBER,
                f'저항 {level:,.{DP}f} 바로 아래(5% 이내)에서 변동성이 줄어든 상태로 버티고 있습니다. 돌파 진입 직전 대기 구간입니다.', 'square', extra=dict(level=level))
        # --- breakout entry
        bigbar = (H[i] - L[i]) >= 1.2 * a and C[i] >= L[i] + 0.66 * (H[i] - L[i])
        below21 = sum(C[j] < df.e21.iat[j] for j in range(i - 8, i))
        s200ok = not math.isnan(df.s200.iat[i]) and C[i] > df.s200.iat[i]
        reclaim = (state == '관찰' and s200ok and below21 >= 3 and C[i - 1] <= df.e21.iat[i - 1] and C[i] > df.e21.iat[i]
                   and C[i] > H[i - 1] and C[i] > df.e55.iat[i])
        if state == '관찰' and level and C[i] > level and C[i - 1] <= level and (df.vr20.iat[i] >= 1.0 or bigbar) and C[i] > df.e21.iat[i] and C[i] > df.e55.iat[i]:
            state, entry, lvl, ei = '보유', C[i], level, i
            stop = min(L[i], C[i] - 1.5 * a)
            R = entry - stop; tp1, tp2 = entry + 2 * R, entry + 3.5 * R
            pyr, f8, f14, f21, hitTP1, hitTP2 = 0, False, False, False, False, False
            add(i, 'bo', '돌파 진입', 'entry', 'belowBar', GREEN,
                f'종가가 저항 {level:,.{DP}f}를 거래량 {df.vr.iat[i]:.1f}배로 넘었습니다. 진입 {entry:,.{DP}f} · 손절 {stop:,.{DP}f} · TP1 {tp1:,.{DP}f} · TP2 {tp2:,.{DP}f} (손익비 1:2 / 1:3.5).',
                extra=dict(entry=entry, stop=stop, tp1=tp1, tp2=tp2, level=level))
        elif reclaim:
            state, entry, lvl, ei = '보유', C[i], df.e21.iat[i], i
            stop = max(min(L[i - 4:i + 1]), C[i] - 2.5 * a)
            R = entry - stop; tp1, tp2 = entry + 2 * R, entry + 3.5 * R
            pyr, f8, f14, f21, hitTP1, hitTP2 = 0, False, False, False, False, False
            add(i, 'reclaim', '21일선 회복 매수', 'entry', 'belowBar', GREEN,
                f'21일선 아래에서 쉬던 가격이 다시 21일선({df.e21.iat[i]:,.{DP}f}) 위로, 전일 고가 위에서 마감했습니다. 200일선과 55일선 위에 있을 때만 냅니다. 진입 {entry:,.{DP}f} · 손절 {stop:,.{DP}f} · TP1 {tp1:,.{DP}f} · TP2 {tp2:,.{DP}f}.',
                extra=dict(entry=entry, stop=stop, tp1=tp1, tp2=tp2, level=lvl))
        elif state in ('보유', '관리'):
            R = entry - stop if entry > stop else a
            # SR flip
            if 2 <= i - ei <= 10 and L[i] <= lvl + 0.3 * a and C[i] > lvl and ok('srf', i, 15):
                add(i, 'srflip', 'SR flip', 'entry', 'belowBar', GREEN,
                    f'돌파했던 저항 {lvl:,.{DP}f}까지 되밀린 뒤 그 위에서 마감했습니다. 저항이 지지로 바뀐 걸 확인한 2차 진입 자리입니다.')
            # failed breakout
            if i - ei <= 15 and C[i] < lvl - 0.5 * a:
                add(i, 'bofail', '돌파 청산', 'exit', 'aboveBar', RED,
                    f'돌파 후 {i-ei}봉 만에 저항선 {lvl:,.{DP}f} 아래로 다시 밀려 마감했습니다. 실패한 돌파는 빠르게 정리하는 규칙입니다.')
                state = '관찰'; continue_exit = True
            else:
                # TP
                if not hitTP1 and H[i] >= tp1:
                    hitTP1 = True; state = '관리'; stop = max(stop, entry)
                    add(i, 'tp1', 'TP1 · 1차 분할청산', 'exit', 'aboveBar', BLUE,
                        f'1차 목표 {tp1:,.{DP}f}(2R)에 닿았습니다. 일부 익절하고 손절을 본전 {entry:,.{DP}f}로 올립니다.', 'circle')
                if hitTP1 and not hitTP2 and H[i] >= tp2:
                    hitTP2 = True
                    add(i, 'tp2', 'TP2', 'exit', 'aboveBar', BLUE, f'2차 목표 {tp2:,.{DP}f}(3.5R) 도달.', 'circle')
                # pyramiding
                if pyr < 2 and i - ei >= 3 and L[i - 1] <= df.e14.iat[i - 1] * 1.005 and C[i] > H[i - 1] \
                        and C[i] > df.e14.iat[i] and df.e8.iat[i] > df.e21.iat[i]:
                    pyr += 1
                    add(i, 'pyr', f'피라미딩 {pyr}차', 'entry', 'belowBar', GREEN,
                        '보유 중 14일선까지 눌렸다가 전일 고가를 넘기며 재상승했습니다. 수익 포지션에만 물량을 더 싣는 자리입니다.')
                # trim / overheat
                gainR = (C[i] - entry) / R if R > 0 else 0
                if gainR >= 1.5 and H[i] > df.bbU.iat[i] and ok('trim', i, 8):
                    add(i, 'trim', '부분익절 고려', 'exit', 'aboveBar', VIOLET,
                        f'진입 대비 {gainR:.1f}R 수익에 시그마 밴드 상단 {df.bbU.iat[i]:,.{DP}f}를 넘었습니다. 일부 Trim하고 눌림에서 다시 싣는 구간입니다.', 'circle')
                # EMA exits
                if C[i] < df.e8.iat[i] and not f8:
                    f8 = True
                    add(i, 'x8', '8선 이탈', 'exit', 'aboveBar', GREY, '8일선 아래 마감. 단기 탄력이 꺾였다는 첫 경고입니다.', 'circle')
                if C[i] > df.e8.iat[i] and f8 and not f14:
                    f8 = False
                    add(i, 'r8', '8선 회복', 'entry', 'belowBar', GREY, '8일선을 다시 회복했습니다.', 'circle')
                if C[i] < df.e14.iat[i] and not f14:
                    f14 = True
                    add(i, 'x14', '분할청산 · 14선', 'exit', 'aboveBar', RED, '14일선 이탈 마감. 보유 물량 일부를 정리하는 트레일링 규칙입니다.')
                if C[i] < df.e21.iat[i] and not f21:
                    f21 = True
                    add(i, 'x21', '분할청산 · 21선', 'exit', 'aboveBar', RED, '21일선 이탈 마감. 중기 추세 기준선이 깨져 비중을 크게 줄이는 자리입니다.')
                if f14 and C[i] > df.e8.iat[i] and df.e8.iat[i] > df.e14.iat[i]:
                    f14 = f21 = f8 = False
                below21 = all(C[j] < df.e21.iat[j] for j in range(i - 2, i + 1))
                if C[i] < stop or (f21 and below21):
                    why = '손절선' if C[i] < stop else '21일선 3봉 연속 이탈'
                    add(i, 'final', '최종 청산', 'exit', 'aboveBar', RED,
                        f'{why} 기준이 깨졌습니다. 이번 사이클(진입 {entry:,.{DP}f}, {i-ei}봉 보유)을 마무리합니다.')
                    state = '관찰'
        # --- 급등 후 풀백
        if i >= 15:
            run_ = max((C[j] - C[j - 10]) / A[j] for j in range(i - 8, i))
            if run_ >= 6 and L[i] <= df.e8.iat[i] and C[i] > df.e21.iat[i] and ok('pbs', i, 15):
                add(i, 'pullsurge', '급등 후 풀백', 'entry', 'belowBar', BLUE,
                    f'최근 10봉 동안 ATR의 {run_:.0f}배를 오른 뒤 처음으로 8일선까지 눌렸습니다. 강한 추세의 첫 눌림은 재진입 후보입니다.')
        # --- 과열 경고
        if C[i] > df.bbU.iat[i] and (C[i] - df.e21.iat[i]) / a >= 3 and df.rsi.iat[i] > 72 and ok('hot', i, 8):
            add(i, 'hot', '과열 경고', 'warn', 'aboveBar', VIOLET,
                f'21일선과 이격이 ATR의 {(C[i]-df.e21.iat[i])/a:.1f}배, RSI {df.rsi.iat[i]:.0f}, 시그마 밴드 상단 돌파. 신규 진입보다 비중 축소를 고민할 자리입니다.', 'square')
        # --- PEG
        gp = O[i] / C[i - 1] - 1
        if O[i] > H[i - 1] and gp >= max(0.03, 1.0 * a / C[i - 1]) and df.vr.iat[i] >= 1.4:
            base = C[i - 1]; top = C[i]
            if top > base:
                f382, f50, f618 = top - .382 * (top - base), top - .5 * (top - base), top - .618 * (top - base)
                peg = dict(i=i, base=base, top=top, hi=H[i], f382=f382, f50=f50, f618=f618, retr=False, done=False)
                add(i, 'peg', 'PEG', 'peg', 'belowBar', GREEN,
                    f'시가가 전일 고가 위로 {gp*100:.1f}% 갭을 띄웠고 거래량 {df.vr.iat[i]:.1f}배입니다. 갭 구간 피보나치 38.2/50/61.8% = {f382:,.{DP}f} / {f50:,.{DP}f} / {f618:,.{DP}f}.',
                    extra=dict(f382=f382, f50=f50, f618=f618, base=base))
        elif peg and not peg['done'] and i - peg['i'] <= 30:
            if C[i] < peg['base']:
                add(i, 'peginv', 'PEG 무효', 'peg', 'aboveBar', RED, f'갭 하단 {peg["base"]:,.{DP}f} 아래로 마감해 갭이 다 메워졌습니다.', 'circle')
                peg['done'] = True
            elif not peg['retr'] and L[i] <= peg['f382'] and L[i] >= peg['f618'] - 0.3 * a and C[i] > peg['f618'] and C[i] > O[i]:
                peg['retr'] = True
                add(i, 'pegrt', 'PEG 되돌림 매수', 'entry', 'belowBar', GREEN,
                    f'갭의 38.2~61.8% 구간({peg["f618"]:,.{DP}f}~{peg["f382"]:,.{DP}f})까지 메운 뒤 양봉으로 받쳤습니다. 추세 좋은 갭은 절반쯤 메우고 다시 갑니다.')
            elif peg['retr'] and C[i] > max(H[peg['i']:i]):
                add(i, 'pegrb', 'PEG 재돌파', 'entry', 'belowBar', GREEN, 'PEG 이후 고점을 종가로 다시 넘었습니다.')
                peg['done'] = True
        # --- momentum
        hst = df['hist'].values
        if hst[i - 1] <= 0 < hst[i] and C[i] > df.e21.iat[i]:
            add(i, 'mbuy', '모멘텀 BUY', 'momo', 'belowBar', GREEN,
                f'MACD 히스토그램이 0 위로 전환하고 종가가 21일선 위입니다. 진입 {C[i]:,.{DP}f} · TP {C[i]+3*a:,.{DP}f} · SL {C[i]-1.5*a:,.{DP}f} · 손익비 1:2 · 유효 8봉.',
                extra=dict(entry=C[i], tp=C[i] + 3 * a, sl=C[i] - 1.5 * a))
            msell_i = None
        if hst[i - 1] >= 0 > hst[i] and C[i] < df.e21.iat[i]:
            add(i, 'msell', '모멘텀 SELL', 'momo', 'aboveBar', RED,
                'MACD 히스토그램이 0 아래로 전환하고 종가가 21일선 아래입니다. 하락 가속 구간의 시작입니다.')
            msell_i = i
        if msell_i is not None and i - msell_i >= 3 and hst[i] < 0 and hst[i] > hst[i - 1] > hst[i - 2] > hst[i - 3]:
            add(i, 'mend', '하락 모멘텀 종료', 'momo', 'belowBar', GREY,
                '하락 속도(가속)가 멈췄다는 뜻이지 반등 확정이 아닙니다. 바닥 다지기나 횡보로 이어질 수 있습니다.', 'circle')
            msell_i = None
        # --- PBB / PBS
        if df.e21.iat[i] > df.e55.iat[i] and C[i] > df.e55.iat[i] and L[i] <= df.e21.iat[i] * 1.003 and C[i] > df.e21.iat[i] and C[i] > O[i] and ok('pbb', i, 6):
            add(i, 'pbb', 'PBB', 'pb', 'belowBar', GREEN, '상승 추세에서 21일선까지 눌린 뒤 양봉으로 지지받았습니다(눌림 지지).', 'circle')
        if df.e21.iat[i] < df.e55.iat[i] and H[i] >= df.e21.iat[i] * 0.997 and C[i] < df.e21.iat[i] and C[i] < O[i] and ok('pbs', i, 6):
            add(i, 'pbs', 'PBS', 'pb', 'aboveBar', RED, '하락 추세에서 21일선까지 반등했다가 음봉으로 밀렸습니다(반등 저항).', 'circle')
        # --- MR
        if C[i - 1] < df.bbL.iat[i - 1] and df.rsi.iat[i - 1] < 33 and C[i] > df.bbL.iat[i] and ok('mrl', i, 10):
            add(i, 'mrl', 'MR Long', 'mr', 'belowBar', BLUE, '시그마 밴드 하단 아래 과매도(RSI<33)에서 밴드 안으로 복귀했습니다. 평균회귀 반등 신호로, 추세 신호보다 짧게 봅니다.', 'circle')
        if C[i - 1] > df.bbU.iat[i - 1] and df.rsi.iat[i - 1] > 75 and C[i] < df.bbU.iat[i] and ok('mrs', i, 10):
            add(i, 'mrs', 'MR Short', 'mr', 'aboveBar', VIOLET, '시그마 밴드 상단 위 과매수(RSI>75)에서 밴드 안으로 되돌아왔습니다. 평균회귀 숏/익절 신호입니다.', 'circle')
        # --- NH
        if i >= 200 and C[i] >= C[max(0, i - 251):i + 1].max() and ok('nh', i, 5):
            add(i, 'nh', 'NH', 'nh', 'aboveBar', GREY, '종가 기준 52주 신고가.', 'circle')
        # --- chart patterns
        if len(hc) >= 2 and len(lc) >= 2:
            ph, pl = hc[-3:], lc[-3:]
            fh, fl = fitline(ph, [H[p] for p in ph]), fitline(pl, [L[p] for p in pl])
            kind, name = classify(fh[0], fl[0], a)
            if kind:
                up_i = fh[0] * i + fh[1]; lo_i = fl[0] * i + fl[1]
                up_p = fh[0] * (i - 1) + fh[1]; lo_p = fl[0] * (i - 1) + fl[1]
                pid = (tuple(ph), tuple(pl))
                if up_i > lo_i:
                    if C[i] > up_i + 0.2 * a and C[i - 1] <= up_p + 0.2 * a and (pid, 'u') not in pat_done:
                        pat_done.add((pid, 'u'))
                        add(i, 'patup', f'{name.replace("상승 ","").replace("하락 ","").replace("하강 ","")} 상방 돌파', 'pattern', 'belowBar', GREEN,
                            f'{name} 상단선({up_i:,.{DP}f})을 종가로 넘었습니다.')
                    if C[i] < lo_i - 0.2 * a and C[i - 1] >= lo_p - 0.2 * a and (pid, 'd') not in pat_done:
                        pat_done.add((pid, 'd'))
                        add(i, 'patdn', f'{name.replace("상승 ","").replace("하락 ","").replace("하강 ","")} · 하방 이탈', 'pattern', 'aboveBar', RED,
                            f'{name} 하단선({lo_i:,.{DP}f})을 종가로 깼습니다.')
        # --- W / M
        piv = sorted([(p, 'H') for p in hc] + [(p, 'L') for p in lc])
        if len(piv) >= 3:
            (p1, t1), (p2, t2), (p3, t3) = piv[-3:]
            if t1 == 'L' and t2 == 'H' and t3 == 'L' and abs(L[p3] - L[p1]) <= max(0.8 * a, 0.03 * L[p1]) \
                    and C[i] > H[p2] and C[i - 1] <= H[p2] and (p1, p3) not in w_done:
                w_done.add((p1, p3))
                add(i, 'w', 'W 돌파', 'pattern', 'belowBar', VIOLET, f'쌍바닥({L[p1]:,.{DP}f} / {L[p3]:,.{DP}f}) 후 넥라인 {H[p2]:,.{DP}f} 돌파.', 'square')
            if t1 == 'H' and t2 == 'L' and t3 == 'H' and abs(H[p3] - H[p1]) <= max(0.8 * a, 0.03 * H[p1]) \
                    and C[i] < L[p2] and C[i - 1] >= L[p2] and (p1, p3) not in w_done:
                w_done.add((p1, p3))
                add(i, 'm', 'M 이탈', 'pattern', 'aboveBar', VIOLET, f'쌍봉({H[p1]:,.{DP}f} / {H[p3]:,.{DP}f}) 후 넥라인 {L[p2]:,.{DP}f} 이탈.', 'square')
        trail.append(state)

    return df, ev, hs, ls, dict(state=state, entry=entry, stop=stop, tp1=tp1, tp2=tp2, lvl=lvl, ei=ei,
                                hitTP1=hitTP1, f8=f8, f14=f14, f21=f21, pyr=pyr, peg=peg)

def weekly_up(df):
    w = df.set_index('date').c.resample('W-FRI').last().dropna()
    e10, e30 = ema(w, 10), ema(w, 30)
    return bool(w.iat[-1] > e10.iat[-1] and e10.iat[-1] > e30.iat[-1]), float(e10.iat[-1]), float(e30.iat[-1])

def rs_score(c):
    if len(c) < 260: return float('nan')
    r = lambda k: c.iat[-1] / c.iat[-1 - k] - 1
    return 0.4 * r(63) + 0.2 * r(126) + 0.2 * r(189) + 0.2 * r(252)

def mc(S, sig, up, dn, H=10, N=20000, seed=7):
    rng = np.random.default_rng(seed)
    z = rng.standard_normal((N, H)) * sig - 0.5 * sig * sig
    paths = S * np.exp(np.cumsum(z, axis=1))
    hit_u = (paths >= up).argmax(axis=1); hu = (paths >= up).any(axis=1)
    hit_d = (paths <= dn).argmax(axis=1); hd = (paths <= dn).any(axis=1)
    hit_u = np.where(hu, hit_u, 999); hit_d = np.where(hd, hit_d, 999)
    pu = float(((hit_u < hit_d)).mean()); pd_ = float(((hit_d < hit_u)).mean()); pn = 1 - pu - pd_
    q = np.percentile(paths[:, -1], [10, 50, 90])
    return pu, pd_, pn, [float(x) for x in q]

def story(sym, r):
    d, L, P = r['dash'], r['levels'], r['prob']
    ev = r['events']; last = [e for e in ev if e['t'] >= ev[-1]['t']] if ev else []
    rec = [e for e in ev if e['t'] >= r['candles'][-10][0]]
    lines = []
    head = f"{sym}는 추세 등급 {d['grade']}({d['gname']}), 이평선 {d['align']}, {d['weekly']} 상태이고 트렌드 템플릿 9개 중 {d['nchk']}개를 충족합니다."
    lines.append(head)
    if rec:
        seq = ' → '.join(dict.fromkeys(e['text'] for e in rec if e['cat'] not in ('nh',) and e['code'] not in ('x8','r8')))
        if seq: lines.append(f"최근 10봉 신호 흐름: {seq}.")
    lines.append(f"다음 10거래일 기준 위쪽 레벨은 {L['U']:,} (그다음 {L['U2']:,}), 아래쪽 레벨은 {L['D']:,} (그다음 {L['D2']:,})입니다. "
                 f"최근 변동성(일 {P['sigD']}%)으로 돌린 몬테카를로에서 {L['U']:,}에 먼저 닿을 확률 {P['up']}%, {L['D']:,}에 먼저 닿을 확률 {P['dn']}%, 둘 다 안 닿을 확률 {P['none']}%입니다.")
    if d['state'].startswith('보유') or d['entry']:
        lines.append(f"보유 사이클 진행 중: 진입 {d['entry']:,} · 손절 {d['stop']:,} · TP1 {d['tp1']:,}.")
    trig = max(L['U'], d['e21'])
    lines.append(f"상방 시나리오의 확인 조건은 종가 {trig:,} 돌파(위쪽 레벨과 21일선 중 높은 쪽)와 거래량 1.15배 이상입니다. "
                 f"하방은 종가가 {L['D']:,} 아래로 마감하면 다음 지지 {L['D2']:,}까지 열어둡니다.")
    return lines


SIMPLE = {'bo': 'buy', 'reclaim': 'buy', 'srflip': 'buy', 'pegrt': 'buy', 'pegrb': 'buy',
          'pyr': 'add', 'pullsurge': 'add',
          'tp1': 'trim', 'tp2': 'trim', 'trim': 'trim',
          'final': 'sell', 'bofail': 'sell'}
SNAME = {'buy': '매수', 'add': '추가 매수', 'trim': '일부 익절', 'sell': '매도'}
SDESC = {'buy': '막혀 있던 고점을 거래량과 함께 넘었거나, 넘은 뒤 다시 지지를 확인했습니다. 손절가를 먼저 정하고 들어가는 자리입니다.',
         'add': '이미 수익 중인 상태에서 잠깐 눌렸다가 다시 오르기 시작했습니다. 수익 난 종목에만 조금 더 싣는 자리입니다.',
         'trim': '목표가에 닿았거나 너무 빨리 올랐습니다. 일부를 팔아 수익을 챙겨 두는 자리입니다.',
         'sell': '추세가 꺾였거나 손절선을 깼습니다. 남은 물량을 정리하고 다음 기회를 기다리는 자리입니다.'}

def easy(sym, r, st_raw):
    d, c = r['dash'], r['dash']['close']
    cand = r['candles']; n = len(cand)
    s200, e21, e55, atr = d['s200'], d['e21'], d['e55'], d['atr']
    if s200 is None: s200 = d['s100'] if d['s100'] is not None else e55
    # simple signals, one per kind per day
    sig, seen = [], set()
    for e in r['events']:
        k = SIMPLE.get(e['code'])
        if not k or (e['t'], k) in seen: continue
        seen.add((e['t'], k))
        sig.append(dict(t=e['t'], k=k, name=SNAME[k], why=e['desc'], f10=e['f10'], f5=e['f5']))
    # track record
    rec = {}
    for k in SNAME:
        f = [x['f10'] for x in sig if x['k'] == k and x['f10'] is not None]
        if not f: rec[k] = dict(n=0); continue
        good = [v > 0 for v in f] if k in ('buy', 'add') else [v < 0 for v in f]
        rec[k] = dict(n=len(f), good=sum(good), avg=round(sum(f) / len(f), 1))
    recent_idx = {x[0]: j for j, x in enumerate(cand)}
    last10 = set(x[0] for x in cand[-10:])
    recent_sell = [x for x in sig if x['k'] == 'sell' and x['t'] in last10]
    holding = st_raw['state'] in ('보유', '관리')
    checks = [('장기 추세: 200일선 위에 있나요?', c > s200, f'200일선 {s200:,.{DP}f}'),
              ('단기 추세: 21일선 위에 있나요?', c > e21, f'21일선 {e21:,.{DP}f}'),
              ('최근 2주 안에 매도 신호가 없었나요?', not recent_sell, recent_sell[-1]['t'][5:].replace('-', '/') + ' 매도 신호' if recent_sell else '없음')]
    if holding:
        light = '보유'
        entry, stop, tgt = d['entry'], d['stop'], d['tp2'] if st_raw.get('hitTP1') else d['tp1']
        lastbuy = next((x for x in reversed(sig) if x['k'] == 'buy'), None)
        reason = f"{lastbuy['t'][5:].replace('-', '/') if lastbuy else '최근'} 매수 신호 이후 보유 중입니다. 종가가 손절가 {stop:,.{DP}f} 아래로 내려가면 매도합니다."
        plan = dict(kind='hold', entry=entry, stop=stop, target=tgt, title='지금 진행 중인 계획')
    else:
        trig = round(max(e21, r['levels']['U']) if c > s200 else max(s200, e21), 2)
        stop = round(trig - 2 * atr, 2); tgt = round(trig + 4 * atr, 2)
        plan = dict(kind='wait', entry=trig, stop=stop, target=tgt, title='다음 매수 계획 (아직 진입 전)')
        if c < s200:
            light = '위험'
            reason = f"장기 추세선인 200일선({s200:,.{DP}f}) 아래에 있습니다. 하락 추세에서는 매수 신호를 기다리지 않습니다."
        elif c < e21:
            light = '관망'
            tail = f" {recent_sell[-1]['t'][5:].replace('-', '/')}에 매도 신호도 나왔습니다." if recent_sell else ''
            reason = f"단기 추세선인 21일선({e21:,.{DP}f}) 아래로 내려와 쉬는 중입니다.{tail} 종가가 {trig:,.{DP}f} 위로, 전날 고가보다 높게 마감하면 매수 신호가 나옵니다."
        elif e21 > e55:
            light = '매수 대기'
            reason = f"추세는 살아 있습니다. {trig:,.{DP}f} 위로 거래량이 붙어 마감하면 매수 신호가 나옵니다."
        else:
            light = '관망'
            reason = f"방향이 정해지지 않았습니다. {trig:,.{DP}f} 위로 올라올 때까지 기다립니다."
    plan['rr'] = round((plan['target'] - plan['entry']) / (plan['entry'] - plan['stop']), 1) if plan['entry'] > plan['stop'] else None
    plan['gap'] = round((plan['entry'] / c - 1) * 100, 1)
    return dict(light=light, reason=reason, checks=[[a, bool(b), t] for a, b, t in checks], plan=plan, signals=sig, record=rec, sdesc=SDESC)

def build_all(data, log=print):
    out = {}
    allev = []
    bench = 'QQQ' if 'QQQ' in data else next(iter(data))
    qqq = data[bench].set_index('date').c.copy()
    for sym, df in data.items():
        if len(df) < 130:
            log(f'SKIP {sym}: {len(df)} bars'); continue
        global DP
        _c = float(df.c.iloc[-1]); DP = 0 if _c >= 10000 else 2
        try:
            df, ev, hs, ls, st = run(sym, df.copy())
        except Exception as ex:
            log(f'FAIL {sym}: {ex}'); continue
        n = len(df); i = n - 1
        C = df.c.values
        for e in ev:
            j = e['i']
            e['fwd5'] = float(C[j + 5] / C[j] - 1) if j + 5 < n else None
            e['fwd10'] = float(C[j + 10] / C[j] - 1) if j + 10 < n else None
            e['sym'] = sym
        allev += ev
        out[sym] = dict(df=df, ev=ev, hs=hs, ls=ls, st=st)

    # signal statistics (bullish = belowBar signals expect up)
    stats = {}
    for code in sorted(set(e['code'] for e in allev)):
        for scope in ('all',) + tuple(out):
            es = [e for e in allev if e['code'] == code and e['fwd10'] is not None and (scope == 'all' or e['sym'] == scope)]
            if not es: continue
            f = np.array([e['fwd10'] for e in es])
            stats.setdefault(code, {})[scope] = dict(n=len(es), up=float((f > 0).mean()), avg=float(f.mean()), med=float(np.median(f)))

    result = {}
    for sym, o in out.items():
        df, ev, hs, ls, st = o['df'], o['ev'], o['hs'], o['ls'], o['st']
        n = len(df); i = n - 1; a = df.atr.iat[i]; c = df.c.iat[i]
        dates = df.date.dt.strftime('%Y-%m-%d').tolist()
        r2 = lambda x: None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), 2)
        series = {k: [r2(x) for x in df[k]] for k in ('e8', 'e14', 'e21', 'e55', 's100', 's200', 'bbU', 'bbL')}
        candles = [[dates[j], r2(df.o.iat[j]), r2(df.h.iat[j]), r2(df.l.iat[j]), r2(df.c.iat[j]), int(df.v.iat[j])] for j in range(n)]
        sq = [dates[j] for j in range(n) if df['sq'].iat[j]]
        # zigzag
        piv = sorted([(p, 'H', df.h.iat[p]) for p in hs] + [(p, 'L', df.l.iat[p]) for p in ls])
        zz = []
        for p, t, v in piv:
            if zz and zz[-1][1] == t:
                if (t == 'H' and v > zz[-1][2]) or (t == 'L' and v < zz[-1][2]): zz[-1] = (p, t, v)
            else: zz.append((p, t, v))
        zigzag = [[dates[p], r2(v)] for p, t, v in zz]
        # current pattern (confirmed pivots)
        K = 5
        hc = [p for p in hs if p <= i - K and p >= i - 90]; lc = [p for p in ls if p <= i - K and p >= i - 90]
        pattern = None
        FUT = 20
        if len(hc) >= 2 and len(lc) >= 2:
            ph, pl = hc[-3:], lc[-3:]
            mh, bh = np.polyfit(ph, [df.h.iat[p] for p in ph], 1); ml, bl = np.polyfit(pl, [df.l.iat[p] for p in pl], 1)
            kind, name = classify(mh, ml, a)
            x0 = min(ph[0], pl[0])
            pattern = dict(kind=kind, name=name or '불규칙', x0=x0, upper=[mh, bh], lower=[ml, bl],
                           upNow=float(mh * i + bh), loNow=float(ml * i + bl), ph=ph, pl=pl)
        # levels
        lastH = [p for p in hs if p >= i - 60]; lastL = [p for p in ls if p >= i - 60]
        res_cands = sorted(set([r2(df.h.iat[p]) for p in hs if df.h.iat[p] > c and p >= i - 120] +
                               [r2(df[k].iat[i]) for k in ('e8', 'e14', 'e21', 'e55', 's100', 's200') if df[k].iat[i] > c * 1.003]))
        sup_cands = sorted(set([r2(df.l.iat[p]) for p in ls if df.l.iat[p] < c and p >= i - 120] +
                               [r2(df[k].iat[i]) for k in ('e8', 'e14', 'e21', 'e55', 's100', 's200') if df[k].iat[i] < c * 0.997]), reverse=True)
        if pattern and pattern['kind']:
            if pattern['upNow'] > c: res_cands = sorted(set(res_cands + [r2(pattern['upNow'])]))
            if pattern['loNow'] < c: sup_cands = sorted(set(sup_cands + [r2(pattern['loNow'])]), reverse=True)
        # choose levels at least 0.6 ATR away
        U = next((x for x in res_cands if x - c >= 0.6 * a), c + 2 * a)
        U2 = next((x for x in res_cands if x - U >= 1.0 * a), U + 2 * a)
        D = next((x for x in sup_cands if c - x >= 0.6 * a), c - 2 * a)
        D2 = next((x for x in sup_cands if D - x >= 1.0 * a), D - 2 * a)
        lr = np.log(df.c).diff()
        sig = float(0.5 * lr.iloc[-20:].std() + 0.5 * lr.iloc[-60:].std())
        pu, pd_, pn, q = mc(c, sig, U, D)
        # dashboard
        wu, we10, we30 = weekly_up(df)
        e8, e14, e21, e55 = (df[k].iat[i] for k in ('e8', 'e14', 'e21', 'e55'))
        s50, s150, s200 = df.s50.iat[i], df.s150.iat[i], df.s200.iat[i]
        if e8 > e14 > e21 > e55: align = '정배열'
        elif e8 < e14 < e21 < e55: align = '역배열'
        else: align = '꼬임'
        hi52, lo52 = df.h.iloc[-252:].max(), df.l.iloc[-252:].min()
        rsS = rs_score(df.c); rsQ = rs_score(qqq)
        rsline = (df.set_index('date').c / qqq.reindex(df.date).ffill()).reset_index(drop=True)
        updays = df.c.diff() > 0
        upv = df.v.where(updays, 0).iloc[-50:].sum(); dnv = df.v.where(~updays, 0).iloc[-50:].sum()
        checks = [
            ('종가 > 150·200일선', bool(c > s150 and c > s200)),
            ('150일선 > 200일선', bool(s150 > s200)),
            ('200일선 1개월 상승', bool(s200 > df.s200.iat[i - 22])),
            ('50일선 > 150·200일선', bool(s50 > s150 and s50 > s200)),
            ('종가 > 50일선', bool(c > s50)),
            ('52주 저점 대비 +30% 이상', bool(c >= 1.3 * lo52)),
            ('52주 고점 대비 -25% 이내', bool(c >= 0.75 * hi52)),
            ('QQQ 대비 RS선 > 50일 평균' if sym != bench else 'RS 점수 플러스', bool(rsline.iat[-1] > rsline.iloc[-50:].mean()) if sym != bench else bool(rsS > 0)),
            ('50일 상승일 거래량 > 하락일', bool(upv > dnv)),
        ]
        nchk = sum(x for _, x in checks)
        score = sum([c > e21, e8 > e21, e21 > e55, c > s200, s200 > df.s200.iat[i - 20], wu,
                     df.adx.iat[i] > 20 and df.pdi.iat[i] > df.mdi.iat[i]])
        grade = 'S' if score >= 6 else 'H' if score == 5 else 'N' if score >= 3 else 'W' if score == 2 else 'D'
        gname = dict(S='강세', H='양호', N='중립', W='약세', D='하락')[grade]
        conv = 'A' if nchk >= 8 and grade in 'SH' else 'B' if nchk >= 6 and grade in 'SHN' else 'C' if grade in 'SHN' else 'D'
        bp = df.v.where(updays, 0).iloc[-20:].sum() / df.v.iloc[-20:].sum()
        recent = [e for e in ev if e['i'] >= i - 15]
        stt = st['state']
        if stt == '관찰':
            su = [e for e in ev if e['code'] == 'setup' and e['i'] >= i - 10]
            if su and su[-1]['level'] * 0.95 <= c < su[-1]['level'] and c > e55: stt = '셋업 형성 중'
            elif any(e['code'] in ('final', 'bofail') for e in ev if e['i'] >= i - 5): stt = '청산 직후 · 관찰'
        dash = dict(
            state=stt, grade=grade, gname=gname, score=int(score), conv=conv,
            pull=r2(e8), align=align, weekly='주봉 상승' if wu else '주봉 약세', we10=r2(we10),
            adx=r2(df.adx.iat[i]), di='+DI 우위' if df.pdi.iat[i] > df.mdi.iat[i] else '-DI 우위',
            bp=round(float(bp) * 100), vr=r2(df.vr.iat[i]), hi52=r2(hi52), fromHi=round(float(c / hi52 - 1) * 100, 1),
            rs=None if math.isnan(rsS) else round(float(rsS * 100), 1), rsQ=None if math.isnan(rsQ) else round(float(rsQ * 100), 1), rsi=r2(df.rsi.iat[i]),
            checks=checks, nchk=int(nchk), atr=r2(a), atrPct=round(float(a / c * 100), 2),
            entry=r2(st['entry']) if st['state'] != '관찰' else None, stop=r2(st['stop']) if st['state'] != '관찰' else None,
            tp1=r2(st['tp1']) if st['state'] != '관찰' else None, tp2=r2(st['tp2']) if st['state'] != '관찰' else None,
            sq=bool(df['sq'].iat[i]), sqCount=int(df['sq'].iloc[-20:].sum()),
            close=r2(c), chg=round(float(c / df.c.iat[i - 1] - 1) * 100, 2), date=dates[i],
            e8=r2(e8), e14=r2(e14), e21=r2(e21), e55=r2(e55), s100=r2(df.s100.iat[i]), s200=r2(s200),
            bbU=r2(df.bbU.iat[i]), bbL=r2(df.bbL.iat[i]),
        )
        evs = [dict(t=dates[e['i']], live=e['i'] == n - 1, code=e['code'], text=e['text'], cat=e['cat'], pos=e['pos'], color=e['color'],
                    shape=e['shape'], desc=e['desc'], f10=None if e['fwd10'] is None else round(e['fwd10'] * 100, 1),
                    f5=None if e['fwd5'] is None else round(e['fwd5'] * 100, 1),
                    **({k: r2(e[k]) for k in ('entry', 'stop', 'tp1', 'tp2', 'tp', 'sl', 'level', 'f382', 'f50', 'f618', 'base') if k in e}))
               for e in ev]
        result[sym] = dict(candles=candles, series=series, sq=sq, zigzag=zigzag, events=evs, dash=dash,
                           pattern=None if not pattern else dict(kind=pattern['kind'], name=pattern['name'],
                               x0=dates[pattern['x0']], x0i=int(pattern['x0']), upper=[float(pattern['upper'][0]), float(pattern['upper'][1])],
                               lower=[float(pattern['lower'][0]), float(pattern['lower'][1])], upNow=r2(pattern['upNow']), loNow=r2(pattern['loNow'])),
                           n=n, levels=dict(U=r2(U), U2=r2(U2), D=r2(D), D2=r2(D2)),
                           prob=dict(up=round(pu * 100), dn=round(pd_ * 100), none=round(pn * 100), q10=r2(q[0]), q50=r2(q[1]), q90=r2(q[2]),
                                     sigD=round(sig * 100, 2), sig10=round(sig * math.sqrt(10) * 100, 1)),
                           peg=None if not st['peg'] or st['peg']['done'] or i - st['peg']['i'] > 30 else
                               dict(t=dates[st['peg']['i']], f382=r2(st['peg']['f382']), f50=r2(st['peg']['f50']), f618=r2(st['peg']['f618']), base=r2(st['peg']['base'])))
    base = {}
    for sym, o in out.items():
        c = o['df'].c.values; f = np.array([c[j + 10] / c[j] - 1 for j in range(60, len(c) - 10)])
        base[sym] = dict(n=len(f), up=float((f > 0).mean()), avg=float(f.mean()))
    allf = np.concatenate([[o['df'].c.values[j + 10] / o['df'].c.values[j] - 1 for j in range(60, len(o['df']) - 10)] for o in out.values()])
    base['all'] = dict(n=len(allf), up=float((allf > 0).mean()), avg=float(allf.mean()))
    result['_base'] = base
    for sym in out:
        r = result[sym]; p = r['pattern']; c = r['dash']['close']
        if p:
            p['status'] = '하방 이탈' if c < p['loNow'] else '상방 돌파' if c > p['upNow'] else '진행 중'
        DP = 0 if r['dash']['close'] >= 10000 else 2
        r['story'] = story(sym, r)
        r['easy'] = easy(sym, r, out[sym]['st'])
        for e in r['events']: e['live'] = False
    result['_stats'] = stats
    return result

if __name__ == '__main__':
    result = build_all(load())
    json.dump(result, open('engine.json', 'w'), ensure_ascii=False, separators=(',', ':'))
    for sym in result:
        if sym.startswith('_'): continue
        r = result[sym]; d = r['dash']
        print(sym, d['close'], d['state'], d['grade'], d['conv'], d['nchk'], r['easy']['light'])
