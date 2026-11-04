import sys, unittest
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from metrics import DataError, compute, compute_etf, facts, rsi14, ttm
from update import parse_watchlist


def flow(start, end, val, filed, form="10-K"):
    return {"start": start, "end": end, "val": val, "filed": filed, "form": form}


def inst(end, val, filed, form="10-K"):
    return {"end": end, "val": val, "filed": filed, "form": form}


def company(eps_fn=lambda y, v: v, shares=1e9):
    """12월 결산, 2020~2025 연간과 2026년 9개월 누적을 가진 가상 회사."""
    def annual(base, grow):
        rows = []
        for i, y in enumerate(range(2020, 2026)):
            rows.append(flow(f"{y}-01-01", f"{y}-12-31", base + grow * i, f"{y+1}-02-01"))
        rows.append(flow("2025-01-01", "2025-09-30", base * .7, "2025-11-01", "10-Q"))
        rows.append(flow("2026-01-01", "2026-09-30", base * .9, "2026-10-20", "10-Q"))
        rows.append(flow("2024-01-01", "2024-09-30", base * .6, "2024-11-01", "10-Q"))
        return rows
    gaap = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": annual(100e9, 10e9)}},
        "NetIncomeLoss": {"units": {"USD": annual(20e9, 2e9)}},
        "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": annual(25e9, 2e9)}},
        "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": annual(5e9, 0)}},
        "EarningsPerShareDiluted": {"units": {"USD/shares": annual(20, 2)}},
        "StockholdersEquity": {"units": {"USD": [inst("2025-09-30", 40e9, "2025-11-01", "10-Q"), inst("2026-09-30", 60e9, "2026-10-20", "10-Q")]}},
        "LongTermDebtNoncurrent": {"units": {"USD": [inst("2026-09-30", 30e9, "2026-10-20", "10-Q")]}},
        "CommercialPaper": {"units": {"USD": [inst("2026-09-30", 6e9, "2026-10-20", "10-Q")]}},
    }
    dei = {"EntityCommonStockSharesOutstanding": {"units": {"shares": [inst("2026-10-15", shares, "2026-10-20", "10-Q")]}}}
    return {"facts": {"us-gaap": gaap, "dei": dei}}


def prices(price=300.0, split_on=None, ratio=1):
    rows, day = [], date(2020, 1, 2)
    while day <= date(2026, 10, 30):
        if day.weekday() < 5:
            pre = split_on and day < split_on
            p = price * (ratio if pre else 1)
            rows.append({"date": day.isoformat() + "T00:00:00Z", "close": p, "high": p * 1.01, "low": p * .99, "splitFactor": ratio if split_on == day else 1.0})
        day += timedelta(days=1)
    return rows


class Tests(unittest.TestCase):
    def test_ttm_is_annual_plus_ytd_minus_prior(self):
        s = compute("X", "", "Example", prices(), company())
        # EPS: FY25 30 + 9M26 18 - 9M25 14 = 34
        self.assertEqual(s["epsT"], 34)
        self.assertEqual(s["pe"], round(300 / 34, 2))
        self.assertEqual(s["period"], "2026-09-30")

    def test_revenue_growth_compares_same_periods(self):
        s = compute("X", "", "Example", prices(), company())
        # TTM 2026-09 = 150+90-70 = 170B, TTM 2025-09 = 140+70-60 = 150B
        self.assertEqual(s["rev"], round((170 / 150 - 1) * 100, 2))

    def test_fcf_roe_de(self):
        s = compute("X", "", "Example", prices(), company())
        ocf = 35 + 22.5 - 17.5  # 40B
        capex = 5 + 4.5 - 3.5  # 6B
        self.assertEqual(s["fcfT"], round((ocf - capex) * 1000))
        ni = 30 + 18 - 14  # 34B
        self.assertEqual(s["roe"], round(ni / 50 * 100, 2))
        self.assertEqual(s["de"], 0.6)

    def test_split_adjusts_old_prices_and_eps_consistently(self):
        plain = compute("X", "", "Example", prices(300), company())
        split = prices(30, date(2026, 6, 1), 10)
        c = company()
        for row in c["facts"]["us-gaap"]["EarningsPerShareDiluted"]["units"]["USD/shares"]:
            if row["filed"] >= "2026-06-01":
                row["val"] /= 10
        c["facts"]["dei"]["EntityCommonStockSharesOutstanding"]["units"]["shares"][0]["val"] = 1e10
        s = compute("X", "", "Example", split, c)
        self.assertEqual(s["peH"], plain["peH"])
        self.assertEqual(s["fcfH"], plain["fcfH"])
        self.assertEqual(s["pe"], plain["pe"])
        self.assertEqual(s["fcfy"], plain["fcfy"])
        self.assertEqual(s["ma200"], 30)

    def test_latest_filed_value_wins(self):
        cf = {"facts": {"us-gaap": {"NetIncomeLoss": {"units": {"USD": [flow("2024-01-01", "2024-12-31", 1, "2025-02-01"), flow("2024-01-01", "2024-12-31", 2, "2026-02-01")]}}}}}
        self.assertEqual(ttm(facts(cf, ["NetIncomeLoss"]), date(2024, 12, 31)), 2)

    def test_loss_is_reported_not_crashed(self):
        c = company()
        for row in c["facts"]["us-gaap"]["EarningsPerShareDiluted"]["units"]["USD/shares"]:
            row["val"] = -abs(row["val"])
        with self.assertRaises(DataError):
            compute("X", "", "Example", prices(), c)

    def test_rsi_extremes(self):
        self.assertEqual(rsi14(list(range(1, 40))), 100.0)
        self.assertLess(rsi14(list(range(40, 1, -1))), 1)

    def test_watchlist(self):
        self.assertEqual(parse_watchlist("aapl:애플, BRK.B\nAAPL,,ko,voo:S&P500:etf,qqq::ETF"), [("AAPL", "애플", False), ("BRK-B", "", False), ("KO", "", False), ("VOO", "S&P500", True), ("QQQ", "", True)])

    def test_etf_uses_prices_only(self):
        s = compute_etf("VOO", "S&P500", prices(500))
        self.assertTrue(s["etf"])
        self.assertEqual((s["price"], s["ma200"]), (500, 500))
        self.assertNotIn("pe", s)


if __name__ == "__main__":
    unittest.main()
