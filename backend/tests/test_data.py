"""Ground truths from implementation_plan.md section 2, verified against the CSVs."""

import pandas as pd

from app import data
from app.models import InvoiceFilters


def test_load_and_join():
    df = data.invoices()
    assert len(df) == 140
    assert df["vendor_status"].notna().all()
    assert df["currency"].value_counts().to_dict() == {"EUR": 89, "GBP": 27, "USD": 24}


def test_spain_totals_per_currency():
    df = data.filter_invoices(InvoiceFilters(vendor_country="spain"))
    groups = data.aggregate(df, "sum_amount", ["currency"], None, True)
    got = {g["currency"]: (g["value"], g["invoice_count"]) for g in groups}
    assert got == {"EUR": (1576971.22, 30), "GBP": (646618.51, 12), "USD": (343748.06, 7)}


def test_conversion_uses_ecb_rate_on_invoice_date():
    df = data.invoices().set_index("invoice_number")
    eur = df[df["currency"] == "EUR"]
    assert (eur["fx_rate"] == 1.0).all() and (eur["amount_eur"] == eur["amount"]).all()
    # Rates checked by hand in eurofxref-hist.csv.
    assert df.loc["INV-20002", ["fx_rate", "amount_eur"]].tolist() == [0.84088, 25071.57]  # GBP, Friday 2025-03-07
    # GBP on Sunday 2025-07-27: no ECB rate, so Friday 2025-07-25's rate is used.
    assert str(df.loc["INV-20034", "fx_rate_date"]) == "2025-07-25"
    assert df.loc["INV-20034", ["fx_rate", "amount_eur"]].tolist() == [0.8715, 83527.77]


def test_spain_total_converted():
    # Expected value from the raw CSVs and ECB file with merge_asof, independent of scripts/convert_invoices.py.
    raw = pd.read_csv(data.DATA_DIR / "invoices_2025_clean.csv", parse_dates=["invoice_date"])
    ven = pd.read_csv(data.DATA_DIR / "vendor_master.csv")
    ecb = pd.read_csv(data.DATA_DIR / "conversion" / "eurofxref-hist.csv", usecols=["Date", "USD", "GBP"],
                      parse_dates=["Date"]).sort_values("Date")
    ecb = ecb.melt(id_vars="Date", var_name="currency", value_name="rate").dropna().sort_values("Date")
    spain = raw[raw["vendor_id"].isin(ven[ven["country"] == "Spain"]["vendor_id"])].sort_values("invoice_date")
    spain = pd.merge_asof(spain, ecb, left_on="invoice_date", right_on="Date", by="currency")
    spain.loc[spain["currency"] == "EUR", "rate"] = 1.0
    expected = (spain["amount"] / spain["rate"]).round(2).sum()

    groups = data.aggregate(data.filter_invoices(InvoiceFilters(vendor_country="Spain")), "sum_amount", [], None, True)
    assert len(groups) == 1 and groups[0]["currency"] == "EUR" and groups[0]["invoice_count"] == 49
    assert groups[0]["value"] == round(expected, 2)
    assert groups[0]["converted_invoice_count"] == 19


def test_inactive_without_approver():
    df = data.filter_invoices(InvoiceFilters(vendor_status="INACTIVE", has_approver=False))
    assert sorted(df["invoice_number"]) == ["INV-20056", "INV-20108", "INV-20136"]


def test_on_hold_eur_over_50k():
    df = data.filter_invoices(InvoiceFilters(vendor_status="ON_HOLD", currency="EUR", min_amount=50000))
    assert set(df["invoice_number"]) == {"INV-20083", "INV-20127", "INV-20130", "INV-20106"}


def test_top_n_is_one_ranking_in_eur():
    groups = data.aggregate(data.invoices(), "sum_amount", ["vendor_name"], 5, True)
    assert len(groups) == 5 and {g["currency"] for g in groups} == {"EUR"}
    assert [g["value"] for g in groups] == sorted((g["value"] for g in groups), reverse=True)


def test_top_n_is_per_currency_when_grouped_by_currency():
    groups = data.aggregate(data.invoices(), "sum_amount", ["vendor_name", "currency"], 5, True)
    for cur in ("EUR", "GBP", "USD"):
        assert len([g for g in groups if g["currency"] == cur]) == 5


def test_amount_filters_are_in_eur():
    df = data.filter_invoices(InvoiceFilters(min_amount=50000))
    assert (df["amount_eur"] >= 50000).all()
    assert len(df[df["currency"] != "EUR"]) == 22


def test_summary_flags():
    s = data.get_summary()
    assert s["invoice_count"] == 140
    assert s["compliance_flags"] == {"missing_po": 21, "missing_approver": 25, "non_active_vendor": 29, "credit_notes": 2}
    assert sum(c["count"] for c in s["spend_by_currency"]) == 140
    assert s["total_spend_eur"] == round(sum(c["total_eur"] for c in s["spend_by_currency"]), 2)
    assert s["fx"]["converted_invoice_count"] == 51 and s["fx"]["prior_rate_invoice_count"] == 16


def test_missing_values_are_null():
    rows = data.to_records(data.filter_invoices(InvoiceFilters(has_po=False)))
    assert len(rows) == 21 and all(r["po_number"] is None for r in rows)
