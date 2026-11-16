"""Web version of CanVouch (FastAPI backend + Vue frontend)."""

from webapp.catalog import Project, scan_projects
from webapp.version import deployment_version

__all__ = ["Project", "scan_projects", "deployment_version"]
