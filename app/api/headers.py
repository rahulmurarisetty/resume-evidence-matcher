"""Security headers on every response, and the API docs page with its own policy.

API responses are JSON and never need to load anything, so their
Content-Security-Policy allows nothing. The docs page (Swagger UI) loads its
script and styles from jsdelivr and runs one inline script, which the policy
allows by its SHA-256 hash rather than with 'unsafe-inline'.
"""

import base64
import hashlib
import re

from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse
from starlette.datastructures import MutableHeaders

JSON_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
HSTS = "max-age=31536000; includeSubDomains"
_CDN = "https://cdn.jsdelivr.net"
_INLINE_SCRIPT_RE = re.compile(r"<script>(.*?)</script>", re.DOTALL)
DOCS_PATH = "/docs"


def apply_security_headers(headers: MutableHeaders, path: str, *, production: bool) -> None:
    """Set the headers every response carries. A route that sets its own
    Content-Security-Policy (the docs page) keeps it."""
    headers["X-Content-Type-Options"] = "nosniff"
    headers["X-Frame-Options"] = "DENY"
    headers["Referrer-Policy"] = "no-referrer"
    headers["Cross-Origin-Opener-Policy"] = "same-origin"
    headers.setdefault("Content-Security-Policy", JSON_CSP)
    if path.startswith("/api/"):
        # Reports quote the resume, so no browser or proxy keeps a copy.
        headers.setdefault("Cache-Control", "no-store")
    if production:
        headers["Strict-Transport-Security"] = HSTS


_INLINE_STYLE_RE = re.compile(r"<style>(.*?)</style>", re.DOTALL)


def _sha256(text: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode() + "'"


def inline_style_csp(html: str) -> str:
    """The policy for a page that loads nothing and has only its own inline <style>
    blocks (the match report): those blocks by hash, and nothing else."""
    styles = " ".join(_sha256(style) for style in _INLINE_STYLE_RE.findall(html))
    return "; ".join(
        [
            "default-src 'none'",
            f"style-src {styles}" if styles else "style-src 'none'",
            "frame-ancestors 'none'",
            "base-uri 'none'",
            "form-action 'none'",
        ]
    )


def docs_csp(html: str) -> str:
    hashes = " ".join(_sha256(script) for script in _INLINE_SCRIPT_RE.findall(html))
    return "; ".join(
        [
            "default-src 'none'",
            f"script-src {_CDN} {hashes}".strip(),
            # Swagger UI sets some styles inline.
            f"style-src {_CDN} 'unsafe-inline'",
            "img-src 'self' data: https://fastapi.tiangolo.com",
            "connect-src 'self'",
            "frame-ancestors 'none'",
            "base-uri 'none'",
            "form-action 'none'",
        ]
    )


def install_docs(app: FastAPI) -> None:
    """Serve Swagger UI at /docs with a policy made for it. ReDoc is off."""

    @app.get(DOCS_PATH, include_in_schema=False)
    def docs() -> HTMLResponse:
        page = get_swagger_ui_html(openapi_url=app.openapi_url or "/openapi.json", title=app.title)
        html = bytes(page.body).decode("utf-8")
        page.headers["Content-Security-Policy"] = docs_csp(html)
        return page
