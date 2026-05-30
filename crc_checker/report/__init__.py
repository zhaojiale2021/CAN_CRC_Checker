"""Report generators."""

from crc_checker.report.csv_writer import write_csv
from crc_checker.report.json_writer import write_json
from crc_checker.report.html import write_html

__all__ = ["write_csv", "write_json", "write_html"]
