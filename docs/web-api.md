# CAN CRC Checker 网页版 — API 与部署

网页工具两种用法：选择项目 → 上传 trace；或手动上传 DBC（可多个）+ trace
（+ 可选 DataID 文件），在页面上填写原 `config.json` 的算法/范围/DataID 等选项 → 服务端
跑一次校验 → 页面查看汇总与失败明细，并可下载自包含的 HTML 报告。

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

## 手动上传模式

不想把项目放进服务端目录时，页面切到「手动上传 DBC + trace」：

- 上传 1..10 个 DBC、1 个 trace、可选 1 个 DataID 文件（`.json` / `.xlsx` / `.xls`）。
- 在页面上填写 CLI `config.json` 的常用段：`crc`（算法 preset、`byte_swap`、
  `auto_classify`、`profile_by_width`）、`range`、`dataid`（位置/字节序/sheet/映射/
  默认值）、`filter.frame_ids`、`signals` 正则、`rc.max_valid`、`dbc_merge`。
- **路径字段永远由服务端生成**：请求里的 `dbc`/`dbcs`/`traces`、
  `dataid.xlsx`/`dataid.json`/`dataid.mapping_file`、`signals.patterns_file` 会被拒绝
  （400）或忽略，手写 config 无法让服务端读取任意文件。
- DBC 选择、DataID 应用、报告生成与项目模式走同一条 `crc_checker/verify/runner.py`。
- 算法下拉来自 `GET /api/presets`，并标注是否已用仓库内真实 trace 验证过。

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
| GET | `/api/presets` | 内置算法列表及验证状态 |
| POST | `/api/verify` | multipart 上传 trace 并按项目配置校验 |
| POST | `/api/verify-manual` | multipart 上传 DBC + trace（+ DataID）并按页面填写的配置校验 |
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

### `GET /api/presets`

```json
{
  "presets": [{
    "name": "CRC8/SAE-J1850-ZERO", "width": 8, "checksum_type": "crc",
    "validated": true, "note": "captured CAN traces, E2E Profile 1"
  }]
}
```

`validated` 表示该算法已在仓库里的真实 trace 上复现过（与 `crc-check presets`
的标注一致）。

### `POST /api/verify-manual`

`multipart/form-data`:

| 字段 | 必填 | 说明 |
|------|------|------|
| `dbcs` | 是 | 1..10 个 `.dbc`（按 trace 通道自动选 DBC，或 `dbc_merge` 合并） |
| `trace` | 是 | trace 文件（BLF/ASC/MF4/TRC/CSV/LOG） |
| `dataid` | 否 | 预处理后的 `.json` 或 `.xlsx`/`.xls` |
| `config` | 否 | JSON 字符串（默认 `{}`），允许的顶层键见下 |
| `max_frames` | 否 | 同 `/api/verify` |
| `only_failures` | 否 | 同 `/api/verify` |

`config` 只接受 `crc`、`range`、`dataid`、`filter`、`signals`、`rc`、`output`、
`dbc_merge`。`dbc`/`dbcs`/`traces`、`dataid.xlsx`/`dataid.json`/`dataid.mapping_file`、
`signals.patterns_file` 由服务端控制或直接拒绝（400）——浏览器仍不能提交路径。

```json
{
  "crc": {"preset": "CRC8/SAE-J1850-ZERO", "byte_swap": false,
          "auto_classify": false, "profile_by_width": false},
  "range": {"mode": "exclude_crc"},
  "dataid": {"position": "prepend", "byte_order": "lo_hi"},
  "filter": {"frame_ids": ["0x143"], "max_frames": 6000},
  "signals": {"checksum_pattern": "^Checksum_"},
  "rc": {"max_valid": 14}
}
```

响应同 `/api/verify`，其中 `project_id` 为 `"manual"`、`project.name` 为「手动配置」。

### 状态码

| 码 | 场景 |
|----|------|
| 404 | 未知 `project_id`；`run_id` 不存在或报告已过期 |
| 400 | 空文件、文件类型不支持、配置里出现路径字段、帧数上限不是整数、配置/trace 解析失败 |
| 413 | 上传超过 `CRC_WEB_MAX_UPLOAD_MB` |

错误体沿用 FastAPI 的 `{"detail": "..."}`。

## 运行产物

写入 `data/`（已 gitignore）：

```
data/web/uploads/<run_id>/              # 上传的 trace / DBC / DataID,跑完即删
data/web/runs/<run_id>/<run_id>.html    # 生成的报告,最多保留最近 20 次(LRU)
```

每个 run 一个子目录：报告主文件与 `_pN` 分片只落在自己的目录里，路由不会命中
其它 run 的文件；淘汰时整个目录一起删除。

## 与 CLI 的关系

`crc_checker/verify/runner.py` 承载「DBC 选择 → DataID → CRC 配置 → 校验」的完整
顺序；CLI 只负责参数解析与打印，`webapp/` 只负责传输（临时文件、JSON、报告缓存）。
改校验口径只需改 runner 一处，两边同时生效。
