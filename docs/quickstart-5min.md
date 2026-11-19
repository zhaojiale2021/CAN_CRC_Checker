# Five-Minute Quickstart

This walkthrough uses only the synthetic trace bundled in the repository. It verifies that CLI, report generation, and failure gating work without vehicle data.

## 1. Install

```bash
git clone https://github.com/zhaojiale2021/canvouch.git
cd canvouch
python -m pip install -r requirements.txt
python -m pip install -e .
```

Python 3.11 or newer is required.

## 2. Run the bundled trace

```bash
canvouch run -c examples/example/config.json --verbose
```

Expected result: 160 frames, 320 checks, 100% pass.

The command creates `examples/example/report.html`. Open it locally to inspect frame-level results and trends.

## 3. Exercise failure gating

```bash
canvouch run -c examples/example/config_bad.json --fail-on-failure --verbose
```

The deliberately broken example should exit with status `1`. In CI, treat that result as a verification failure rather than a command-line crash.

## 4. Start the Web UI

```bash
./run_web.sh 8000
```

Windows:

```bat
run_web.bat 8000
```

Open `http://127.0.0.1:8000`.

## Docker alternative

```bash
docker build -t canvouch .
docker run --rm -p 8000:8000 canvouch
```

Open `http://127.0.0.1:8000`.

## Package and container releases

Push a `v*` tag such as `v0.2.2`. Release automation:

1. verifies the tag against `crc_checker.__version__`;
2. runs pylint and pytest;
3. builds wheel and source distribution;
4. publishes to PyPI through the configured trusted publisher;
5. publishes `latest` and the version tag to GHCR.
