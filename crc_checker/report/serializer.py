"""JSON serialization for verification reports."""

from __future__ import annotations

from crc_checker.report.trends import check_sample_stats, crc_sample_stats, rc_sample_stats


def report_to_dict(report, only_failures: bool = False) -> dict:
    """Convert one report to a JSON-compatible dictionary.

    CRC and rolling-counter summaries use sample-based counts, so folded RC
    failure verdicts do not understate the number of failed frames. The full RC
    sample series is included separately from the folded verdict list. When
    ``only_failures`` is true, only the detailed verdict list is filtered; summary
    counts and RC sample series retain their complete accounting.
    """
    passed, total = check_sample_stats(report)
    crc_passed, crc_total = crc_sample_stats(report)
    rc_passed, rc_total = rc_sample_stats(report)
    summary = {
        "frames": report.total_frames,
        "checks": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": passed / total if total else None,
        "crc": {
            "checks": crc_total,
            "passed": crc_passed,
            "failed": crc_total - crc_passed,
        },
        "rolling_counter": {
            "checks": rc_total,
            "passed": rc_passed,
            "failed": rc_total - rc_passed,
        },
        "frames_truncated": report.frames_truncated,
        "frame_limit": report.frame_limit,
        "dlc_mismatch_skipped": report.dlc_mismatch_skipped,
    }
    verdicts = [
        {
            "frame_id": verdict.frame_id,
            "timestamp": verdict.timestamp,
            "channel": verdict.channel,
            "algorithm": verdict.algorithm,
            "signal_name": verdict.signal_name,
            "expected_value": verdict.expected_value,
            "actual_value": verdict.actual_value,
            "passed": verdict.is_pass,
            "detail": verdict.detail,
            "start_bit": verdict.start_bit,
            "length": verdict.length,
            "byte_order": verdict.byte_order,
            "dataid": verdict.dataid,
            "dataid_name": verdict.dataid_name,
            "dataid_profile": verdict.dataid_profile,
            "crc_algorithm": verdict.crc_algorithm,
            "repeat_count": verdict.repeat_count,
        }
        for verdict in report.verdicts
        if not only_failures or not verdict.is_pass
    ]
    rc_series = [
        {
            "frame_id": frame_id,
            "channel": channel,
            "signal_name": signal_name,
            "samples": [
                {
                    "timestamp": timestamp,
                    "value": value,
                    "passed": is_pass,
                    "category": category,
                }
                for timestamp, value, is_pass, category in points
            ],
        }
        for (frame_id, channel, signal_name), points in sorted(
            report.rc_series.items())
    ]
    return {
        "trace": report.trace_path,
        "dbc": report.dbc_path,
        "dbcs": list(report.dbc_paths),
        "summary": summary,
        "verdicts": verdicts,
        "rolling_counter_series": rc_series,
    }


def reports_to_dict(reports, only_failures: bool = False) -> dict:
    """Convert one or more reports to a single JSON document."""
    serialized = [report_to_dict(report, only_failures=only_failures)
                  for report in reports]
    passed = sum(item["summary"]["passed"] for item in serialized)
    total = sum(item["summary"]["checks"] for item in serialized)
    return {
        "summary": {
            "reports": len(serialized),
            "frames": sum(item["summary"]["frames"] for item in serialized),
            "checks": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": passed / total if total else None,
            "frames_truncated": any(
                item["summary"]["frames_truncated"] for item in serialized),
        },
        "reports": serialized,
    }
