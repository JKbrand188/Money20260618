import csv
import io
import json
import pathlib
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

SYMBOLS = {
    "2330": "2330.TW", "2454": "2454.TW", "2881": "2881.TW",
    "AAPL": "AAPL", "NVDA": "NVDA", "MSFT": "MSFT",
}
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JKbrandbig888/1.0)"}


def get_text(url, timeout=25):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def yahoo_quote(symbol, provider_symbol):
    encoded = urllib.parse.quote(provider_symbol)
    last_error = None
    for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        for attempt in range(2):
            try:
                url = f"https://{host}/v8/finance/chart/{encoded}?interval=1m&range=1d"
                result = json.loads(get_text(url))["chart"]["result"][0]
                meta = result["meta"]
                price = float(meta["regularMarketPrice"])
                previous = float(meta.get("chartPreviousClose") or meta.get("previousClose") or price)
                return make_quote(symbol, price, previous, meta.get("currency"), meta.get("marketState"), "Yahoo")
            except Exception as exc:
                last_error = exc
                time.sleep(1 + attempt)
    raise last_error or RuntimeError("Yahoo quote unavailable")


def twse_quote(symbol):
    channel = urllib.parse.quote(f"tse_{symbol}.tw")
    url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={channel}&json=1&delay=0"
    row = json.loads(get_text(url))["msgArray"][0]
    raw_price = row.get("z")
    if not raw_price or raw_price == "-":
        raw_price = (row.get("b") or row.get("o") or "").split("_")[0]
    price = float(raw_price)
    previous = float(row.get("y") or price)
    return make_quote(symbol, price, previous, "TWD", "CLOSED" if row.get("t") >= "13:30:00" else "REGULAR", "TWSE")


def stooq_quote(symbol):
    ticker = symbol.lower() + ".us"
    url = f"https://stooq.com/q/d/l/?s={ticker}&i=d"
    rows = list(csv.DictReader(io.StringIO(get_text(url))))
    if not rows:
        raise RuntimeError("Stooq returned no rows")
    latest = rows[-1]
    previous_row = rows[-2] if len(rows) > 1 else latest
    return make_quote(symbol, float(latest["Close"]), float(previous_row["Close"]), "USD", "CLOSED", "Stooq")


def make_quote(symbol, price, previous, currency, market_state, source):
    change = round((price - previous) / previous * 100, 2) if previous else 0
    return {"symbol": symbol, "price": price, "change": change, "currency": currency,
            "marketState": market_state, "provider": source}


def fetch_quote(symbol, provider_symbol):
    try:
        return yahoo_quote(symbol, provider_symbol)
    except Exception as yahoo_error:
        try:
            return twse_quote(symbol) if symbol.isdigit() else stooq_quote(symbol)
        except Exception as fallback_error:
            raise RuntimeError(f"Yahoo: {yahoo_error}; fallback: {fallback_error}")


quotes, errors = [], []
for symbol, provider_symbol in SYMBOLS.items():
    try:
        quotes.append(fetch_quote(symbol, provider_symbol))
    except Exception as exc:
        errors.append({"symbol": symbol, "message": str(exc)[:240]})

if not quotes:
    raise RuntimeError("All quote providers failed: " + json.dumps(errors, ensure_ascii=False))

output = pathlib.Path("data/quotes.json")
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps({
    "updatedAt": datetime.now(timezone.utc).isoformat(),
    "source": "GitHub Actions delayed market data with provider fallback",
    "quotes": quotes,
    "errors": errors,
}, ensure_ascii=False, indent=2), encoding="utf-8")
