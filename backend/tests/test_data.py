"""Ground truths from implementation_plan.md section 2, verified against the CSVs."""

from app import data
from app.models import InvoiceFilters


def test_load_and_join():
    df = data.invoices()
    assert len(df) == 140
    assert df["vendor_status"].notna().all()
    assert df["currency"].value_counts().to_dict() == {"EUR": 89, "GBP": 27, "USD": 24}


def test_spain_totals_per_currency():
    df = data.filter_invoices(InvoiceFilters(vendor_country="spain"))
    groups = data.aggregate(df, "sum_amount", [], None, True)
    got = {g["currency"]: (g["value"], g["invoice_count"]) for g in groups}
    assert got == {"EUR": (1576971.22, 30), "GBP": (646618.51, 12), "USD": (343748.06, 7)}


def test_inactive_without_approver():
    df = data.filter_invoices(InvoiceFilters(vendor_status="INACTIVE", has_approver=False))
    assert sorted(df["invoice_number"]) == ["INV-20056", "INV-20108", "INV-20136"]


def test_on_hold_eur_over_50k():
    df = data.filter_invoices(InvoiceFilters(vendor_status="ON_HOLD", currency="EUR", min_amount=50000))
    assert set(df["invoice_number"]) == {"INV-20083", "INV-20127", "INV-20130", "INV-20106"}


def test_top_n_is_per_currency():
    groups = data.aggregate(data.invoices(), "sum_amount", ["vendor_name"], 5, True)
    for cur in ("EUR", "GBP", "USD"):
        assert len([g for g in groups if g["currency"] == cur]) == 5


def test_summary_flags():
    s = data.get_summary()
    assert s["invoice_count"] == 140
    assert s["compliance_flags"] == {"missing_po": 21, "missing_approver": 25, "non_active_vendor": 29, "credit_notes": 2}
    assert sum(c["count"] for c in s["spend_by_currency"]) == 140


def test_missing_values_are_null():
    rows = data.to_records(data.filter_invoices(InvoiceFilters(has_po=False)))
    assert len(rows) == 21 and all(r["po_number"] is None for r in rows)
