"""
45-strategy technical backtest engine.
Each strategy produces a signal series: 1 = buy, -1 = sell, 0 = no signal.
Backtest is long-only, single position: enter on buy signal if flat, exit on sell signal if in position.
"""
import numpy as np
import pandas as pd


# ---------- indicator helpers ----------
def sma(s, n):
    return s.rolling(n).mean()


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi(close, n=14):
    delta = close.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    roll_up = up.ewm(alpha=1 / n, adjust=False).mean()
    roll_down = down.ewm(alpha=1 / n, adjust=False).mean()
    rs = roll_up / roll_down.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(close, fast=12, slow=26, signal=9):
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    return macd_line, signal_line


def bollinger(close, n=20, k=2):
    mid = sma(close, n)
    std = close.rolling(n).std()
    upper = mid + k * std
    lower = mid - k * std
    return upper, mid, lower


def stochastic(high, low, close, k=14, d=3, smooth=3):
    lowest = low.rolling(k).min()
    highest = high.rolling(k).max()
    raw_k = 100 * (close - lowest) / (highest - lowest).replace(0, np.nan)
    pct_k = raw_k.rolling(smooth).mean()
    pct_d = pct_k.rolling(d).mean()
    return pct_k, pct_d


def cci(high, low, close, n=14):
    tp = (high + low + close) / 3
    ma = tp.rolling(n).mean()
    md = tp.rolling(n).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    return (tp - ma) / (0.015 * md.replace(0, np.nan))


def williams_r(high, low, close, n=14):
    highest = high.rolling(n).max()
    lowest = low.rolling(n).min()
    return -100 * (highest - close) / (highest - lowest).replace(0, np.nan)


def true_range(high, low, close):
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr


def adx_di(high, low, close, n=14):
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr = true_range(high, low, close)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=high.index).ewm(alpha=1 / n, adjust=False).mean() / atr.replace(0, np.nan)
    minus_di = 100 * pd.Series(minus_dm, index=high.index).ewm(alpha=1 / n, adjust=False).mean() / atr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / n, adjust=False).mean()
    return adx, plus_di, minus_di


def obv(close, volume):
    direction = np.sign(close.diff().fillna(0))
    return (direction * volume).fillna(0).cumsum()


def roc(close, n=10):
    return 100 * (close - close.shift(n)) / close.shift(n)


def parabolic_sar(high, low, close, af_step=0.02, af_max=0.2):
    n = len(close)
    sar = np.zeros(n)
    trend = np.zeros(n)  # 1 uptrend, -1 downtrend
    ep = np.zeros(n)
    af = np.zeros(n)
    trend[0] = 1
    sar[0] = low.iloc[0]
    ep[0] = high.iloc[0]
    af[0] = af_step
    for i in range(1, n):
        prev_sar = sar[i - 1]
        if trend[i - 1] == 1:
            sar[i] = prev_sar + af[i - 1] * (ep[i - 1] - prev_sar)
            sar[i] = min(sar[i], low.iloc[i - 1], low.iloc[i - 2] if i > 1 else low.iloc[i - 1])
            if low.iloc[i] < sar[i]:
                trend[i] = -1
                sar[i] = ep[i - 1]
                ep[i] = low.iloc[i]
                af[i] = af_step
            else:
                trend[i] = 1
                if high.iloc[i] > ep[i - 1]:
                    ep[i] = high.iloc[i]
                    af[i] = min(af[i - 1] + af_step, af_max)
                else:
                    ep[i] = ep[i - 1]
                    af[i] = af[i - 1]
        else:
            sar[i] = prev_sar + af[i - 1] * (ep[i - 1] - prev_sar)
            sar[i] = max(sar[i], high.iloc[i - 1], high.iloc[i - 2] if i > 1 else high.iloc[i - 1])
            if high.iloc[i] > sar[i]:
                trend[i] = 1
                sar[i] = ep[i - 1]
                ep[i] = high.iloc[i]
                af[i] = af_step
            else:
                trend[i] = -1
                if low.iloc[i] < ep[i - 1]:
                    ep[i] = low.iloc[i]
                    af[i] = min(af[i - 1] + af_step, af_max)
                else:
                    ep[i] = ep[i - 1]
                    af[i] = af[i - 1]
    return pd.Series(sar, index=close.index), pd.Series(trend, index=close.index)


def compute_trend_status(df, ma_fast=20, ma_slow=50, adx_n=14):
    """Always-on structural 'is this still an uptrend' read, separate from the 45-strategy
    backtest pool (those are backtested entry/exit signals; this is just a current-state
    trend classification with no backtest behind it). Combines three independent trend
    reads and takes a majority vote so a single noisy indicator can't flip the call:
      1. MA(20/50) 정배열/역배열 - fast MA above slow MA = uptrend structure intact
      2. ADX/DMI - +DI above -DI = buyers in control (ADX value itself flags trend strength)
      3. Parabolic SAR - dots below price = still in an uptrend leg
    `up_votes` of 3 is exposed as-is so the report can show a confidence label (3/3 vs 2/1)
    rather than collapsing straight to a bare up/down call.
    """
    close = df.Close
    ma_f = sma(close, ma_fast)
    ma_s = sma(close, ma_slow)
    ma_vote = "up" if ma_f.iloc[-1] > ma_s.iloc[-1] else "down"

    adx, pdi, mdi = adx_di(df.High, df.Low, df.Close, adx_n)
    adx_vote = "up" if pdi.iloc[-1] > mdi.iloc[-1] else "down"

    sar, sar_trend = parabolic_sar(df.High, df.Low, df.Close)
    sar_vote = "up" if sar_trend.iloc[-1] == 1 else "down"

    votes = [ma_vote, adx_vote, sar_vote]
    up_votes = votes.count("up")

    def _r(x, nd=2):
        return round(float(x), nd) if x is not None and not pd.isna(x) else None

    return {
        "overall": "up" if up_votes >= 2 else "down",
        "up_votes": up_votes,
        "total_votes": len(votes),
        "ma_fast": ma_fast,
        "ma_slow": ma_slow,
        "ma_fast_value": _r(ma_f.iloc[-1]),
        "ma_slow_value": _r(ma_s.iloc[-1]),
        "ma_vote": ma_vote,
        "adx_value": _r(adx.iloc[-1], 1),
        "plus_di": _r(pdi.iloc[-1], 1),
        "minus_di": _r(mdi.iloc[-1], 1),
        "adx_vote": adx_vote,
        "sar_value": _r(sar.iloc[-1]),
        "sar_vote": sar_vote,
    }


def donchian(high, low, n=20):
    return high.rolling(n).max(), low.rolling(n).min()


# ---- extra indicators added to match the real "45 strategies" catalog (see
# https://alphasquare.oopy.io/board/technical-indicator and the 증권플러스-style
# indicator picker screenshot) - one canonical rule per indicator, not parameter
# sweeps. A few of these (매물대/이격도/SONAR/투자심리도/Volume Ratio) don't have a
# single universally-agreed numeric rule, so the thresholds below are standard
# textbook defaults, not verified against any specific vendor's exact formula. ----

def money_flow_index(high, low, close, volume, n=14):
    tp = (high + low + close) / 3
    raw_mf = tp * volume
    direction = np.sign(tp.diff().fillna(0))
    pos_mf = raw_mf.where(direction > 0, 0.0)
    neg_mf = raw_mf.where(direction < 0, 0.0)
    pos_sum = pos_mf.rolling(n).sum()
    neg_sum = neg_mf.rolling(n).sum()
    ratio = pos_sum / neg_sum.replace(0, np.nan)
    return 100 - (100 / (1 + ratio))


def ad_line(high, low, close, volume):
    mfm = ((close - low) - (high - close)) / (high - low).replace(0, np.nan)
    return (mfm * volume).fillna(0).cumsum()


def chaikin_money_flow(high, low, close, volume, n=20):
    mfm = ((close - low) - (high - close)) / (high - low).replace(0, np.nan)
    mfv = (mfm * volume).fillna(0)
    return mfv.rolling(n).sum() / volume.rolling(n).sum().replace(0, np.nan)


def chaikin_oscillator(high, low, close, volume, fast=3, slow=10):
    ad = ad_line(high, low, close, volume)
    return ema(ad, fast) - ema(ad, slow)


def chaikin_volatility(high, low, n=10, roc_n=10):
    hl_ema = ema(high - low, n)
    return 100 * (hl_ema - hl_ema.shift(roc_n)) / hl_ema.shift(roc_n).replace(0, np.nan)


def trix(close, n=15):
    e1 = ema(close, n)
    e2 = ema(e1, n)
    e3 = ema(e2, n)
    return 100 * (e3 - e3.shift(1)) / e3.shift(1).replace(0, np.nan)


def aroon(high, low, n=25):
    def _up(x):
        return 100 * (n - (len(x) - 1 - np.argmax(x.values))) / n

    def _down(x):
        return 100 * (n - (len(x) - 1 - np.argmin(x.values))) / n

    aroon_up = high.rolling(n + 1).apply(_up, raw=False)
    aroon_down = low.rolling(n + 1).apply(_down, raw=False)
    return aroon_up, aroon_down


def elder_ray(high, low, close, n=13):
    e = ema(close, n)
    return high - e, low - e  # bull_power, bear_power


def stoch_rsi(close, rsi_n=14, stoch_n=14):
    r = rsi(close, rsi_n)
    lo = r.rolling(stoch_n).min()
    hi = r.rolling(stoch_n).max()
    return 100 * (r - lo) / (hi - lo).replace(0, np.nan)


def mass_index(high, low, ema_n=9, sum_n=25):
    rng = high - low
    single = ema(rng, ema_n)
    double = ema(single, ema_n)
    ratio = single / double.replace(0, np.nan)
    return ratio.rolling(sum_n).sum()


def pvi(close, volume):
    idx = close.index
    vals = np.full(len(close), 100.0)
    c = close.values
    v = volume.values
    for i in range(1, len(close)):
        if v[i] > v[i - 1]:
            vals[i] = vals[i - 1] * (1 + (c[i] - c[i - 1]) / c[i - 1])
        else:
            vals[i] = vals[i - 1]
    return pd.Series(vals, index=idx)


