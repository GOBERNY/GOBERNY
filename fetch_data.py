"""
Fetch fresh daily OHLCV data for the tracked tickers via yfinance and save to data/*.csv.

Guards against using an in-progress/partial trading day as if it were a final close:
if the most recent row's date is today (US/Eastern) and the market hasn't been closed
for at least 15 minutes yet, that row is dropped so the report always reflects the last
FULLY COMPLETED session's close, not a mid-day snapshot.

Quote fallback for Yahoo's daily-bar lag:
Yahoo serves the daily history bar and the live quote from two different endpoints, and
the daily bar can stay unpopulated (Close = NaN, or the row missing entirely) for hours
after the session has actually closed - which used to make this script silently fall back
to the PREVIOUS day's close even though the real close was already visible on the Yahoo
Finance site. When that happens, `_quote_snapshot()` reads the close off the quote
endpoint instead and appends it as that day's bar. It only ever does this when all of:
  - the session for that date is already complete per the guard above,
  - the quote's own `regularMarketTime` falls on exactly that date (so we never stamp a
    quote onto a date it doesn't belong to), and
  - the market is not still in its REGULAR trading phase.
Crypto (BTC) is excluded: it has no session close, so a 24/7 last price is not a
meaningful daily close and a missing BTC bar is left missing.
Note this does mix sources - a quote-filled bar's OHLC come from the consolidated quote
rather than the adjusted daily bar, so its Volume in particular can differ slightly from
what the daily bar will eventually report. Such bars are flagged in the fetch output.
"""
import datetime
import time
import zoneinfo
import pandas as pd
import yfinance as yf

TICKERS = {
    # original 10
    "NVDA": "NVDA", "MU": "MU", "SOXX": "SOXX", "TSLA": "TSLA", "IONQ": "IONQ",
    "NVTS": "NVTS", "SNDK": "SNDK", "PLTR": "PLTR", "RKLB": "RKLB", "BTC": "BTC-USD",
    # 반도체 및 테슬라
    "QCOM": "QCOM", "COHR": "COHR", "AMD": "AMD", "INTC": "INTC", "MRVL": "MRVL",
    "ORCL": "ORCL", "SMCI": "SMCI",
    # AI 인프라 / 데이터센터
    "POET": "POET", "CIFR": "CIFR", "CRWV": "CRWV",
    # 양자컴퓨터
    "RGTI": "RGTI", "QBTS": "QBTS",
    # 드론 택시 (eVTOL)
    "ACHR": "ACHR", "JOBY": "JOBY", "RCAT": "RCAT",
    # 휴머노이드 관련주
    "ARBE": "ARBE", "RR": "RR", "SERV": "SERV",
    # 우주/자원/기타 성장주
    "DXYZ": "DXYZ", "MP": "MP", "OPEN": "OPEN", "TEM": "TEM",
    "RXRX": "RXRX", "RZLV": "RZLV", "SATL": "SATL", "SES": "SES", "SMR": "SMR",
    # M7
    "AAPL": "AAPL", "MSFT": "MSFT", "GOOGL": "GOOGL", "AMZN": "AMZN", "META": "META",
    # 빅테크 추가
    "AVGO": "AVGO", "CRM": "CRM", "ADBE": "ADBE", "NFLX": "NFLX",
    # 섹터 ETF
    "SPY": "SPY", "XLV": "XLV", "XLB": "XLB", "XLY": "XLY", "XLF": "XLF",
    "XLRE": "XLRE", "XLI": "XLI", "XLP": "XLP", "XLK": "XLK", "XLU": "XLU",
    "XLC": "XLC", "XLE": "XLE",
    # 반도체 공급망 핵심주 (파운드리/장비 - 지금까지는 수요기업 위주였음)
    "TSM": "TSM", "ASML": "ASML", "AMAT": "AMAT",
    # 금융/헬스케어/소비재/에너지 블루칩
    "JPM": "JPM", "V": "V", "UNH": "UNH", "WMT": "WMT", "XOM": "XOM",
    # 사이버보안
    "CRWD": "CRWD",
    # 크립토 연계주 (BTC 보유/노출 기업)
    "COIN": "COIN", "MSTR": "MSTR",
    # 지수 ETF
    "QQQ": "QQQ", "DIA": "DIA", "IWM": "IWM",
    # 한국 반도체
    "삼성전자": "005930.KS", "SK하이닉스": "000660.KS",
}


def _market_session_complete_for(last_row_date):
    """True if `last_row_date` (a date) is safe to treat as a final stock-market close right now."""
    now_et = datetime.datetime.now(zoneinfo.ZoneInfo("America/New_York"))
    if last_row_date < now_et.date():
        return True  # a prior calendar day is always final
    if last_row_date > now_et.date():
        return False  # shouldn't happen, but don't trust future dates
    # same ET calendar day as "now" - only final if we're comfortably past the 4pm ET close
    return (now_et.hour, now_et.minute) >= (16, 15)


def _crypto_day_complete_for(last_row_date):
    """BTC trades 24/7, so there's no market close - a daily bar (UTC-based) is only
    final once that UTC calendar day has fully elapsed, not tied to US market hours."""
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    return last_row_date < now_utc.date()


