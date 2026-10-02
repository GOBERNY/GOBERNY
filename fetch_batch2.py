import sys, os
sys.path.insert(0, os.getcwd())
import fetch_data

remaining_names = ["XLB","XLY","XLF","XLRE","XLI","XLP","XLK","XLU","XLC","XLE",
                    "TSM","ASML","AMAT","JPM","V","UNH","WMT","XOM","CRWD","COIN",
                    "MSTR","QQQ","DIA","IWM","삼성전자","SK하이닉스"]
fetch_data.TICKERS = {k: v for k, v in fetch_data.TICKERS.items() if k in remaining_names}
print(f"Fetching {len(fetch_data.TICKERS)} remaining tickers: {list(fetch_data.TICKERS.keys())}")
for name, (status, detail) in fetch_data.fetch_all().items():
    print(f"{name:8s} {status:5s} {detail}")