def nvi(close, volume):
    idx = close.index
    vals = np.full(len(close), 100.0)
    c = close.values
    v = volume.values
    for i in range(1, len(close)):
        if v[i] < v[i - 1]:
            vals[i] = vals[i - 1] * (1 + (c[i] - c[i - 1]) / c[i - 1])
        else:
            vals[i] = vals[i - 1]
    return pd.Series(vals, index=idx)


def eom(high, low, volume, n=14):
    mid_move = ((high + low) / 2) - ((high.shift(1) + low.shift(1)) / 2)
    box_ratio = (volume / 1e8) / (high - low).replace(0, np.nan)
    one_period = mid_move / box_ratio.replace(0, np.nan)
    return one_period.rolling(n).mean()


def envelope(close, n=20, pct=6):
    mid = sma(close, n)
    return mid * (1 + pct / 100), mid, mid * (1 - pct / 100)


def pivot_point(high, low, close):
    """Classic prior-bar pivot: (prevH+prevL+prevC)/3."""
    return (high.shift(1) + low.shift(1) + close.shift(1)) / 3


def disparity(close, n=20):
    return close / sma(close, n) * 100


def psychological_line(close, n=12):
    up_day = (close.diff() > 0).astype(float)
    return up_day.rolling(n).sum() / n * 100


def volume_ratio(close, volume, n=20):
    up_vol = volume.where(close.diff() > 0, 0.0)
    down_vol = volume.where(close.diff() < 0, 0.0)
    return up_vol.rolling(n).sum() / down_vol.rolling(n).sum().replace(0, np.nan) * 100


def sonar(close, n=9, m=13):
    """Approximation of the Korean-HTS 'SONAR' oscillator: momentum of an EMA
    relative to itself m bars ago, expressed as a %. Not a verified exact formula."""
    e = ema(close, n)
    return 100 * (e - e.shift(m)) / e.shift(m).replace(0, np.nan)


def momentum(close, n=10):
    return close - close.shift(n)


def volume_profile_poc(close, volume, window=60, nbins=20):
    """Very simplified 매물대(volume profile): over a rolling window, bucket price
    into `nbins` bins and find the bin with the largest cumulative volume (the
    point of control). Returns that price level per bar."""
    poc = np.full(len(close), np.nan)
    c = close.values
    v = volume.values
    for i in range(window, len(close)):
        seg_c = c[i - window:i]
        seg_v = v[i - window:i]
        lo, hi = seg_c.min(), seg_c.max()
        if hi <= lo:
            continue
        bins = np.linspace(lo, hi, nbins + 1)
        idxs = np.clip(np.digitize(seg_c, bins) - 1, 0, nbins - 1)
        vol_by_bin = np.zeros(nbins)
        for b, vv in zip(idxs, seg_v):
            vol_by_bin[b] += vv
        best_bin = vol_by_bin.argmax()
        poc[i] = (bins[best_bin] + bins[best_bin + 1]) / 2
    return pd.Series(poc, index=close.index)


def ultimate_oscillator(high, low, close, n1=7, n2=14, n3=28):
    prior_close = close.shift(1)
    bp = close - pd.concat([low, prior_close], axis=1).min(axis=1)
    tr = pd.concat([high, prior_close], axis=1).max(axis=1) - pd.concat([low, prior_close], axis=1).min(axis=1)
    avg1 = bp.rolling(n1).sum() / tr.rolling(n1).sum().replace(0, np.nan)
    avg2 = bp.rolling(n2).sum() / tr.rolling(n2).sum().replace(0, np.nan)
    avg3 = bp.rolling(n3).sum() / tr.rolling(n3).sum().replace(0, np.nan)
    return 100 * (4 * avg1 + 2 * avg2 + avg3) / 7


def ppo(close, fast=12, slow=26, signal=9):
    line = 100 * (ema(close, fast) - ema(close, slow)) / ema(close, slow).replace(0, np.nan)
    return line, ema(line, signal)


def pvo(volume, fast=12, slow=26, signal=9):
    line = 100 * (ema(volume, fast) - ema(volume, slow)) / ema(volume, slow).replace(0, np.nan)
    return line, ema(line, signal)


def crossover(a, b):
    """True where series a crosses above series b."""
    return (a > b) & (a.shift(1) <= b.shift(1))


def crossunder(a, b):
    return (a < b) & (a.shift(1) >= b.shift(1))


# ---------- strategy signal builders ----------
def sig_ma_cross(df, short, long, kind="sma"):
    f = sma if kind == "sma" else ema
    s, l = f(df.Close, short), f(df.Close, long)
    buy = crossover(s, l)
    sell = crossunder(s, l)
    return build_signal(buy, sell)


def sig_rsi(df, n, low_th, high_th):
    r = rsi(df.Close, n)
    buy = (r > low_th) & (r.shift(1) <= low_th)
    sell = (r < high_th) & (r.shift(1) >= high_th)
    return build_signal(buy, sell)


def sig_macd(df, fast, slow, signal):
    m, s = macd(df.Close, fast, slow, signal)
    buy = crossover(m, s)
    sell = crossunder(m, s)
    return build_signal(buy, sell)


def sig_bb_reversion(df, n, k):
    upper, mid, lower = bollinger(df.Close, n, k)
    buy = (df.Close > lower) & (df.Close.shift(1) <= lower.shift(1))
    sell = (df.Close < upper) & (df.Close.shift(1) >= upper.shift(1))
    return build_signal(buy, sell)


def sig_bb_breakout(df, n, k):
    upper, mid, lower = bollinger(df.Close, n, k)
    buy = crossover(df.Close, upper)
    sell = crossunder(df.Close, lower)
    return build_signal(buy, sell)


def sig_stochastic(df, k, d, smooth, low_th=20, high_th=80):
    pk, pd_ = stochastic(df.High, df.Low, df.Close, k, d, smooth)
    buy = crossover(pk, pd_) & (pk < low_th + 15)
    sell = crossunder(pk, pd_) & (pk > high_th - 15)
    return build_signal(buy, sell)


def sig_cci(df, n, th=100):
    c = cci(df.High, df.Low, df.Close, n)
    buy = crossover(c, pd.Series(-th, index=df.index))
    sell = crossunder(c, pd.Series(th, index=df.index))
    return build_signal(buy, sell)


def sig_williams(df, n=14, low_th=-80, high_th=-20):
    w = williams_r(df.High, df.Low, df.Close, n)
    buy = crossover(w, pd.Series(low_th, index=df.index))
    sell = crossunder(w, pd.Series(high_th, index=df.index))
    return build_signal(buy, sell)


def sig_adx_di(df, n=14, adx_min=20):
    adx, pdi, mdi = adx_di(df.High, df.Low, df.Close, n)
    buy = crossover(pdi, mdi) & (adx > adx_min)
    sell = crossover(mdi, pdi)
    return build_signal(buy, sell)


def sig_obv_trend(df, n=20):
    o = obv(df.Close, df.Volume)
    ma20 = sma(df.Close, n)
    obv_high = o.rolling(n).max()
    obv_low = o.rolling(n).min()
    buy = (o >= obv_high) & (df.Close > ma20)
    sell = (o <= obv_low) & (df.Close < ma20)
    return build_signal(buy, sell)


def sig_roc(df, n):
    r = roc(df.Close, n)
    buy = crossover(r, pd.Series(0, index=df.index))
    sell = crossunder(r, pd.Series(0, index=df.index))
    return build_signal(buy, sell)


def sig_donchian(df, n):
    dh, dl = donchian(df.High, df.Low, n)
    buy = crossover(df.Close, dh.shift(1))
    sell = crossunder(df.Close, dl.shift(1))
    return build_signal(buy, sell)


def sig_psar(df):
    sar, trend = parabolic_sar(df.High, df.Low, df.Close)
    buy = (trend == 1) & (pd.Series(trend, index=df.index).shift(1) == -1)
    sell = (trend == -1) & (pd.Series(trend, index=df.index).shift(1) == 1)
    return build_signal(buy, sell)


def sig_ichimoku_tk(df, tenkan_n=9, kijun_n=26):
    tenkan = (df.High.rolling(tenkan_n).max() + df.Low.rolling(tenkan_n).min()) / 2
    kijun = (df.High.rolling(kijun_n).max() + df.Low.rolling(kijun_n).min()) / 2
    buy = crossover(tenkan, kijun)
    sell = crossunder(tenkan, kijun)
    return build_signal(buy, sell)


def sig_volume_breakout(df, n=20, vol_mult=1.5):
    hi_n = df.High.rolling(n).max()
    lo_n = df.Low.rolling(n).min()
    vol_avg = df.Volume.rolling(n).mean()
    buy = (df.Close > hi_n.shift(1)) & (df.Volume > vol_mult * vol_avg)
    sell = df.Close < lo_n.shift(1)
    return build_signal(buy, sell)


def sig_triple_ma_alignment(df, s=5, m=20, l=60):
    ms, mm, ml = sma(df.Close, s), sma(df.Close, m), sma(df.Close, l)
    aligned_up = (ms > mm) & (mm > ml)
    aligned_down = (ms < mm) & (mm < ml)
    prev_up = aligned_up.shift(1).fillna(False).astype(bool)
    prev_down = aligned_down.shift(1).fillna(False).astype(bool)
    buy = aligned_up & (~prev_up)
    sell = aligned_down & (~prev_down)
    return build_signal(buy, sell)


def build_signal(buy, sell):
    sig = pd.Series(0, index=buy.index)
    sig[buy.fillna(False)] = 1
    sig[sell.fillna(False)] = -1
    return sig


# ---- signal builders for the extra "catalog match" indicators ----
def sig_mfi(df, n=14, lo=20, hi=80):
    m = money_flow_index(df.High, df.Low, df.Close, df.Volume, n)
    buy = crossover(m, pd.Series(lo, index=df.index))
    sell = crossunder(m, pd.Series(hi, index=df.index))
    return build_signal(buy, sell)


def sig_cmf(df, n=20):
    c = chaikin_money_flow(df.High, df.Low, df.Close, df.Volume, n)
    zero = pd.Series(0, index=df.index)
    return build_signal(crossover(c, zero), crossunder(c, zero))


