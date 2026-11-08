"""Streamlit screen for the resume evidence matcher.

It talks to the API over HTTP and keeps nothing itself. A person logs in or
creates an account first (unless the API runs with AUTH_MODE=disabled). Before an
upload it shows the consent notice from the API with a required box, and a second,
optional box for Claude when Claude is on. Next to each requirement it shows
rewrite suggestions to accept or reject and gap questions to answer, then the
section order advice, the terms noticed in the posting and questions about bullets
without a number, and below the report a form to fix lines the app read wrongly,
the list of changes and buttons that download the Word file and the match report.
The sidebar has Log out and "Delete my account and data".

Accessibility: every input has a visible label, statuses are written in words,
headings go h1, h2, h3 in order, nothing is shown by color alone, and an error is
written next to the input or button that caused it.

The session token lives only in st.session_state, which Streamlit keeps in the
server's memory for one browser tab. It is never put in a URL, a cookie or a log,
and closing the tab forgets it.

    pip install -e ".[ui]"
    streamlit run ui/app.py

Set API_URL when the API isn't at http://localhost:8000.

The helpers above main() don't import Streamlit, so the tests can check them
against the real API without installing it.
"""

from __future__ import annotations

import json
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
MIN_PASSWORD_LENGTH = 12
_MAX_FORWARDED = 2000
# What the screen keeps per browser tab. Logging out or deleting the account clears it.
SESSION_KEYS = (
    "token",
    "user",
    "analysis",
    "edits",
    "reports",
    "confirm_delete",
    "consent_notice",
)
EMPLOYER_SYSTEMS_NOTE = (
    "Employers use different applicant tracking systems and different criteria, so there "
    "is no universal ATS score, and this app doesn't produce one. It shows which of your "
    "lines support each requirement of this job description. It doesn't predict any "
    "employer's decision."
)
TERMS_NOTE = (
    "These lines describe how the job is contracted or who may apply. They aren't "
    "requirements and weren't used to score anything."
)
# Where an API error is shown: next to the input that caused it.
_JOB_ERRORS = {"job_description_too_short", "job_description_too_long"}
_FORM_ERRORS = {"rate_limited", "invalid_request"}


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


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


def forwarded_for(incoming: str | None, peer: str | None) -> str | None:
    """The X-Forwarded-For value to send: what reached the screen, plus the address
    that connected to it. The API reads it only from proxies in its
    TRUSTED_PROXIES, so per-address rate limits can count each visitor."""
    hops = [hop.strip() for hop in (incoming or "").split(",") if hop.strip()]
    if peer:
        hops.append(peer)
    value = ", ".join(hops)[-_MAX_FORWARDED:].lstrip(", ")
    return value or None


def api_client(token: str | None = None, forwarded: str | None = None) -> httpx.Client:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if forwarded:
        headers["X-Forwarded-For"] = forwarded
    return httpx.Client(base_url=API_URL, timeout=TIMEOUT, headers=headers)


def register(client: httpx.Client, email: str, password: str) -> str:
    """Create an account. The API answers the same whether or not the email was
    already in use, so this returns its message and nothing else."""
    body = {"email": email, "password": password}
    message: str = _json(client.post("/api/v1/auth/register", json=body))["message"]
    return message


def login(client: httpx.Client, email: str, password: str) -> dict[str, Any]:
    """Log in. Returns the token, its expiry and the account."""
    body = {"email": email, "password": password}
    result: dict[str, Any] = _json(client.post("/api/v1/auth/login", json=body))
    return result


def current_user(client: httpx.Client) -> dict[str, Any] | None:
    """The logged-in account, or None when the client has no valid session. With
    AUTH_MODE=disabled the API answers with its local account even without one."""
    response = client.get("/api/v1/auth/me")
    if response.status_code == 401:
        return None
    result: dict[str, Any] = _json(response)
    return result


def logout(client: httpx.Client) -> None:
    _check(client.post("/api/v1/auth/logout"))


def delete_account(client: httpx.Client) -> None:
    """Delete the account and everything it owns, at once."""
    _check(client.delete("/api/v1/auth/me"))


