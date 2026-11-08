import uuid
from collections.abc import Iterable
from datetime import datetime, timedelta

from sqlalchemy import Select, delete, func, select
from sqlalchemy.orm import Session

from app.models import AnalysisReport, FileType, ResumeDocument, SuggestionStatus
from app.storage.db import (
    CHILD_TABLES,
    AnalysisRecord,
    Base,
    CorrectionRecord,
    GapAnswerRecord,
    ResumeRecord,
    SuggestionRecord,
    SuggestionRunRecord,
    analysis_column,
    utcnow,
)


def aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes even for timezone-aware columns."""
    return value if value.tzinfo else value.replace(tzinfo=utcnow().tzinfo)


_aware = aware


class AnalysisRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # -- analyses -------------------------------------------------------------

    def create(
        self,
        report: AnalysisReport,
        owner_id: str,
        file_type: FileType,
        file_sha256: str,
        retention: timedelta,
        resume: ResumeDocument | None = None,
        *,
        consent_version: str | None = None,
        llm_consent: bool = False,
    ) -> AnalysisRecord:
        """Store an analysis. With `consent_version`, the consent time is now."""
        now = utcnow()
        record = AnalysisRecord(
            id=uuid.uuid4().hex,
            owner_id=owner_id,
            created_at=now,
            expires_at=now + retention,
            pipeline_version=report.pipeline_version,
            file_type=file_type.value,
            file_sha256=file_sha256,
            report_json=report.model_dump_json(),
            consent_at=now if consent_version is not None else None,
            consent_version=consent_version,
            llm_consent=llm_consent,
        )
        self.session.add(record)
        if resume is not None:
            # Flush the parent first so the foreign key holds on databases that check it.
            self.session.flush()
            stored = ResumeRecord(analysis_id=record.id, resume_json=resume.model_dump_json())
            self.session.add(stored)
        self.session.commit()
        return record

    def get(self, analysis_id: str, owner_id: str) -> AnalysisRecord | None:
        """The analysis, or None when it doesn't exist, has expired or belongs to
        someone else. Callers answer all three the same way (404)."""
        record = self.session.get(AnalysisRecord, analysis_id)
        if record is None or record.owner_id != owner_id:
            return None
        if _aware(record.expires_at) <= utcnow():
            return None
        record.created_at = _aware(record.created_at)
        record.expires_at = _aware(record.expires_at)
        if record.consent_at is not None:
            record.consent_at = _aware(record.consent_at)
        return record

    def list_for_owner(self, owner_id: str) -> list[AnalysisRecord]:
        """The owner's analyses that haven't expired, newest first."""
        rows = self.session.scalars(
            select(AnalysisRecord)
            .where(AnalysisRecord.owner_id == owner_id, AnalysisRecord.expires_at > utcnow())
            .order_by(AnalysisRecord.created_at.desc())
        )
        records = list(rows)
        for record in records:
            record.created_at = _aware(record.created_at)
            record.expires_at = _aware(record.expires_at)
        return records

    def delete(self, analysis_id: str, owner_id: str) -> bool:
        """Delete an analysis and everything stored with it, if `owner_id` owns it."""
        owned = select(AnalysisRecord.id).where(
            AnalysisRecord.id == analysis_id, AnalysisRecord.owner_id == owner_id
        )
        return self._delete_where(owned) > 0

    def delete_all_for_owner(self, owner_id: str, *, commit: bool = True) -> int:
        """Delete every analysis the owner has, with everything stored with them.
        With commit=False the caller commits, so this can be part of a larger delete."""
        owned = select(AnalysisRecord.id).where(AnalysisRecord.owner_id == owner_id)
        return self._delete_where(owned, commit=commit)

    def _delete_where(self, ids: Select[str], *, commit: bool = True) -> int:
        # Child rows first, so the delete holds on databases that check foreign keys.
        for table in CHILD_TABLES:
            self.session.execute(delete(table).where(analysis_column(table).in_(ids)))
        result = self.session.execute(delete(AnalysisRecord).where(AnalysisRecord.id.in_(ids)))
        if commit:
            self.session.commit()
        return int(result.rowcount)  # type: ignore[attr-defined]

    def purge_expired(self) -> int:
        return self._delete_where(
            select(AnalysisRecord.id).where(AnalysisRecord.expires_at <= utcnow())
        )

    def ping(self) -> None:
        self.session.execute(select(1))

    def count_rows(self, analysis_id: str) -> int:
        """Rows stored for an analysis across every table. Used to check deletion."""
        total = 0
        tables: tuple[type[Base], ...] = (AnalysisRecord, *CHILD_TABLES)
        for table in tables:
            query = select(func.count()).select_from(table)
            query = query.where(analysis_column(table) == analysis_id)
            total += int(self.session.scalar(query) or 0)
        return total

    # -- resume lines ---------------------------------------------------------

    def get_resume(self, analysis_id: str) -> ResumeDocument | None:
        """None for analyses made before v0.3, which didn't store their lines."""
        record = self.session.get(ResumeRecord, analysis_id)
        return ResumeDocument.model_validate_json(record.resume_json) if record else None

    def corrections(self, analysis_id: str) -> dict[str, CorrectionRecord]:
        rows = self.session.scalars(
            select(CorrectionRecord).where(CorrectionRecord.analysis_id == analysis_id)
        )
        return {row.span_id: row for row in rows}

    def set_correction(self, analysis_id: str, span_id: str, text: str | None) -> None:
        """Store a correction, or remove it when `text` is None."""
        record = self.session.get(CorrectionRecord, (analysis_id, span_id))
        if text is None:
            if record is not None:
                self.session.delete(record)
        elif record is None:
            self.session.add(
                CorrectionRecord(
                    analysis_id=analysis_id, span_id=span_id, text=text, updated_at=utcnow()
                )
            )
        else:
            record.text = text
            record.updated_at = utcnow()
        self.session.commit()

    # -- suggestions ----------------------------------------------------------

    def suggestions(self, analysis_id: str) -> list[SuggestionRecord]:
        rows = self.session.scalars(
            select(SuggestionRecord)
            .where(SuggestionRecord.analysis_id == analysis_id)
            .order_by(SuggestionRecord.created_at, SuggestionRecord.position)
        )
        return list(rows)

    def get_suggestion(self, analysis_id: str, suggestion_id: str) -> SuggestionRecord | None:
        record = self.session.get(SuggestionRecord, suggestion_id)
        if record is None or record.analysis_id != analysis_id:
            return None
        return record

    def add_suggestions(
        self, records: Iterable[SuggestionRecord], run: SuggestionRunRecord
    ) -> None:
        self.session.add_all(list(records))
        self.session.add(run)
        self.session.commit()

    def set_suggestion_status(self, record: SuggestionRecord, status: SuggestionStatus) -> None:
        record.status = status.value
        record.updated_at = utcnow()
        self.session.commit()

    def suggestion_usage(self, analysis_id: str) -> tuple[int, int]:
        """Rewrite candidates asked of Claude so far, and how many the fact checker
        rejected."""
        row = self.session.execute(
            select(
                func.coalesce(func.sum(SuggestionRunRecord.requested), 0),
                func.coalesce(func.sum(SuggestionRunRecord.rejected), 0),
            ).where(SuggestionRunRecord.analysis_id == analysis_id)
        ).one()
        return int(row[0]), int(row[1])

    # -- gap answers ----------------------------------------------------------

    def gap_answers(self, analysis_id: str) -> dict[str, GapAnswerRecord]:
        rows = self.session.scalars(
            select(GapAnswerRecord).where(GapAnswerRecord.analysis_id == analysis_id)
        )
        return {row.requirement_id: row for row in rows}

    def set_gap_answer(self, analysis_id: str, requirement_id: str, answer: str | None) -> None:
        record = self.session.get(GapAnswerRecord, (analysis_id, requirement_id))
        if answer is None:
            if record is not None:
                self.session.delete(record)
        elif record is None:
            self.session.add(
                GapAnswerRecord(
                    analysis_id=analysis_id,
                    requirement_id=requirement_id,
                    answer=answer,
                    updated_at=utcnow(),
                )
            )
        else:
            record.answer = answer
            record.updated_at = utcnow()
        self.session.commit()