def sig_ad_line(df, n=20):
    ad = ad_line(df.High, df.Low, df.Close, df.Volume)
    ad_ma = sma(ad, n)
    return build_signal(crossover(ad, ad_ma), crossunder(ad, ad_ma))


def sig_chaikin_osc(df):
    co = chaikin_oscillator(df.High, df.Low, df.Close, df.Volume)
    zero = pd.Series(0, index=df.index)
    return build_signal(crossover(co, zero), crossunder(co, zero))


def sig_chaikin_vol(df, n=10, roc_n=10):
    """Chaikin Volatility isn't directional by itself; used here as an
    expansion/contraction regime flag combined with price vs MA20 for direction."""
    cv = chaikin_volatility(df.High, df.Low, n, roc_n)
    ma20 = sma(df.Close, 20)
    expanding = (cv > 0) & (cv.shift(1) <= 0)
    contracting = (cv < 0) & (cv.shift(1) >= 0)
    buy = expanding & (df.Close > ma20)
    sell = contracting & (df.Close < ma20)
    return build_signal(buy, sell)


def sig_trix(df, n=15):
    t = trix(df.Close, n)
    sig_line = ema(t, 9)
    return build_signal(crossover(t, sig_line), crossunder(t, sig_line))


def sig_aroon(df, n=25):
    up, down = aroon(df.High, df.Low, n)
    return build_signal(crossover(up, down), crossunder(up, down))


def sig_aroon_osc(df, n=25):
    up, down = aroon(df.High, df.Low, n)
    osc = up - down
    zero = pd.Series(0, index=df.index)
    return build_signal(crossover(osc, zero), crossunder(osc, zero))


def sig_elder_ray_bull(df, n=13):
    bull, _ = elder_ray(df.High, df.Low, df.Close, n)
    zero = pd.Series(0, index=df.index)
    return build_signal(crossover(bull, zero), crossunder(bull, zero))


def sig_elder_ray_bear(df, n=13):
    _, bear = elder_ray(df.High, df.Low, df.Close, n)
    zero = pd.Series(0, index=df.index)
    return build_signal(crossover(bear, zero), crossunder(bear, zero))


def sig_atr_breakout(df, n=14, mult=1.0):
    a = true_range(df.High, df.Low, df.Close).ewm(alpha=1 / n, adjust=False).mean()
    chg = df.Close.diff()
    buy = chg > mult * a
    sell = chg < -mult * a
    return build_signal(buy, sell)


def sig_uo(df, lo=30, hi=70):
    u = ultimate_oscillator(df.High, df.Low, df.Close)
    buy = crossover(u, pd.Series(lo, index=df.index))
    sell = crossunder(u, pd.Series(hi, index=df.index))
    return build_signal(buy, sell)


def sig_ppo(df):
    line, signal = ppo(df.Close)
    return build_signal(crossover(line, signal), crossunder(line, signal))


def sig_pvo(df):
    line, signal = pvo(df.Volume)
    return build_signal(crossover(line, signal), crossunder(line, signal))


def sig_stoch_rsi(df, rsi_n=14, stoch_n=14, lo=20, hi=80):
    sr = stoch_rsi(df.Close, rsi_n, stoch_n)
    buy = crossover(sr, pd.Series(lo, index=df.index))
    sell = crossunder(sr, pd.Series(hi, index=df.index))
    return build_signal(buy, sell)


def sig_mass_index(df, ema_n=9, sum_n=25, trigger=27, revert=26.5):
    mi = mass_index(df.High, df.Low, ema_n, sum_n)
    ma20 = sma(df.Close, 20)
    bulge_reversal = (mi < revert) & (mi.shift(1) >= revert) & (mi.rolling(sum_n).max() > trigger)
    buy = bulge_reversal & (df.Close > ma20)
    sell = bulge_reversal & (df.Close < ma20)
    return build_signal(buy, sell)


def sig_pvi(df, n=20):
    p = pvi(df.Close, df.Volume)
    p_ma = sma(p, n)
    return build_signal(crossover(p, p_ma), crossunder(p, p_ma))


def sig_nvi(df, n=20):
    nv = nvi(df.Close, df.Volume)
    nv_ma = sma(nv, n)
    return build_signal(crossover(nv, nv_ma), crossunder(nv, nv_ma))


def sig_eom(df, n=14):
    e = eom(df.High, df.Low, df.Volume, n)
    zero = pd.Series(0, index=df.index)
    return build_signal(crossover(e, zero), crossunder(e, zero))


def sig_envelope(df, n=20, pct=6):
    upper, mid, lower = envelope(df.Close, n, pct)
    buy = (df.Close > lower) & (df.Close.shift(1) <= lower.shift(1))
    sell = (df.Close < upper) & (df.Close.shift(1) >= upper.shift(1))
    return build_signal(buy, sell)


def sig_pivot(df):
    piv = pivot_point(df.High, df.Low, df.Close)
    return build_signal(crossover(df.Close, piv), crossunder(df.Close, piv))


def sig_disparity(df, n=20, lo=95, hi=105):
    d = disparity(df.Close, n)
    buy = crossover(d, pd.Series(lo, index=df.index))
    sell = crossunder(d, pd.Series(hi, index=df.index))
    return build_signal(buy, sell)


def sig_psychological(df, n=12, lo=25, hi=75):
    p = psychological_line(df.Close, n)
    buy = crossover(p, pd.Series(lo, index=df.index))
    sell = crossunder(p, pd.Series(hi, index=df.index))
    return build_signal(buy, sell)


def sig_volume_ratio(df, n=20, lo=70, hi=150):
    vr = volume_ratio(df.Close, df.Volume, n)
    buy = crossover(vr, pd.Series(lo, index=df.index))
    sell = crossunder(vr, pd.Series(hi, index=df.index))
    return build_signal(buy, sell)


def sig_sonar(df, n=9, m=13):
    s = sonar(df.Close, n, m)
    zero = pd.Series(0, index=df.index)
    return build_signal(crossover(s, zero), crossunder(s, zero))


def sig_momentum(df, n=10):
    mm = momentum(df.Close, n)
    zero = pd.Series(0, index=df.index)
    return build_signal(crossover(mm, zero), crossunder(mm, zero))


def sig_dmi_cross(df, n=14):
    """Plain +DI/-DI cross, no ADX strength filter (separate from the ADX item below)."""
    adx, pdi, mdi = adx_di(df.High, df.Low, df.Close, n)
    return build_signal(crossover(pdi, mdi), crossover(mdi, pdi))


def sig_adx_trend(df, n=14, th=25):
    """ADX crossing above `th` = a trend is starting; direction comes from which DI leads."""
    adx, pdi, mdi = adx_di(df.High, df.Low, df.Close, n)
    trend_start = crossover(adx, pd.Series(th, index=df.index))
    buy = trend_start & (pdi > mdi)
    sell = trend_start & (mdi > pdi)
    return build_signal(buy, sell)


def sig_adxr(df, n=14, lag=14, th=20):
    adx, pdi, mdi = adx_di(df.High, df.Low, df.Close, n)
    adxr = (adx + adx.shift(lag)) / 2
    trend_start = crossover(adxr, pd.Series(th, index=df.index))
    buy = trend_start & (pdi > mdi)
    sell = trend_start & (mdi > pdi)
    return build_signal(buy, sell)


def sig_volume_surge(df, n=20, mult=2.0):
    vol_avg = df.Volume.rolling(n).mean()
    surge = df.Volume > mult * vol_avg
    up_day = df.Close > df.Open
    down_day = df.Close < df.Open
    return build_signal(surge & up_day, surge & down_day)


def sig_trading_value_surge(df, n=20, mult=2.0):
    tv = df.Close * df.Volume
    tv_avg = tv.rolling(n).mean()
    surge = tv > mult * tv_avg
    up_day = df.Close > df.Open
    down_day = df.Close < df.Open
    return build_signal(surge & up_day, surge & down_day)


def sig_volume_profile(df, window=60, nbins=20):
    poc = volume_profile_poc(df.Close, df.Volume, window, nbins)
    return build_signal(crossover(df.Close, poc), crossunder(df.Close, poc))


def sig_ma_price_cross(df, n=20):
    """이동평균선: price crossing a single MA (not two MAs against each other)."""
    m = sma(df.Close, n)
    return build_signal(crossover(df.Close, m), crossunder(df.Close, m))


