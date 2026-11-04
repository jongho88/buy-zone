"""관심 종목 데이터를 받아 판독용 지표를 계산하고, 비밀번호로 암호화해 docs/data.enc.json에 저장한다.

공개 저장소의 실행 로그에도 종목과 숫자가 남지 않도록 건수만 출력한다.
"""
import base64
import json
import os
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

sys.path.insert(0, str(Path(__file__).parent))
from metrics import DataError, compute, compute_etf  # noqa: E402

MAX_TICKERS = 40  # Tiingo 무료 요금제의 시간당 50회 안에 들도록 제한한다
ITERATIONS = 600_000
OUT = Path(__file__).parent.parent / "docs" / "data.enc.json"


def parse_watchlist(text):
    seen, out = set(), []
    for raw in text.replace("\n", ",").split(","):
        raw = raw.strip()
        if not raw:
            continue
        parts = [p.strip() for p in raw.split(":")]
        ticker = parts[0].upper().replace(".", "-")
        is_etf = len(parts) > 2 and parts[-1].upper() == "ETF"
        label = ":".join(parts[1:-1] if is_etf else parts[1:])
        if ticker not in seen:
            seen.add(ticker)
            out.append((ticker, label, is_etf))
    return out[:MAX_TICKERS]


def get_json(url, headers):
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def encrypt(payload, password):
    salt, nonce = os.urandom(16), os.urandom(12)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERATIONS)
    cipher = AESGCM(kdf.derive(password.encode())).encrypt(nonce, json.dumps(payload, ensure_ascii=False).encode(), None)
    b64 = lambda b: base64.b64encode(b).decode()
    return {"v": 1, "iter": ITERATIONS, "salt": b64(salt), "nonce": b64(nonce), "data": b64(cipher)}


def main():
    token, contact, password = os.environ["TIINGO_TOKEN"], os.environ["SEC_CONTACT"], os.environ["PAGE_PASSWORD"]
    watch = parse_watchlist(os.environ["WATCHLIST"])
    sec = {"User-Agent": f"buy-zone-reader {contact}", "Accept-Encoding": "identity"}
    tiingo = {"Authorization": f"Token {token}", "Content-Type": "application/json"}
    start = (date.today() - timedelta(days=int(365.25 * 6.5))).isoformat()

    index = get_json("https://www.sec.gov/files/company_tickers.json", sec)
    ciks = {row["ticker"].upper().replace(".", "-"): row for row in index.values()}

    stocks, errors = [], []
    for ticker, label, is_etf in watch:
        try:
            if is_etf:
                prices = get_json(f"https://api.tiingo.com/tiingo/daily/{ticker}/prices?startDate={start}", tiingo)
                time.sleep(0.2)
                stocks.append(compute_etf(ticker, label, prices))
                continue
            row = ciks.get(ticker)
            if not row:
                raise DataError("SEC에 등록된 미국 상장 종목을 찾지 못했습니다")
            prices = get_json(f"https://api.tiingo.com/tiingo/daily/{ticker}/prices?startDate={start}", tiingo)
            time.sleep(0.2)
            facts = get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(row['cik_str']):010d}.json", sec)
            time.sleep(0.2)
            stocks.append(compute(ticker, label, row["title"], prices, facts))
        except DataError as exc:
            errors.append({"t": ticker, "why": str(exc)})
        except Exception as exc:  # 한 종목 실패가 전체를 멈추지 않게 한다
            errors.append({"t": ticker, "why": f"데이터를 받지 못했습니다 ({type(exc).__name__})"})

    print(f"판독 성공 {len(stocks)}건, 실패 {len(errors)}건")
    if not stocks:
        print("판독에 성공한 종목이 없어 기존 결과를 유지합니다.")
        return 1
    payload = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "stocks": stocks, "errors": errors}
    OUT.write_text(json.dumps(encrypt(payload, password)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
