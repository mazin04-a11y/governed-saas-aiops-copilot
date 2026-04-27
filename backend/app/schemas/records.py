from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class MetricIn(BaseModel):
    service_name: str = Field(min_length=1, max_length=120)
    cpu_usage: float = Field(ge=0, le=100)
    memory_usage: float = Field(ge=0, le=100)
    response_time_ms: int = Field(ge=0)
    error_rate: float = Field(ge=0, le=100)
    status: str = Field(default="healthy", max_length=50)


class AccessLogIn(BaseModel):
    username: str = Field(min_length=1, max_length=160)
    action: str = Field(min_length=1, max_length=80)
    ip_address: str = Field(min_length=1, max_length=80)
    outcome: str = Field(min_length=1, max_length=50)


class IncidentOut(BaseModel):
    id: int
    incident_type: str
    title: str
    severity: str
    status: str
    correlation_key: str
    description: str
    evidence_ids: list[int]
    occurrence_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OperationalRecommendation(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    rationale: str = Field(min_length=10)
    risk_level: Literal["low", "medium", "high"]
    requires_human_approval: bool

    @field_validator("requires_human_approval")
    @classmethod
    def high_risk_requires_approval(cls, value: bool, info):
        risk_level = info.data.get("risk_level")
        if risk_level == "high" and not value:
            raise ValueError("high-risk recommendations require human approval")
        return value


class OperationalReportPayload(BaseModel):
    incident_id: int
    executive_summary: str = Field(min_length=10)
    evidence_ids: list[int] = Field(min_length=1)
    root_cause_hypotheses: list[str] = Field(min_length=1)
    risk_assessment: str = Field(min_length=10)
    recommendations: list[OperationalRecommendation] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class ApprovalDecisionIn(BaseModel):
    status: Literal["approved", "rejected"]
    reviewer: str = Field(min_length=1, max_length=120)
    decision_reason: str = Field(min_length=1, max_length=500)


class ReportRequest(BaseModel):
    use_external_intel: bool = False


class IncidentStatusUpdate(BaseModel):
    status: Literal["open", "resolved"]
    actor: str = Field(default="operator", min_length=1, max_length=120)
    reason: str = Field(min_length=1, max_length=500)


class OperatorLoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=500)


class OperatorSessionOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    username: str