# ---------- strategy registry ----------
# One canonical rule per indicator, matching the real indicator catalog a user found
# at https://alphasquare.oopy.io/board/technical-indicator and in a 증권플러스-style
# "보조지표 선택" screenshot (거래량/거래대금/MACD/Stochastic Fast&Slow/RSI/CCI/
# Parabolic SAR/Envelope/Pivot Points/Price Channel/이동평균선/볼린저밴드/일목균형표/
# 매물대/AD Line/ATR/CMF/MFI/OBV/투자심리도/SONAR/Chaikin Volatility/Chaikin
# Oscillator/TRIX/Williams %R/DMI/모멘텀/이격도/Volume Ratio/ROC/ADX/ADXR/Aroon/
# Aroon Oscillator/Elder Ray Bull/Elder Ray Bear/Stochastic RSI/Mass Index/PVI/NVI/
# EOM - that's the confirmed 43). Ultimate Oscillator/PPO/PVO were added to round
# out to 45 since they appear on the same vendor's indicator list but were cut off
# in the screenshot - NOT independently confirmed, flagged here for transparency.
def build_strategies():
    strategies = [
        ("거래량 급증 매매", "거래량", lambda df: sig_volume_surge(df)),
        ("거래대금 급증 매매", "거래량", lambda df: sig_trading_value_surge(df)),
        ("MACD(12,26,9) 시그널크로스", "추세추종", lambda df: sig_macd(df, 12, 26, 9)),
        ("Stochastic Fast(14,3)", "오실레이터", lambda df: sig_stochastic(df, 14, 3, 1)),
        ("Stochastic Slow(14,3,3)", "오실레이터", lambda df: sig_stochastic(df, 14, 3, 3)),
        ("RSI(14) 30/70", "오실레이터", lambda df: sig_rsi(df, 14, 30, 70)),
        ("CCI(14) ±100", "오실레이터", lambda df: sig_cci(df, 14)),
        ("Parabolic SAR 전환", "추세추종", lambda df: sig_psar(df)),
        ("Envelope(20,6%) 회귀", "오실레이터", lambda df: sig_envelope(df, 20, 6)),
        ("Pivot Points 돌파", "추세추종", lambda df: sig_pivot(df)),
        ("Price Channel(20) 돌파", "추세추종", lambda df: sig_donchian(df, 20)),
        ("이동평균선(20) 돌파", "추세추종", lambda df: sig_ma_price_cross(df, 20)),
        ("볼린저밴드(20,2) 회귀", "오실레이터", lambda df: sig_bb_reversion(df, 20, 2)),
        ("일목균형표 전환선/기준선 크로스", "추세추종", lambda df: sig_ichimoku_tk(df)),
        ("매물대(POC) 돌파", "거래량", lambda df: sig_volume_profile(df, 60, 20)),
        ("AD Line vs MA(20)", "거래량", lambda df: sig_ad_line(df, 20)),
        ("ATR(14) 변동성 돌파", "변동성", lambda df: sig_atr_breakout(df, 14, 1.0)),
        ("CMF(20) 0선 크로스", "거래량", lambda df: sig_cmf(df, 20)),
        ("MFI(14) 20/80", "오실레이터", lambda df: sig_mfi(df, 14, 20, 80)),
        ("OBV 신고점 + MA20 확인", "거래량", lambda df: sig_obv_trend(df, 20)),
        ("투자심리도(12) 25/75", "오실레이터", lambda df: sig_psychological(df, 12, 25, 75)),
        ("SONAR(9,13) 0선 크로스", "모멘텀", lambda df: sig_sonar(df, 9, 13)),
        ("Chaikin Volatility 확장/수축", "변동성", lambda df: sig_chaikin_vol(df, 10, 10)),
        ("Chaikin Oscillator 0선 크로스", "거래량", lambda df: sig_chaikin_osc(df)),
        ("TRIX(15) 시그널크로스", "추세추종", lambda df: sig_trix(df, 15)),
        ("Williams %R(14) -80/-20", "오실레이터", lambda df: sig_williams(df, 14)),
        ("DMI(14) +DI/-DI 크로스", "추세추종", lambda df: sig_dmi_cross(df, 14)),
        ("모멘텀(10) 0선 크로스", "모멘텀", lambda df: sig_momentum(df, 10)),
        ("이격도(20) 95/105", "오실레이터", lambda df: sig_disparity(df, 20, 95, 105)),
        ("Volume Ratio(20) 70/150", "거래량", lambda df: sig_volume_ratio(df, 20, 70, 150)),
        ("ROC(10) 0선 크로스", "모멘텀", lambda df: sig_roc(df, 10)),
        ("ADX(14) 추세시작(25)", "추세추종", lambda df: sig_adx_trend(df, 14, 25)),
        ("ADXR(14) 추세시작(20)", "추세추종", lambda df: sig_adxr(df, 14, 14, 20)),
        ("Aroon(25) Up/Down 크로스", "추세추종", lambda df: sig_aroon(df, 25)),
        ("Aroon Oscillator(25) 0선 크로스", "추세추종", lambda df: sig_aroon_osc(df, 25)),
        ("Elder Ray Bull Power(13) 0선 크로스", "모멘텀", lambda df: sig_elder_ray_bull(df, 13)),
        ("Elder Ray Bear Power(13) 0선 크로스", "모멘텀", lambda df: sig_elder_ray_bear(df, 13)),
        ("Stochastic RSI(14,14) 20/80", "오실레이터", lambda df: sig_stoch_rsi(df, 14, 14, 20, 80)),
        ("Mass Index 버지 리버설", "변동성", lambda df: sig_mass_index(df, 9, 25)),
        ("PVI(20) vs MA", "거래량", lambda df: sig_pvi(df, 20)),
        ("NVI(20) vs MA", "거래량", lambda df: sig_nvi(df, 20)),
        ("EOM(14) 0선 크로스", "거래량", lambda df: sig_eom(df, 14)),
        ("Ultimate Oscillator 30/70", "오실레이터", lambda df: sig_uo(df, 30, 70)),
        ("PPO(12,26,9) 시그널크로스", "추세추종", lambda df: sig_ppo(df)),
        ("PVO(12,26,9) 시그널크로스", "거래량", lambda df: sig_pvo(df)),
    ]
    return strategies


# ---------- backtest ----------
def _forward_signal_stats(df, sig, valid_from, signal_value, want_direction, horizon=10):
    """
    For every occurrence of `signal_value` (1=buy signal, -1=sell signal), look `horizon`
    bars ahead and check whether price moved in `want_direction` (1=up, -1=down).
    Returns (median_forward_return_pct, accuracy_pct, n) using only signals that have a
    full horizon of future data available (so very recent signals are excluded from
    this historical accuracy check - there's no future to measure yet).

    Uses the MEDIAN (not mean) forward return: these are highly volatile growth/momentum
    tickers, so a handful of huge outlier moves can drag a mean return positive even when
    most signals pointed the other way (e.g. a "매도" signal with >50% down-accuracy but a
    positive average return because of one giant rally). The median's sign always agrees
    with the majority-direction accuracy% above, which keeps the two numbers consistent.
    """
    close = df.Close
    idxs = [i for i in range(valid_from, len(df)) if sig.iloc[i] == signal_value]
    rets, hits = [], 0
    for i in idxs:
        if i + horizon >= len(df):
            continue
        p0, p1 = close.iloc[i], close.iloc[i + horizon]
        ret = (p1 - p0) / p0 * 100
        rets.append(ret)
        if (want_direction == 1 and ret > 0) or (want_direction == -1 and ret < 0):
            hits += 1
    n = len(rets)
    if n > 0:
        srets = sorted(rets)
        mid = n // 2
        median_ret = srets[mid] if n % 2 == 1 else (srets[mid - 1] + srets[mid]) / 2
        median_ret = round(median_ret, 2)
    else:
        median_ret = None
    acc = round(hits / n * 100, 1) if n > 0 else None
    return median_ret, acc, n


def _signal_track_record(df, sig, valid_from, signal_value, want_direction, horizon=10, window=10, max_points=30):
    """Rolling reliability trend for one directional signal type (matches `opinion`'s
    direction), as opposed to `_forward_signal_stats`'s single aggregate accuracy% number.

    Walks every historical occurrence of `signal_value` that has a known outcome (a full
    `horizon` bars of future data available), in chronological order, and at each one computes
    the hit-rate over the trailing `window` occurrences up to and including that one - i.e.
    "as of this signal, how did the strategy's last `window` signals of this type do". This
    lets the report show whether a strategy's real-world reliability has been improving or
    decaying recently, instead of only a single point-in-time aggregate that can hide a fading
    edge. Trimmed to the most recent `max_points` occurrences to keep the chart readable."""
    close = df.Close
    idxs = [i for i in range(valid_from, len(df)) if sig.iloc[i] == signal_value]
    hits, dates = [], []
    for i in idxs:
        if i + horizon >= len(df):
            continue
        p0, p1 = close.iloc[i], close.iloc[i + horizon]
        ret = (p1 - p0) / p0 * 100
        hit = 1 if ((want_direction == 1 and ret > 0) or (want_direction == -1 and ret < 0)) else 0
        hits.append(hit)
        dates.append(str(df.index[i].date()))
    n = len(hits)
    if n == 0:
        return []
    points = []
    for k in range(n):
        lo = max(0, k - window + 1)
        window_hits = hits[lo:k + 1]
        acc = round(sum(window_hits) / len(window_hits) * 100, 1)
        points.append({"date": dates[k], "accuracy_pct": acc, "n": len(window_hits)})
    return points[-max_points:]


def _chart_data(df, signal_fn, valid_from=0, lookback_days=252):
    """Last `lookback_days` (~1 trading year) of close prices plus this strategy's ACTUAL
    trade entries/exits within that window, for drawing a small price chart with arrows.

    Important: this walks the same single-position state machine as `_simulate_trades`
    (buy only possible while flat, sell only possible while holding) rather than just
    marking every bar where the raw indicator condition happens to be true. Some
    indicators stay "oversold"/"overbought" for several days in a row, which would
    otherwise draw a run of several sell arrows back-to-back even though only the first
    one was an actual trade - misleadingly implying multiple sells with no buy between
    them. Position state is tracked from `valid_from` (the same point run_backtest's own
    "last_signal_date" walk starts at - NOT from bar 0) so the state entering the display
    window is correct, but only markers inside the window are kept.

    `valid_from` matters even though it defaults to 0 for backwards compatibility: some
    indicators technically produce non-NaN signal values well before `min_bars`
    (their own warmup is shorter than the report's global min_bars), so a full-history
    walk starting at bar 0 can pick up "trades" that run_backtest's valid_from-onward walk
    never counted - silently drifting the chart's last arrow away from the date shown in
    the "이 신호는 N거래일 전 발생" text. Starting both walks at the same index removes that
    possibility structurally instead of relying on the two happening to agree."""
    sig = signal_fn(df).fillna(0)
    close = df.Close
    n = len(df)
    start = max(0, n - lookback_days)

    dates = [str(d.date()) for d in df.index[start:]]
    prices = [round(float(p), 2) for p in close.iloc[start:]]

    position = 0
    markers = []
    for i in range(valid_from, n):
        s = sig.iloc[i]
        if position == 0 and s == 1:
            position = 1
            if i >= start:
                markers.append({"date": str(df.index[i].date()), "price": round(float(close.iloc[i]), 2), "type": "buy"})
        elif position == 1 and s == -1:
            position = 0
            if i >= start:
                markers.append({"date": str(df.index[i].date()), "price": round(float(close.iloc[i]), 2), "type": "sell"})
    return {"dates": dates, "prices": prices, "markers": markers}


