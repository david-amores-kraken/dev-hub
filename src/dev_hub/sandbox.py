"""Show a model-written HTML file safely, for any section that has one."""

from __future__ import annotations

import re
from pathlib import Path

from flask import Response

HEAD_OPEN_RE = re.compile(r"<head[^>]*>", re.IGNORECASE)
# These files are documents the model wrote, so they are shown in a sandbox: no scripts, no
# network, and links open in a new tab. They only need inline CSS and <details>, which this allows.
CSP = (
    "sandbox allow-popups allow-popups-to-escape-sandbox; default-src 'none'; "
    "style-src 'unsafe-inline'; img-src data:; font-src data:"
)


def sandboxed_html(path: Path) -> Response:
    html = path.read_text()
    if "<base " not in html.lower():
        html = HEAD_OPEN_RE.sub(lambda m: m[0] + '<base target="_blank">', html, count=1)
    response = Response(html, mimetype="text/html")
    response.headers["Content-Security-Policy"] = CSP
    return response
