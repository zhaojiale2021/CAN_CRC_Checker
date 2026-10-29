# CAN CRC Checker 网页版 — API 与部署

网页工具：选择项目 → 上传 trace（BLF/ASC/MF4/TRC/CSV）→ 服务端用该项目的
`config.json`（DBC/DataID/算法）跑一次校验 → 页面查看汇总与失败明细，并可下载
自包含的 HTML 报告。

校验逻辑与 CLI **完全同源**：`crc_checker/verify/runner.py` 是唯一实现，
`crc-check run` 与 `POST /api/verify` 都调用它，两边不会算出不同结论。

## 启动

```bash
pip install -r requirements.txt
./run_web.sh 8000          # Windows: run_web.bat 8000
# 浏览器访问 http://<服务器IP>:8000
```

前端产物 `frontend/dist` 已提交进 git，部署机无需 Node。改前端时：

```bash
cd frontend
npm install
npm run dev                # 5173, /api 代理到 127.0.0.1:8000
npm run build              # 构建到 frontend/dist,提交 dist 后部署机 git pull + 重启
```

## 项目目录

网页版只扫描服务端目录里的项目，**浏览器只提交项目 id，从不提交路径**：

- 默认扫描 `projects/`；不存在时扫描自带的 `examples/`（演示项目）。
- 环境变量 `CRC_CHECKER_PROJECTS_DIR` 可指向任意目录。
- 支持 `<分组>/<项目>/config.json` 与 `<项目>/config.json` 两种布局。

新增项目：把一个 `config.json`（以及它引用的 DBC/DataID/trace）放进扫描目录即可，
无需改代码。

## 查看部署版本（commit 节点）

导航栏右上角「版本」入口，或直接访问 `/api/version`：

- **运行 commit** 在服务加载时固定（进程启动那一刻的 HEAD），并显示启动时间
- **部署目录 commit** 每次查询单独读取 —— `git pull` 后没重启服务时，页面会提示
  「部署目录与服务启动时的版本状态不同」，这时后端代码尚未生效（重启即可）
- 运行代码或项目目录有未提交改动时标记「有修改」
- 缺少 `.git` 或 Git 不可用时显示「版本未知」，不影响校验功能

`running`/`checkout` 各含 `{commit, branch, subject, committed_at, dirty}`；
`checkout_changed` 在任一侧版本未知时为 `null`（不是 `false`）。

## 接口

所有接口同源、无鉴权（内网工具），请求/响应均为 JSON（注明的除外）。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/projects` | 项目列表（服务端扫描项目目录） |
| POST | `/api/verify` | multipart 上传 trace 并校验 |
| GET | `/api/runs/{run_id}/report.html` | 下载本次校验的 HTML 报告 |
| GET | `/api/version` | 部署版本（commit 节点），`Cache-Control: no-store` |

### `GET /api/projects`

```json
{
  "count": 1,
  "projects": [{
    "id": "examples/example",
    "oem": "examples",
    "model": "example",
    "name": "example",
    "dbc_files": ["network.dbc"],
    "sample_traces": ["example.blf", "example_bad.blf"],
    "summary": {
      "crc": "CRC8/SAE-J1850 (from DBC comments)",
      "dataid": "dataid.json / hi_lo_two_cols / prepend",
      "range": "exclude_crc", "range_start": 0, "range_end": -1,
      "default_max_frames": 0, "dbc_merge": false
    }
  }]
}
```

只返回文件名，不返回任何服务端路径。

### `POST /api/verify`

`multipart/form-data`:

| 字段 | 必填 | 说明 |
|------|------|------|
| `project_id` | 是 | `/api/projects` 里的 `id` |
| `file` | 是 | trace 文件（BLF/ASC/MF4/TRC/CSV/LOG） |
| `max_frames` | 否 | 帧数上限：`""`=用项目配置默认，`0`=不限，`N`=前 N 帧 |
| `only_failures` | 否 | `"true"` 时 HTML 报告只写失败项 |

上限 `CRC_WEB_MAX_UPLOAD_MB`（默认 200MB）。上传文件写到
`data/web/uploads/<run_id>/`，**跑完即删**；只保留生成的报告。

响应（节选）：

```json
{
  "run_id": "DnM0oBFVUVEl",
  "project_id": "examples/example",
  "trace_name": "example.blf",
  "report_url": "/api/runs/DnM0oBFVUVEl/report.html",
  "elapsed_ms": 415,
  "setup": {
    "dbc_names": ["network.dbc"],
    "channels": {},
    "dataid_entries": 2, "dataid_sheet": "",
    "counts": {"profiles": 4, "auto_classify": 3},
    "notes": ["DBC files: 1 file(s)", "..."],
    "max_frames": 6000
  },
  "reports": [{
    "total_frames": 160, "total_verdicts": 320,
    "pass_count": 320, "fail_count": 0, "pass_rate": 1.0,
    "crc_total": 160, "crc_pass": 160, "crc_rate": 1.0,
    "rc_total": 160, "rc_pass": 160, "rc_rate": 1.0,
    "failures": [],
    "failures_truncated": false,
    "frames": [{
      "frame_id_hex": "0x100", "frame_name": "MsgAlpha", "channel": 0,
      "dbc_source": "network.dbc",
      "total": 40, "pass": 40, "fail": 0, "rate": 1.0,
      "signals": [{"signal": "Checksum_Alpha", "algorithm": "crc",
                   "total": 40, "pass": 40, "fail": 0, "last_detail": ""}]
    }],
    "frames_truncated": false
  }]
}
```

序列化上限：失败明细每条 trace 最多 2000 行、报文最多 500 个、每个报文的信号最多
50 个（超出时 `*_truncated: true`，完整内容以上面的 HTML 报告为准）。

### 状态码

| 码 | 场景 |
|----|------|
| 404 | 未知 `project_id`；`run_id` 不存在或报告已过期 |
| 400 | 空文件、帧数上限不是整数、配置/trace 解析失败 |
| 413 | 上传超过 `CRC_WEB_MAX_UPLOAD_MB` |

错误体沿用 FastAPI 的 `{"detail": "..."}`。

## 运行产物

写入 `data/`（已 gitignore）：

```
data/web/uploads/<run_id>/              # 上传的 trace,跑完即删
data/web/runs/<run_id>/<run_id>.html    # 生成的报告,最多保留最近 20 次(LRU)
```

每个 run 一个子目录：报告主文件与 `_pN` 分片只落在自己的目录里，路由不会命中
其它 run 的文件；淘汰时整个目录一起删除。

## 与 CLI 的关系

`crc_checker/verify/runner.py` 承载「DBC 选择 → DataID → CRC 配置 → 校验」的完整
顺序；CLI 只负责参数解析与打印，`webapp/` 只负责传输（临时文件、JSON、报告缓存）。
改校验口径只需改 runner 一处，两边同时生效。
