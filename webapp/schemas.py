"""Pydantic response models — the web API's OpenAPI contract.

The routes previously returned bare ``dict`` values, so the generated schema
was empty and the frontend had to be kept in sync by hand. These models pin
the shapes without changing the JSON the Vue app already consumes.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class LimitsResponse(BaseModel):
    """Upload caps and defaults the page renders (single source of truth)."""

    max_upload_mb: int
    max_dbc_files: int
    manual_default_frames: int


class ProjectOut(BaseModel):
    """One scanned project (never exposes a server path)."""

    id: str
    oem: str
    model: str
    name: str
    dbc_files: list[str] = Field(default_factory=list)
    sample_traces: list[str] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class ProjectsResponse(BaseModel):
    """Project list payload for the project picker."""

    projects: list[ProjectOut]
    count: int


class PresetOut(BaseModel):
    """One built-in CRC/checksum preset and its real-data validation status."""

    name: str
    width: int
    checksum_type: str
    validated: bool
    note: Optional[str] = None


class PresetsResponse(BaseModel):
    """Preset list payload for the algorithm picker."""

    presets: list[PresetOut]


class JobAccepted(BaseModel):
    """A staged verification job (``202`` on the verify endpoints)."""

    job_id: str
    status: str


class JobState(BaseModel):
    """Current state of an asynchronous verification job."""

    job_id: str
    status: str
    processed_frames: int = 0
    error: Optional[str] = None
    result: Optional[dict[str, Any]] = None


class CancelResponse(BaseModel):
    """Result of a cancellation request."""

    job_id: str
    status: str
    cancel_requested: bool


class VersionInfo(BaseModel):
    """One revision snapshot; fields are ``None`` when git is unavailable."""

    commit: Optional[str] = None
    branch: Optional[str] = None
    subject: Optional[str] = None
    committed_at: Optional[str] = None
    dirty: Optional[bool] = None


class VersionResponse(BaseModel):
    """Running vs. deploy-directory revision payload."""

    running: VersionInfo
    checkout: VersionInfo
    checkout_changed: Optional[bool] = None
    started_at: str
