from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ErrorCode(StrEnum):
    BROWSER_PROFILE_IN_USE = "BROWSER_PROFILE_IN_USE"
    BROWSER_NAVIGATION_FAILED = "BROWSER_NAVIGATION_FAILED"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    REAUTH_REQUIRED = "REAUTH_REQUIRED"
    LOCALIZER_NOT_FOUND = "LOCALIZER_NOT_FOUND"
    PROCESS_NOT_FOUND = "PROCESS_NOT_FOUND"
    REQUISITION_NOT_FOUND = "REQUISITION_NOT_FOUND"
    DOCUMENT_NOT_FOUND = "DOCUMENT_NOT_FOUND"
    MULTIPLE_DOCUMENTS = "MULTIPLE_DOCUMENTS"
    DOWNLOAD_FAILED = "DOWNLOAD_FAILED"
    PDF_PARSE_FAILED = "PDF_PARSE_FAILED"
    OCR_FAILED = "OCR_FAILED"
    FIELD_NOT_FOUND = "FIELD_NOT_FOUND"
    FIELD_AMBIGUOUS = "FIELD_AMBIGUOUS"
    UI_CHANGED = "UI_CHANGED"
    TIMEOUT = "TIMEOUT"
    HTTP_ERROR = "HTTP_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    CONFLICTING_SOURCES = "CONFLICTING_SOURCES"
    NOT_VERIFIABLE = "NOT_VERIFIABLE"
    WORKER_CRASHED = "WORKER_CRASHED"
    IPC_ERROR = "IPC_ERROR"
    DATABASE_ERROR = "DATABASE_ERROR"
    DISCOVERY_REQUIRED = "DISCOVERY_REQUIRED"
    SNAPSHOT_CHANGED = "SNAPSHOT_CHANGED"
    SESSION_SCOPE_CHANGED = "SESSION_SCOPE_CHANGED"


class AlmaError(Exception):
    def __init__(self, code: ErrorCode, stage: str, retryable: bool = False):
        self.code, self.stage, self.retryable = code, stage, retryable
        # Exception text intentionally excludes URLs, DOM and third-party errors.
        super().__init__(code.value)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Command(StrictModel):
    version: Literal[1]
    id: str
    type: Literal["COMMAND"]
    name: str
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        UUID(value)
        return value


class SessionState(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    AUTHENTICATED = "AUTHENTICATED"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    REAUTH_REQUIRED = "REAUTH_REQUIRED"
    ERROR = "ERROR"


class FieldValue(StrictModel):
    raw: str | None = None
    normalized: str | bool | None = None
    presence: Literal["present", "missing", "not_applicable", "unknown"] = "unknown"


class Requisition(StrictModel):
    fields: dict[str, FieldValue]


class Beneficiary(StrictModel):
    id: str
    fields: dict[str, FieldValue]


class Fee(StrictModel):
    id: str
    fields: dict[str, FieldValue]


class RpvSnapshot(StrictModel):
    process_id: str
    requisition_id: str
    requisition: Requisition
    beneficiaries: list[Beneficiary] = Field(default_factory=list)
    fees: list[Fee] = Field(default_factory=list)
    captured_at: str
    coverage: dict[str, Literal["read", "unknown", "not_applicable"]] = Field(
        default_factory=lambda: {"requisition": "unknown", "beneficiaries": "unknown", "fees": "unknown"})


class Evidence(StrictModel):
    process_id: str
    requisition_id: str
    document_id: str
    document_name: str
    event: str | None
    page: int | None = Field(default=None, ge=1)
    html_location: str | None = None
    raw_text: str
    bbox: list[float] | None = None  # Geometry only; never monetary values.
    normalized_value: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extracted_at: str


class ExtractedFact(StrictModel):
    field: str
    subject_id: str | None = None
    scope_verified: bool = False
    value_raw: str
    value_normalized: str
    source: Evidence
    confidence: Literal["EXACT_TEXT", "STRUCTURED_TABLE", "REGEX_MATCH", "OCR_HIGH", "OCR_LOW"]