def consent_notice(client: httpx.Client) -> dict[str, Any]:
    """The notice to show before an upload, built by the API from its settings."""
    result: dict[str, Any] = _json(client.get("/api/v1/consent"))
    return result


def create_analysis(
    client: httpx.Client,
    file_name: str,
    data: bytes,
    job_description: str,
    *,
    consent: bool,
    llm_consent: bool = False,
) -> dict[str, Any]:
    """Send the resume and the job description. `consent` is the required box;
    `llm_consent` the optional one for Claude."""
    response = client.post(
        "/api/v1/analyses",
        files={"resume": (file_name, data, mime_type(file_name))},
        data={
            "job_description": job_description,
            "consent": "true" if consent else "false",
            "llm_consent": "true" if llm_consent else "false",
        },
    )
    _check(response)
    body: dict[str, Any] = response.json()
    return body


def error_place(code: str) -> str:
    """Which input an analysis error belongs next to: "job", "consent", "form" (the
    button) or "file"."""
    if code in _JOB_ERRORS:
        return "job"
    if code == "consent_required":
        return "consent"
    if code in _FORM_ERRORS or not code:
        return "form"
    return "file"


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


def download_report(client: httpx.Client, analysis_id: str, kind: str) -> bytes:
    """The match report: kind "html" or "md"."""
    response = client.get(_url(analysis_id, f"report.{kind}"))
    _check(response)
    return response.content


def load_edits(client: httpx.Client, analysis_id: str) -> dict[str, Any]:
    """Everything the edit views show. Analyses made before v0.3 have no stored
    lines, so their lines, changes and export are left empty."""
    questions = list_gap_questions(client, analysis_id)
    edits: dict[str, Any] = {
        "suggestions": list_suggestions(client, analysis_id),
        "questions": {q["requirement_id"]: q for q in questions if q["kind"] == "gap"},
        "metric_questions": [q for q in questions if q["kind"] == "metric"],
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


def export_key(analysis_id: str, changes: list[dict[str, Any]]) -> str:
    """Identifies the Word file's content: the analysis and its list of changes."""
    return json.dumps([analysis_id, changes], sort_keys=True)


def change_rows(changes: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "Change": CHANGE_LABELS.get(c["kind"], c["kind"]),
            "Before": c["before"],
            "After": c["after"],
        }
        for c in changes
    ]


def status_text(status: str) -> str:
    """A status in words, with its label, so it never depends on color or bold."""
    return f"Status: {STATUS_LABELS.get(status, status.replace('_', ' '))}"


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


def _client(st: Any) -> httpx.Client:
    """A client with this tab's session token and the visitor's address."""
    context = getattr(st, "context", None)
    headers = getattr(context, "headers", None)
    incoming = headers.get("X-Forwarded-For") if headers is not None else None
    peer = getattr(context, "ip_address", None)
    forwarded = forwarded_for(
        incoming if isinstance(incoming, str) else None, peer if isinstance(peer, str) else None
    )
    return api_client(st.session_state.get("token"), forwarded)


def _clear(st: Any) -> None:
    for key in SESSION_KEYS:
        st.session_state.pop(key, None)


def _session_ended(st: Any, exc: ApiError) -> bool:
    """When the API no longer accepts the token (it expired, or the person logged
    out elsewhere), forget it and go back to the login screen."""
    if exc.code != "not_authenticated":
        return False
    _clear(st)
    st.session_state["notice"] = ("error", "Your session ended. Log in again.", "top")
    return True


