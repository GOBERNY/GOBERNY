"""
Capture the per-ticker summary card out of report.html as PNG images.

Produces the same view you get by opening a single ticker from the search page - report.html
already has a single-ticker mode keyed off the URL hash (#ticker-PLTR), which widens the card
to full width AND reveals the `.detail-extra` blocks (the 이동평균 / ADX-DMI / Parabolic SAR
rows under 추세상태). So this script just drives that existing behaviour rather than
re-styling anything: no change to generate_report_v2.py is needed or made.

Each image is cropped to the summary portion - header, 가격 차트, 종합의견, 지표분석 + 추세상태 -
by clipping from the top of the card through the bottom of the `.row-indicator-trend` block.

Output (overwritten / added to on every run):
    images/latest/<TICKER>.png            <- the 6 files to grab each day
    images/<YYYY-MM-DD>/<TICKER>.png      <- dated copy, mirrors the archive/ convention

Requires the headless Chromium environment - run `source setup_capture_env.sh` first.

Usage:
    python3 capture_cards.py                 # the 6 configured tickers
    python3 capture_cards.py NVDA AMD        # ad-hoc override
"""
import datetime
import json
import os
import pathlib
import shutil
import sys
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

# Chromium needs libXdamage.so.1, which setup_capture_env.sh extracts into a local prefix
# because there's no root in the sandbox. Point the loader at it here rather than relying on
# the caller having *sourced* that script - `source x.sh | tee` silently loses the export to
# a subshell, and the resulting failure is an opaque "exitCode=127" from deep inside
# playwright. The child Chromium process inherits this, which is what actually matters.
_DEPS = os.path.join(os.path.expanduser("~"), ".local", "chromium-deps",
                     "usr", "lib", "x86_64-linux-gnu")
if os.path.isdir(_DEPS):
    _cur = os.environ.get("LD_LIBRARY_PATH", "")
    if _DEPS not in _cur.split(":"):
        os.environ["LD_LIBRARY_PATH"] = f"{_DEPS}:{_cur}" if _cur else _DEPS

# The six the report is checked for daily. Any ticker present in report.html works.
CAPTURE_TICKERS = ["QQQ", "MU", "SNDK", "SOXX", "IONQ", "TSLA"]

VIEWPORT_WIDTH = 1060      # single-view card settles at ~1020px wide, matching the site
SCALE = 2                  # retina-ish output (~2040px wide PNG, ~0.2MB each)
REPORT = "report.html"
OUT_ROOT = "images"


def _crop_box(page, ticker):
    """Card top -> bottom of the 지표분석/추세상태 row, in page coordinates."""
    return page.evaluate(
        """(t) => {
            const a = document.querySelector('#ticker-' + t);
            if (!a) return null;
            const c = a.classList.contains('ticker-card') ? a : a.closest('.ticker-card') || a;
            const cr = c.getBoundingClientRect();
            // Summary ends at the 지표분석 + 추세상태 row. If that block is ever renamed,
            // fall back to the whole card rather than producing a wrongly-cropped image.
            const last = c.querySelector('.row-indicator-trend');
            const pad = parseFloat(getComputedStyle(c).paddingBottom) || 0;
            const bottom = last ? last.getBoundingClientRect().bottom + pad : cr.bottom;
            return {x: cr.x + window.scrollX, y: cr.y + window.scrollY,
                    width: cr.width, height: bottom - cr.top,
                    cropped: !!last};
        }""",
        ticker,
    )


def main(tickers):
    from playwright.sync_api import sync_playwright

    if not os.path.exists(REPORT):
        raise SystemExit(f"ERROR: {REPORT} not found - run generate_report_v2.py first.")

    # Label the dated folder with the data's own date when available, so the folder name
    # matches the closes in the images rather than whenever the job happened to run.
    data_date = None
    if os.path.exists("backtest_results.json"):
        try:
            with open("backtest_results.json", "r", encoding="utf-8") as f:
                t = json.load(f)["tickers"]
            dates = [t[x]["last_date"] for x in tickers if x in t]
            if dates:
                data_date = max(dates)
        except Exception:
            pass
    stamp = data_date or datetime.datetime.now(KST).date().isoformat()

    latest_dir = os.path.join(OUT_ROOT, "latest")
    dated_dir = os.path.join(OUT_ROOT, stamp)
    os.makedirs(latest_dir, exist_ok=True)
    os.makedirs(dated_dir, exist_ok=True)

    base = pathlib.Path(REPORT).resolve().as_uri()
    saved, missing = [], []

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(
            viewport={"width": VIEWPORT_WIDTH, "height": 1200}, device_scale_factor=SCALE
        )
        for tk in tickers:
            # Reload per ticker: the hash handler runs on load, so a fresh goto is the
            # simplest way to get a clean single-ticker view for each one.
            page.goto(f"{base}#ticker-{tk}", wait_until="networkidle", timeout=120_000)
            page.wait_for_timeout(1200)  # let the inline chart/gauge SVGs settle

            box = _crop_box(page, tk)
            if box is None:
                missing.append(tk)
                print(f"  {tk:6s} SKIP  - #ticker-{tk} not in {REPORT}")
                continue

            out = os.path.join(latest_dir, f"{tk}.png")
            page.screenshot(
                path=out,
                clip={k: box[k] for k in ("x", "y", "width", "height")},
                full_page=True,
            )
            shutil.copy(out, os.path.join(dated_dir, f"{tk}.png"))
            saved.append(tk)
            note = "" if box["cropped"] else "  (WARN: .row-indicator-trend missing - full card)"
            print(
                f"  {tk:6s} OK    {int(box['width'])}x{int(box['height'])}pt "
                f"-> {out}{note}"
            )
        browser.close()

    print(f"\n{len(saved)} image(s) saved to {latest_dir}/ and {dated_dir}/")
    if missing:
        print(f"missing from report: {missing}")
    return 0 if saved else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or CAPTURE_TICKERS))
