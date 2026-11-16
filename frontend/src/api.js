// 与后端 REST 接口的唯一接触面。所有路径都是同源相对路径(生产由 FastAPI 直接托管)。

const JSON_TYPE = 'application/json'
const TOKEN_KEY = 'crc-api-token'

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

/** 服务端可选的 API token(部署时设置 CRC_WEB_API_TOKEN 后需要)。 */
export function getApiToken() {
  try {
    return localStorage.getItem(TOKEN_KEY) || ''
  } catch {
    return ''
  }
}

export function setApiToken(value) {
  try {
    if (value) localStorage.setItem(TOKEN_KEY, value)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    // 隐私模式/localStorage 不可用时忽略:服务端仍会给出 401。
  }
}

function authHeaders() {
  const token = getApiToken()
  return token ? { 'X-API-Token': token } : {}
}

/** 错误响应可能用 detail,也可能用兜底的 message(500)。 */
function errorDetail(body) {
  if (body && typeof body === 'object' && 'detail' in body) return body.detail
  return body
}

async function request(path, options = {}) {
  let response
  try {
    response = await fetch(path, {
      ...options,
      headers: { ...authHeaders(), ...(options.headers || {}) },
    })
  } catch (err) {
    if (err.name === 'AbortError') throw err
    throw new Error(`无法连接服务:${err.message}`)
  }
  const type = response.headers.get('content-type') || ''
  const body = type.includes(JSON_TYPE)
    ? await response.json().catch(() => null)
    : await response.text()
  if (!response.ok) {
    const error = new Error(formatApiDetail(errorDetail(body), response.status))
    error.status = response.status
    throw error
  }
  return body
}

/**
 * multipart 上传:需要上传进度与“202 之前也能取消”,所以用 XHR 而不是 fetch。
 * 返回与 request 相同的解析结果;取消时 reject 一个 name=AbortError 的错误。
 */
function uploadRequest(path, form, { onProgress, signal } = {}) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', path)
    const token = getApiToken()
    if (token) xhr.setRequestHeader('X-API-Token', token)

    const abort = () => xhr.abort()
    if (signal) {
      if (signal.aborted) {
        abort()
        return
      }
      signal.addEventListener('abort', abort, { once: true })
    }
    const cleanup = () => signal?.removeEventListener('abort', abort)

    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable || !onProgress) return
      onProgress(event.loaded, event.total)
    }
    xhr.onerror = () => {
      cleanup()
      reject(new Error('无法连接服务:网络错误'))
    }
    xhr.onabort = () => {
      cleanup()
      const error = new Error('上传已取消')
      error.name = 'AbortError'
      reject(error)
    }
    xhr.onload = () => {
      cleanup()
      let body = null
      try {
        body = xhr.responseText ? JSON.parse(xhr.responseText) : null
      } catch {
        body = xhr.responseText
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body)
        return
      }
      const error = new Error(formatApiDetail(errorDetail(body), xhr.status))
      error.status = xhr.status
      reject(error)
    }
    xhr.send(form)
  })
}

export function fetchProjects() {
  return request('/api/projects')
}

export function fetchPresets() {
  return request('/api/presets')
}

/** 服务端限额(上传大小 / 单请求总大小 / DBC 个数 / 手动模式默认帧数)。 */
export function fetchLimits() {
  return request('/api/limits')
}

export function fetchVersion() {
  return request('/api/version')
}

/**
 * 上传 trace 并校验。帧数上限:null = 用项目配置里的默认值,0 = 不限。
 */
export function verifyTrace({
  projectId,
  file,
  maxFrames = null,
  onlyFailures = false,
  onProgress,
  signal,
}) {
  const form = new FormData()
  form.append('project_id', projectId)
  form.append('file', file)
  form.append('max_frames', maxFrames === null ? '' : String(maxFrames))
  form.append('only_failures', onlyFailures ? 'true' : 'false')
  return uploadRequest('/api/verify', form, { onProgress, signal })
}

/**
 * 校验项目自带的示例 trace(服务端路径,浏览器只提交项目 id + 文件名)。
 */
export function verifySample({
  projectId,
  traceName,
  maxFrames = null,
  onlyFailures = false,
  onProgress,
  signal,
}) {
  const form = new FormData()
  form.append('project_id', projectId)
  form.append('trace_name', traceName)
  form.append('max_frames', maxFrames === null ? '' : String(maxFrames))
  form.append('only_failures', onlyFailures ? 'true' : 'false')
  return uploadRequest('/api/verify-sample', form, { onProgress, signal })
}

/**
 * 手动模式:上传 DBC(+ 可选 DataID)和 trace,并提交页面上填写的 config。
 * `config` 必须是普通对象,服务端会覆盖其中的所有路径字段。
 */
export function verifyManual({
  dbcs,
  trace,
  dataid = null,
  config,
  maxFrames = null,
  onlyFailures = false,
  onProgress,
  signal,
}) {
  const form = new FormData()
  dbcs.forEach((file) => form.append('dbcs', file))
  form.append('trace', trace)
  if (dataid) form.append('dataid', dataid)
  form.append('config', JSON.stringify(config || {}))
  form.append('max_frames', maxFrames === null ? '' : String(maxFrames))
  form.append('only_failures', onlyFailures ? 'true' : 'false')
  return uploadRequest('/api/verify-manual', form, { onProgress, signal })
}

/** Read the current state and progress of an asynchronous verification job. */
export function fetchJob(jobId, { signal } = {}) {
  return request(`/api/jobs/${encodeURIComponent(jobId)}`, { signal })
}

/** Request server-side cancellation; terminal jobs may respond with HTTP 409. */
export function cancelJob(jobId) {
  return request(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: 'POST',
  })
}