def _position_series(df, signal_fn, valid_from):
    """Full-history position array (1 = holding/매수보유, 0 = flat/관망) for one strategy,
    using the exact same single-position state machine as _simulate_trades/_chart_data
    (buy only while flat, sell only while holding). Bars before `valid_from` are left 0."""
    sig = signal_fn(df).fillna(0)
    n = len(df)
    pos = np.zeros(n, dtype=int)
    position = 0
    for i in range(valid_from, n):
        s = sig.iloc[i]
        if position == 0 and s == 1:
            position = 1
        elif position == 1 and s == -1:
            position = 0
        pos[i] = position
    return pos


def _composite_chart_data(df, active_results, top_n_results, strategy_fn_by_name, valid_from, lookback_days=252, band=30.0):
    """Approximates the 종합의견(overall verdict) card's history for drawing chart arrows,
    instead of a single reference strategy's own trade signals - those two used to disagree
    (한 전략의 개별 매매 시점 vs 4개 요소를 합친 종합점수) which was confusing on the same card.

    Combines the 3 of the 4 종합의견 blocks (see combine_opinion.py) that CAN be
    reconstructed day-by-day from price history alone:
      - 지표분석: breadth of "active" (eligibility-passing) strategies currently holding
      - 추세상태: MA(20/50)/ADX-DMI/Parabolic SAR majority vote (already full-series here)
      - 백테스트예측: top-5(top_n) ranked strategies' vote
    The 4th block, 옵션포지셔닝, is a real-time snapshot with no historical time series, so
    it's simply left out of this walk (weights renormalize over whichever of the 3 are
    available, same convention as combine_opinion.py) - the caller is expected to correct
    the LAST bar afterward against the real final_opinion (which may include options) so
    today's marker always matches the badge exactly; see combine_opinion.apply_final_opinion_to_chart.
    """
    close = df.Close
    n = len(df)

    components = []

    active_fns = [strategy_fn_by_name[r["name"]] for r in active_results if strategy_fn_by_name.get(r["name"]) is not None]
    if active_fns:
        stacked = np.vstack([_position_series(df, fn, valid_from) for fn in active_fns])
        buy_pct = stacked.mean(axis=0) * 100
        components.append(buy_pct * 2 - 100)  # buy_pct - sell_pct, sell_pct = 100 - buy_pct

    top_fns = [strategy_fn_by_name[r["name"]] for r in top_n_results if strategy_fn_by_name.get(r["name"]) is not None]
    if top_fns:
        stacked = np.vstack([_position_series(df, fn, valid_from) for fn in top_fns])
        vote_buy_pct = stacked.mean(axis=0)
        components.append((vote_buy_pct - 0.5) * 200)

    ma_f = sma(close, 20)
    ma_s = sma(close, 50)
    adx, pdi, mdi = adx_di(df.High, df.Low, df.Close, 14)
    _, sar_trend = parabolic_sar(df.High, df.Low, df.Close)
    ma_up = (ma_f > ma_s).astype(int).values
    adx_up = (pdi > mdi).astype(int).values
    sar_up = (sar_trend == 1).astype(int).values
    up_votes = ma_up + adx_up + sar_up
    components.append((up_votes / 3 - 0.5) * 200)

    if not components:
        return None
    combined = np.mean(np.vstack(components), axis=0)
    labels = np.where(combined >= band, "매수", np.where(combined <= -band, "매도", "관망"))

    start = max(0, n - lookback_days)
    dates = [str(d.date()) for d in df.index[start:]]
    prices = [round(float(p), 2) for p in close.iloc[start:]]

    markers = []
    state = None
    for i in range(valid_from, n):
        lab = labels[i]
        if lab != "관망" and lab != state:
            if i >= start:
                markers.append({
                    "date": str(df.index[i].date()),
                    "price": round(float(close.iloc[i]), 2),
                    "type": "buy" if lab == "매수" else "sell",
                })
            state = lab

    # How long TODAY's label (매수/매도/관망 included) has been in effect, walking backward
    # from the last bar while it stays unchanged - this is what the index/검색 page shows
    # next to the 종합의견 badge ("N거래일 전"), so that number is about the SAME thing the
    # badge is (unlike top_strategy.last_signal_bars_ago, which is one reference strategy's
    # own signal recency and can legitimately be a different, older/newer date - see
    # combine_opinion.compute_composite_signal_recency, which additionally corrects this
    # against the REAL final_opinion since 옵션포지셔닝 isn't part of `labels` here).
    approx_current_label = str(labels[n - 1])
    approx_signal_start_idx = n - 1
    j = n - 1
    while j - 1 >= valid_from and labels[j - 1] == approx_current_label:
        j -= 1
    approx_signal_start_idx = j

    return {
        "dates": dates,
        "prices": prices,
        "markers": markers,
        "approx_current_label": approx_current_label,
        "approx_signal_date": str(df.index[approx_signal_start_idx].date()),
        "approx_signal_bars_ago": (n - 1) - approx_signal_start_idx,
    }


def _median(xs):
    if not xs:
        return None
    s = sorted(xs)
    m = len(s) // 2
    return s[m] if len(s) % 2 == 1 else (s[m - 1] + s[m]) / 2


def _percentile(xs, p):
    if not xs:
        return None
    s = sorted(xs)
    k = (len(s) - 1) * p
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def _sell_aftermath_stats(df, sig, valid_from):
    """
    For every completed 'sold and later bought back' cycle (a real position that was
    closed on a sell signal, followed by a later buy signal in the data - so nothing
    censored/still-open), measure two things about the gap in between:
      - wait_days: how many trading days passed until the next buy signal
      - drawdown_pct: how much further price fell (lowest close reached) vs. the sell
        price, before that next buy signal fired
    These become the basis for 1차/2차 지지선 (typical vs. deeper pullback) and an
    average "관망 기간" for tickers currently in a 매도/관망 state - built the same way
    as the buy-side trade plan (from this strategy's own realized history on this
    ticker), not a generic technical support formula.
    """
    close = df.Close
    position = 0
    exits = []
    for i in range(valid_from, len(df)):
        s = sig.iloc[i]
        if position == 0 and s == 1:
            position = 1
        elif position == 1 and s == -1:
            exits.append((i, close.iloc[i]))
            position = 0

    waits, drawdowns = [], []
    for exit_idx, exit_price in exits:
        next_buy_idx = None
        for j in range(exit_idx + 1, len(df)):
            if sig.iloc[j] == 1:
                next_buy_idx = j
                break
        if next_buy_idx is None:
            continue  # still waiting as of the latest bar - censored, excluded from stats
        wait_days = next_buy_idx - exit_idx
        window_low = close.iloc[exit_idx:next_buy_idx + 1].min()
        drawdown_pct = (window_low - exit_price) / exit_price * 100
        waits.append(wait_days)
        drawdowns.append(drawdown_pct)

    n = len(waits)
    return {
        "n": n,
        "wait_days_median": round(_median(waits), 1) if n > 0 else None,
        "support1_pct": round(_median(drawdowns), 2) if n > 0 else None,
        "support2_pct": round(_percentile(drawdowns, 0.25), 2) if n > 0 else None,
    }


def _simulate_trades(close, sig, start_idx, end_idx, cost_pct=0.0):
    """Core long-only, single-position simulation over close[start_idx:end_idx].
    `cost_pct` is a round-trip transaction cost (commission + slippage/spread) in percent,
    subtracted from every CLOSED trade's return (e.g. cost_pct=0.2 assumes ~0.1% in + 0.1%
    out). An open/unrealized position at the end of the window has not paid the exit leg yet,
    so its unrealized return is left cost-free - the report notes this explicitly.
    Returns (closed_trade_returns, open_trade_return_or_None, ending_position, entry_price)."""
    position = 0
    entry_price = None
    entry_i = None
    trades = []
    durations = []  # trading-days held, parallel array to `trades`
    for i in range(start_idx, end_idx):
        s = sig.iloc[i]
        price = close.iloc[i]
        if position == 0 and s == 1:
            position = 1
            entry_price = price
            entry_i = i
        elif position == 1 and s == -1:
            ret = (price - entry_price) / entry_price * 100 - cost_pct
            trades.append(ret)
            durations.append(i - entry_i)
            position = 0
            entry_price = None
            entry_i = None
    open_trade_return = None
    if position == 1 and entry_price is not None and end_idx > start_idx:
        open_trade_return = (close.iloc[end_idx - 1] - entry_price) / entry_price * 100
    return trades, durations, open_trade_return, position, entry_price


def _compound_return(trades, open_ret=None):
    total = 1.0
    for r in trades:
        total *= (1 + r / 100)
    total = (total - 1) * 100
    if open_ret is not None:
        total = ((total / 100 + 1) * (1 + open_ret / 100) - 1) * 100
    return round(total, 2)


DEFAULT_COST_PCT = 0.2  # assumed round-trip commission+slippage, in percent of trade value
RECENCY_WINDOW_BARS = 252  # ~1 trading year, used to check a strategy is still actively firing
UNDERWATER_THRESHOLD_PCT = -10  # held-position unrealized loss beyond which a strategy is excluded from ranking
MISSED_RALLY_THRESHOLD_PCT = 10  # missed rally-since-sell beyond which a strategy is excluded from ranking


