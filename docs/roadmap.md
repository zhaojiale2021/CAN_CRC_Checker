# CanVouch roadmap

Last updated: 2026-11-20 · Current release: **v0.2.1** · Status: living document

CanVouch already answers the core question — *does this captured trace match the
protection the DBC promises?* — for a single project, from both the CLI and the
web UI. The roadmap below turns it from a *verification tool* into a *protection
observability workflow*: discover the right configuration quickly, gate CI on
it, and compare runs over time.

## Where we are

| Area | Shipped today | Confidence |
| --- | --- | --- |
| Input | DBC (single/list/merge, per-channel selection), BLF/ASC/MF4/MDF4/TRC/CSV/LOG/SQLite traces (MDF3 rejected with a clear error), DataID `.xlsx`/`.xls`/JSON | High |
| Signal discovery | Prefix/suffix regexes, bus markers, indexed instances, block-counter exclusion, custom YAML | High |
| Algorithms | E2E P1/1A/P5, CRC8/16/32 presets, SUM8, SUM8/XOR-FF, XOR8/SEED, custom params, DBC-comment classification, per-message overrides/profiles | High |
| Verification | CRC, RC continuity (PASS/STALE/SKIP/RESET/INVALID), per-channel state, DLC gate, folded failure episodes | High |
| Output | Table, JSON (`schema_version: 1`), self-contained HTML with byte highlighting, RC trend charts, split reports | High |
| Web | Project mode, manual upload, sample traces, async jobs, cancel, token gate, upload caps, version panel | Medium |
| Engineering | 410 tests, 80 % coverage gate, pylint 10.00, Python 3.11–3.13 + Windows CI, wheel smoke, Docker image, PyPI/GHCR release | High |

