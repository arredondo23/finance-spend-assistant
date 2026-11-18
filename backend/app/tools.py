"""LLM-callable tools. Pydantic models generate the JSON schemas, validate LLM arguments, and type the code."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import data
from .models import InvoiceFilters, VendorStatus

GroupBy = Literal[
    "vendor_name", "vendor_country", "vendor_category", "vendor_status",
    "cost_center", "approved_by", "description", "month",
]


class QueryInvoicesArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filters: InvoiceFilters = Field(default_factory=InvoiceFilters)
    sort_by: Literal["amount", "invoice_date", "vendor_name"] = "invoice_date"
    sort_desc: bool = True
    limit: int = Field(20, ge=1, le=50)


class AggregateArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: Literal["sum_amount", "count", "avg_amount"]
    group_by: list[GroupBy] = Field(default_factory=list)
    filters: InvoiceFilters = Field(default_factory=InvoiceFilters)
    top_n: int | None = Field(None, ge=1, le=20, description="Keep the top N groups (per currency for money metrics)")
    sort_desc: bool = True


class VendorFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vendor_id: str | None = None
    vendor_name: str | None = Field(None, description="Case-insensitive substring of the vendor name")
    country: str | None = None
    category: str | None = None
    status: VendorStatus | None = None


class GetVendorsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filters: VendorFilters = Field(default_factory=VendorFilters)


def query_invoices(args: QueryInvoicesArgs) -> dict:
    df = data.filter_invoices(args.filters)
    df = df.sort_values(args.sort_by, ascending=not args.sort_desc, kind="stable")
    rows = data.to_records(df.head(args.limit))
    return {"total_matched": len(df), "returned": len(rows), "truncated": len(df) > len(rows), "rows": rows}


def aggregate(args: AggregateArgs) -> dict:
    df = data.filter_invoices(args.filters)
    groups = data.aggregate(df, args.metric, args.group_by, args.top_n, args.sort_desc)
    return {"metric": args.metric, "total_invoices_matched": len(df), "groups": groups}


def get_vendors(args: GetVendorsArgs) -> dict:
    f = args.filters
    df = data.vendors()
    for col, val in [("vendor_id", f.vendor_id), ("country", f.country), ("category", f.category), ("status", f.status)]:
        if val:
            df = df[df[col].str.lower() == val.strip().lower()]
    if f.vendor_name:
        df = df[df["vendor_name"].str.contains(f.vendor_name.strip(), case=False, regex=False)]
    return {"count": len(df), "vendors": df.to_dict(orient="records")}


@dataclass(frozen=True)
class Tool:
    args_model: type[BaseModel]
    fn: Callable[[Any], dict]
    description: str


TOOLS: dict[str, Tool] = {
    "query_invoices": Tool(
        QueryInvoicesArgs,
        query_invoices,
        "Return individual invoice rows matching filters (combined with AND). Use for 'show me / which invoices...' "
        "questions. Each row includes vendor_country, vendor_category and vendor_status joined from the vendor master, "
        "and is_credit_note (amount < 0). Missing PO or approver is null. "
        "Amount filters are RAW amounts in each invoice's own currency with no FX conversion, so for a threshold like "
        "'over EUR 50,000' you MUST also set currency=EUR. "
        "This tool does not compute totals, counts across groups, or rankings: use `aggregate` for those. "
        "Results are capped by `limit` (max 50); check `total_matched` and `truncated` before claiming a list is complete.",
    ),
    "aggregate": Tool(
        AggregateArgs,
        aggregate,
        "Compute sum_amount, count or avg_amount over invoices matching filters, optionally grouped. Use for 'how much', "
        "'how many', 'top N' and 'by month / by vendor' questions. For sum_amount and avg_amount the result is ALWAYS "
        "split by currency (enforced in code), because there are no FX rates; top_n then ranks within each currency. "
        "Sums include credit notes (negative amounts); each group reports credit_note_count and invoice_numbers. "
        "Amount filters are raw amounts in each invoice's own currency.",
    ),
    "get_vendors": Tool(
        GetVendorsArgs,
        get_vendors,
        "Look up the vendor master (vendor_id, vendor_name, country, category, status). Use for questions about vendors "
        "themselves, e.g. 'which vendors are on hold' or 'where is Helix based'. Does not return invoices.",
    ),
}


def _inline_refs(schema: dict) -> dict:
    """Pydantic emits $defs/$ref; inline them so each tool schema is self-contained."""
    defs = schema.pop("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(dict(defs[node["$ref"].split("/")[-1]]))
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


def tool_definitions() -> list[dict]:
    return [
        {"name": name, "description": t.description, "input_schema": _inline_refs(t.args_model.model_json_schema())}
        for name, t in TOOLS.items()
    ]
