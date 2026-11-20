"""Data layer shared by GET /summary and the LLM tools, so their numbers cannot disagree."""

from functools import lru_cache
from pathlib import Path

import pandas as pd

from .models import InvoiceFilters

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

INVOICE_COLUMNS = [
    "invoice_number", "invoice_date", "vendor_id", "vendor_name", "vendor_country",
    "vendor_category", "vendor_status", "description", "amount", "currency",
    "fx_rate", "fx_rate_date", "amount_eur",
    "cost_center", "po_number", "approved_by", "is_credit_note",
]

FX_NOTE = (
    "GBP and USD amounts are converted to EUR at the ECB reference rate on the invoice date (policy §5.1). "
    "ECB publishes no rate on weekends and TARGET holidays, so invoices dated on those days use the last rate "
    "published before the invoice date (shown as fx_rate_date)."
)


@lru_cache
def invoices() -> pd.DataFrame:
    # Built by scripts/convert_invoices.py: the raw invoices plus fx_rate, fx_rate_date and amount_eur.
    inv = pd.read_csv(DATA_DIR / "conversion" / "invoices_2025_clean.converted.csv", dtype=str)
    for col in ("amount", "fx_rate", "amount_eur"):
        inv[col] = inv[col].astype(float)
    inv["invoice_date"] = pd.to_datetime(inv["invoice_date"]).dt.date
    inv["fx_rate_date"] = pd.to_datetime(inv["fx_rate_date"]).dt.date
    vendors_df = vendors().rename(
        columns={"country": "vendor_country", "category": "vendor_category", "status": "vendor_status"}
    )
    # Invoices only carry vendor_id and name; country, category and status come from the vendor master.
    df = inv.merge(vendors_df.drop(columns="vendor_name"), on="vendor_id", how="left", validate="many_to_one")
    df["month"] = pd.to_datetime(df["invoice_date"]).dt.strftime("%Y-%m")
    df["is_credit_note"] = df["amount"] < 0
    return df


@lru_cache
def vendors() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "vendor_master.csv", dtype=str)


@lru_cache
def policy_text() -> str:
    return (DATA_DIR / "procurement_policy.md").read_text()


def _ieq(series: pd.Series, value: str) -> pd.Series:
    return series.str.lower() == value.strip().lower()


def _icontains(series: pd.Series, value: str) -> pd.Series:
    return series.str.contains(value.strip(), case=False, regex=False, na=False)


def filter_invoices(f: InvoiceFilters) -> pd.DataFrame:
    df = invoices()
    mask = pd.Series(True, index=df.index)
    if f.vendor_id:
        mask &= _ieq(df["vendor_id"], f.vendor_id)
    if f.vendor_name:
        mask &= _icontains(df["vendor_name"], f.vendor_name)
    if f.vendor_country:
        mask &= _ieq(df["vendor_country"], f.vendor_country)
    if f.vendor_category:
        mask &= _ieq(df["vendor_category"], f.vendor_category)
    if f.vendor_status:
        mask &= df["vendor_status"] == f.vendor_status
    if f.currency:
        mask &= df["currency"] == f.currency
    if f.date_from:
        mask &= df["invoice_date"] >= f.date_from
    if f.date_to:
        mask &= df["invoice_date"] <= f.date_to
    if f.cost_center:
        mask &= _ieq(df["cost_center"], f.cost_center)
    if f.description_contains:
        mask &= _icontains(df["description"], f.description_contains)
    if f.min_amount is not None:
        mask &= df["amount_eur"] >= f.min_amount
    if f.max_amount is not None:
        mask &= df["amount_eur"] <= f.max_amount
    if f.has_po is not None:
        mask &= df["po_number"].notna() == f.has_po
    if f.has_approver is not None:
        mask &= df["approved_by"].notna() == f.has_approver
    if f.approved_by:
        mask &= _ieq(df["approved_by"], f.approved_by)
    return df[mask]


def to_records(df: pd.DataFrame, columns: list[str] = INVOICE_COLUMNS) -> list[dict]:
    """JSON-safe rows. Missing values become None, dates become ISO strings."""
    out = []
    for rec in df[columns].to_dict(orient="records"):
        row = {}
        for k, v in rec.items():
            if pd.isna(v):  # None, NaN, and NaT (missing fx_rate_date on EUR rows)
                row[k] = None
            elif hasattr(v, "isoformat"):
                row[k] = v.isoformat()
            elif isinstance(v, float):
                row[k] = round(v, 6 if k == "fx_rate" else 2)
            elif hasattr(v, "item"):  # numpy scalar
                row[k] = v.item()
            else:
                row[k] = v
        out.append(row)
    return out


