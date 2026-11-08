"""Streamlit screen for the resume evidence matcher.

It talks to the API over HTTP and keeps nothing itself. Next to each requirement
it shows rewrite suggestions to accept or reject and gap questions to answer, and
below the report a form to fix lines the app read wrongly, the list of changes and
a button that downloads the Word file.

    pip install -e ".[ui]"
    streamlit run ui/app.py

Set API_URL when the API isn't at http://localhost:8000.

The helpers above main() don't import Streamlit, so the tests can check them
against the real API without installing it.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from functools import partial
from typing import Any

import httpx

API_URL = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
TIMEOUT = httpx.Timeout(120.0, connect=5.0)

MIME_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
STATUS_LABELS = {
    "direct": "Proven",
    "partial": "Partly shown",
    "adjacent": "Related, please check",
    "gap": "Missing",
    "not_assessed": "Check it yourself",
}
PRIORITY_LABELS = {
    "required": "Required",
    "preferred": "Preferred",
    "context": "Job duties",
}
COVERAGE_COLUMNS = ["direct", "partial", "adjacent", "gap", "not_assessed"]


CHANGE_LABELS = {"correction": "Your correction", "rewrite": "Accepted rewrite"}
SUGGESTION_STATUSES = {"direct", "partial", "adjacent"}


class ApiError(Exception):
    """An error the API reported, with its message for the person and its code."""

    def __init__(self, message: str, code: str = "") -> None:
        super().__init__(message)
        self.code = code


def _check(response: httpx.Response) -> None:
    if response.is_success:
        return
    try:
        error = response.json()["error"]
        message, code = error["message"], error["code"]
    except (ValueError, KeyError, TypeError):
        message, code = f"The API answered with status {response.status_code}.", ""
    raise ApiError(message, code)


def _json(response: httpx.Response) -> Any:
    _check(response)
    return response.json()


def mime_type(file_name: str) -> str:
    return MIME_TYPES.get(file_name.rsplit(".", 1)[-1].lower(), "application/octet-stream")


def create_analysis(
    client: httpx.Client, file_name: str, data: bytes, job_description: str
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/analyses",
        files={"resume": (file_name, data, mime_type(file_name))},
        data={"job_description": job_description},
    )
    _check(response)
    body: dict[str, Any] = response.json()
    return body


def extract_text(client: httpx.Client, file_name: str, data: bytes) -> dict[str, Any]:
    response = client.post(
        "/api/v1/extract", files={"resume": (file_name, data, mime_type(file_name))}
    )
    _check(response)
    body: dict[str, Any] = response.json()
    return body


def delete_analysis(client: httpx.Client, analysis_id: str) -> None:
    _check(client.delete(f"/api/v1/analyses/{analysis_id}"))


def _url(analysis_id: str, path: str) -> str:
    return f"/api/v1/analyses/{analysis_id}/{path}"


def request_suggestions(
    client: httpx.Client, analysis_id: str, requirement_ids: list[str] | None = None
) -> dict[str, Any]:
    body = {"requirement_ids": requirement_ids} if requirement_ids is not None else None
    result: dict[str, Any] = _json(client.post(_url(analysis_id, "suggestions"), json=body))
    return result


def list_suggestions(client: httpx.Client, analysis_id: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = _json(client.get(_url(analysis_id, "suggestions")))[
        "suggestions"
    ]
    return result


def decide_suggestion(
    client: httpx.Client, analysis_id: str, suggestion_id: str, accept: bool
) -> dict[str, Any]:
    action = "accept" if accept else "reject"
    result: dict[str, Any] = _json(
        client.post(_url(analysis_id, f"suggestions/{suggestion_id}/{action}"))
    )
    return result


def list_spans(client: httpx.Client, analysis_id: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = _json(client.get(_url(analysis_id, "spans")))["spans"]
    return result


def correct_line(client: httpx.Client, analysis_id: str, span_id: str, text: str) -> dict[str, Any]:
    result: dict[str, Any] = _json(
        client.patch(_url(analysis_id, f"spans/{span_id}"), json={"text": text})
    )
    return result


def list_gap_questions(client: httpx.Client, analysis_id: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = _json(client.get(_url(analysis_id, "gap-questions")))[
        "questions"
    ]
    return result


def save_gap_answer(
    client: httpx.Client, analysis_id: str, requirement_id: str, answer: str
) -> dict[str, Any]:
    result: dict[str, Any] = _json(
        client.put(_url(analysis_id, f"gap-answers/{requirement_id}"), json={"answer": answer})
    )
    return result


def list_changes(client: httpx.Client, analysis_id: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = _json(client.get(_url(analysis_id, "export/changes")))["changes"]
    return result


def download_export(client: httpx.Client, analysis_id: str) -> bytes:
    response = client.get(_url(analysis_id, "export.docx"))
    _check(response)
    return response.content


def load_edits(client: httpx.Client, analysis_id: str) -> dict[str, Any]:
    """Everything the edit views show. Analyses made before v0.3 have no stored
    lines, so their lines, changes and export are left empty."""
    edits: dict[str, Any] = {
        "suggestions": list_suggestions(client, analysis_id),
        "questions": {q["requirement_id"]: q for q in list_gap_questions(client, analysis_id)},
        "spans": [],
        "changes": [],
        "lines_stored": True,
    }
    try:
        edits["spans"] = list_spans(client, analysis_id)
        edits["changes"] = list_changes(client, analysis_id)
    except ApiError as exc:
        if exc.code != "resume_not_stored":
            raise
        edits["lines_stored"] = False
    return edits


def can_suggest(match: dict[str, Any]) -> bool:
    """Rewrites are offered where the resume has evidence, and not for requirements
    that only ask for years."""
    requirement = match["requirement"]
    years_only = bool(requirement.get("min_years")) and not requirement["skills"]
    return match["status"] in SUGGESTION_STATUSES and not years_only


def suggestions_for(suggestions: list[dict[str, Any]], requirement_id: str) -> list[dict[str, Any]]:
    return [s for s in suggestions if s["requirement_id"] == requirement_id]


def change_rows(changes: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "Change": CHANGE_LABELS.get(c["kind"], c["kind"]),
            "Before": c["before"],
            "After": c["after"],
        }
        for c in changes
    ]


def coverage_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per priority that has requirements, with a count per status."""
    rows: list[dict[str, Any]] = []
    for priority, label in PRIORITY_LABELS.items():
        counts = report["coverage"].get(priority, {})
        if not counts.get("total"):
            continue
        row: dict[str, Any] = {"Requirements": label, "Total": counts["total"]}
        for status in COVERAGE_COLUMNS:
            row[STATUS_LABELS[status]] = counts.get(status, 0)
        rows.append(row)
    return rows


