from pydantic import BaseModel, field_validator
from typing import Optional
from enum import Enum


class Severity(str, Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class Finding(BaseModel):
    id: str
    category: str = "general"
    title: str
    detail: str = ""
    severity: Severity = Severity.medium
    impact: int = 5
    effort: int = 5
    affected_urls: list[str] = []
    recommendation: str = ""

    @field_validator("severity", mode="before")
    @classmethod
    def normalise_severity(cls, v):
        if isinstance(v, str):
            v = v.lower().strip()
            if v not in ("critical", "high", "medium", "low"):
                return "medium"
        return v

    @field_validator("impact", "effort", mode="before")
    @classmethod
    def clamp_score(cls, v):
        try:
            return max(1, min(10, int(v)))
        except (TypeError, ValueError):
            return 5


class AuditDomain(BaseModel):
    name: str
    status: str          # running | done | error
    score: Optional[int] = None
    findings_count: int = 0
    findings: list[Finding] = []
    error: Optional[str] = None


class AuditReport(BaseModel):
    session_id: str
    url: str
    platform: str
    audited_at: str
    overall_score: int
    domains: dict[str, AuditDomain]
    all_findings: list[Finding] = []


class Task(BaseModel):
    id: str
    week: int
    title: str
    description: str
    platform_action: str
    impact: int
    effort: int
    priority_score: float
    estimated_minutes: int
    target_url: Optional[str] = None
    status: str = "pending"


class Plan(BaseModel):
    session_id: str
    url: str
    platform: str
    generated_at: str
    tasks: list[Task]


class PreviewTaskRequest(BaseModel):
    task_id: str
    wp_url: Optional[str] = None
    wp_username: Optional[str] = None
    wp_app_password: Optional[str] = None


class TaskPreview(BaseModel):
    task_id: str
    action: str
    target_url: str
    summary: str                  # one-line "what will happen"
    current: dict                 # current live values (meta_title, meta_desc, etc.)
    suggested: dict               # Claude's proposed new values
    needs_credentials: bool = False


class ExecuteTaskRequest(BaseModel):
    task_id: str
    wp_url: Optional[str] = None
    wp_username: Optional[str] = None
    wp_app_password: Optional[str] = None
    skip: bool = False
    approved_content: Optional[dict] = None   # user-edited version of suggested content


class TaskResult(BaseModel):
    task_id: str
    status: str          # completed | failed | skipped
    action_taken: str
    verified: bool = False
    error: Optional[str] = None
