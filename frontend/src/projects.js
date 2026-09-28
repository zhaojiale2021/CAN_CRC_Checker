// 项目目录相关的纯逻辑:按 OEM 分组、默认项目选择、结果表格的行构造。

/** 按 OEM 分组,保持后端返回的顺序。 */
export function groupByOem(projects) {
  const groups = []
  const index = new Map()
  for (const project of projects || []) {
    let group = index.get(project.oem)
    if (!group) {
      group = { label: project.oem.toUpperCase(), items: [] }
      index.set(project.oem, group)
      groups.push(group)
    }
    group.items.push(project)
  }
  return groups
}

export function findProject(projects, id) {
  return (projects || []).find((p) => p.id === id) || null
}

/** 校验按钮的可用条件:选了项目、选了文件、且当前没有在跑。 */
export function canRun({ projectId, file, running }) {
  return Boolean(projectId && file && !running)
}

/** 配置摘要里最值得先看到的两三项(用于项目卡片)。 */
export function summaryHighlights(project) {
  const summary = project?.summary || {}
  const items = []
  if (summary.crc) items.push({ label: '算法', value: summary.crc })
  if (summary.dataid && summary.dataid !== '无') {
    items.push({ label: 'DataID', value: summary.dataid })
  }
  if (summary.range && summary.range !== 'exclude_crc') {
    const end = summary.range_end === -1 ? '末尾' : summary.range_end
    items.push({ label: '范围', value: `${summary.range}_${summary.range_start}..${end}` })
  }
  if (summary.dbc_merge) items.push({ label: 'DBC', value: '合并为一个映射' })
  return items
}

/** 失败明细表:按 (报文, 信号) 去重后的行,保留首次出现的期望/实际值。 */
export function failureRows(report) {
  const rows = []
  const seen = new Map()
  for (const failure of report?.failures || []) {
    const key = `${failure.frame_id}-${failure.signal}`
    const existing = seen.get(key)
    if (existing) {
      existing.count += 1
      existing.last_timestamp = failure.timestamp
      continue
    }
    const row = { ...failure, count: 1, last_timestamp: failure.timestamp, key }
    seen.set(key, row)
    rows.push(row)
  }
  return rows
}

/** 报文汇总表:失败多的排前面(后端已排序,这里只做通道筛选)。 */
export function frameRows(report, onlyFailing = false) {
  const frames = report?.frames || []
  return onlyFailing ? frames.filter((f) => f.fail > 0) : frames
}