def where(section: str, page: int | None) -> str:
    place = section.replace("_", " ")
    return f"{place}, page {page}" if page else place


def exact_evidence(match: dict[str, Any]) -> list[tuple[str, str]]:
    """(quote, where) for each resume line that names a skill, without repeats."""
    seen: set[str] = set()
    lines: list[tuple[str, str]] = []
    for skill in match["skills"]:
        for evidence in skill["evidence"]:
            if evidence["span_id"] in seen:
                continue
            seen.add(evidence["span_id"])
            lines.append((evidence["text"], where(evidence["section"], evidence["page"])))
    return lines


def escape_markdown(text: str) -> str:
    """Resume text shown as Markdown: "$1.2M" must not turn into math, "*" into italics."""
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|$<>~])", r"\\\1", text)


def matches_by_priority(report: dict[str, Any]) -> list[tuple[str, list[dict[str, Any]]]]:
    groups: list[tuple[str, list[dict[str, Any]]]] = []
    for priority, label in PRIORITY_LABELS.items():
        items = [m for m in report["matches"] if m["requirement"]["priority"] == priority]
        if items:
            groups.append((label, items))
    return groups


# ---------------------------------------------------------------------------
# Screen
# ---------------------------------------------------------------------------


def _act(
    st: Any, analysis_id: str, action: Callable[[httpx.Client], object], note: str = ""
) -> None:
    """Run one API action, reload the edit views and redraw the screen. An action
    that returns text shows it as a notice."""
    try:
        with httpx.Client(base_url=API_URL, timeout=TIMEOUT) as client:
            result = action(client)
            st.session_state["edits"] = load_edits(client, analysis_id)
    except ApiError as exc:
        st.session_state["notice"] = ("error", str(exc))
    except httpx.HTTPError:
        st.session_state["notice"] = ("error", f"Couldn't reach the API at {API_URL}.")
    else:
        message = result if isinstance(result, str) else note
        if message:
            st.session_state["notice"] = ("info", message)
    st.rerun()


