import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import AnalysisReport, FileType
from app.storage.db import AnalysisRecord, utcnow


def _aware(value: datetime) -> datetime:
    # SQLite returns naive datetimes even for timezone-aware columns.
    return value if value.tzinfo else value.replace(tzinfo=utcnow().tzinfo)


class AnalysisRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        report: AnalysisReport,
        file_type: FileType,
        file_sha256: str,
        retention: timedelta,
    ) -> AnalysisRecord:
        now = utcnow()
        record = AnalysisRecord(
            id=uuid.uuid4().hex,
            created_at=now,
            expires_at=now + retention,
            pipeline_version=report.pipeline_version,
            file_type=file_type.value,
            file_sha256=file_sha256,
            report_json=report.model_dump_json(),
        )
        self.session.add(record)
        self.session.commit()
        return record

    def get(self, analysis_id: str) -> AnalysisRecord | None:
        record = self.session.get(AnalysisRecord, analysis_id)
        if record is None or _aware(record.expires_at) <= utcnow():
            return None
        record.created_at = _aware(record.created_at)
        record.expires_at = _aware(record.expires_at)
        return record

    def delete(self, analysis_id: str) -> bool:
        result = self.session.execute(
            delete(AnalysisRecord).where(AnalysisRecord.id == analysis_id)
        )
        self.session.commit()
        return bool(result.rowcount)  # type: ignore[attr-defined]

    def purge_expired(self) -> int:
        result = self.session.execute(
            delete(AnalysisRecord).where(AnalysisRecord.expires_at <= utcnow())
        )
        self.session.commit()
        return int(result.rowcount)  # type: ignore[attr-defined]

    def ping(self) -> None:
        self.session.execute(select(1))