def _act(
    st: Any,
    analysis_id: str,
    action: Callable[[httpx.Client], object],
    note: str = "",
    where: str = "top",
) -> None:
    """Run one API action, reload the edit views and redraw the screen. An action
    that returns text shows it as a notice. The notice, or the error, is shown at
    `where`: next to the button or form that ran the action."""
    try:
        with _client(st) as client:
            result = action(client)
            st.session_state["edits"] = load_edits(client, analysis_id)
    except ApiError as exc:
        if not _session_ended(st, exc):
            st.session_state["notice"] = ("error", str(exc), where)
    except httpx.HTTPError:
        st.session_state["notice"] = ("error", f"Couldn't reach the API at {API_URL}.", where)
    else:
        message = result if isinstance(result, str) else note
        if message:
            st.session_state["notice"] = ("info", message, where)
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
            right.caption(f"Suggested rewrite, {suggestion['status']}")
            right.markdown(escape_markdown(suggestion["text"]))
            accept, reject = st.columns(2)
            sid = suggestion["id"]
            for column, label, accept_it in ((accept, "Accept", True), (reject, "Reject", False)):
                done = "accepted" if accept_it else "rejected"
                if suggestion["status"] != done and column.button(label, key=f"{label}-{sid}"):
                    _act(
                        st,
                        analysis_id,
                        partial(_decide, analysis_id, sid, accept_it),
                        where=f"req-{requirement_id}",
                    )
    if st.button("Suggest rewrites", key=f"suggest-{requirement_id}"):
        _act(
            st,
            analysis_id,
            partial(_suggest, analysis_id, requirement_id),
            where=f"req-{requirement_id}",
        )


def _decide(analysis_id: str, suggestion_id: str, accept: bool, client: httpx.Client) -> None:
    decide_suggestion(client, analysis_id, suggestion_id, accept)


def _suggest(analysis_id: str, requirement_id: str, client: httpx.Client) -> str:
    return _batch_note(request_suggestions(client, analysis_id, [requirement_id]))


def _render_question(st: Any, analysis_id: str, question: dict[str, Any]) -> None:
    question_id = question["id"]
    st.markdown(f"Question: {escape_markdown(question['question'])}")
    with st.form(f"gap-{question_id}"):
        answer = st.text_area(
            "Your answer. It is kept with this analysis and never added to your resume.",
            value=question["answer"] or "",
            key=f"answer-{question_id}",
        )
        if st.form_submit_button("Save answer"):
            _act(
                st,
                analysis_id,
                partial(_answer, analysis_id, question_id, answer),
                note="Answer saved.",
                where=f"q-{question_id}",
            )
    _show_notice(st, f"q-{question_id}")


def _answer(analysis_id: str, question_id: str, answer: str, client: httpx.Client) -> None:
    save_gap_answer(client, analysis_id, question_id, answer)


def _render_corrections(st: Any, analysis_id: str, spans: list[dict[str, Any]]) -> None:
    st.subheader("Fix text the app read wrongly")
    with st.expander("Show every line the app read, to correct it"):
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

                _act(st, analysis_id, save, where="corrections")
        _show_notice(st, "corrections")


def _text_of(spans: list[dict[str, Any]], span_id: str) -> str:
    return next(str(s["text"]) for s in spans if s["id"] == span_id)


def _cached_download(
    st: Any, key: str, fetch: Callable[[httpx.Client], bytes], what: str
) -> bytes | None:
    """A download the API counts against the export limit, fetched again only when
    `key` changes. On an error, says so where the button would be."""
    cache: dict[str, tuple[str, bytes]] = st.session_state.setdefault("reports", {})
    cached = cache.get(what)
    if cached is not None and cached[0] == key:
        return cached[1]
    try:
        with _client(st) as client:
            data = fetch(client)
    except ApiError as exc:
        if not _session_ended(st, exc):
            st.error(f"The {what} couldn't be built: {exc}")
        return None
    except httpx.HTTPError as exc:
        st.error(f"The {what} couldn't be built: {exc}")
        return None
    cache[what] = (key, data)
    return data