def _batch_note(batch: dict[str, Any]) -> str:
    made = len(batch["suggestions"])
    note = f"{made} new suggestion{'s' if made != 1 else ''}."
    if batch["rejected"]:
        note += f" {batch['rejected']} more were thrown away because they added facts."
    reasons = {s["message"] for s in batch["skipped"] if s["reason"] != "already_suggested"}
    return " ".join([note, *sorted(reasons)])


def _render_suggestions(
    st: Any, analysis_id: str, match: dict[str, Any], suggestions: list[dict[str, Any]]
) -> None:
    requirement_id = match["requirement"]["id"]
    for suggestion in suggestions_for(suggestions, requirement_id):
        with st.container(border=True):
            left, right = st.columns(2)
            left.caption("Your line")
            left.markdown(escape_markdown(suggestion["original"]))
            right.caption(f"Suggested rewrite ({suggestion['status']})")
            right.markdown(escape_markdown(suggestion["text"]))
            accept, reject = st.columns(2)
            sid = suggestion["id"]
            for column, label, accept_it in ((accept, "Accept", True), (reject, "Reject", False)):
                done = "accepted" if accept_it else "rejected"
                if suggestion["status"] != done and column.button(label, key=f"{label}-{sid}"):
                    _act(st, analysis_id, partial(_decide, analysis_id, sid, accept_it))
    if st.button("Suggest rewrites", key=f"suggest-{requirement_id}"):
        _act(st, analysis_id, partial(_suggest, analysis_id, requirement_id))


def _decide(analysis_id: str, suggestion_id: str, accept: bool, client: httpx.Client) -> None:
    decide_suggestion(client, analysis_id, suggestion_id, accept)


def _suggest(analysis_id: str, requirement_id: str, client: httpx.Client) -> str:
    return _batch_note(request_suggestions(client, analysis_id, [requirement_id]))


def _render_question(st: Any, analysis_id: str, question: dict[str, Any]) -> None:
    requirement_id = question["requirement_id"]
    st.markdown(f"Question: {escape_markdown(question['question'])}")
    with st.form(f"gap-{requirement_id}"):
        answer = st.text_area(
            "Your answer. It is kept with this analysis and never added to your resume.",
            value=question["answer"] or "",
            key=f"answer-{requirement_id}",
        )
        if st.form_submit_button("Save answer"):
            _act(
                st,
                analysis_id,
                partial(_answer, analysis_id, requirement_id, answer),
                note="Answer saved.",
            )


def _answer(analysis_id: str, requirement_id: str, answer: str, client: httpx.Client) -> None:
    save_gap_answer(client, analysis_id, requirement_id, answer)


def _render_corrections(st: Any, analysis_id: str, spans: list[dict[str, Any]]) -> None:
    with st.expander("Fix text the app read wrongly"):
        st.caption(
            "Corrections are your own words, so the fact checker doesn't check them. They "
            "show up as corrections, apart from rewrites, in the list of changes."
        )
        with st.form("corrections"):
            edited: dict[str, str] = {}
            for span in spans:
                label = f"{where(span['section'], span['page'])}, {span['kind']}"
                if span["source"] == "user_correction":
                    label += " (corrected)"
                edited[span["id"]] = st.text_input(label, value=span["text"], key=f"s-{span['id']}")
            if st.form_submit_button("Save corrections"):
                changed = {i: t for i, t in edited.items() if t.strip() and t != _text_of(spans, i)}

                def save(client: httpx.Client) -> str:
                    for span_id, text in changed.items():
                        correct_line(client, analysis_id, span_id, text)
                    return f"Saved {len(changed)} correction{'s' if len(changed) != 1 else ''}."

                _act(st, analysis_id, save)


def _text_of(spans: list[dict[str, Any]], span_id: str) -> str:
    return next(str(s["text"]) for s in spans if s["id"] == span_id)


def _render_export(st: Any, analysis_id: str, edits: dict[str, Any]) -> None:
    st.subheader("Your changes")
    rows = change_rows(edits["changes"])
    if rows:
        st.table(rows)
    else:
        st.write("No changes yet. Accept a rewrite or fix a line to see it here.")
    try:
        with httpx.Client(base_url=API_URL, timeout=TIMEOUT) as client:
            data = download_export(client, analysis_id)
    except (ApiError, httpx.HTTPError) as exc:
        st.error(f"The Word file couldn't be built: {exc}")
        return
    st.download_button(
        "Download Word file",
        data=data,
        file_name="resume.docx",
        mime=MIME_TYPES["docx"],
    )
    st.caption(
        "A plain single-column file: your lines in their original order, with your "
        "corrections and accepted rewrites. Your uploaded file is not changed or stored."
    )


