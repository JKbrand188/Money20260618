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
        symbol = str(row.get("公司代號") or "").strip()
        industry_code = str(row.get("產業別") or "").strip().zfill(2)
        if symbol.isdigit() and len(symbol) == 4 and industry_code in TECH_INDUSTRIES:
            universe[symbol] = TECH_INDUSTRIES[industry_code]
    if not universe:
        raise RuntimeError("TWSE technology industry list is empty")
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


def score_stock(symbol, rows, industry_name):
    rows = sorted(rows, key=lambda row: row["date"])[-70:]
    if len(rows) < 35:
        return None
    closes = [row["close"] for row in rows]
    latest, previous = rows[-1], rows[-2]
    ma5, ma10, ma20 = (statistics.mean(closes[-period:]) for period in (5, 10, 20))
    above_mas = latest["close"] > ma5 and latest["close"] > ma10 and latest["close"] > ma20
    body = max(abs(latest["close"] - latest["open"]), latest["close"] * 0.001)
    lower_shadow = min(latest["open"], latest["close"]) - latest["low"]
    long_shadow = lower_shadow >= body * 2
    macd_line = [a - b for a, b in zip(ema(closes, 12), ema(closes, 26))]
    signal_line = ema(macd_line, 9)
    histogram = [a - b for a, b in zip(macd_line, signal_line)]
    macd_turn = histogram[-2] <= 0 < histogram[-1]
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
    passed = sum((long_shadow, macd_turn, above_mas))
    reasons = []
    if long_shadow: reasons.append("出現長下引線")
    if macd_turn: reasons.append("MACD 柱狀體由綠轉紅")
    if above_mas: reasons.append("收盤價站上 MA5、MA10、MA20")
    if not reasons: reasons.append("依估值與風險分數進入排行")
    return {
        "symbol": symbol, "name": latest["name"], "market": "TW", "sector": industry_name,
        "price": latest["close"], "change": change, "score": score,
        "signal": "偏多" if score >= 75 else "觀察" if score >= 60 else "中性",
        "logo": latest["name"][:1], "dims": [fundamental_proxy, round(trend_score), value_score, round(risk_score)],
        "pe": f"{pe:.1f}x" if pe else "—", "growth": "—", "roe": "—",
        "margin": "—", "vol": f"{volatility * 100:.1f}%",
        "thesis": reasons + [f"技術條件通過 {passed}/3；資料日期 {latest['date']}。"],
        "risk": f"近 20 日年化波動約 {volatility * 100:.1f}%，近 70 日最大回撤約 {max_drawdown * 100:.1f}%。",
        "technical": {"shadow": long_shadow, "macd": macd_turn, "mas": above_mas},
        "dataDate": latest["date"], "peRaw": pe, "pbRaw": pb, "yieldRaw": dividend_yield,
    }


tech_universe = fetch_tech_universe()
history = json.loads(HISTORY_FILE.read_text(encoding="utf-8")) if HISTORY_FILE.exists() else {}
history = {symbol: rows for symbol, rows in history.items() if symbol in tech_universe}
today = datetime.now(timezone.utc).date()
existing_dates = {row["date"] for rows in history.values() for row in rows}
lookback = 90 if len(existing_dates) < 35 else 7
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
    "method": "TWSE technology stocks: end-of-day technical, valuation proxy and risk ranking", "stocks": opportunities[:30],
}, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Generated {min(30, len(opportunities))} opportunities from {len(opportunities)} eligible stocks")