def run_backtest(df, signal_fn, min_bars=130, horizon=10, cost_pct=DEFAULT_COST_PCT):
    """Returns dict with total_return_pct, win_rate, num_trades, current_state, last_signal_bars_ago,
    plus horizon-based forward-looking accuracy for buy signals (price up in `horizon` bars) and
    sell signals (price down in `horizon` bars) - used to keep the "opinion" and its confidence
    number pointing the same direction. `cost_pct` (round-trip %) is subtracted from every closed
    trade to approximate commissions/slippage - set to 0 for a cost-free/theoretical comparison."""
    sig = signal_fn(df)
    sig = sig.fillna(0)
    close = df.Close

    valid_from = min_bars
    trades, durations, open_trade_return, position, entry_price = _simulate_trades(close, sig, valid_from, len(df), cost_pct)

    closed_returns = trades
    num_trades = len(closed_returns)
    wins = sum(1 for r in closed_returns if r > 0)
    win_rate = (wins / num_trades * 100) if num_trades > 0 else None
    avg_trade_return = (sum(closed_returns) / num_trades) if num_trades > 0 else None

    winning_trades = [r for r in closed_returns if r > 0]
    losing_trades = [r for r in closed_returns if r <= 0]
    win_median_pct = _median(winning_trades)
    loss_median_pct = _median(losing_trades)
    # How many trading days a typical WINNING/LOSING trade was actually held for, entry to
    # exit signal - this is what makes "2차 목표가" comparable to the 10-day short-term
    # expected return instead of silently mixing two different time horizons.
    win_durations = [durations[i] for i, r in enumerate(closed_returns) if r > 0]
    loss_durations = [durations[i] for i, r in enumerate(closed_returns) if r <= 0]
    win_median_hold_days = _median(win_durations)
    loss_median_hold_days = _median(loss_durations)
    sell_aftermath = _sell_aftermath_stats(df, sig, valid_from)

    buy_fwd_avg_ret, buy_fwd_acc, buy_fwd_n = _forward_signal_stats(df, sig, valid_from, 1, 1, horizon)
    sell_fwd_avg_ret, sell_fwd_acc, sell_fwd_n = _forward_signal_stats(df, sig, valid_from, -1, -1, horizon)

    # compounded total return across closed trades (sequential, non-overlapping); cost
    # already deducted per-trade inside _simulate_trades
    total_return = _compound_return(closed_returns, open_trade_return)

    # current signal: date of the last ACTUAL position transition (real trade entry/exit),
    # NOT just the last day the raw indicator condition happened to be true. Some indicators
    # can re-trigger their "buy" condition again while already holding (a harmless no-op for
    # the trade simulation), and counting that as "the signal" made this date drift ahead of
    # the actual trade shown on the price chart - i.e. two different parts of the report
    # disagreeing about when the current position was opened.
    # Also count how many of these position-transition events fall within the last
    # RECENCY_WINDOW_BARS (~1 trading year) - a strategy can clear the >=10-trades-over-3-years
    # bar entirely on trading it did 2-3 years ago and then go completely silent while price
    # moves a lot (a chart with its last arrow near the start of the visible 1yr window and a
    # big, un-reacted-to move afterward) - the "current position" claim from such a strategy
    # is stale, not a live read. recent_num_trades lets analyze_ticker additionally require
    # the strategy to have actually fired recently, not just historically.
    recent_start_idx = max(valid_from, len(df) - RECENCY_WINDOW_BARS)
    _pos = 0
    last_sig_val = 0
    last_sig_idx = None
    recent_num_trades = 0
    for i in range(valid_from, len(df)):
        s = sig.iloc[i]
        if _pos == 0 and s == 1:
            _pos = 1
            last_sig_val = 1
            last_sig_idx = df.index[i]
            if i >= recent_start_idx:
                recent_num_trades += 1
        elif _pos == 1 and s == -1:
            _pos = 0
            last_sig_val = -1
            last_sig_idx = df.index[i]
            if i >= recent_start_idx:
                recent_num_trades += 1
    if last_sig_idx is not None:
        bars_ago = len(df) - 1 - df.index.get_loc(last_sig_idx)
        last_sig_date = str(last_sig_idx.date())
    else:
        bars_ago = None
        last_sig_date = None

    current_state = "매수보유" if position == 1 else "관망"

    # Mirror image of open_trade_return_pct for the 관망(watching) side: if the strategy
    # is currently flat after a sell, how much has price moved SINCE that sell with no
    # buy-back signal yet. A strategy that sold and then missed a big rally is just as
    # live a red flag as one that's holding through a big drawdown - "매도" doesn't mean
    # "this was later validated by price going down", it just means the strategy hasn't
    # flipped back to buy.
    open_watch_return_pct = None
    if position == 0 and last_sig_val == -1 and last_sig_idx is not None:
        sell_price = float(close.loc[last_sig_idx])
        if sell_price:
            open_watch_return_pct = round((float(close.iloc[-1]) - sell_price) / sell_price * 100, 2)

    return {
        "total_return_pct": round(total_return, 2),
        "win_rate": round(win_rate, 1) if win_rate is not None else None,
        "num_trades": num_trades,
        "avg_trade_return_pct": round(avg_trade_return, 2) if avg_trade_return is not None else None,
        "current_state": current_state,
        "last_signal": "매수" if last_sig_val == 1 else ("매도" if last_sig_val == -1 else "없음"),
        "last_signal_bars_ago": bars_ago,
        "last_signal_date": last_sig_date,
        "recent_num_trades": recent_num_trades,
        "open_trade_return_pct": round(open_trade_return, 2) if open_trade_return is not None else None,
        "open_watch_return_pct": open_watch_return_pct,
        "horizon_days": horizon,
        "buy_forward_avg_return_pct": buy_fwd_avg_ret,
        "buy_forward_accuracy_pct": buy_fwd_acc,
        "buy_forward_n": buy_fwd_n,
        "sell_forward_avg_return_pct": sell_fwd_avg_ret,
        "sell_forward_accuracy_pct": sell_fwd_acc,
        "sell_forward_n": sell_fwd_n,
        "win_median_pct": round(win_median_pct, 2) if win_median_pct is not None else None,
        "loss_median_pct": round(loss_median_pct, 2) if loss_median_pct is not None else None,
        "win_median_hold_days": win_median_hold_days,
        "loss_median_hold_days": loss_median_hold_days,
        "num_wins": len(winning_trades),
        "num_losses": len(losing_trades),
        "sell_aftermath_n": sell_aftermath["n"],
        "sell_aftermath_wait_days_median": sell_aftermath["wait_days_median"],
        "sell_aftermath_support1_pct": sell_aftermath["support1_pct"],
        "sell_aftermath_support2_pct": sell_aftermath["support2_pct"],
        "cost_pct_assumed": cost_pct,
    }


def run_backtest_holdout(df, signal_fn, min_bars=130, train_frac=0.75, cost_pct=DEFAULT_COST_PCT):
    """
    Train/test (holdout) split to sanity-check overfitting: rank strategies using only
    the TRAIN segment, then check whether the winner's edge held up on the TEST segment it
    was never selected on. This is a single holdout split (not full rolling walk-forward
    with re-selection at every step), which is a lighter-weight but still meaningful
    overfitting check - it directly answers "did this strategy's edge exist before the
    most recent stretch of data, or did we just pick whatever happened to work most
    recently?"
    Both segments reset to a flat position at their own start (each is evaluated as if
    starting fresh), so segment returns are independent and comparable.
    """
    sig = signal_fn(df).fillna(0)
    close = df.Close
    valid_from = min_bars
    n_usable = len(df) - valid_from
    train_end_idx = valid_from + int(n_usable * train_frac)
    train_end_idx = max(valid_from + 1, min(train_end_idx, len(df) - 1))

    train_trades, _, _, _, _ = _simulate_trades(close, sig, valid_from, train_end_idx, cost_pct)
    test_trades, _, test_open_ret, _, _ = _simulate_trades(close, sig, train_end_idx, len(df), cost_pct)

    def _stats(trades):
        n = len(trades)
        wins = sum(1 for r in trades if r > 0)
        wr = round(wins / n * 100, 1) if n > 0 else None
        return n, wr

    train_n, train_wr = _stats(train_trades)
    test_n, test_wr = _stats(test_trades)

    return {
        "train_return_pct": _compound_return(train_trades),
        "train_win_rate": train_wr,
        "train_num_trades": train_n,
        "test_return_pct": _compound_return(test_trades, test_open_ret),
        "test_win_rate": test_wr,
        "test_num_trades": test_n,
        "train_end_date": str(df.index[train_end_idx].date()),
        "train_frac": train_frac,
    }


def _direction_matched_stats(r):
    """Given one strategy's backtest result dict, return (direction, accuracy_pct,
    accuracy_n, expected_return_pct) picking whichever of the buy-/sell-forward stats
    matches the strategy's OWN current_state - so a single strategy's own numbers never
    contradict its own direction (e.g. a strategy currently in 매도 never gets a buy-signal
    accuracy% attached to it)."""
    direction = "매수" if r["current_state"] == "매수보유" else "매도"
    if direction == "매수":
        acc = r.get("buy_forward_accuracy_pct")
        acc_n = r.get("buy_forward_n") or 0
        exp_ret = r.get("buy_forward_avg_return_pct")
        if acc is None:  # not enough future bars to score recent signals yet
            acc = r.get("win_rate")
            exp_ret = r.get("avg_trade_return_pct")
    else:
        acc = r.get("sell_forward_accuracy_pct")
        acc_n = r.get("sell_forward_n") or 0
        exp_ret = r.get("sell_forward_avg_return_pct")
    return direction, acc, acc_n, exp_ret


