# 매수 구간 판독기

미국 주식의 200일선, 52주 위치, RSI, PER, FCF 수익률, 기업 체력을 규칙으로 계산해 고점 매수를 피하도록 돕는 개인용 페이지입니다. GitHub Actions가 평일 장 마감 뒤 데이터를 갱신하고, 결과는 비밀번호로 암호화해 GitHub Pages에 올립니다.

투자 자문이 아닌 참고 도구이며, 판정 기준은 아직 과거 데이터로 검증하지 않은 초기값입니다.

## 설정

**Settings → Secrets and variables → Actions**에 다음 4개를 등록합니다.

| 이름 | 값 |
|---|---|
| `TIINGO_TOKEN` | [Tiingo](https://www.tiingo.com/) 무료 가입 후 받은 API 토큰 |
| `SEC_CONTACT` | SEC 요청에 함께 보낼 연락처 이메일 (SEC 규정) |
| `PAGE_PASSWORD` | 페이지 비밀번호. 저장소에 암호문이 공개되므로 16자 이상으로 길게 만드세요 |
| `WATCHLIST` | 관심 종목. 예: `AAPL:애플, MSFT:마이크로소프트, VOO:S&P500:ETF, QQQ:나스닥100:ETF` (최대 40개). ETF는 끝에 `:ETF`를 붙입니다 |

**Settings → Pages → Source**를 **GitHub Actions**로 바꾼 뒤, **Actions → 판독 데이터 갱신 → Run workflow**로 첫 실행을 합니다.

## 관심 종목 바꾸기

`WATCHLIST` 값을 수정한 뒤 Run workflow를 누르거나 다음 갱신을 기다립니다.

## ETF

ETF는 재무 공시가 없어 200일선, 52주 위치, RSI만으로 판정합니다. 실적 대비 가격은 판단하지 않습니다.

## 구조

- `scripts/metrics.py`: 지표 계산
- `scripts/update.py`: 데이터 수집과 암호화
- `docs/index.html`: 화면과 판정 규칙
- `.github/workflows/update.yml`: 예약 실행과 배포

## 데이터 약관

Tiingo 무료 데이터는 개인 사용 조건입니다. 페이지와 비밀번호를 다른 사람과 공유하지 마세요. 공유하려면 Tiingo의 별도 라이선스가 필요합니다.
