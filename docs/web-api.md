# CAN CRC Checker 网页版 — API 与部署

内网网页工具:选客户项目 → 上传 trace(BLF/ASC/MF4/TRC/CSV)→ 服务端用该项目
`config.json` 的 DBC/DataID/算法配置跑一次校验 → 页面看汇总与失败明细,并可下载
自包含的 HTML 报告。

校验逻辑与 CLI **完全同源**:`crc_checker/verify/runner.py` 是唯一实现,
`crc-check run` 与 `POST /api/verify` 都调用它,两边不会算出不同结论。

## 启动

```bash
pip install -r requirements.txt
./run_web.sh 8000          # Windows: run_web.bat 8000
# 浏览器访问 http://<服务器IP>:8000
```

前端产物 `frontend/dist` 已提交进 git,部署机无需 Node。改前端时:

```bash
cd frontend
npm install
npm run dev                # 5173, /api 代理到 127.0.0.1:8000
npm run build              # 构建到 frontend/dist,提交 dist 后部署机 git pull + 重启
```

## 查看部署版本(commit 节点)

导航栏右上角「版本」入口,或直接访问 `/api/version`:

- **运行 commit** 在服务加载时固定(进程启动那一刻的 HEAD),并显示服务启动时间
- **部署目录 commit** 每次查询单独读取 —— `git pull` 后没重启服务时,页面会提示
  「部署目录与服务启动时的版本状态不同」,这时后端代码尚未生效(重启即可)
- 运行代码或 `customers/` 有未提交改动时标记「有修改」,此时 commit 只代表基础版本
- 缺少 `.git` 或 Git 不可用时显示「版本未知」,不影响校验功能

`running`/`checkout` 各含 `{commit, branch, subject, committed_at, dirty}`;
`checkout_changed` 在任一侧版本未知时为 `null`(不是 `false`)。

## 接口

所有接口同源、无鉴权(内网工具),请求/响应均为 JSON,除注明的除外。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/projects` | 项目列表(服务端扫描 `customers/<oem>/<model>/config.json`) |
| POST | `/api/verify` | multipart 上传 trace 并校验 |
| GET | `/api/runs/{run_id}/report.html` | 下载本次校验的 HTML 报告 |
| GET | `/api/version` | 部署版本(commit 节点),`Cache-Control: no-store` |

### `GET /api/projects`

```json
{
  "count": 10,
  "projects": [{
    "id": "gac/eea40",
    "oem": "gac",
    "model": "eea40",
    "name": "GAC eea40",
    "dbc_files": ["ADCPublic_CANFD1.dbc", "ADCPublic_CANFD2.dbc"],
    "sample_traces": [],
    "summary": {
      "crc": "按 CRC 位宽选 Profile(p01)",
      "dataid": "dataid.json / gac_eea4 / append",
      "range": "custom_range", "range_start": 0, "range_end": 56,
      "default_max_frames": 2000, "dbc_merge": false
    }
  }]
}
```

只返回文件名,不返回任何服务端路径;浏览器也从不提交路径 —— 只提交 `id`。

### `POST /api/verify`

`multipart/form-data`:

| 字段 | 必填 | 说明 |
|------|------|------|
| `project_id` | 是 | `/api/projects` 里的 `id` |
| `file` | 是 | trace 文件(BLF/ASC/MF4/TRC/CSV/LOG) |
| `max_frames` | 否 | 帧数上限:`""`=用项目配置默认,`0`=不限,`N`=前 N 帧 |
| `only_failures` | 否 | `"true"` 时 HTML 报告只写失败项 |

上限 `CRC_WEB_MAX_UPLOAD_MB`(默认 200MB)。上传文件写到
`data/web/uploads/<run_id>/`,**跑完即删**;只保留生成的报告。

响应(节选):

```json
{
  "run_id": "DnM0oBFVUVEl",
  "project_id": "chery/t1jfl3",
  "trace_name": "T1J_FL3_490_车辆控制失败11111.blf",
  "report_url": "/api/runs/DnM0oBFVUVEl/report.html",
  "elapsed_ms": 415,
  "setup": {
    "dbc_names": ["...FL_CH_CANFD_APA....dbc", "...FL_DA_CANFD_APA....dbc"],
    "channels": {"0": "a.dbc", "1": "b.dbc"},
    "dataid_entries": 63, "dataid_sheet": "CANFD1",
    "counts": {"profiles": 69, "skip": 1, "auto_classify": 18},
    "notes": ["DBC files: 2 file(s)", "Merged 2 DBCs into one protection map", "..."],
    "max_frames": 6000
  },
  "reports": [{
    "total_frames": 6000, "total_verdicts": 15456,
    "pass_count": 13748, "fail_count": 1708, "pass_rate": 0.8895,
    "crc_total": 8385, "crc_pass": 7410, "crc_rate": 0.8837,
    "rc_total": 7071, "rc_pass": 6338, "rc_rate": 0.8963,
    "failures": [{
      "frame_id_hex": "0x14F", "frame_name": "ONEBOX_5", "channel": 1,
      "signal": "ONEBOX_CRC3_14Fh", "algorithm": "crc",
      "crc_algorithm": "CRC8/SAE-J1850-ZERO",
      "expected_hex": "0xA8", "actual_hex": "0x0",
      "detail": "CRC mismatch in ONEBOX_5 (ONEBOX_3): expected 0xA8, got 0x00",
      "timestamp": 1783711150.875639
    }],
    "failures_truncated": false,
    "frames": [{
      "frame_id_hex": "0x14F", "frame_name": "ONEBOX_5", "channel": 1,
      "dbc_source": "...FL_CH_CANFD_APA....dbc",
      "total": 1434, "pass": 957, "fail": 477, "rate": 0.6674,
      "signals": [{"signal": "ONEBOX_CRC3_14Fh", "algorithm": "crc",
                   "total": 717, "pass": 478, "fail": 239, "last_detail": "..."}]
    }],
    "frames_truncated": false
  }]
}
```

序列化上限:失败明细每条 trace 最多 2000 行、报文最多 500 个、每个报文的信号最多
50 个(超出时 `*_truncated: true`,完整内容以上面的 HTML 报告为准)。

### 状态码

| 码 | 场景 |
|----|------|
| 404 | 未知 `project_id`;`run_id` 不存在或报告已过期 |
| 400 | 空文件、帧数上限不是整数、配置/ trace 解析失败(`RunnerError`) |
| 413 | 上传超过 `CRC_WEB_MAX_UPLOAD_MB` |

错误体沿用 FastAPI 的 `{"detail": "..."}`。

## 运行产物

写入 `data/`(已 gitignore):

```
data/web/uploads/<run_id>/     # 上传的 trace,跑完即删
data/web/runs/<run_id>.html    # 生成的报告,最多保留最近 20 次(LRU)
```

## 与 CLI 的关系

`crc_checker/verify/runner.py` 承载「DBC 选择 → DataID → CRC 配置 → 校验」的完整
顺序;CLI 只负责参数解析与打印,`webapp/` 只负责传输(临时文件、JSON、报告缓存)。
改校验口径只需改 runner 一处,两边同时生效。
