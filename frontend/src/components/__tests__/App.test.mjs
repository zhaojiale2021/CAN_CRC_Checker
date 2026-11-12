import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus from 'element-plus'

import App from '../../App.vue'
import {
  cancelJob,
  fetchJob,
  fetchLimits,
  fetchPresets,
  fetchProjects,
  verifySample,
} from '../../api.js'

vi.mock('../../api.js', () => ({
  cancelJob: vi.fn(),
  fetchJob: vi.fn(),
  fetchLimits: vi.fn(),
  fetchPresets: vi.fn(),
  fetchProjects: vi.fn(),
  verifyManual: vi.fn(),
  verifySample: vi.fn(),
  verifyTrace: vi.fn(),
}))

if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
}

const result = {
  trace_name: 'demo.csv',
  project_id: 'demo/basic',
  reports: [{ check_total: 1, check_fail: 0 }],
}

async function mountApp() {
  fetchProjects.mockResolvedValue({
    projects: [
      {
        id: 'demo/basic',
        oem: 'demo',
        model: 'basic',
        summary: {},
        dbc_files: [],
        sample_traces: ['demo.csv'],
      },
    ],
  })
  fetchPresets.mockResolvedValue({ presets: [] })
  fetchLimits.mockResolvedValue({})
  const wrapper = mount(App, {
    global: {
      plugins: [ElementPlus],
      stubs: { VersionPanel: true, ResultPanel: true, ManualOptionsForm: true },
    },
  })
  await flushPromises()
  return wrapper
}

async function startSample(wrapper) {
  verifySample.mockResolvedValue({ job_id: 'job-1', status: 'queued' })
  const run = wrapper.vm.runSample('demo.csv')
  await flushPromises()
  return { run }
}

async function pollAgain() {
  await vi.advanceTimersByTimeAsync(1000)
  await flushPromises()
}

describe('App async verification', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('shows processed-frame progress and focuses the result on success', async () => {
    fetchJob
      .mockResolvedValueOnce({
        job_id: 'job-1',
        status: 'running',
        processed_frames: 12,
      })
      .mockResolvedValueOnce({
        job_id: 'job-1',
        status: 'succeeded',
        processed_frames: 30,
        result,
      })
    const wrapper = await mountApp()
    const { run } = await startSample(wrapper)

    expect(wrapper.text()).toContain('已处理 12 帧')
    expect(fetchJob).toHaveBeenCalledTimes(1)
    const finishing = vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    await finishing
    await flushPromises()
    await run

    expect(wrapper.find('#result-panel').exists()).toBe(true)
    expect(wrapper.text()).toContain('demo.csv')
    expect(wrapper.find('#result-panel').attributes('tabindex')).toBe('-1')
    expect(fetchJob).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('surfaces a failed job error and stops polling', async () => {
    fetchJob.mockResolvedValue({
      job_id: 'job-1',
      status: 'failed',
      processed_frames: 4,
      error: 'trace could not be decoded',
    })
    const wrapper = await mountApp()
    const { run } = await startSample(wrapper)

    expect(wrapper.text()).toContain('trace could not be decoded')
    expect(fetchJob).toHaveBeenCalledTimes(1)
    await run
    await pollAgain()
    expect(fetchJob).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('requests server cancellation and displays the cancelled terminal state', async () => {
    fetchJob
      .mockResolvedValueOnce({
        job_id: 'job-1',
        status: 'running',
        processed_frames: 5,
      })
      .mockResolvedValueOnce({
        job_id: 'job-1',
        status: 'cancelled',
        processed_frames: 5,
      })
    cancelJob.mockResolvedValue({
      job_id: 'job-1',
      status: 'cancelled',
      processed_frames: 5,
    })
    const wrapper = await mountApp()
    const { run } = await startSample(wrapper)

    const cancelButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('取消校验'))
    expect(cancelButton).toBeTruthy()
    await cancelButton.trigger('click')
    await flushPromises()
    expect(cancelJob).toHaveBeenCalledWith('job-1')
    const finishing = vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    await finishing
    await flushPromises()
    await run

    expect(wrapper.text()).toContain('校验已取消')
    expect(wrapper.find('#result-panel').exists()).toBe(false)
    expect(fetchJob).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('keeps the active job cancellable and retries transient progress errors', async () => {
    fetchJob
      .mockRejectedValueOnce(new Error('temporary network error'))
      .mockResolvedValueOnce({
        job_id: 'job-1',
        status: 'running',
        processed_frames: 8,
      })
      .mockResolvedValueOnce({
        job_id: 'job-1',
        status: 'cancelled',
        processed_frames: 8,
      })
    cancelJob.mockResolvedValue({
      job_id: 'job-1',
      status: 'cancelled',
      processed_frames: 8,
    })
    const wrapper = await mountApp()
    const { run } = await startSample(wrapper)

    expect(wrapper.text()).toContain('temporary network error')
    expect(
      wrapper
        .findAll('button')
        .some((button) => button.text().includes('取消校验')),
    ).toBe(true)
    expect(fetchJob).toHaveBeenCalledTimes(1)

    const retry = vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    await retry
    await flushPromises()
    expect(wrapper.text()).toContain('已处理 8 帧')
    expect(wrapper.text()).not.toContain('temporary network error')

    const cancelButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('取消校验'))
    await cancelButton.trigger('click')
    await flushPromises()
    expect(cancelJob).toHaveBeenCalledWith('job-1')
    const finish = vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    await finish
    await flushPromises()
    await run
    expect(wrapper.text()).toContain('校验已取消')
    expect(fetchJob).toHaveBeenCalledTimes(3)
    wrapper.unmount()
  })

  it('stops polling and clears the active job when the server no longer knows it', async () => {
    const missingJob = new Error('not found')
    missingJob.status = 404
    fetchJob.mockRejectedValue(missingJob)
    const wrapper = await mountApp()
    const { run } = await startSample(wrapper)

    expect(wrapper.text()).toContain('校验任务状态已失效')
    expect(wrapper.text()).toContain('请重新提交')
    expect(fetchJob).toHaveBeenCalledTimes(1)
    await run
    await pollAgain()
    expect(fetchJob).toHaveBeenCalledTimes(1)
    expect(wrapper.vm.currentJobId).toBe('')
    wrapper.unmount()
  })

  it('stops scheduled polling when the component unmounts', async () => {
    fetchJob.mockResolvedValue({
      job_id: 'job-1',
      status: 'running',
      processed_frames: 2,
    })
    const wrapper = await mountApp()
    await startSample(wrapper)
    expect(fetchJob).toHaveBeenCalledTimes(1)

    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(2000)
    await flushPromises()
    expect(fetchJob).toHaveBeenCalledTimes(1)
  })
})