def analyze_ticker(df, min_bars=130, min_trades_for_ranking=10, min_recent_trades=2, cost_pct=DEFAULT_COST_PCT, train_frac=0.75, top_n=5):
    strategies = build_strategies()
    results = []
    for name, category, fn in strategies:
        try:
            r = run_backtest(df, fn, min_bars=min_bars, cost_pct=cost_pct)
            r["name"] = name
            r["category"] = category
            r.update(run_backtest_holdout(df, fn, min_bars=min_bars, train_frac=train_frac, cost_pct=cost_pct))
            results.append(r)
        except Exception as e:
            results.append({"name": name, "category": category, "error": str(e)})

    valid = [r for r in results if "error" not in r]
    # Rank by TRAIN-period return only (not the full 3-year return) - picking "whichever
    # of 45 did best over the ENTIRE window we're also evaluating it on" is textbook
    # overfitting. Using train_return_pct means the winner is chosen without ever looking
    # at the test segment, so test_return_pct below is a genuine out-of-sample check.
    #
    # Eligibility filter uses `num_trades` (trades over the FULL ~3-year history, train+test
    # combined), not just train_num_trades. A strategy can clear the train-segment trade
    # count but have gone completely silent since (e.g. one buy near a local top in the
    # test/holdout window and nothing after, even through a large subsequent drawdown) - its
    # stale chart arrows and "current state" would then be shown as if still live. Requiring
    # >=10 trades over the whole history (raised from an earlier 5 - even 5-6 trades in 3
    # years turned out to still be too thin a sample to trust) keeps only strategies that
    # actually fire with enough regularity to be worth reading as a current signal.
    # A strategy can clear the >=10-trades-over-3-years bar purely on trading it did years
    # ago and then go quiet - a chart whose last arrow sits near the start of the visible
    # 1-year window while price keeps moving a lot afterward, with the "current position"
    # never reconfirmed by anything recent. So on top of the full-history trade count, also
    # require at least `min_recent_trades` trades within the last ~1 year (RECENCY_WINDOW_BARS)
    # for a strategy to be eligible for ranking/selection - this keeps the chosen strategies
    # actually reactive to recent price action, not just historically active.
    #
    # On top of both trade-count bars, a strategy is excluded if its CURRENTLY CLAIMED
    # position already looks wrong: holding a long position that's now down more than
    # UNDERWATER_THRESHOLD_PCT since entry, or sitting flat after a sell that's since missed
    # more than MISSED_RALLY_THRESHOLD_PCT of upside. This is checked and filtered out HERE,
    # before selection, rather than picking the strategy and merely warning about it
    # afterward - a stale/wrong-looking current position shouldn't be the report's answer for
    # a ticker when a strategy without that problem is available.
    def _is_stale_open_position(r):
        if r["current_state"] == "매수보유" and r.get("open_trade_return_pct") is not None:
            return r["open_trade_return_pct"] < UNDERWATER_THRESHOLD_PCT
        if r["current_state"] == "관망" and r.get("open_watch_return_pct") is not None:
            return r["open_watch_return_pct"] > MISSED_RALLY_THRESHOLD_PCT
        return False

    # 오실레이터(mean-reversion) 계열 지표는 추세를 끝까지 타지 않고 과매수/과매도 구간에서
    # 미리 진입/청산한다 - 개별 신호만 보면 "왜 반등 직전에 팔았지", "왜 신호 이후에도 계속
    # 오르지" 처럼 차트상 direction이 어색해 보여 대표전략/상위 5개로 뽑히면 신뢰를 잃는다.
    # 승률/수익률 자체는 나쁘지 않을 수 있어도, 대표 전략 선정 단계에서는 배제한다.
    EXCLUDED_CATEGORIES = {"오실레이터"}

    def _is_oscillator(r):
        return r.get("category") in EXCLUDED_CATEGORIES

    fallback_reason = None
    eligible = [
        r for r in valid
        if not _is_oscillator(r)
        and r["num_trades"] >= min_trades_for_ranking
        and r.get("recent_num_trades", 0) >= min_recent_trades
        and not _is_stale_open_position(r)
    ]
    if not eligible:
        # relax recency first (still enough total trades, still non-oscillator, and not
        # currently stale, just not recently active) - avoiding a stale/wrong-looking current
        # position matters more than recency, so this is dropped before the staleness
        # exclusion is.
        eligible = [
            r for r in valid
            if not _is_oscillator(r)
            and r["num_trades"] >= min_trades_for_ranking
            and not _is_stale_open_position(r)
        ]
        if eligible:
            fallback_reason = "no_recent_activity"
    if not eligible:
        # nothing clears the history bar without being stale (still excluding oscillators) -
        # allow stale positions back in rather than drop the history requirement, and flag it
        # clearly for the report.
        eligible = [r for r in valid if not _is_oscillator(r) and r["num_trades"] >= min_trades_for_ranking]
        if eligible:
            fallback_reason = "stale_open_position_unavoidable"
    if not eligible:
        # only oscillator-category strategies clear the history bar for this ticker - allow
        # them back in as an absolute last resort rather than fall through to "insufficient
        # history" (which would be misleading; there IS enough history, just not from a
        # non-oscillator strategy).
        eligible = [r for r in valid if r["num_trades"] >= min_trades_for_ranking]
        if eligible:
            fallback_reason = "oscillator_unavoidable"
    if not eligible:
        # last resort: nothing cleared even the full-history bar (very short-history ticker)
        eligible = valid
        fallback_reason = "insufficient_history"
    ranked = sorted(eligible, key=lambda r: r["train_return_pct"], reverse=True)
    # Fallback when NOT EVEN ONE strategy clears the bar (can happen for short-history
    # tickers): pick the best by train_return_pct anyway, but flag it so the report can warn
    # readers this pick has a thin trade history rather than silently presenting it as if it
    # cleared the same bar as everyone else.
    thin_fallback = fallback_reason is not None
    top = ranked[0] if ranked else sorted(valid, key=lambda r: r["train_return_pct"], reverse=True)[0]
    top_n_list = ranked[:top_n] if ranked else [top]

    # binary split (매수 vs 매도) so the two ratios always sum to 100%,
    # matching a "N개 전략 중 매수/매도 우세" style summary.
    #
    # Only counts strategies that clear the same eligibility bar as the ranking above
    # (num_trades >= min_trades_for_ranking). Previously this counted ALL 45 strategies
    # including ones that had barely traded (sometimes a single signal years ago, still
    # showing as "holding" today) - that stale noise could push this breadth number to the
    # opposite side of the merit-weighted opinion below, with both shown on the same card as
    # if they were two independent conclusions. Since a user can't tell "이 카드에 있는 신호는
    # 다 백테스트 기반인데 왜 서로 반대야?" apart from a genuine methodology difference, both
    # numbers now come from the same actively-trading strategy pool - they can still disagree
    # (that's real, informative disagreement among active strategies), but no longer diverge
    # just because one metric included strategies with almost no trading history.
    active = [
        r for r in valid
        if not _is_oscillator(r)
        and r["num_trades"] >= min_trades_for_ranking
        and r.get("recent_num_trades", 0) >= min_recent_trades
    ]
    if not active:
        active = [r for r in valid if not _is_oscillator(r) and r["num_trades"] >= min_trades_for_ranking]
    if not active:
        active = [r for r in valid if r["num_trades"] >= min_trades_for_ranking]
    buy_count = sum(1 for r in active if r["current_state"] == "매수보유")
    total = len(active)
    sell_count = total - buy_count
    buy_ratio_pct = round(buy_count / total * 100, 2) if total else 0
    sell_ratio_pct = round(100 - buy_ratio_pct, 2) if total else 0

    # "prediction card" opinion: majority vote across the top-N (by train-period return)
    # strategies, NOT just the single #1 strategy. A lone #1 pick can flip direction on any
    # given day and swing wildly out of step with the all-45 ratio above, which is confusing
    # ("매수신호 82%인데 왜 백테스트 예측은 매도야?"). Voting across the top N historically-best
    # strategies is much less noisy - and is literally what "상위 N개 전략 백테스트" means.
    info = []
    for r in top_n_list:
        direction, acc, acc_n, exp_ret = _direction_matched_stats(r)
        info.append({"r": r, "direction": direction, "acc": acc, "acc_n": acc_n, "exp_ret": exp_ret})

    vote_buy = sum(1 for x in info if x["direction"] == "매수")
    vote_total = len(info)
    vote_sell = vote_total - vote_buy
    if vote_buy > vote_sell:
        opinion = "매수"
    elif vote_sell > vote_buy:
        opinion = "매도"
    else:
        opinion = info[0]["direction"]  # tie-break: defer to the single best-ranked strategy

    # Only the subset of the top-N that actually agrees with the vote outcome is used to
    # compute the displayed accuracy/expected-return/trade-plan numbers - averaging in
    # strategies pointing the opposite way would reintroduce the same contradiction we're
    # trying to fix. `agreeing` is never empty by construction (opinion is defined as
    # whichever direction has >= as many votes as the other).
    agreeing = [x for x in info if x["direction"] == opinion]
    ref_r = agreeing[0]["r"]  # highest-ranked strategy consistent with the final opinion
    horizon_days = top.get("horizon_days", 10)

    def _agg_median(key):
        vals = [x[key] for x in agreeing if x[key] is not None]
        return round(_median(vals), 2) if vals else None

    signal_accuracy_pct = _agg_median("acc")
    signal_accuracy_n = sum(x["acc_n"] for x in agreeing)
    signal_expected_return_pct = _agg_median("exp_ret")

    agree_rs = [x["r"] for x in agreeing]

    def _agg_median_field(field):
        vals = [rr.get(field) for rr in agree_rs if rr.get(field) is not None]
        return round(_median(vals), 2) if vals else None

    def _agg_sum_field(field):
        return sum((rr.get(field) or 0) for rr in agree_rs)

    # trade plan (매수타점/손절가/1·2차 목표가) - ONLY meaningful when opinion is 매수.
    # Built from the MEDIAN of the agreeing top-N strategies' own historical closed trades
    # on this ticker (not just the single #1 strategy):
    #   손절가 = entry x (1 + median losing-trade return)               [full-trade history]
    #   1차 목표가 = entry x (1 + horizon-day forward expected return)   [near-term, 10-day]
    #   2차 목표가 = entry x (1 + median winning-trade return)           [full-trade history]
    # If there aren't at least 2 losing/winning trades (combined across agreeing strategies)
    # to take a median from, that field is left as None rather than guessing. And if the
    # near-term (10-day) expected return is <= 0 - which can happen even while opinion is
    # 매수, since "매수" just means a majority of top strategies currently hold a position,
    # not that the near-term odds are good - target1 is left out too.
    trade_plan = None
    _last_close = float(df.Close.iloc[-1])
    if opinion == "매수" and _last_close == _last_close:  # NaN check w/o extra import
        entry_price = _last_close
        loss_med = _agg_median_field("loss_median_pct")
        win_med = _agg_median_field("win_median_pct")
        num_losses_agg = _agg_sum_field("num_losses")
        num_wins_agg = _agg_sum_field("num_wins")
        win_hold_days_agg = _agg_median_field("win_median_hold_days")
        weak_short_term = signal_accuracy_pct is not None and signal_accuracy_pct <= 50
        target1_price = None
        if signal_expected_return_pct is not None and signal_expected_return_pct > 0 and not weak_short_term:
            target1_price = entry_price * (1 + signal_expected_return_pct / 100)
        stop_price = entry_price * (1 + loss_med / 100) if (loss_med is not None and num_losses_agg >= 2) else None
        target2_price = entry_price * (1 + win_med / 100) if (win_med is not None and num_wins_agg >= 2 and win_med > 0) else None
        risk_reward = None
        if stop_price is not None and target2_price is not None and entry_price != stop_price:
            risk = entry_price - stop_price
            reward = target2_price - entry_price
            if risk > 0:
                risk_reward = round(reward / risk, 2)
        trade_plan = {
            "entry_price": round(entry_price, 2),
            "stop_price": round(stop_price, 2) if stop_price is not None else None,
            "stop_pct": loss_med,
            "target1_price": round(target1_price, 2) if target1_price is not None else None,
            "target1_horizon_days": horizon_days,
            "target1_unavailable": target1_price is None,
            "target2_price": round(target2_price, 2) if target2_price is not None else None,
            "target2_pct": win_med,
            "target2_median_hold_days": win_hold_days_agg,
            "risk_reward": risk_reward,
            "num_losses_sample": num_losses_agg,
            "num_wins_sample": num_wins_agg,
            "weak_short_term": weak_short_term,
        }

    # watch plan (1차/2차 지지선 + 평균 관망기간) - the 매도-side counterpart to trade_plan,
    # aggregated the same way across the agreeing top-N strategies. Historical statistics,
    # not a timing forecast - we deliberately do NOT claim to predict exactly when a
    # reversal will happen.
    watch_plan = None
    if opinion == "매도" and _last_close == _last_close:  # NaN check w/o extra import
        ref_price = _last_close
        n_cycles = _agg_sum_field("sell_aftermath_n")
        s1 = _agg_median_field("sell_aftermath_support1_pct")
        s2 = _agg_median_field("sell_aftermath_support2_pct")
        wait_days = _agg_median_field("sell_aftermath_wait_days_median")
        watch_plan = {
            "ref_price": round(ref_price, 2),
            "support1_price": round(ref_price * (1 + s1 / 100), 2) if (s1 is not None and n_cycles >= 2) else None,
            "support1_pct": s1,
            "support2_price": round(ref_price * (1 + s2 / 100), 2) if (s2 is not None and n_cycles >= 2) else None,
            "support2_pct": s2,
            "wait_days_median": wait_days if n_cycles >= 2 else None,
            "n_cycles": n_cycles,
        }

    # chart data (최근 1년 가격 + 매수/매도 화살표) - built from the SAME reference strategy
    # (`ref_r`) whose name is shown as the signal-timing source above, so the arrows always
    # match the "이 신호는 N거래일 전 발생" line. Re-runs that one strategy's signal function
    # over the FULL history (indicators need the lookback) and then keeps only the last
    # `chart_lookback_days` bars for display.
    strategy_fn_by_name = {name: fn for name, category, fn in strategies}
    ref_fn = strategy_fn_by_name.get(ref_r.get("name"))

    # Chart arrows now approximate the 종합의견(overall verdict) history instead of this one
    # reference strategy's own trade signals - see _composite_chart_data's docstring. Falls
    # back to the old single-strategy chart if the composite can't be built for some reason
    # (e.g. no active strategies at all), so the chart never silently disappears.
    chart_data = _composite_chart_data(df, active, top_n_list, strategy_fn_by_name, min_bars)
    if chart_data is None:
        chart_data = _chart_data(df, ref_fn, valid_from=min_bars) if ref_fn is not None else None

    # signal reliability trend (see _signal_track_record docstring) - same reference
    # strategy and direction as the rest of the card, so the chart's last point lines up
    # with the "opinion 신호 적중률" gauge above it (won't match numerically since the
    # gauge is a median across the agreeing top-N strategies while this is the single
    # reference strategy's own trailing-window history, but both describe the same signal).
    signal_value = 1 if opinion == "매수" else -1
    signal_track_record = (
        _signal_track_record(df, ref_fn(df).fillna(0), min_bars, signal_value, signal_value, horizon=horizon_days)
        if ref_fn is not None else []
    )

    return {
        "all_results": results,
        "top_strategy": ref_r,
        "trend_status": compute_trend_status(df),
        "chart_data": chart_data,
        "signal_track_record": signal_track_record,
        "top_n_vote_buy": vote_buy,
        "top_n_vote_total": vote_total,
        "buy_hold_count": buy_count,
        "sell_count": sell_count,
        "total_strategies": total,
        "buy_ratio_pct": buy_ratio_pct,
        "sell_ratio_pct": sell_ratio_pct,
        "opinion": opinion,
        "horizon_days": horizon_days,
        "signal_accuracy_pct": signal_accuracy_pct,
        "signal_accuracy_n": signal_accuracy_n,
        "expected_return_pct": round(signal_expected_return_pct, 2) if signal_expected_return_pct is not None else None,
        "trade_plan": trade_plan,
        "watch_plan": watch_plan,
        "cost_pct_assumed": cost_pct,
        "train_frac": train_frac,
        "oos_holds_up": (ref_r.get("test_return_pct") is not None and ref_r.get("test_num_trades", 0) >= 1 and ref_r["test_return_pct"] > 0),
        "thin_fallback": thin_fallback,
        "fallback_reason": fallback_reason,
        "min_trades_for_ranking": min_trades_for_ranking,
        "min_recent_trades": min_recent_trades,
    }