def aggregate(
    df: pd.DataFrame, metric: str, group_by: list[str], top_n: int | None, sort_desc: bool
) -> list[dict]:
    """Group and aggregate. Money metrics use amount_eur (converted at ECB rates) unless currency is a group key,
    in which case each group reports the original amount in its own currency plus the EUR equivalent."""
    if df.empty:
        return []
    money = metric in ("sum_amount", "avg_amount")
    by_currency = "currency" in group_by
    keys = list(dict.fromkeys(group_by))
    grouped = df.groupby(keys, dropna=False, sort=False) if keys else [((), df)]

    groups = []
    for key_vals, g in grouped:
        if not isinstance(key_vals, tuple):
            key_vals = (key_vals,)
        key_map = {k: (None if pd.isna(v) else v) for k, v in zip(keys, key_vals)}
        currency = None
        if money:
            currency = key_map.pop("currency") if by_currency else "EUR"
        amount_col = "amount" if by_currency else "amount_eur"
        agg = "sum" if metric == "sum_amount" else "mean"
        value = getattr(g[amount_col], agg)() if money else len(g)
        group = {
            "keys": key_map,
            "currency": currency,
            "value": round(float(value), 2) if money else int(value),
            "invoice_count": int(len(g)),
            "credit_note_count": int(g["is_credit_note"].sum()),
            "invoice_numbers": sorted(g["invoice_number"].tolist()),
        }
        if money:
            group["value_eur"] = round(float(getattr(g["amount_eur"], agg)()), 2)
            group["converted_invoice_count"] = int((g["currency"] != "EUR").sum())
            group["prior_rate_invoice_count"] = _prior_rate_count(g)
        groups.append(group)

    groups.sort(key=lambda r: r["value"], reverse=sort_desc)
    if top_n is not None:
        if money:
            per_currency: dict[str, int] = {}
            ranked = []
            for r in groups:
                per_currency[r["currency"]] = per_currency.get(r["currency"], 0) + 1
                if per_currency[r["currency"]] <= top_n:
                    ranked.append(r)
            groups = ranked
        else:
            groups = groups[:top_n]
    if money:
        groups.sort(key=lambda r: (r["currency"], -r["value"] if sort_desc else r["value"]))
    return groups


def _prior_rate_count(df: pd.DataFrame) -> int:
    """Invoices dated on a day without an ECB rate, converted at the last rate published before the invoice date."""
    return int((df["fx_rate_date"].notna() & (df["fx_rate_date"] != df["invoice_date"])).sum())


def get_summary() -> dict:
    df = invoices()
    all_rows = InvoiceFilters()
    total = aggregate(df, "sum_amount", [], None, True)[0]
    by_currency = aggregate(df, "sum_amount", ["currency"], None, True)
    by_status = aggregate(df, "sum_amount", ["vendor_status"], None, True)
    return {
        "invoice_count": len(df),
        "vendor_count": int(df["vendor_id"].nunique()),
        "date_from": df["invoice_date"].min(),
        "date_to": df["invoice_date"].max(),
        "total_spend_eur": total["value"],
        "spend_by_currency": [
            {"currency": g["currency"], "total": g["value"], "total_eur": g["value_eur"], "count": g["invoice_count"]}
            for g in by_currency
        ],
        "spend_by_vendor_status": [
            {"status": g["keys"]["vendor_status"], "currency": g["currency"], "total": g["value"],
             "count": g["invoice_count"]}
            for g in sorted(by_status, key=lambda g: (g["keys"]["vendor_status"], g["currency"]))
        ],
        "compliance_flags": {
            "missing_po": len(filter_invoices(all_rows.model_copy(update={"has_po": False}))),
            "missing_approver": len(filter_invoices(all_rows.model_copy(update={"has_approver": False}))),
            "non_active_vendor": int((df["vendor_status"] != "ACTIVE").sum()),
            "credit_notes": int(df["is_credit_note"].sum()),
        },
        "fx": {
            "converted_invoice_count": total["converted_invoice_count"],
            "prior_rate_invoice_count": total["prior_rate_invoice_count"],
            "note": FX_NOTE,
        },
        "note": "Totals include credit notes (negative amounts). Spend by vendor status is in EUR after conversion.",
    }
