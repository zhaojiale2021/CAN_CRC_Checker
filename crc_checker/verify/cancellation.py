"""Cooperative cancellation primitives for verification runs."""

from __future__ import annotations

import threading


class VerificationCancelled(Exception):
    """Raised when a verification run is cooperatively cancelled.

    ``processed_frames`` counts eligible frames whose processing completed
    before cancellation was observed.
    """

    def __init__(self, processed_frames: int = 0):
        super().__init__("Verification cancelled")
        self.processed_frames = processed_frames


class CancellationToken:
    """Thread-safe cancellation signal checked at verification frame boundaries."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        """Request cancellation; the active frame, if any, finishes first."""
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        """Whether cancellation has been requested."""
        return self._event.is_set()

    def raise_if_cancelled(self, processed_frames: int = 0) -> None:
        """Raise with the completed frame count when cancellation was requested."""
        if self.is_cancelled:
            raise VerificationCancelled(processed_frames)
