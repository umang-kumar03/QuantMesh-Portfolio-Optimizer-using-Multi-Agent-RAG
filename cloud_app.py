"""Select this entrypoint on Streamlit Community Cloud, never the local app.py."""
import runpy
from pathlib import Path

import streamlit as st

from quantmesh.cloud import configure
from quantmesh.http import ServiceError

try:
    try:
        settings = dict(st.secrets)
    except FileNotFoundError:
        settings = {}  # Explicit process settings are supported for private local checks.
    with st.spinner("Connecting to secure research storage…"):
        configure(settings)
except ServiceError as exc:
    # ServiceError messages are deliberately sanitized and contain no connection credentials.
    st.error(f"Secure startup failed: {exc}")
    st.stop()
except FileNotFoundError:
    st.error("Secure database configuration is unavailable. Access denied; contact the operator.")
    st.stop()

runpy.run_path(str(Path(__file__).with_name("app.py")), run_name="__main__")