def _render_export(st: Any, analysis_id: str, edits: dict[str, Any]) -> None:
    st.subheader("Your changes")
    rows = change_rows(edits["changes"])
    if rows:
        st.table(rows)
    else:
        st.write("No changes yet. Accept a rewrite or fix a line to see it here.")
    st.subheader("Downloads")
    # Downloads count against the API's export limit, so a file is fetched again
    # only when the changes (or, for the report, the answers too) differ.
    key = export_key(analysis_id, edits["changes"])
    data = _cached_download(st, key, partial(download_export, analysis_id=analysis_id), "Word file")
    if data is not None:
        st.download_button(
            "Download Word file", data=data, file_name="resume.docx", mime=MIME_TYPES["docx"]
        )
        st.caption(
            "A plain single-column file: your lines in their original order, with your "
            "corrections and accepted rewrites. Your uploaded file is not changed or stored."
        )
    answers = [
        (q["id"], q["answer"])
        for q in [*edits["questions"].values(), *edits.get("metric_questions", [])]
    ]
    report_key = json.dumps([key, answers], sort_keys=True)
    for kind, label, mime in (
        ("html", "Download match report (HTML)", "text/html"),
        ("md", "Download match report (Markdown)", "text/markdown"),
    ):
        report = _cached_download(
            st,
            report_key,
            partial(_report_file, analysis_id=analysis_id, kind=kind),
            f"match report ({kind})",
        )
        if report is not None:
            st.download_button(
                label, data=report, file_name=f"match-report.{kind}", mime=mime, key=f"dl-{kind}"
            )
    st.caption(
        "The match report lists every requirement with its status in words, the lines that "
        "support it, the next step, your questions and answers, and the advice below. It "
        "needs no internet connection to open."
    )


def _report_file(client: httpx.Client, *, analysis_id: str, kind: str) -> bytes:
    return download_report(client, analysis_id, kind)


def _render_requirement(
    st: Any, analysis_id: str, match: dict[str, Any], edits: dict[str, Any] | None
) -> None:
    with st.container(border=True):
        st.markdown(escape_markdown(status_text(match["status"])))
        st.markdown(f"Requirement: {escape_markdown(match['requirement']['text'])}")
        evidence = exact_evidence(match)
        if evidence:
            st.markdown("Exact evidence:")
            for quote, place in evidence:
                st.markdown(f"> {escape_markdown(quote)}  \n> {escape_markdown(place)}")
        related = match.get("related_evidence", [])
        if related:
            st.markdown("Related by meaning (confirm before you rely on it):")
            for item in related:
                place = where(item["section"], item["page"])
                st.markdown(
                    f"> {escape_markdown(item['text'])}  \n"
                    f"> {escape_markdown(place)}, score {item['score']:.2f}"
                )
        st.markdown(f"Next step: {escape_markdown(match['next_action'])}")
        if edits is None:
            return
        requirement_id = match["requirement"]["id"]
        if can_suggest(match) and edits["lines_stored"]:
            _render_suggestions(st, analysis_id, match, edits["suggestions"])
        _show_notice(st, f"req-{requirement_id}")
        question = edits["questions"].get(requirement_id)
        if question is not None:
            _render_question(st, analysis_id, question)


def _render_report(st: Any, analysis: dict[str, Any], edits: dict[str, Any] | None) -> None:
    report = analysis["report"]
    profile = report.get("profile", {})
    analysis_id = analysis["id"]

    st.header("Results")
    st.info(EMPLOYER_SYSTEMS_NOTE)
    for warning in [*report["warnings"], *profile.get("warnings", [])]:
        st.warning(f"Warning: {warning}")

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
            _render_requirement(st, analysis_id, match, edits)

    st.subheader("Section order advice")
    advice = report.get("section_advice", [])
    if advice:
        st.caption("Advice only. Nothing in your resume is moved unless you move it.")
        for item in advice:
            st.markdown(f"- {escape_markdown(item['message'])}")
    else:
        st.write("No advice about the order of your lines or sections.")

    terms = report.get("job", {}).get("employment_terms", [])
    if terms:
        st.subheader("Terms noticed in the posting")
        st.caption(TERMS_NOTE)
        for term in terms:
            st.markdown(f"- {escape_markdown(term)}")

    if edits is not None and edits.get("metric_questions"):
        st.subheader("Bullets without a number")
        st.caption(
            "Add a number only if you know it. Your answers are kept with this analysis and "
            "never added to your resume."
        )
        for question in edits["metric_questions"]:
            _render_question(st, analysis_id, question)

    if edits is None or not edits["lines_stored"]:
        return
    _render_corrections(st, analysis_id, edits["spans"])
    _render_export(st, analysis_id, edits)


def _unreachable(st: Any) -> None:
    st.error(f"Couldn't reach the API at {API_URL}. Is it running?")


