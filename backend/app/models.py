from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

VendorStatus = Literal["ACTIVE", "INACTIVE", "ON_HOLD"]
Currency = Literal["EUR", "GBP", "USD"]


class InvoiceFilters(BaseModel):
    """All filters are optional and combined with AND."""

    model_config = ConfigDict(extra="forbid")

    vendor_id: str | None = Field(None, description="Exact vendor ID, e.g. V-1006")
    vendor_name: str | None = Field(None, description="Case-insensitive substring of the vendor name")
    vendor_country: str | None = Field(None, description="Vendor country from the vendor master, e.g. Spain, UK")
    vendor_category: str | None = Field(None, description="Vendor category, e.g. IT Services")
    vendor_status: VendorStatus | None = None
    currency: Currency | None = None
    date_from: date | None = Field(None, description="Invoice date on or after (YYYY-MM-DD)")
    date_to: date | None = Field(None, description="Invoice date on or before (YYYY-MM-DD)")
    cost_center: str | None = Field(None, description="Exact cost center, e.g. CC-IT-550")
    description_contains: str | None = Field(None, description="Case-insensitive substring of the invoice description")
    min_amount: float | None = Field(
        None, description="Inclusive lower bound on the raw amount in the invoice's own currency (no FX conversion)"
    )
    max_amount: float | None = Field(
        None, description="Inclusive upper bound on the raw amount in the invoice's own currency (no FX conversion)"
    )
    has_po: bool | None = Field(None, description="true = has a PO number, false = PO number missing")
    has_approver: bool | None = Field(None, description="true = has an approver, false = approver missing")
    approved_by: str | None = Field(None, description="Exact approver user ID, e.g. m.garcia")


# ---------- /ask ----------


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)


class PolicyEvidence(BaseModel):
    section: str
    text: str


class DataEvidence(BaseModel):
    tool: str
    args: dict[str, Any]
    total_matched: int
    truncated: bool
    rows: list[dict[str, Any]] | None = None
    groups: list[dict[str, Any]] | None = None


class AskResponse(BaseModel):
    status: Literal["answered", "declined"]
    answer: str
    route: list[Literal["policy", "data"]]
    policy_evidence: list[PolicyEvidence]
    data_evidence: list[DataEvidence]
    warnings: list[str]
    llm: str = Field(..., description="Which LLM path produced the answer, e.g. bedrock:<model>")


class ErrorResponse(BaseModel):
    error: str
    message: str


# ---------- /summary ----------


class CurrencyTotal(BaseModel):
    currency: str
    total: float
    count: int


class StatusCurrencyTotal(BaseModel):
    status: str
    currency: str
    total: float
    count: int


class ComplianceFlags(BaseModel):
    missing_po: int
    missing_approver: int
    non_active_vendor: int
    credit_notes: int


class SummaryResponse(BaseModel):
    invoice_count: int
    vendor_count: int
    date_from: date
    date_to: date
    spend_by_currency: list[CurrencyTotal]
    spend_by_vendor_status: list[StatusCurrencyTotal]
    compliance_flags: ComplianceFlags
    note: str