def _quote_snapshot(symbol):
    """Read `symbol`'s last quote off Yahoo's quote endpoint.

    Returns (quote_date, ohlcv_dict) where quote_date is the exchange-LOCAL calendar date
    the quote belongs to, or (None, None) if the quote is missing/unusable/still live.
    Deliberately conservative: anything unexpected returns (None, None) so the caller
    just keeps the last fully completed daily bar instead.
    """
    try:
        info = yf.Ticker(symbol).info or {}
    except Exception:
        return None, None

    # Still trading - a mid-session snapshot is exactly what this script refuses to use.
    if info.get("marketState") == "REGULAR":
        return None, None

    ts = info.get("regularMarketTime")
    tzname = info.get("exchangeTimezoneName")
    close = info.get("regularMarketPrice")
    op = info.get("regularMarketOpen")
    hi = info.get("regularMarketDayHigh")
    lo = info.get("regularMarketDayLow")
    vol = info.get("regularMarketVolume")
    if ts is None or not tzname or any(v is None for v in (close, op, hi, lo, vol)):
        return None, None

    try:
        quote_date = datetime.datetime.fromtimestamp(ts, zoneinfo.ZoneInfo(tzname)).date()
    except Exception:
        return None, None

    try:
        row = {
            "Open": float(op), "High": float(hi), "Low": float(lo),
            "Close": float(close), "Volume": float(vol),
        }
    except (TypeError, ValueError):
        return None, None
    # A quoted close outside its own quoted day range means the payload is inconsistent.
    if not (row["Low"] <= row["Close"] <= row["High"]):
        return None, None
    return quote_date, row


def _download_with_retry(symbol, period, retries=2, delay_sec=0.6, backoff_sec=3.0):
    """yfinance sequential fetches get more likely to hit Yahoo's (undocumented) rate
    limiting as the ticker list grows - a small delay between every request plus one retry
    with a longer backoff on failure covers the common transient case without meaningfully
    slowing down a once-a-day batch job."""
    last_err = None
    for attempt in range(retries + 1):
        try:
            df = yf.download(symbol, period=period, interval="1d", progress=False, auto_adjust=True)
            time.sleep(delay_sec)
            return df, None
        except Exception as e:
            last_err = e
            time.sleep(backoff_sec)
    return None, last_err


def fetch_all(out_dir="data", period="3y"):
    import os
    os.makedirs(out_dir, exist_ok=True)
    results = {}
    for name, symbol in TICKERS.items():
        try:
            df, err = _download_with_retry(symbol, period)
            if err is not None:
                results[name] = ("FAIL", str(err))
                continue
            if df.empty:
                results[name] = ("FAIL", "empty response (symbol may not exist / not tradable via Yahoo Finance)")
                continue
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

            # Yahoo occasionally returns a trailing row with a valid Volume but NaN OHLC
            # (a data glitch, not an in-progress bar) - strip any such unusable trailing rows
            # before doing the session-completeness check, since that check only looks at
            # dates and would otherwise treat a NaN-price row from a prior day as "final".
            n_before = len(df)
            nan_dates = []
            while len(df) > 0 and df["Close"].iloc[-1] != df["Close"].iloc[-1]:  # NaN check
                nan_dates.append(df.index[-1].date())
                df = df.iloc[:-1]
            dropped_nan_rows = n_before - len(df)

            if df.empty:
                results[name] = ("FAIL", "no valid rows after dropping NaN-price rows")
                continue

            # Yahoo's daily bar for an already-closed session can still be NaN/absent for
            # hours. If so, take that day's close off the quote endpoint instead of
            # silently reporting the previous day as the latest close. See module docstring.
            quote_filled_date = None
            if name != "BTC":
                fillable = [d for d in nan_dates if _market_session_complete_for(d)]
                if fillable:
                    quote_date, quote_row = _quote_snapshot(symbol)
                    # Only accept a quote that lands on one of the dates we actually lost,
                    # and only ahead of the newest bar we still hold.
                    if quote_date in fillable and quote_date > df.index[-1].date():
                        idx = pd.Timestamp(quote_date)
                        if df.index.tz is not None:
                            idx = idx.tz_localize(df.index.tz)
                        if all(c in quote_row for c in df.columns):
                            df.loc[idx] = [quote_row[c] for c in df.columns]
                            df = df.sort_index()
                            quote_filled_date = quote_date

            last_date = df.index[-1].date()
            is_complete = _crypto_day_complete_for(last_date) if name == "BTC" else _market_session_complete_for(last_date)
            if not is_complete:
                df = df.iloc[:-1]  # drop the still-forming/partial last bar
                dropped = True
            else:
                dropped = False
            if df.empty:
                results[name] = ("FAIL", "no completed sessions available")
                continue
            df.to_csv(f"{out_dir}/{name}.csv")
            note = ""
            if dropped_nan_rows:
                note += f" (dropped {dropped_nan_rows} NaN-price row(s))"
            if quote_filled_date:
                note += f" (QUOTE-FILLED {quote_filled_date} from live quote - daily bar lagging)"
            if dropped:
                note += " (dropped in-progress bar)"
            results[name] = ("OK", f"{len(df)} rows, last={df.index[-1].date()}" + note)
        except Exception as e:
            results[name] = ("FAIL", str(e))
    return results


if __name__ == "__main__":
    for name, (status, detail) in fetch_all().items():
        print(f"{name:6s} {status:5s} {detail}")