def _signed_in_user(st: Any) -> dict[str, Any] | None:
    """The account this tab works as, or None when the person has to log in. With
    AUTH_MODE=disabled the API names its local account and no login is needed."""
    user: dict[str, Any] | None = st.session_state.get("user")
    if user is not None:
        return user
    if st.session_state.get("token") is None:
        try:
            with _client(st) as client:
                user = current_user(client)
        except (ApiError, httpx.HTTPError):
            _unreachable(st)
            return None
        if user is not None and user.get("auth_mode") == "disabled":
            st.session_state["user"] = user
            return user
    return None


def _start_session(st: Any, result: dict[str, Any]) -> None:
    st.session_state["token"] = result["token"]
    st.session_state["user"] = result["user"]
    st.rerun()


def _render_login(st: Any) -> None:
    st.caption(
        "Log in to see your analyses. Each one is kept for 24 hours unless you delete it "
        "sooner, and nobody else can see it."
    )
    log_in, create = st.tabs(["Log in", "Create account"])
    with log_in, st.form("login"):
        email = st.text_input("Email", key="login-email")
        password = st.text_input("Password", type="password", key="login-password")
        if st.form_submit_button("Log in"):
            try:
                with _client(st) as client:
                    result = login(client, email, password)
            except ApiError as exc:
                st.error(str(exc))
            except httpx.HTTPError:
                _unreachable(st)
            else:
                _start_session(st, result)
    with create, st.form("register"):
        email = st.text_input("Email", key="register-email")
        password = st.text_input(
            f"Password (at least {MIN_PASSWORD_LENGTH} characters)",
            type="password",
            key="register-password",
        )
        again = st.text_input("Same password again", type="password", key="register-again")
        st.caption(
            "No email is sent: there is no address check and no reset link yet. Keep the "
            "password somewhere safe."
        )
        if st.form_submit_button("Create account"):
            if password != again:
                st.error("The two passwords differ.")
                return
            message = ""
            try:
                with _client(st) as client:
                    message = register(client, email, password)
                    result = login(client, email, password)
            except ApiError as exc:
                # The API answers registration the same way for a new and a used
                # email, so a failed login afterwards is shown with that answer.
                st.error(str(exc) if exc.code != "invalid_credentials" else message)
            except httpx.HTTPError:
                _unreachable(st)
            else:
                _start_session(st, result)


def _render_account(st: Any, user: dict[str, Any]) -> None:
    """The sidebar: who is logged in, Log out, and deleting the account."""
    sidebar = st.sidebar
    disabled = user.get("auth_mode") == "disabled"
    if disabled:
        sidebar.caption("Accounts are off on this server: everything belongs to one local user.")
    else:
        sidebar.write(f"Logged in as {user['email']}")
        if sidebar.button("Log out", key="logout"):
            try:
                with _client(st) as client:
                    logout(client)
            except ApiError as exc:
                if not _session_ended(st, exc):
                    sidebar.error(str(exc))
                    return
            except httpx.HTTPError:
                _unreachable(st)
                return
            _clear(st)
            st.session_state["notice"] = ("info", "Logged out.", "top")
            st.rerun()

    if not st.session_state.get("confirm_delete"):
        if sidebar.button("Delete my account and data", key="delete-account"):
            st.session_state["confirm_delete"] = True
            st.rerun()
        return
    sidebar.warning(
        "This deletes your account and every analysis, suggestion, correction and answer "
        "it owns, right now. It can't be undone."
    )
    confirm, cancel = sidebar.columns(2)
    if cancel.button("Cancel", key="delete-cancel"):
        st.session_state.pop("confirm_delete", None)
        st.rerun()
    if confirm.button("Yes, delete everything", key="delete-confirm", type="primary"):
        try:
            with _client(st) as client:
                delete_account(client)
        except ApiError as exc:
            if not _session_ended(st, exc):
                sidebar.error(str(exc))
            return
        except httpx.HTTPError:
            _unreachable(st)
            return
        _clear(st)
        st.session_state["notice"] = (
            "info",
            "Your account and all of its data were deleted."
            if not disabled
            else "All of the local account's data was deleted.",
            "top",
        )
        st.rerun()


