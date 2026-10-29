// 纯展示格式化函数(与 UI 框架解耦,便于 node --test 单测)。

export function formatBytes(bytes) {
  if (bytes === null || bytes === undefined) return '-'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = Number(bytes)
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${unit === 0 ? value : value.toFixed(1)} ${units[unit]}`
}

export function formatDuration(ms) {
  if (ms === null || ms === undefined) return '-'
  if (ms < 1000) return `${ms} ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(2)} s`
  const minutes = Math.floor(ms / 60000)
  return `${minutes} min ${Math.round((ms % 60000) / 1000)} s`
}

export function formatPercent(rate) {
  if (rate === null || rate === undefined) return '-'
  return `${(rate * 100).toFixed(2)}%`
}

/** 通过率(按通过数/总数):有失败项时绝不四舍五入成 100.00%
 *  —— 卡片写着 100% 却在旁边列出 1 个失败会误导人。 */
export function formatRate(passed, total) {
  if (total === null || total === undefined || total <= 0) return '-'
  if (passed >= total) return '100.00%'
  const rate = (passed / total) * 100
  for (const digits of [2, 3, 4, 5]) {
    const text = rate.toFixed(digits)
    if (Number(text) < 100) return `${text}%`
  }
  return `${rate.toFixed(6)}%`
}

export function formatTimestamp(seconds) {
  if (seconds === null || seconds === undefined) return '-'
  return Number(seconds).toFixed(6)
}

export function shortCommit(commit) {
  return commit ? String(commit).slice(0, 7) : ''
}

/** 版本入口的按钮文案:commit 短号 + 是否有本地修改 / 版本未知。 */
export function versionLabel(running) {
  if (!running || !running.commit) return '版本未知'
  return `版本 ${shortCommit(running.commit)}${running.dirty ? ' · 有修改' : ''}`
}

/** 部署目录 commit 与运行 commit 是否不一致(用于页面提示)。 */
export function checkoutChanged(info) {
  if (!info || info.checkout_changed === null || info.checkout_changed === undefined) {
    return false
  }
  return Boolean(info.checkout_changed)
}

/** 把后端 setup.notes 里的路径行换成文件名,便于界面展示。 */
export function fileName(path) {
  if (!path) return ''
  const parts = String(path).split(/[\\/]/)
  return parts[parts.length - 1] || String(path)
}
