// 与后端 REST 接口的唯一接触面。所有路径都是同源相对路径(生产由 FastAPI 直接托管)。

const JSON_TYPE = 'application/json'

/** 把 FastAPI 的 detail(字符串 / {message, diagnostics[]}) 摊平成一行行文本。 */
export function formatApiDetail(detail, status) {
  if (!detail) return `请求失败 (HTTP ${status})`
  if (typeof detail === 'string') return detail
  const lines = []
  if (detail.message) lines.push(detail.message)
  if (Array.isArray(detail.diagnostics)) {
    detail.diagnostics.forEach((d) => lines.push(`- ${d.message ?? d}`))
  }
  return lines.join('\n') || JSON.stringify(detail)
}

async function request(path, options = {}) {
  let response
  try {
    response = await fetch(path, options)
  } catch (err) {
    throw new Error(`无法连接服务:${err.message}`)
  }
  const type = response.headers.get('content-type') || ''
  const body = type.includes(JSON_TYPE)
    ? await response.json().catch(() => null)
    : await response.text()
  if (!response.ok) {
    const detail = body && typeof body === 'object' ? body.detail : body
    throw new Error(formatApiDetail(detail, response.status))
  }
  return body
}

export function fetchProjects() {
  return request('/api/projects')
}

export function fetchVersion() {
  return request('/api/version')
}

/**
 * 上传 trace 并校验。帧数上限:null = 用项目配置里的默认值,0 = 不限。
 */
export function verifyTrace({ projectId, file, maxFrames = null, onlyFailures = false }) {
  const form = new FormData()
  form.append('project_id', projectId)
  form.append('file', file)
  form.append('max_frames', maxFrames === null ? '' : String(maxFrames))
  form.append('only_failures', onlyFailures ? 'true' : 'false')
  return request('/api/verify', { method: 'POST', body: form })
}