Known weak spots (from the 2026-11-20 review) are listed in
[Open issues](#open-issues-not-fixed-in-this-pass) below.

## Themes

1. **Trust the verdict.** A false failure costs more than a missed feature; a
   false-clean report is worse. Every feature must make coverage explicit.
2. **Configuration is the hard part.** Users know their firmware and their
   trace; they struggle to express CRC range, profile, DataID layout and counter
   semantics correctly. Tooling should infer and explain configuration.
3. **Fit into the pipeline.** A verification result is only useful if it can
   fail a build, annotate a PR, and be compared with the previous run.
4. **No customer data in the repository.** All examples stay synthetic; every
   capability stays configuration-driven.

## Now — v0.3 (next 4–6 weeks): correctness and CLI ergonomics

| Item | Why | Acceptance |
| --- | --- | --- |
| **Resolve the review's correctness fixes** | Profile reclassification, comment-only P05/P01, channel fallback and global RC overrides produced wrong or false-clean results | Shipped in this pass; keep regression tests for each case |
| **UTF-8 / encoding hardening** | Chinese Windows consoles and DBC files are the primary environment | All CLI output round-trips on cp936 consoles; GBK DBC regression tests stay green |
| **CLI result aggregation** | A broken CRC on a 6 000-frame trace prints thousands of rows | Default per-frame/signal summary; `--show-all` keeps raw verdicts; `--group-by` optional |
| **`canvouch validate-config`** | Users discover config errors only after a full trace run | Loads a config, resolves paths, prints per-section diagnostics, exits non-zero on error; no trace parsing |
| **`inspect --config` / `explain`** | `inspect` only shows signal positions, not the algorithm/range/DataID that will actually run | Prints per message: algorithm, profile, CRC range, DataID value/source, skip reason, counter limit |
| **Config error messages** | Nested type errors used to reach the worker and surface as a 500 | Every schema-shaped field is type-checked at load time with the offending key named |
| **Report split notice** | Split parts (`_p2.html`…) are silent | CLI prints every written part |
| **Docs drift** | Pylint version, CI matrix, JSON output and validation wording were stale | README/zh/CONTRIBUTING updated to match `requirements.txt` and `ci.yml` (a docs test can follow) |

## Next — v0.4 (1–2 quarters): onboarding and CI

### N1. `canvouch discover` — infer the protection configuration

The highest-value feature for new users. Given a DBC and a trace, try every
preset, range mode, byte order and DataID layout the DBC enables, then rank the
candidates by pass rate and coverage.

- Output: candidate table (algorithm, range, profile, DataID, pass rate,
  matched frames) plus a ready-to-run `config.json`.
- Confidence must be honest: no result when no candidate covers enough frames.
- Must reuse the existing engine; no second CRC implementation.
- Acceptance: on the bundled example it recovers the shipped config; on a
  mixed P01/P05/SUM8 bus it identifies each message's algorithm.

### N2. CI integration

- `--junit-xml` output (Jenkins/GitLab/Azure).
- SARIF output (GitHub code scanning annotations).
- `--baseline previous.json`: fail only on *new* failures; show fixed/resolved.
- Publish a composite GitHub Action that installs CanVouch, runs a config and
  uploads the HTML report.
- Acceptance: a sample workflow in `examples/` fails a PR for one new CRC
  failure and passes after the fix.

### N3. RC semantics for real capture conditions

- Configurable gap tolerance: `rc.max_gap` (default 1) so a logged/dropped
  frame is `SKIP` but not a failure.
- Optional resync after a timeout or a bus-off interval (`rc.resync_after_s`).
- Optional cycle-time awareness: a gap larger than N message periods is a new
  baseline, not a counter jump.
- Acceptance: dropped-frame and late-join traces produce no false failures;
  genuine stuck counters still fail.

### N4. Make coverage visible

- Per-channel coverage diagnostics in report and web result: matched frames /
  protected frames / unverified IDs.
- Explicit `dbcs` → channel mapping in config (today only auto-selection).
- Warn when a channel's matched-ID ratio is below a threshold.
- Acceptance: a trace whose second channel starts after the sampling window is
  either verified or reported as unverified — never silently clean.

### N5. Web manual mode: advanced config

- Advanced JSON panel for `crc.custom`, `crc.overrides`, `crc.profiles`,
  `crc.range_overrides`, `crc.skip`.
- Saved configurations per browser (localStorage) and a server-side run history
  with a compare view.
- Acceptance: every config key the CLI accepts can be expressed from the web
  page (paths excluded by design).

## Later — v0.5 → v1.0: breadth and platform

| Item | Rationale |
| --- | --- |
| **E2E Profile 2 / 4 / 7 / 22** | Wider DataID, counter inside CRC, different sequence rules; requested by ADAS/body projects |
| **ARXML / DBC-attribute configuration import** | Read E2E config from the same source the firmware uses |
| **Multi-trace batch dashboard** | One summary across a test suite, with per-trace drill-down |
| **Windows portable package** | Zip with embedded Python + committed frontend; no install, no Node |
| **Web auth / RBAC** | Token gate is enough for a lab; shared deployments need users and roles |
| **English report output** | Public OSS users need English; keep Chinese as the default |
| **Performance guardrails** | Memory ceiling for unlimited traces, parallel trace parsing, streaming split writes |
| **Plugin API for custom algorithms** | Let downstream projects register checksums without forking |
| **Preset promotion** | Promote the remaining presets from "known-answer" to "verified" with a public benchmark corpus |

## Feature map

| Capability | v0.2 | v0.3 | v0.4 | v0.5+ |
| --- | --- | --- | --- | --- |
| E2E P1/1A/P5 | ✅ | | | |
| E2E P2/P4/P7/P22 | | | | ◻ |
| Comment classification | ✅ | width diagnostics | | |
| Algorithm discovery | | | ◻ | |
| Resolved-config explain | | ◻ | | |
| RC gap tolerance / resync | | | ◻ | |
| Coverage diagnostics | partial | | ◻ | |
| JSON output | ✅ | docs | | |
| JUnit / SARIF / baseline | | | ◻ | |
| Web manual advanced config | | | ◻ | |
| Run history / compare | | | ◻ | |
| ARXML import | | | | ◻ |
| Batch dashboard | | | | ◻ |
| Portable Windows package | | | | ◻ |
| English report | | | | ◻ |

Legend: ✅ shipped · ◻ planned · blank = not scheduled.

## Open issues (not fixed in this pass)

Ranked by risk. Each is a candidate GitHub issue.

1. **Upload bodies are only capped after receipt (High).** A chunked
   `multipart/form-data` request has no `Content-Length`, so Starlette spools the
   whole body before `_save_upload` counts it. A `Content-Length` pre-check is
   shipped; the streaming receive-wrapper is still needed.
2. **Job result retention is unbounded before trimming (Medium).** Failure rows
   and RC trend points are materialised before `_bounded_result` runs, and the
   full payload is retained in the run store. Add caps at serialisation time and
   bound `RunOutcome.payload`.
3. **CLI failure output is not aggregated (Medium).** See v0.3 item.
4. **No resolved-config view (Medium).** `inspect` ignores the config and
   classification decisions.
5. **Web manual mode cannot express custom/advanced CRC config (Medium).**
6. **Release workflow does not create a GitHub Release (Medium).** The release
   badge and `pyproject.toml` changelog link point at `/releases`; tags only
   publish PyPI/GHCR. Also check `frontend/package.json` version against
   `crc_checker.__version__`.
7. **Docker uses Python 3.14, which CI does not test (Medium).** Pin the image
   to a tested interpreter or extend the matrix, and add a Docker build smoke
   job.
8. **Wheels ship no `examples/` (Low-Medium).** `pip install canvouch[web]`
   starts with an empty project list; package the example or document manual
   mode for pip installs.
9. **Fuzzy DataID matching can copy a sibling instance's DataID (Low-Medium).**
   Improve the sibling guard and report a missing entry instead of guessing.
10. **`parse_sum_byte_range` widens on unrelated byte mentions (Low).** Limit
    the range to the contiguous list before any "checksum lives in" phrase.
11. **Unsupported E2E profile numbers still fall through to generic CRC (Low).**
    Prefer an explicit "unsupported profile" skip over a plausible wrong CRC.
12. **Dependency audits are scheduled, not PR gates (Low).**
13. **Pre-push hook has no POSIX installer (Low).**
14. **`gen-config` defaults to an unverified preset (Low).** It warns
    immediately on every generated starter.

## Non-goals

- Real-time bus monitoring or CAN interface control.
- Replacing CANoe/CANalyzer trace capture.
- Shipping customer DBCs, traces or DataID tables.
- A hosted multi-tenant SaaS.

## How this roadmap is maintained

- Correctness fixes always outrank features.
- Every roadmap item lands with a test that would fail without it.
- Items move to "Now" only when the design fits the existing
  configuration-driven architecture (YAML/JSON, no customer-specific code).
