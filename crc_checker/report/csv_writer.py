"""CSV report writer."""

from __future__ import annotations

import csv
import sys
from crc_checker.verify.models import VerifyReport, VerifyVerdict


def write_csv(report: VerifyReport, file_path: str | None = None,
              only_failures: bool = False, delimiter: str = ",") -> None:
    """Write verification results to CSV.

    Args:
        report: The verification report.
        file_path: Output path (None = stdout).
        only_failures: If True, only include failed verdicts.
        delimiter: CSV delimiter character.
    """
    verdicts = report.failed if only_failures else report.verdicts

    fh = open(file_path, "w", newline="") if file_path else sys.stdout
    try:
        writer = csv.writer(fh, delimiter=delimiter)
        # Header
        writer.writerow([
            "Timestamp", "FrameID", "FrameID_Hex", "Algorithm",
            "SignalName", "ExpectedValue", "ActualValue", "Verdict", "Detail"
        ])
        for v in verdicts:
            writer.writerow([
                f"{v.timestamp:.6f}",
                v.frame_id,
                f"0x{v.frame_id:03X}",
                v.algorithm,
                v.signal_name,
                v.expected_value,
                v.actual_value,
                "PASS" if v.is_pass else "FAIL",
                v.detail,
            ])

        # Summary footer
        summary = report.summary()
        writer.writerow([])
        writer.writerow(["SUMMARY"])
        writer.writerow(["Total Frames", summary["total_frames"]])
        writer.writerow(["Total Verdicts", summary["total_verdicts"]])
        writer.writerow(["Pass", summary["pass_count"]])
        writer.writerow(["Fail", summary["fail_count"]])
        writer.writerow(["Pass Rate", summary["pass_rate"]])
    finally:
        if file_path:
            fh.close()
