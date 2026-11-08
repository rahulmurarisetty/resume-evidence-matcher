"""Streamlit screen for the resume evidence matcher.

It talks to the API over HTTP and keeps nothing itself.

    pip install -e ".[ui]"
    streamlit run ui/app.py

Set API_URL when the API isn't at http://localhost:8000.

The helpers above main() don't import Streamlit, so the tests can check them
against the real API without installing it.
"""

from __future__ import annotations

import os
import re
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


class ApiError(Exception):
    """An error the API reported, with its message for the person."""


def _check(response: httpx.Response) -> None:
    if response.is_success:
        return
    try:
        message = response.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        message = f"The API answered with status {response.status_code}."
    raise ApiError(message)


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


def _render_report(st: Any, analysis: dict[str, Any], extracted: dict[str, Any] | None) -> None:
    report = analysis["report"]
    profile = report.get("profile", {})

    for warning in [*report["warnings"], *profile.get("warnings", [])]:
        st.info(warning)

    st.subheader("Coverage")
    st.table(coverage_rows(report))
    if profile.get("total_years") is not None:
        st.write(f"Years of experience read from your role dates: about {profile['total_years']}.")
    st.caption(f"Matching: {report.get('matching_mode', 'exact')} ({report['pipeline_version']})")

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

    if extracted is not None:
        with st.expander("Text the app read from your resume"):
            for span in extracted["resume"]["spans"]:
                place = where(span["section"], span["page"])
                st.text(f"[{place}] {span['kind']}: {span['text']}")


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
                    st.session_state["analysis"] = create_analysis(
                        client, upload.name, data, job_text
                    )
                    st.session_state["extracted"] = extract_text(client, upload.name, data)
            except ApiError as exc:
                st.error(str(exc))
            except httpx.HTTPError:
                st.error(f"Couldn't reach the API at {API_URL}. Is it running?")

    if st.session_state.pop("deleted", False):
        st.success("Deleted. Nothing from that analysis is stored any more.")

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
            st.session_state.pop("extracted", None)
            st.session_state["deleted"] = True
            st.rerun()

    _render_report(st, analysis, st.session_state.get("extracted"))


if __name__ == "__main__":
    main()
