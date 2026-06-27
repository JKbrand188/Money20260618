import csv
import io
import json
import math
import pathlib
import statistics
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JKbrandbig888/1.0)"}
HISTORY_FILE = pathlib.Path("data/twse_history.json")
OUTPUT_FILE = pathlib.Path("data/tw_opportunities.json")
TECH_INDUSTRIES = {
    "24": "半導體業", "25": "電腦及週邊設備業", "26": "光電業",
    "27": "通信網路業", "28": "電子零組件業", "29": "電子通路業",
    "30": "資訊服務業", "31": "其他電子業", "36": "數位雲端業",
}
FALLBACK_TECH_UNIVERSE = {
    "2301": "電腦及週邊設備業", "2303": "半導體業", "2308": "電子零組件業",
    "2317": "其他電子業", "2324": "電腦及週邊設備業", "2330": "半導體業",
    "2344": "半導體業", "2352": "電腦及週邊設備業", "2353": "電腦及週邊設備業",
    "2356": "電腦及週邊設備業", "2379": "半導體業", "2382": "電腦及週邊設備業",
    "2383": "電子零組件業", "2395": "電腦及週邊設備業", "2408": "半導體業",
    "2409": "光電業", "2412": "通信網路業", "2449": "光電業",
    "2454": "半導體業", "2474": "電子零組件業", "2498": "通信網路業",
    "2305": "電腦及週邊設備業", "2327": "電子零組件業", "2337": "半導體業",
    "2345": "通信網路業", "2354": "電腦及週邊設備業", "2360": "電腦及週邊設備業",
    "2362": "電腦及週邊設備業", "2368": "電子零組件業", "2376": "電腦及週邊設備業",
    "2377": "電腦及週邊設備業", "2385": "電子零組件業", "2392": "電子零組件業",
    "2404": "電子零組件業", "2417": "電子零組件業", "2421": "電子零組件業",
    "2439": "光電業", "2441": "半導體業", "2448": "半導體業",
    "2451": "半導體業", "2455": "電子零組件業", "2458": "電子零組件業",
    "2464": "光電業", "2476": "光電業", "2481": "半導體業",
    "2485": "光電業", "2492": "其他電子業", "2493": "電子零組件業",
    "3008": "光電業", "3017": "電子零組件業", "3034": "半導體業",
    "3035": "電子零組件業", "3036": "電子零組件業", "3042": "光電業",
    "3044": "光電業", "3045": "通信網路業", "3054": "光電業",
    "3189": "電子零組件業", "3231": "電腦及週邊設備業", "3338": "光電業",
    "3443": "半導體業", "3653": "半導體業", "3711": "半導體業",
    "4915": "電子零組件業", "4938": "光電業", "4958": "其他電子業",
    "5269": "半導體業", "6239": "其他電子業", "6278": "電子零組件業",
    "6415": "電腦及週邊設備業", "6669": "半導體業", "6770": "半導體業",
}


def number(value):
    if value is None:
        return None
    text = str(value).replace(",", "").replace("--", "").replace("---", "").strip()
    if not text or text in {"-", "除權", "除息"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def fetch_day(day):
    day_text = day.strftime("%Y%m%d")
    url = f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={day_text}&type=ALLBUT0999&response=json"
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=35) as response:
        payload = json.load(response)
    for table in payload.get("tables", []):
        fields = table.get("fields") or []
        joined = "|".join(fields)
        if "證券代號" not in joined or "收盤價" not in joined or "開盤價" not in joined:
            continue
        indexes = {field: i for i, field in enumerate(fields)}
        def find_index(*names):
            for name in names:
                for field, idx in indexes.items():
                    if name in field:
                        return idx
            return None
        ids = {key: find_index(*names) for key, names in {
            "symbol": ("證券代號",), "name": ("證券名稱",), "open": ("開盤價",),
            "high": ("最高價",), "low": ("最低價",), "close": ("收盤價",),
            "volume": ("成交股數",), "pe": ("本益比",), "pb": ("股價淨值比",),
            "yield": ("殖利率",),
        }.items()}
        records = []
        for row in table.get("data", []):
            symbol = str(row[ids["symbol"]]).strip() if ids["symbol"] is not None else ""
            if not symbol.isdigit() or len(symbol) != 4:
                continue
            values = {key: number(row[idx]) if idx is not None and idx < len(row) else None for key, idx in ids.items() if key not in {"symbol", "name"}}
            if any(values.get(k) is None for k in ("open", "high", "low", "close")):
                continue
            records.append({"date": day.isoformat(), "symbol": symbol,
                            "name": str(row[ids["name"]]).strip(), **values})
        return records
    return []


