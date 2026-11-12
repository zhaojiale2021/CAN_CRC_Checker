"""Smoke-test a built and installed wheel without the source checkout on sys.path."""

# pylint: disable=too-many-locals,consider-using-with
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional, Tuple
from urllib.error import URLError
from urllib.request import urlopen


def _get(url: str) -> Tuple[int, bytes, str]:
    with urlopen(url, timeout=3) as response:  # noqa: S310 - local smoke server
        return response.status, response.read(), response.headers.get_content_type()


def main() -> int:
    """Launch the installed web app from a temporary non-checkout directory."""
    with tempfile.TemporaryDirectory(prefix="crc-checker-wheel-smoke-") as temp_dir:
        work_dir = Path(temp_dir)
        data_dir = work_dir / "data"
        data_dir.mkdir()
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env["CRC_CHECKER_DATA_DIR"] = str(data_dir)
        env["CRC_CHECKER_PROJECTS_DIR"] = str(work_dir / "no-projects")

        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        base_url = f"http://127.0.0.1:{port}"
        log_path = work_dir / "uvicorn.log"
        with log_path.open("w", encoding="utf-8") as log_file:
            process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "webapp.main:app",
                 "--host", "127.0.0.1", "--port", str(port), "--workers", "1"],
                cwd=work_dir,
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
            try:
                deadline = time.monotonic() + 30
                last_error: Optional[Exception] = None
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        break
                    try:
                        status, body, content_type = _get(base_url + "/")
                        if status != 200 or "html" not in content_type:
                            raise RuntimeError("wheel root did not return HTML")
                        html = body.decode("utf-8")
                        assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html)
                        if not assets:
                            raise RuntimeError(
                                f"wheel frontend references no static assets: {html[:500]!r}")
                        for asset_path in assets:
                            asset_status, asset, _asset_type = _get(base_url + asset_path)
                            if asset_status != 200 or not asset:
                                raise RuntimeError(f"wheel static asset failed: {asset_path}")

                        api_status, api_body, _api_type = _get(base_url + "/api/limits")
                        limits = json.loads(api_body)
                        if api_status != 200 or "max_upload_mb" not in limits:
                            raise RuntimeError("wheel API probe failed")
                        print("Wheel root, bundled static assets, and /api/limits passed")
                        return 0
                    except (URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
                        last_error = exc
                        time.sleep(0.25)

                log = log_path.read_text(encoding="utf-8", errors="replace")
                raise RuntimeError(
                    f"wheel smoke server failed: {last_error or 'process exited'}\n{log}")
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
