# Security policy

## Reporting a vulnerability

Please open a private security advisory on GitHub
(<https://github.com/zhaojiale2021/CAN_CRC_Checker/security/advisories/new>)
or contact the maintainer. Do not open a public issue with exploitable details
before a fix is available.

## Deployment notes

- The web app has **no authentication by default** and binds to `127.0.0.1`
  in the launchers. Exposing it on a network is only safe behind an
  authenticated reverse proxy or with `CRC_WEB_API_TOKEN` set.
- When `CRC_WEB_API_TOKEN` is set, every `/api/*` request must send
  `X-API-Token: <token>` (or `Authorization: Bearer <token>`). The web UI
  stores the token in the browser's localStorage.
- Upload limits: `CRC_WEB_MAX_UPLOAD_MB` (per file, default 200) and
  `CRC_WEB_MAX_REQUEST_MB` (per request, default 400).
- Uploaded traces are deleted when the job reaches a terminal state; only the
  rendered HTML report is retained (LRU, 20 runs).
- The job registry and report store are in-process. Run a single uvicorn
  worker unless you move them to shared storage.
