"""JSON report writer."""

from __future__ import annotations

import json
import sys
from crc_checker.verify.models import VerifyReport, VerifyVerdict


class _VerdictEncoder(json.JSONEncoder):
    """Custom JSON encoder for VerifyVerdict and VerifyReport."""
    def default(self, obj):
        if isinstance(obj, VerifyVerdict):
            return {
                "timestamp": obj.timestamp,
                "frame_id": obj.frame_id,
                "frame_id_hex": f"0x{obj.frame_id:03X}",
                "algorithm": obj.algorithm,
                "signal_name": obj.signal_name,
                "expected_value": obj.expected_value,
                "actual_value": obj.actual_value,
                "is_pass": obj.is_pass,
                "detail": obj.detail,
            }
        if isinstance(obj, VerifyReport):
            return {
                "dbc_path": obj.dbc_path,
                "trace_path": obj.trace_path,
                "total_frames": obj.total_frames,
                "total_verdicts": obj.total_verdicts,
                "pass_count": obj.pass_count,
                "fail_count": obj.fail_count,
                "pass_rate": obj.pass_rate,
                "verdicts": obj.verdicts,
            }
        return super().default(obj)


def write_json(report: VerifyReport, file_path: str | None = None,
               only_failures: bool = False, indent: int = 2) -> None:
    """Write verification results to JSON.

    Args:
        report: The verification report.
        file_path: Output path (None = stdout).
        only_failures: If True, only include failed verdicts.
        indent: JSON indentation level.
    """
    output = {
        "dbc_path": report.dbc_path,
        "trace_path": report.trace_path,
        "summary": report.summary(),
        "verdicts": report.failed if only_failures else report.verdicts,
    }

    if file_path:
        with open(file_path, "w") as f:
            json.dump(output, f, cls=_VerdictEncoder, indent=indent, ensure_ascii=False)
    else:
        print(json.dumps(output, cls=_VerdictEncoder, indent=indent, ensure_ascii=False))
