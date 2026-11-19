"""Build data/conversion/invoices_2025_clean.converted.csv from the raw invoices and the ECB reference rates.

Policy §5.1: non-EUR invoices are converted at the ECB reference rate on the invoice date. ECB publishes no rate on
weekends and TARGET holidays; those invoices use the latest rate published before the invoice date, and
fx_rate_date records which ECB date was used. EUR invoices get fx_rate 1.0 and no fx_rate_date.

ECB quotes 1 EUR = fx_rate units of the foreign currency, so amount_eur = amount / fx_rate.

Run from backend/: uv run python scripts/convert_invoices.py
"""

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CONVERSION_DIR = DATA_DIR / "conversion"

inv = pd.read_csv(DATA_DIR / "invoices_2025_clean.csv", dtype=str)
amount = inv["amount"].astype(float)
inv_dates = pd.to_datetime(inv["invoice_date"])

ecb = pd.read_csv(CONVERSION_DIR / "eurofxref-hist.csv", usecols=["Date", "USD", "GBP"], parse_dates=["Date"])
ecb = ecb.sort_values("Date").set_index("Date")

rates, rate_dates = [], []
for date, currency in zip(inv_dates, inv["currency"]):
    if currency == "EUR":
        rates.append(1.0)
        rate_dates.append(None)
        continue
    published = ecb.loc[:date, currency].dropna()
    if published.empty:
        raise ValueError(f"No ECB {currency} rate on or before {date.date()}")
    rates.append(float(published.iloc[-1]))
    rate_dates.append(published.index[-1].date().isoformat())

inv["fx_rate"] = rates
inv["fx_rate_date"] = rate_dates
inv["amount_eur"] = (amount / inv["fx_rate"]).round(2)
inv.to_csv(CONVERSION_DIR / "invoices_2025_clean.converted.csv", index=False)
print(f"Wrote {len(inv)} rows")