def fetch_tech_universe():
    rows = None
    json_url = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
    try:
        request = urllib.request.Request(json_url, headers=HEADERS)
        with urllib.request.urlopen(request, timeout=35) as response:
            raw = response.read()
        rows = json.loads(raw.decode("utf-8-sig"))
    except Exception as exc:
        print(f"TWSE OpenAPI unavailable, switching to MOPS CSV: {exc}")
    if not isinstance(rows, list):
        csv_url = "https://mopsfin.twse.com.tw/opendata/t187ap03_L.csv"
        request = urllib.request.Request(csv_url, headers=HEADERS)
        with urllib.request.urlopen(request, timeout=35) as response:
            raw = response.read()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp950", errors="replace")
        rows = list(csv.DictReader(io.StringIO(text)))
    universe = {}
    for row in rows:
        symbol = str(row.get("公司代號") or row.get("證券代號") or row.get("stock_id") or "").strip()
        if not symbol:
            for key, value in row.items():
                if any(token in str(key).lower() for token in ("公司代號", "證券代號", "代號", "stock")):
                    symbol = str(value or "").strip()
                    break
        industry_raw = str(row.get("產業別") or row.get("產業名稱") or row.get("industry_code") or row.get("industry") or "").strip()
        if not industry_raw:
            for key, value in row.items():
                if any(token in str(key).lower() for token in ("產業", "industry")):
                    industry_raw = str(value or "").strip()
                    break
        industry_code = industry_raw[:2].zfill(2) if industry_raw[:2].strip().isdigit() else ""
        industry_name = TECH_INDUSTRIES.get(industry_code)
        if not industry_name:
            industry_name = next((name for name in TECH_INDUSTRIES.values() if name in industry_raw), None)
        if symbol.isdigit() and len(symbol) == 4 and industry_name:
            universe[symbol] = industry_name
    if not universe:
        print("TWSE technology industry list is empty; using curated fallback technology universe")
        universe = FALLBACK_TECH_UNIVERSE.copy()
    elif len(universe) < 45:
        print(f"TWSE technology industry list has only {len(universe)} stocks; supplementing fallback universe")
        universe.update({symbol: sector for symbol, sector in FALLBACK_TECH_UNIVERSE.items() if symbol not in universe})
    print(f"Loaded {len(universe)} TWSE technology stocks")
    return universe


def ema(values, period):
    alpha = 2 / (period + 1)
    result = [values[0]]
    for value in values[1:]:
        result.append(value * alpha + result[-1] * (1 - alpha))
    return result


def clamp(value, low=0, high=100):
    return max(low, min(high, value))


def window_signals(rows, closes, histogram, days):
    sample = rows[-days:]
    latest = rows[-1]
    open_price = sample[0]["open"]
    close_price = latest["close"]
    high_price = max(row["high"] for row in sample)
    low_price = min(row["low"] for row in sample)
    avg_volume = statistics.mean(row.get("volume") or 0 for row in sample)
    ma5, ma10, ma20 = (statistics.mean(closes[-period:]) for period in (5, 10, 20))
    above_mas = close_price > ma5 and close_price > ma10 and close_price > ma20
    body = max(abs(close_price - open_price), close_price * 0.001)
    lower_shadow = min(open_price, close_price) - low_price
    long_shadow = lower_shadow >= body * 2
    start_index = max(1, len(histogram) - days)
    macd_turn = any(histogram[i - 1] <= 0 < histogram[i] for i in range(start_index, len(histogram)))
    volume_1000 = avg_volume >= 1_000_000
    return {"shadow": long_shadow, "macd": macd_turn, "mas": above_mas, "volume": volume_1000}


