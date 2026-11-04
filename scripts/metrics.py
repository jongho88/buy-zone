"""시세(Tiingo)와 SEC 공시(companyfacts)에서 판독에 필요한 원시 지표를 계산한다. 네트워크를 쓰지 않는 순수 함수만 둔다."""
from datetime import date, timedelta

REVENUE = ["RevenueFromContractWithCustomerExcludingAssessedTax", "RevenueFromContractWithCustomerIncludingAssessedTax", "Revenues", "SalesRevenueNet", "SalesRevenueGoodsNet"]
NET_INCOME = ["NetIncomeLoss", "NetIncomeLossAvailableToCommonStockholdersBasic", "ProfitLoss"]
EPS = ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "EarningsPerShareBasic"]
OPERATING = ["OperatingIncomeLoss"]
OCF = ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"]
CAPEX = ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"]
EQUITY = ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]
DEBT_TOTAL = ["LongTermDebt", "LongTermDebtAndCapitalLeaseObligations"]
DEBT_PARTS = ["LongTermDebtNoncurrent", "LongTermDebtCurrent"]
DEBT_SHORT = ["CommercialPaper", "ShortTermBorrowings"]
FORMS = ("10-K", "10-Q", "20-F", "40-F")


class DataError(Exception):
    """판독에 필요한 값이 없을 때. 메시지는 암호화된 결과에만 들어간다."""


def d(text):
    return date.fromisoformat(text[:10])


def facts(cf, tags, unit="USD", taxonomy="us-gaap"):
    """여러 태그를 합친다. 같은 기간은 앞선 태그가 우선이고, 같은 태그 안에서는 가장 늦게 제출된 값을 쓴다."""
    merged = {}
    pool = cf.get("facts", {}).get(taxonomy, {})
    for tag in tags:
        best = {}
        for row in pool.get(tag, {}).get("units", {}).get(unit, []):
            if not row.get("form", "").startswith(FORMS):
                continue
            item = {"start": d(row["start"]) if row.get("start") else None, "end": d(row["end"]), "val": row["val"], "filed": d(row["filed"])}
            key = (item["start"], item["end"])
            if key not in best or item["filed"] > best[key]["filed"]:
                best[key] = item
        for key, item in best.items():
            merged.setdefault(key, item)
    return list(merged.values())


def days(f):
    return (f["end"] - f["start"]).days + 1


def annuals(rows):
    return sorted((f for f in rows if f["start"] and 350 <= days(f) <= 380), key=lambda f: f["end"])


def near(a, b, tol):
    return abs((a - b).days) <= tol


def one_year_before(day):
    return day - timedelta(days=365)


def ttm(rows, anchor, value=lambda f: f["val"]):
    """anchor로 끝나는 최근 12개월 합계. 연간 + 올해 누적 - 작년 누적, 안 되면 분기 4개 합을 쓴다."""
    ann = [f for f in annuals(rows) if f["end"] <= anchor + timedelta(days=5)]
    if ann and near(ann[-1]["end"], anchor, 5):
        return value(ann[-1])
    if ann:
        base = ann[-1]
        ytd = [f for f in rows if f["start"] and near(f["end"], anchor, 5) and near(f["start"], base["end"] + timedelta(days=1), 10) and days(f) < 350]
        if ytd:
            cur = max(ytd, key=days)
            prior = [f for f in rows if f["start"] and near(f["end"], one_year_before(anchor), 10) and near(f["start"], one_year_before(cur["start"]), 10) and abs(days(f) - days(cur)) <= 10]
            if prior:
                return value(base) + value(cur) - value(prior[0])
    quarters = sorted((f for f in rows if f["start"] and 80 <= days(f) <= 100 and anchor - timedelta(days=370) < f["end"] <= anchor + timedelta(days=5)), key=lambda f: f["end"])
    if len(quarters) == 4 and near(quarters[-1]["end"], anchor, 5):
        return sum(value(f) for f in quarters)
    return None


def latest_instant(rows, anchor):
    found = [f for f in rows if f["start"] is None and f["end"] <= anchor + timedelta(days=5)]
    return max(found, key=lambda f: f["end"]) if found else None