def _show_notice(st: Any, where: str = "top") -> None:
    """Show the notice meant for this place on the screen, once."""
    notice = st.session_state.get("notice")
    if notice is None:
        return
    kind, message, place = notice if len(notice) == 3 else (*notice, "top")
    if place != where:
        return
    st.session_state.pop("notice", None)
    (st.error if kind == "error" else st.info)(message)


def _consent(st: Any) -> dict[str, Any] | None:
    """The API's consent notice, fetched once per tab."""
    notice: dict[str, Any] | None = st.session_state.get("consent_notice")
    if notice is not None:
        return notice
    try:
        with _client(st) as client:
            notice = consent_notice(client)
    except ApiError as exc:
        if _session_ended(st, exc):
            st.rerun()
        st.error(f"The consent notice couldn't be loaded: {exc}")
        return None
    except httpx.HTTPError:
        _unreachable(st)
        return None
    st.session_state["consent_notice"] = notice
    return notice


def _render_upload(st: Any) -> None:
    """The consent notice, the two boxes and the upload form. Each error is written
    next to the input it is about."""
    notice = _consent(st)
    if notice is None:
        return
    st.header("Check your resume against a job")
    with st.form("analyze"):
        st.markdown("Before you upload:")
        for point in notice["points"]:
            st.markdown(f"- {escape_markdown(point)}")
        consent = st.checkbox(notice["checkbox"], key="consent")
        consent_error = st.empty()
        llm_consent = False
        if notice["llm_available"]:
            st.markdown("Claude, optional:")
            for point in notice["llm_points"]:
                st.markdown(f"- {escape_markdown(point)}")
            llm_consent = st.checkbox(notice["llm_checkbox"], key="llm-consent")
        upload = st.file_uploader("Resume (PDF or Word)", type=["pdf", "docx"])
        file_error = st.empty()
        job_text = st.text_area("Job description", height=260)
        job_error = st.empty()
        submitted = st.form_submit_button("Check my resume")
        form_error = st.empty()
    places = {"consent": consent_error, "file": file_error, "job": job_error, "form": form_error}

    if not submitted:
        return
    problems = {
        "consent": "Tick the box above to agree before the resume is read." if not consent else "",
        "file": "Choose a PDF or Word file." if upload is None else "",
        "job": "Paste the job description." if not job_text.strip() else "",
    }
    if any(problems.values()):
        for place, message in problems.items():
            if message:
                places[place].error(message)
        return
    assert upload is not None
    try:
        with (
            _client(st) as client,
            st.spinner("Reading the resume and the job description..."),
        ):
            analysis = create_analysis(
                client,
                upload.name,
                upload.getvalue(),
                job_text,
                consent=consent,
                llm_consent=llm_consent,
            )
            st.session_state["analysis"] = analysis
            st.session_state["edits"] = load_edits(client, analysis["id"])
            st.session_state.pop("reports", None)
    except ApiError as exc:
        if _session_ended(st, exc):
            st.rerun()
        places[error_place(exc.code)].error(str(exc))
    except httpx.HTTPError:
        form_error.error(f"Couldn't reach the API at {API_URL}. Is it running?")


def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="Resume evidence matcher")
    st.title("Resume evidence matcher")
    st.write(
        "Shows which lines of your resume support each requirement in a job description, "
        "and what to do about the rest. It never adds skills, dates or numbers you don't have."
    )

    user = _signed_in_user(st)
    if user is None:
        _show_notice(st)
        _render_login(st)
        return
    _render_account(st, user)
    _render_upload(st)

    if st.session_state.pop("deleted", False):
        st.success("Deleted. Nothing from that analysis is stored any more.")
    _show_notice(st)

    analysis = st.session_state.get("analysis")
    if analysis is None:
        return

    if st.button("Delete this analysis from the server"):
        try:
            with _client(st) as client:
                delete_analysis(client, analysis["id"])
        except ApiError as exc:
            if _session_ended(st, exc):
                st.rerun()
            st.error(str(exc))
        except httpx.HTTPError:
            _unreachable(st)
        else:
            for key in ("analysis", "edits", "reports"):
                st.session_state.pop(key, None)
            st.session_state["deleted"] = True
            st.rerun()

    _render_report(st, analysis, st.session_state.get("edits"))


if __name__ == "__main__":
    main()
