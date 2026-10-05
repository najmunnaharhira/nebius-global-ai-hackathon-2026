"""Data models shared by the API, the chain engine and the LLM layer."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

DocType = Literal["khatian", "deed", "mutation"]
Severity = Literal["high", "medium", "low"]


class Party(BaseModel):
    name: str
    father: Optional[str] = None
    # Fraction of the land this person owns (khatian owners only), e.g. 0.5
    share: Optional[float] = None


class Parcel(BaseModel):
    dag: str = Field(description="Dag (plot) number")
    area_decimal: float = Field(description="Area in decimals (shatangsho)")


class Document(BaseModel):
    id: str
    doc_type: DocType
    title: Optional[str] = None
    date: Optional[str] = Field(default=None, description="ISO date YYYY-MM-DD")
    mouza: Optional[str] = None
    khatian_no: Optional[str] = None
    deed_no: Optional[str] = None
    registry_office: Optional[str] = None
    # khatian: recorded owners; mutation: new owners in whose name it was mutated
    owners: list[Party] = []
    # deed only
    sellers: list[Party] = []
    buyers: list[Party] = []
    parcels: list[Parcel] = []
    source_file: Optional[str] = None
    extracted_by: Optional[str] = None
    notes: Optional[str] = None


class ProposedSale(BaseModel):
    seller: str
    dag: str
    area_decimal: float


class CaseInput(BaseModel):
    documents: list[Document]
    proposed: Optional[ProposedSale] = None
    language: Literal["en", "bn"] = "en"


class Flag(BaseModel):
    id: str
    code: str
    severity: Severity
    title: str
    detail: str
    doc_ids: list[str] = []
    people: list[str] = []
    explanation: Optional[str] = None  # filled by Nemotron 3 Ultra when available


class TimelineEvent(BaseModel):
    id: str
    date: Optional[str]
    kind: Literal["record", "sale", "mutation", "proposed"]
    label: str
    sellers: list[str] = []
    buyers: list[str] = []
    parcels: list[Parcel] = []
    doc_id: Optional[str] = None
    flag_ids: list[str] = []


class Holding(BaseModel):
    name: str
    dag: str
    area_decimal: float


class ChecklistItem(BaseModel):
    en: str
    bn: str
    priority: Literal["must", "should"] = "should"
    related_flag: Optional[str] = None


class TraceStep(BaseModel):
    step: str
    model: Optional[str] = None
    status: Literal["ok", "skipped", "error", "rules"]
    latency_ms: Optional[int] = None
    note: Optional[str] = None


class AnalysisResult(BaseModel):
    risk: Literal["low", "medium", "high"]
    flags: list[Flag]
    timeline: list[TimelineEvent]
    holdings: list[Holding]
    checklist: list[ChecklistItem]
    summary_en: str
    summary_bn: str
    trace: list[TraceStep]
    disclaimer: str = (
        "Dalil is a pre-check, not legal advice. Confirm every finding with a lawyer "
        "and the land office before paying anything."
    )