def rsi14(closes):
    if len(closes) < 15:
        raise DataError("RSI 계산에 필요한 시세가 부족합니다")
    gains = [max(b - a, 0) for a, b in zip(closes, closes[1:])]
    losses = [max(a - b, 0) for a, b in zip(closes, closes[1:])]
    avg_g, avg_l = sum(gains[:14]) / 14, sum(losses[:14]) / 14
    for g, l in zip(gains[14:], losses[14:]):
        avg_g, avg_l = (avg_g * 13 + g) / 14, (avg_l * 13 + l) / 14
    return 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)


def prepare_prices(rows):
    """Tiingo 일봉을 액면분할만 반영한 가격으로 바꾼다. 배당 조정 가격은 쓰지 않는다."""
    rows = sorted(rows, key=lambda r: r["date"])
    if len(rows) < 200:
        raise DataError("200일선 계산에 필요한 시세가 부족합니다")
    splits = [(d(r["date"]), r["splitFactor"]) for r in rows if r.get("splitFactor", 1) not in (1, 1.0, None)]

    def after(day):
        factor = 1.0
        for when, ratio in splits:
            if when > day:
                factor *= ratio
        return factor

    series = [{"date": d(r["date"]), "close": r["close"] / after(d(r["date"])), "high": r["high"] / after(d(r["date"])), "low": r["low"] / after(d(r["date"]))} for r in rows]
    return series, after


def close_on(series, day):
    found = [p for p in series if p["date"] <= day]
    if not found or (day - found[-1]["date"]).days > 7:
        return None
    return found[-1]["close"]


def price_fields(prices):
    series, _ = prepare_prices(prices)
    last = series[-1]
    closes = [p["close"] for p in series]
    year = [p for p in series if p["date"] > last["date"] - timedelta(days=365)]
    paid = sum(r.get("divCash") or 0 for r in prices if d(r["date"]) > last["date"] - timedelta(days=365))
    return {
        "yld": round(paid / last["close"] * 100, 2), "asof": last["date"].isoformat(), "price": round(last["close"], 2), "ma200": round(sum(closes[-200:]) / 200, 2),
        "lo": round(min(p["low"] for p in year), 2), "hi": round(max(p["high"] for p in year), 2), "rsi": round(rsi14(closes), 2),
    }


def compute_etf(ticker, label, prices):
    """ETF는 SEC 재무 데이터가 없으므로 가격 지표만 만든다."""
    return {"t": ticker, "ko": label or ticker, "en": "ETF", "etf": True, **price_fields(prices)}