# ---------- automated consistency checks ----------
# This exists because several past report bugs were exactly this shape: a number and its
# accompanying label pointing in different directions (e.g. "매도 의견인데 상승확률 100%").
# Run validate_all() after building the results dict and BEFORE shipping the report, so
# this class of bug is caught by code instead of by the user screenshotting the report back.
def validate_ticker_result(ticker, d):
    warnings = []
    eps = 0.05  # tolerance for float rounding

    buy_pct = d.get("buy_ratio_pct")
    sell_pct = d.get("sell_ratio_pct")
    if buy_pct is not None and sell_pct is not None and abs((buy_pct + sell_pct) - 100) > eps:
        warnings.append(f"buy_ratio_pct({buy_pct}) + sell_ratio_pct({sell_pct}) != 100")

    opinion = d.get("opinion")
    acc = d.get("signal_accuracy_pct")
    exp_ret = d.get("expected_return_pct")
    # Only a real problem when confidence is high (>50%) - low-confidence cases are
    # allowed to disagree in sign (that's the whole point of the "신뢰도 낮음" flag) and
    # are handled at render time, not flagged here as a data bug.
    if opinion is not None and acc is not None and exp_ret is not None and acc > 50:
        if opinion == "매수" and exp_ret < 0:
            warnings.append(f"opinion=매수 but expected_return_pct={exp_ret} is negative despite accuracy={acc}%")
        if opinion == "매도" and exp_ret > 0:
            warnings.append(f"opinion=매도 but expected_return_pct={exp_ret} is positive despite accuracy={acc}%")

    tp = d.get("trade_plan")
    if tp:
        entry = tp.get("entry_price")
        stop = tp.get("stop_price")
        t1 = tp.get("target1_price")
        t2 = tp.get("target2_price")
        if entry is not None and stop is not None and not (stop < entry):
            warnings.append(f"trade_plan: stop_price({stop}) should be < entry_price({entry})")
        if entry is not None and t1 is not None and not (t1 > entry):
            warnings.append(f"trade_plan: target1_price({t1}) should be > entry_price({entry})")
        if entry is not None and t2 is not None and not (t2 > entry):
            warnings.append(f"trade_plan: target2_price({t2}) should be > entry_price({entry})")
        if t1 is not None and t2 is not None and not (t2 >= t1):
            warnings.append(f"trade_plan: target2_price({t2}) should be >= target1_price({t1})")
        rr = tp.get("risk_reward")
        if rr is not None and rr <= 0:
            warnings.append(f"trade_plan: risk_reward({rr}) should be positive")

    wp = d.get("watch_plan")
    if wp:
        ref = wp.get("ref_price")
        s1 = wp.get("support1_price")
        s2 = wp.get("support2_price")
        if ref is not None and s1 is not None and not (s1 <= ref):
            warnings.append(f"watch_plan: support1_price({s1}) should be <= ref_price({ref})")
        if ref is not None and s2 is not None and not (s2 <= ref):
            warnings.append(f"watch_plan: support2_price({s2}) should be <= ref_price({ref})")
        if s1 is not None and s2 is not None and not (s2 <= s1):
            warnings.append(f"watch_plan: support2_price({s2}) should be <= support1_price({s1}) (2차 should be the deeper level)")

    top = d.get("top_strategy")
    if top:
        if top.get("train_return_pct") is not None and top.get("test_return_pct") is not None:
            pass  # no hard invariant between these - just informational, checked at render time
        if top.get("num_trades", 0) < 0:
            warnings.append("top_strategy: num_trades is negative (should be impossible)")

    # Chart arrows approximate the 종합의견(final_opinion) history now, not the single
    # top_strategy's own signal history (those two are allowed to disagree by design - see
    # backtest_engine._composite_chart_data / combine_opinion.apply_final_opinion_to_chart).
    # The one thing that MUST hold structurally is that the chart's LAST visible arrow
    # matches today's actual 종합의견 label - apply_final_opinion_to_chart is supposed to
    # force that, so a mismatch here means that correction didn't run or didn't take.
    chart_data = d.get("chart_data")
    final_opinion = d.get("final_opinion")
    if chart_data and chart_data.get("markers") and final_opinion and final_opinion.get("label") in ("매수", "매도"):
        last_marker = chart_data["markers"][-1]
        expected_type = "buy" if final_opinion["label"] == "매수" else "sell"
        if last_marker.get("type") != expected_type:
            warnings.append(
                f"chart/final_opinion mismatch: last chart marker on {last_marker.get('date')} is "
                f"'{last_marker.get('type')}' but final_opinion label is '{final_opinion['label']}' - "
                f"the chart's current arrow won't match the 종합의견 badge"
            )

    return warnings


def validate_all(all_results):
    """all_results: {ticker: {..per-ticker dict as saved in backtest_results.json..}}
    Returns {ticker: [warning, ...]} for tickers with at least one warning."""
    problems = {}
    for ticker, d in all_results.items():
        w = validate_ticker_result(ticker, d)
        if w:
            problems[ticker] = w
    return problems
