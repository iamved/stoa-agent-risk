"""Locate the compiled dashboard template.

The template is built once at package build time (``scripts/build_dashboard.sh``,
run by the release workflow) and ships inside the wheel as
``stoa/templates/dashboard.html``. It is not committed to git. A development
checkout that has not built it gets a clear, actionable error instead of a
traceback; ``stoa scan`` degrades to a warning and still writes the registry
and the legacy report.

``STOA_DASHBOARD_TEMPLATE`` overrides the location (tests, local UI work).
"""

from __future__ import annotations

import os
from importlib import resources
from pathlib import Path

TEMPLATE_ENV = "STOA_DASHBOARD_TEMPLATE"
TEMPLATE_NAME = "dashboard.html"


class DashboardTemplateMissing(RuntimeError):
    """The compiled UI is not present in this installation."""


def load_template() -> str:
    override = os.environ.get(TEMPLATE_ENV)
    if override:
        path = Path(override)
        if not path.is_file():
            raise DashboardTemplateMissing(f"{TEMPLATE_ENV} points at a missing file: {override}")
        return path.read_text(encoding="utf-8")
    resource = resources.files("stoa") / "templates" / TEMPLATE_NAME
    try:
        return resource.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as exc:
        raise DashboardTemplateMissing(
            "the compiled dashboard template (stoa/templates/dashboard.html) is not in this "
            "installation. Released wheels include it; in a development checkout run "
            "scripts/build_dashboard.sh (needs Node) or set STOA_DASHBOARD_TEMPLATE."
        ) from exc