def compute(ticker, label, title, prices, cf):
    series, split_after = prepare_prices(prices)
    last = series[-1]
    closes = [p["close"] for p in series]
    year = [p for p in series if p["date"] > last["date"] - timedelta(days=365)]

    per_share = lambda f: f["val"] / split_after(f["filed"])
    shares_now = lambda f: f["val"] * split_after(f["filed"])

    ni, rev, eps, ocf, capex = facts(cf, NET_INCOME), facts(cf, REVENUE), facts(cf, EPS, "USD/shares"), facts(cf, OCF), facts(cf, CAPEX)
    if not ni or not eps or not rev or not ocf:
        raise DataError("SEC 공시에서 매출·이익·현금흐름을 찾지 못했습니다. 금융주, ETF, 해외 기업은 지원하지 않을 수 있습니다")
    flows = [f for f in ni if f["start"] and days(f) <= 380 and f["end"] <= last["date"]]
    if not flows:
        raise DataError("최근 실적 기간을 찾지 못했습니다")
    anchor = max(f["end"] for f in flows)
    ago = one_year_before(anchor)

    eps_t, eps_ago = ttm(eps, anchor, per_share), ttm(eps, ago, per_share)
    ni_t, rev_t, rev_ago = ttm(ni, anchor), ttm(rev, anchor), ttm(rev, ago)
    ocf_t, capex_t = ttm(ocf, anchor), ttm(capex, anchor) if capex else 0
    if None in (eps_t, ni_t, rev_t, rev_ago, ocf_t, capex_t, eps_ago):
        raise DataError("최근 12개월 실적을 계산하지 못했습니다")
    fcf_t = ocf_t - capex_t
    op_rows = facts(cf, OPERATING)
    op_t = ttm(op_rows, anchor) if op_rows else None

    eps_year = {}
    for f in annuals(eps):
        eps_year[f["end"]] = per_share(f)
    ni_year = {f["end"]: f["val"] for f in annuals(ni)}
    ocf_year = {f["end"]: f["val"] for f in annuals(ocf)}
    capex_year = {f["end"]: f["val"] for f in annuals(capex)}
    ends = sorted(end for end in eps_year if any(near(end, o, 5) for o in ocf_year) and any(near(end, n, 5) for n in ni_year))[-5:]
    if len(ends) < 3:
        raise DataError("비교할 과거 회계연도가 3개 미만입니다")

    def by_end(table, end, default=None):
        for key, val in table.items():
            if near(key, end, 5):
                return val
        return default

    fcf_year = {end: by_end(ocf_year, end) - by_end(capex_year, end, 0) for end in ends}
    pe_hist, fcf_hist = [], []
    for end in ends:
        price, e, n = close_on(series, end), eps_year[end], by_end(ni_year, end)
        if price is None or e <= 0 or n <= 0:
            pe_hist.append(None)
            fcf_hist.append(None)
            continue
        pe_hist.append(round(price / e, 2))
        fcf_hist.append(round(fcf_year[end] / (price * n / e) * 100, 2))
    price_only = eps_t <= 0 or len([x for x in pe_hist if x is not None]) < 3

    shares_rows = facts(cf, ["EntityCommonStockSharesOutstanding"], "shares", "dei") or facts(cf, ["CommonStockSharesOutstanding"], "shares")
    latest_shares = latest_instant(shares_rows, last["date"])
    shares = shares_now(latest_shares) if latest_shares else (ni_t / eps_t if eps_t > 0 else None)
    fcfy = round(fcf_t / (last["close"] * shares) * 100, 2) if shares else None

    equity_rows = facts(cf, EQUITY)
    eq_now, eq_ago = latest_instant(equity_rows, anchor), latest_instant(equity_rows, ago)
    roe = de = None
    if eq_now and eq_now["val"] > 0:
        base = (eq_now["val"] + eq_ago["val"]) / 2 if eq_ago and eq_ago["val"] > 0 else eq_now["val"]
        roe = round(ni_t / base * 100, 2)

        def at(tags):
            found = [f for f in facts(cf, tags) if f["start"] is None and near(f["end"], eq_now["end"], 5)]
            return found[0]["val"] if found else None

        parts = [at([t]) for t in DEBT_PARTS]
        long_term = sum(x for x in parts if x is not None) if any(x is not None for x in parts) else at(DEBT_TOTAL)
        short = [at([t]) for t in DEBT_SHORT]
        if long_term is not None or any(x is not None for x in short):
            de = round(((long_term or 0) + sum(x for x in short if x is not None)) / eq_now["val"], 2)

    two_ago = ends[-3]
    return {
        "t": ticker, "ko": label or title, "en": title, "asof": last["date"].isoformat(),
        "price": round(last["close"], 2), "ma200": round(sum(closes[-200:]) / 200, 2),
        "lo": round(min(p["low"] for p in year), 2), "hi": round(max(p["high"] for p in year), 2),
        "rsi": round(rsi14(closes), 2), "pe": round(last["close"] / eps_t, 2) if eps_t > 0 else None, "fcfy": fcfy,
        "priceOnly": price_only, "loss": eps_t <= 0,
        "roe": roe, "de": de, "fy": [f"FY{str(end.year)[2:]}" for end in ends], "peH": pe_hist, "fcfH": fcf_hist,
        "rev": round((rev_t / rev_ago - 1) * 100, 2), "epsT": round(eps_t, 2), "epsAgo": round(eps_ago, 2),
        "epsFY": round(eps_year[ends[-1]], 2), "eps2": round(eps_year[two_ago], 2),
        "niT": round(ni_t / 1e6), "opT": None if op_t is None else round(op_t / 1e6), "fcfT": round(fcf_t / 1e6), "fcf2": round(fcf_year[two_ago] / 1e6), "y2": f"FY{str(two_ago.year)[2:]}",
        "period": anchor.isoformat(),
    }
