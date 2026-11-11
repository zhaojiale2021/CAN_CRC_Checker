// 手动上传模式的纯逻辑:把页面表单转成与 CLI 相同的 config JSON。
// 这里只生成算法/范围/DataID/filter 等配置项;DBC、trace、DataID 的路径
// 由服务端按上传目录写入,前端永远不提交路径。

/** 解析 "0x143, 299  0x300" → ["0x143", "299", "0x300"]。 */
export function parseFrameIds(text) {
  return String(text || '')
    .split(/[\s,;]+/)
    .map((token) => token.trim())
    .filter(Boolean)
}

function hasValue(value) {
  return value !== null && value !== undefined && value !== ''
}

/**
 * @param {object} state 页面表单状态
 * @returns {object} 可直接作为 POST /api/verify-manual 的 `config` 字段
 */
export function buildManualConfig(state = {}) {
  const config = {
    crc: {
      byte_swap: Boolean(state.byteSwap),
      auto_classify: Boolean(state.autoClassify),
      profile_by_width: Boolean(state.profileByWidth),
    },
    range: {
      mode: state.rangeMode || 'exclude_crc',
      start_byte: Number(state.rangeStart ?? 0),
      end_byte: Number(state.rangeEnd ?? -1),
    },
    dataid: {
      position: state.dataidPosition || 'prepend',
      byte_order: state.dataidByteOrder || 'lo_hi',
    },
  }

  if (state.preset) config.crc.preset = state.preset
  if (state.dbcMerge) config.dbc_merge = true

  if (state.dataidSheet) config.dataid.sheet = state.dataidSheet
  if (state.dataidMapping) config.dataid.mapping = state.dataidMapping
  if (hasValue(state.dataidDefault)) config.dataid.default = state.dataidDefault

  const frameIds = parseFrameIds(state.frameIds)
  if (frameIds.length) config.filter = { frame_ids: frameIds }

  if (hasValue(state.rcMaxValid)) config.rc = { max_valid: Number(state.rcMaxValid) }

  if (state.checksumPattern) config.signals = { checksum_pattern: state.checksumPattern }
  if (state.rcPattern) {
    config.signals = { ...(config.signals || {}), rc_pattern: state.rcPattern }
  }
  return config
}

/** 手动模式能否点「开始校验」。 */
export function manualCanRun({ dbcFiles, traceFile, running }) {
  return Boolean(dbcFiles && dbcFiles.length && traceFile && !running)
}

/** 结果标题里的项目名:手动模式显示为「手动配置」。 */
export function resultProjectLabel(projectId) {
  return projectId === 'manual' ? '手动配置' : projectId
}
