"""Fail-closed Community Cloud entrypoint bootstrap; no schema/account auto-provisioning."""
import os

from quantmesh.http import ServiceError
from quantmesh.serve import preflight

SETTINGS = ("QUANTMESH_BACKEND", "QUANTMESH_DEPLOYMENT", "QUANTMESH_AUTH_MODE",
            "QUANTMESH_DATABASE_URL", "QUANTMESH_SSLROOTCERT", "QUANTMESH_SESSION_SECRET", "QUANTMESH_LLM_PROVIDER",
            "QUANTMESH_LLM_MODEL", "QUANTMESH_LLM_API_KEY", "ALPHAVANTAGE_API_KEY")


def configure(settings):
    # Platform settings are shared process configuration, not user-controlled input.
    # Validate the complete candidate before changing the process environment.
    candidate = {key: settings.get(key, os.environ.get(key, "")) for key in SETTINGS}
    if (candidate["QUANTMESH_BACKEND"] != "postgres"
            or candidate["QUANTMESH_DEPLOYMENT"] != "production"
            or candidate["QUANTMESH_AUTH_MODE"] != "multi-user"
            or not all(isinstance(value, str) for value in candidate.values())):
        raise ServiceError("Community Cloud requires postgres, production and multi-user settings. Access denied.")
    # Absence must stay absent: injecting empty optional provider/model values
    # masks the application's documented defaults on every Streamlit rerun.
    os.environ.update({key: value for key, value in candidate.items()
                       if key in settings or key in os.environ})
    preflight()
