"""Private exports stay in the authenticated WebSocket UI, never Streamlit media URLs."""
import base64
import html
import os
import re

import streamlit as st


def download(target, label: str, data: bytes | str, filename: str, mime: str):
    if os.environ.get("QUANTMESH_AUTH_MODE", "single-user") != "multi-user":
        return target.download_button(label, data, filename, mime)
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", filename) or mime not in {"text/csv", "application/json"}:
        raise ValueError("Unsupported private export type.")
    raw = data.encode() if isinstance(data, str) else data
    encoded = base64.b64encode(raw).decode("ascii")
    # Only constant CSS, escaped labels and base64 data enter srcdoc. No external script or URL.
    with target:
        st.iframe(
            '<style>a{display:inline-block;color:#e4eaf6;background:#151d32;padding:10px;'
            'border:1px solid #41dbc0;border-radius:6px;font:14px sans-serif;text-decoration:none}</style>'
            f'<a download="{html.escape(filename, quote=True)}" '
            f'href="data:{mime};base64,{encoded}">{html.escape(label)}</a>',
            height=55)
