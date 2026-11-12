// 校验任务状态机:提交 → 轮询 → 终态(成功/失败/取消),以及取消请求。
// 从 App.vue 抽出的唯一目的:让这段与定时器、竞态、卸载相关的逻辑可单独阅读和测试。

import { computed, onBeforeUnmount, ref } from 'vue'

import { cancelJob, fetchJob } from '../api.js'

const POLL_INTERVAL_MS = 1000
const TERMINAL_JOB_STATES = new Set(['succeeded', 'failed', 'cancelled'])

/**
 * @param {{ onResult?: (payload: object) => void }} options
 *   onResult 在任务成功且拿到 result 后调用(用于滚动/聚焦结果面板)。
 */
export function useVerificationJob({ onResult } = {}) {
  const running = ref(false)
  const jobStatus = ref('')
  const processedFrames = ref(null)
  const currentJobId = ref('')
  const cancelling = ref(false)
  const runError = ref('')
  const result = ref(null)

  let pollTimer = null
  let resolvePollWait = null
  let activeRun = 0
  let isUnmounted = false

  const jobStatusText = computed(() => {
    const labels = {
      queued: '校验任务排队中',
      running: '校验正在进行',
      succeeded: '校验完成',
      failed: '校验失败',
      cancelled: '校验已取消',
      error: '校验状态查询失败',
    }
    return labels[jobStatus.value] || ''
  })

  function clearPollTimer() {
    if (pollTimer !== null) {
      clearTimeout(pollTimer)
      pollTimer = null
    }
    if (resolvePollWait) {
      resolvePollWait()
      resolvePollWait = null
    }
  }

  function updateJobState(job) {
    jobStatus.value = job.status || ''
    processedFrames.value = Number.isFinite(job.processed_frames)
      ? job.processed_frames
      : null
  }

  function waitForNextPoll() {
    return new Promise((resolve) => {
      resolvePollWait = resolve
      pollTimer = setTimeout(() => {
        pollTimer = null
        resolvePollWait = null
        resolve()
      }, POLL_INTERVAL_MS)
    })
  }

  async function pollJob(jobId, runId) {
    while (!isUnmounted && runId === activeRun) {
      try {
        const job = await fetchJob(jobId)
        if (isUnmounted || runId !== activeRun) return null
        runError.value = ''
        updateJobState(job)
        if (TERMINAL_JOB_STATES.has(job.status)) return job
      } catch (err) {
        if (isUnmounted || runId !== activeRun) return null
        if (err.status === 404) {
          return {
            status: 'failed',
            error:
              '校验任务状态已失效（可能是服务重启或任务已过期），请重新提交。',
          }
        }
        // Keep the job handle and retry transient status failures; users can
        // still cancel the server-side job while status polling is recovering.
        runError.value = `读取校验进度失败，将自动重试：${err.message}`
      }
      await waitForNextPoll()
    }
    return null
  }

  async function executeVerification(submit) {
    const runId = ++activeRun
    clearPollTimer()
    running.value = true
    cancelling.value = false
    currentJobId.value = ''
    processedFrames.value = null
    jobStatus.value = ''
    runError.value = ''
    try {
      const submission = await submit()
      if (isUnmounted || runId !== activeRun) return
      if (!submission?.job_id) {
        throw new Error('服务未返回校验任务 ID。')
      }
      currentJobId.value = submission.job_id
      updateJobState(submission)
      const job = await pollJob(submission.job_id, runId)
      if (!job || isUnmounted || runId !== activeRun) return
      updateJobState(job)
      if (job.status === 'succeeded' && job.result) {
        result.value = job.result
        onResult?.(job.result)
      } else if (job.status === 'failed') {
        runError.value = job.error || '校验任务失败。'
        result.value = null
      } else if (job.status === 'cancelled') {
        result.value = null
      }
    } catch (err) {
      if (!isUnmounted && runId === activeRun) {
        jobStatus.value = 'error'
        runError.value = err.message
        result.value = null
      }
    } finally {
      if (!isUnmounted && runId === activeRun) {
        running.value = false
        cancelling.value = false
        currentJobId.value = ''
        clearPollTimer()
      }
    }
  }

  async function cancelVerification() {
    const jobId = currentJobId.value
    if (!jobId || !running.value || cancelling.value) return
    cancelling.value = true
    try {
      const state = await cancelJob(jobId)
      if (!isUnmounted && currentJobId.value === jobId) updateJobState(state)
    } catch (err) {
      if (!isUnmounted && currentJobId.value === jobId) {
        // 409 means the job became terminal before cancellation was accepted;
        // the poll loop remains authoritative and will retrieve its final state.
        if (err.status !== 409) runError.value = err.message
      }
    } finally {
      if (!isUnmounted && currentJobId.value === jobId) cancelling.value = false
    }
  }

  onBeforeUnmount(() => {
    isUnmounted = true
    activeRun += 1
    clearPollTimer()
  })

  return {
    running,
    jobStatus,
    jobStatusText,
    processedFrames,
    currentJobId,
    cancelling,
    runError,
    result,
    executeVerification,
    cancelVerification,
  }
}
