"""Evidence is built by code from source data, never copied from LLM output."""

import re
from functools import lru_cache

from . import data
from .models import DataEvidence, PolicyEvidence

_SECTION = re.compile(r"^## (\d+)\. ")
_CLAUSE = re.compile(r"^(\d+\.\d+) ")


@lru_cache
def policy_sections() -> dict[str, str]:
    """Map section IDs to exact policy text: '3' is the whole section, '3.1' is one clause."""
    sections: dict[str, list[str]] = {}
    current_section = current_clause = None
    for line in data.policy_text().splitlines():
        if m := _SECTION.match(line):
            current_section, current_clause = m.group(1), None
            sections[current_section] = [line]
            continue
        if current_section is None:
            continue
        sections[current_section].append(line)
        if m := _CLAUSE.match(line):
            current_clause = m.group(1)
            sections[current_clause] = [line]
        elif current_clause and line.strip():
            sections[current_clause].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def check_citations(section_ids: list[str]) -> tuple[list[PolicyEvidence], list[str]]:
    """Keep only section IDs that exist in the policy file; report the rest as warnings."""
    known = policy_sections()
    evidence, rejected = [], []
    for raw in dict.fromkeys(section_ids):
        sid = raw.strip().lstrip("§").strip()
        if sid in known:
            evidence.append(PolicyEvidence(section=sid, text=known[sid]))
        else:
            rejected.append(raw)
    warnings = [f"LLM cited policy section(s) not found in the policy document and they were dropped: {', '.join(rejected)}"] if rejected else []
    return evidence, warnings


class EvidenceCollector:
    """Records every successful tool call, with the exact rows or groups the tool returned."""

    def __init__(self) -> None:
        self.items: list[DataEvidence] = []
        self.warnings: list[str] = []

    def record(self, tool: str, args: dict, result: dict) -> None:
        if tool == "query_invoices":
            item = DataEvidence(tool=tool, args=args, total_matched=result["total_matched"],
                                truncated=result["truncated"], rows=result["rows"])
            if result["truncated"]:
                self.warnings.append(f"query_invoices returned {result['returned']} of {result['total_matched']} matching invoices.")
            if any(r["is_credit_note"] for r in result["rows"]):
                self.warnings.append("Some returned invoices are credit notes (negative amounts, policy §6.1).")
        elif tool == "aggregate":
            item = DataEvidence(tool=tool, args=args, total_matched=result["total_invoices_matched"],
                                truncated=False, groups=result["groups"])
            currencies = {g["currency"] for g in result["groups"] if g["currency"]}
            if len(currencies) > 1:
                self.warnings.append("Amounts are reported per currency. No FX rates are available, so currencies are not added together.")
            if credit := sum(g["credit_note_count"] for g in result["groups"]):
                self.warnings.append(f"Totals include {credit} credit note(s) (negative amounts).")
        else:
            item = DataEvidence(tool=tool, args=args, total_matched=result["count"], truncated=False,
                                rows=result["vendors"])
        self.items.append(item)