def _render_report(st: Any, analysis: dict[str, Any], edits: dict[str, Any] | None) -> None:
    report = analysis["report"]
    profile = report.get("profile", {})
    analysis_id = analysis["id"]

    for warning in [*report["warnings"], *profile.get("warnings", [])]:
        st.info(warning)

    st.subheader("Coverage")
    st.table(coverage_rows(report))
    if profile.get("total_years") is not None:
        st.write(f"Years of experience read from your role dates: about {profile['total_years']}.")
    parser = report.get("job_parser", {}).get("name", "rules")
    st.caption(
        f"Matching: {report.get('matching_mode', 'exact')} ({report['pipeline_version']}). "
        f"Job description read by: {parser}."
    )

    for label, matches in matches_by_priority(report):
        st.subheader(label)
        for match in matches:
            with st.container(border=True):
                st.markdown(f"**{STATUS_LABELS.get(match['status'], match['status'])}**")
                st.markdown(escape_markdown(match["requirement"]["text"]))
                evidence = exact_evidence(match)
                if evidence:
                    st.markdown("Exact evidence:")
                    for quote, place in evidence:
                        st.markdown(f"> {escape_markdown(quote)}  \n> _{escape_markdown(place)}_")
                related = match.get("related_evidence", [])
                if related:
                    st.markdown("Related by meaning (confirm before you rely on it):")
                    for item in related:
                        place = where(item["section"], item["page"])
                        st.markdown(
                            f"> {escape_markdown(item['text'])}  \n"
                            f"> _{escape_markdown(place)}, score {item['score']:.2f}_"
                        )
                st.markdown(f"Next step: {escape_markdown(match['next_action'])}")
                if edits is None:
                    continue
                if can_suggest(match) and edits["lines_stored"]:
                    _render_suggestions(st, analysis_id, match, edits["suggestions"])
                question = edits["questions"].get(match["requirement"]["id"])
                if question is not None:
                    _render_question(st, analysis_id, question)

    if edits is None or not edits["lines_stored"]:
        return
    _render_corrections(st, analysis_id, edits["spans"])
    _render_export(st, analysis_id, edits)


def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="Resume evidence matcher")
    st.title("Resume evidence matcher")
    st.write(
        "Shows which lines of your resume support each requirement in a job description, "
        "and what to do about the rest. It never adds skills, dates or numbers you don't have."
    )

    with st.form("analyze"):
        upload = st.file_uploader("Resume (PDF or Word)", type=["pdf", "docx"])
        job_text = st.text_area("Job description", height=260)
        submitted = st.form_submit_button("Check my resume")

    if submitted:
        if upload is None or not job_text.strip():
            st.warning("Add a resume and paste the job description first.")
        else:
            data = upload.getvalue()
            try:
                with (
                    httpx.Client(base_url=API_URL, timeout=TIMEOUT) as client,
                    st.spinner("Reading the resume and the job description..."),
                ):
                    analysis = create_analysis(client, upload.name, data, job_text)
                    st.session_state["analysis"] = analysis
                    st.session_state["edits"] = load_edits(client, analysis["id"])
            except ApiError as exc:
                st.error(str(exc))
            except httpx.HTTPError:
                st.error(f"Couldn't reach the API at {API_URL}. Is it running?")

    if st.session_state.pop("deleted", False):
        st.success("Deleted. Nothing from that analysis is stored any more.")
    notice = st.session_state.pop("notice", None)
    if notice is not None:
        kind, message = notice
        (st.error if kind == "error" else st.info)(message)

    analysis = st.session_state.get("analysis")
    if analysis is None:
        return

    if st.button("Delete this analysis from the server"):
        try:
            with httpx.Client(base_url=API_URL, timeout=TIMEOUT) as client:
                delete_analysis(client, analysis["id"])
        except ApiError as exc:
            st.error(str(exc))
        except httpx.HTTPError:
            st.error(f"Couldn't reach the API at {API_URL}. Is it running?")
        else:
            st.session_state.pop("analysis", None)
            st.session_state.pop("edits", None)
            st.session_state["deleted"] = True
            st.rerun()

    _render_report(st, analysis, st.session_state.get("edits"))


if __name__ == "__main__":
    main()