def score_stock(symbol, rows, industry_name):
    rows = sorted(rows, key=lambda row: row["date"])[-70:]
    if len(rows) < 35:
        return None
    closes = [row["close"] for row in rows]
    latest, previous = rows[-1], rows[-2]
    macd_line = [a - b for a, b in zip(ema(closes, 12), ema(closes, 26))]
    signal_line = ema(macd_line, 9)
    histogram = [a - b for a, b in zip(macd_line, signal_line)]
    technical_windows = {
        "d1": window_signals(rows, closes, histogram, 1),
        "d3": window_signals(rows, closes, histogram, 3),
        "d5": window_signals(rows, closes, histogram, 5),
    }
    long_shadow = technical_windows["d1"]["shadow"]
    macd_turn = technical_windows["d1"]["macd"]
    above_mas = technical_windows["d1"]["mas"]
    volume_1000 = technical_windows["d1"]["volume"]
    returns = [(closes[i] / closes[i - 1] - 1) for i in range(1, len(closes)) if closes[i - 1]]
    volatility = statistics.pstdev(returns[-20:]) * math.sqrt(252) if len(returns) >= 20 else 0.5
    peak, max_drawdown = closes[0], 0
    for close in closes:
        peak = max(peak, close)
        max_drawdown = min(max_drawdown, close / peak - 1)
    momentum20 = closes[-1] / closes[-21] - 1
    trend_score = clamp(35 * above_mas + 30 * macd_turn + 20 * long_shadow + clamp(50 + momentum20 * 250, 0, 100) * 0.15)
    risk_score = clamp(100 - volatility * 105 + max_drawdown * 80)
    pe, pb, dividend_yield = latest.get("pe"), latest.get("pb"), latest.get("yield")
    pe_score = 50 if not pe or pe <= 0 else clamp(105 - pe * 3)
    pb_score = 50 if not pb or pb <= 0 else clamp(100 - pb * 12)
    yield_score = clamp((dividend_yield or 0) * 15)
    value_score = round(pe_score * 0.55 + pb_score * 0.25 + yield_score * 0.20)
    volumes = [row.get("volume") or 0 for row in rows[-20:]]
    avg_turnover_proxy = statistics.mean(volumes) * latest["close"]
    liquidity_score = clamp(35 + math.log10(max(avg_turnover_proxy, 1)) * 7)
    fundamental_proxy = round(value_score * 0.7 + liquidity_score * 0.3)
    score = round(fundamental_proxy * 0.30 + trend_score * 0.40 + value_score * 0.15 + risk_score * 0.15)
    change = round((latest["close"] / previous["close"] - 1) * 100, 2)
    passed = sum((long_shadow, macd_turn, above_mas, volume_1000))
    reasons = []
    if long_shadow: reasons.append("出現長下引線")
    if macd_turn: reasons.append("MACD 柱狀體由綠轉紅")
    if above_mas: reasons.append("收盤價站上 MA5、MA10、MA20")
    if volume_1000: reasons.append("每日交易量 1000 張以上")
    if not reasons: reasons.append("依估值與風險分數進入排行")
    return {
        "symbol": symbol, "name": latest["name"], "market": "TW", "sector": industry_name,
        "price": latest["close"], "change": change, "score": score,
        "signal": "偏多" if score >= 75 else "觀察" if score >= 60 else "中性",
        "logo": latest["name"][:1], "dims": [fundamental_proxy, round(trend_score), value_score, round(risk_score)],
        "pe": f"{pe:.1f}x" if pe else "—", "growth": "—", "roe": "—",
        "margin": "—", "vol": f"{volatility * 100:.1f}%",
        "thesis": reasons + [f"技術條件通過 {passed}/4；資料日期 {latest['date']}。"],
        "risk": f"近 20 日年化波動約 {volatility * 100:.1f}%，近 70 日最大回撤約 {max_drawdown * 100:.1f}%。",
        "technical": technical_windows["d1"], "technicalWindows": technical_windows,
        "volumeShares": latest.get("volume"), "volumeLots": round((latest.get("volume") or 0) / 1000),
        "dataDate": latest["date"], "peRaw": pe, "pbRaw": pb, "yieldRaw": dividend_yield,
    }


tech_universe = fetch_tech_universe()
history = json.loads(HISTORY_FILE.read_text(encoding="utf-8")) if HISTORY_FILE.exists() else {}
history = {symbol: rows for symbol, rows in history.items() if symbol in tech_universe}
today = datetime.now(timezone.utc).date()
existing_dates = {row["date"] for rows in history.values() for row in rows}
symbols_with_enough_history = sum(1 for symbol in tech_universe if len(history.get(symbol, [])) >= 35)
lookback = 90 if len(existing_dates) < 35 or symbols_with_enough_history < 45 else 7
if lookback == 90:
    print(f"Backfilling 90 days because only {symbols_with_enough_history} technology stocks have enough history")
for offset in reversed(range(lookback)):
    day = today - timedelta(days=offset)
    if day.weekday() >= 5 or day.isoformat() in existing_dates:
        continue
    try:
        records = fetch_day(day)
        for record in records:
            if record["symbol"] in tech_universe:
                history.setdefault(record["symbol"], []).append(record)
        if records:
            print(f"{day}: {len(records)} listed stocks")
        time.sleep(0.35)
    except Exception as exc:
        print(f"{day}: skipped ({exc})")

for symbol in list(history):
    unique = {row["date"]: row for row in history[symbol]}
    history[symbol] = sorted(unique.values(), key=lambda row: row["date"])[-75:]

opportunities = [item for symbol, rows in history.items() if (item := score_stock(symbol, rows, tech_universe[symbol]))]
opportunities.sort(key=lambda item: (sum(item["technical"].values()), item["score"]), reverse=True)
HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
OUTPUT_FILE.write_text(json.dumps({
    "updatedAt": datetime.now(timezone.utc).isoformat(), "market": "TWSE_TECH", "count": len(opportunities),
    "universeCount": len(tech_universe), "industries": list(TECH_INDUSTRIES.values()),
    "method": "TWSE technology stocks: end-of-day technical, valuation proxy and risk ranking", "stocks": opportunities[:45],
}, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Generated {min(45, len(opportunities))} opportunities from {len(opportunities)} eligible stocks")
