from datetime import datetime

from pydantic import BaseModel

from app.models import AnalysisReport, ResumeDocument


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class AnalysisResponse(BaseModel):
    id: str
    created_at: datetime
    expires_at: datetime
    report: AnalysisReport


class ExtractResponse(BaseModel):
    """The text the app read from the resume, so a user can check it before trusting
    any match."""

    resume: ResumeDocument


class HealthResponse(BaseModel):
    status: str
