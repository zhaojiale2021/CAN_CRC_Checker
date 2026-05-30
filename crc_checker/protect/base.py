"""Abstract base class for protection algorithm plugins."""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from crc_checker.trace.models import CanFrame
from crc_checker.dbc.models import MessageProtection

if TYPE_CHECKING:
    from crc_checker.verify.models import VerifyVerdict


class ProtectionAlgorithm(ABC):
    """Abstract interface for all protection verification algorithms.

    Each algorithm (CRC, Rolling Counter, E2E Profile, etc.) implements this
    interface. The verification engine calls verify() for each frame.
    """

    @property
    @abstractmethod
    def algorithm_type(self) -> str:
        """Unique algorithm type identifier: 'crc', 'rolling_counter', 'e2e_profile5', etc."""
        ...

    @abstractmethod
    def verify(self, frame: CanFrame, protection: MessageProtection) -> VerifyVerdict | list[VerifyVerdict] | None:
        """Verify one protection group on a single CAN frame.

        Args:
            frame: The CAN data frame.
            protection: The protection group definition (signal positions, algorithm params).

        Returns:
            A single VerifyVerdict, a list of verdicts, or None if the algorithm
            cannot be applied (e.g., missing signal definitions).
        """
        ...

    def reset(self):
        """Reset any stateful tracking (e.g., rolling counter state). Called between runs."""
        pass
