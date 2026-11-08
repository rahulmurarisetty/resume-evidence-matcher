"""The consent notice shown before an upload, and its version.

The notice is built from the server's settings, so it says what this server really
does: how long it keeps an analysis, whether uploads are scanned, and, only when
Claude is on, which text goes to Anthropic. CONSENT_VERSION names the wording; it
is stored with every analysis together with the time consent was given. Change the
version whenever the wording changes.
"""

from dataclasses import dataclass

from app.config import Settings

CONSENT_VERSION = "consent_v1"
CONSENT_REQUIRED = (
    "Tick the box that says you agree to how this analysis is stored, then send the form "
    "again (the API field is consent=true). Nothing was read or stored."
)
LLM_CONSENT_REQUIRED = (
    "This analysis was made without your consent for Claude to see your resume and job "
    "text, so rewrite suggestions are off for it. Run the analysis again with the Claude "
    "box ticked (the API field is llm_consent=true) to use them."
)


@dataclass(frozen=True)
class ConsentNotice:
    version: str
    points: list[str]
    checkbox: str
    llm_available: bool
    llm_points: list[str]
    llm_checkbox: str | None


def _hours(hours: int) -> str:
    return "1 hour" if hours == 1 else f"{hours} hours"


def consent_notice(settings: Settings, *, llm_available: bool, scanning: bool) -> ConsentNotice:
    points = [
        "What is stored: the lines the app reads from your resume, the report, and your "
        "corrections, accepted rewrites and answers. The file itself is read in memory and "
        "never stored.",
        f"It is deleted {_hours(settings.retention_hours)} after the analysis is made, or "
        "sooner when you delete the analysis or your account.",
        "Only your account can see your analyses.",
        "Every upload is scanned for malware before it is read."
        if scanning
        else "This server doesn't scan uploads for malware (SCANNER=off), so only upload a "
        "file you made yourself.",
    ]
    llm_points: list[str] = []
    llm_checkbox: str | None = None
    if llm_available:
        llm_points = [
            "If you also tick the Claude box, the job description is sent to Anthropic to "
            "be read, and when you ask for rewrites, each chosen requirement and the one "
            "resume bullet picked for it are sent too.",
            "Your whole resume, the file, your name and contact lines, your corrections and "
            "your answers are never sent. A bullet that names a person or an employer is "
            "sent as written.",
            "Without that box the rules read the job description and rewrite suggestions "
            "stay off for this analysis.",
        ]
        llm_checkbox = (
            "Claude may see my job description and, when I ask for rewrites, the bullets "
            "picked for them (optional)"
        )
    return ConsentNotice(
        version=CONSENT_VERSION,
        points=points,
        checkbox="I agree to this, and this is my own resume or I have the person's permission",
        llm_available=llm_available,
        llm_points=llm_points,
        llm_checkbox=llm_checkbox,
    )
