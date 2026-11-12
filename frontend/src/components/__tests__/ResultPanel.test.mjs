// ResultPanel 组件冒烟测试(vitest + happy-dom)。
// 只验证与 props 相关的渲染逻辑:汇总卡片、失败折叠、零校验/全通过/截断提示、
// 过滤交互;纯计算逻辑已由 tests/ 下的 node --test 覆盖。

import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'

import ResultPanel from '../ResultPanel.vue'

// happy-dom 没有 ResizeObserver 时补一个空实现(el-table 用来量列宽)
if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
}

/** 4 条失败:Checksum_A 同帧同信号折叠(3+5=8),另有 Checksum_B 与 RC_A。 */
function defaultFailures() {
  const checksumA = (timestamp, repeatCount) => ({
    frame_id: 0x11b,
    frame_id_hex: '0x11B',
    frame_name: 'FrameA',
    channel: 1,
    signal: 'Checksum_A',
    algorithm: 'crc',
    crc_algorithm: 'CRC16/CCITT',
    expected_hex: '0x12',
    actual_hex: '0x34',
    detail: 'crc mismatch',
    timestamp,
    repeat_count: repeatCount,
  })
  return [
    checksumA(1.5, 3),
    checksumA(2.5, 5),
    {
      frame_id: 0x11b,
      frame_id_hex: '0x11B',
      frame_name: 'FrameA',
      channel: 1,
      signal: 'Checksum_B',
      algorithm: 'crc',
      crc_algorithm: 'CRC16/CCITT',
      expected_hex: '0x56',
      actual_hex: '0x78',
      detail: 'crc mismatch',
      timestamp: 3.5,
    },
    {
      frame_id: 0x421,
      frame_id_hex: '0x421',
      frame_name: 'FrameB',
      channel: 1,
      signal: 'RC_A',
      algorithm: 'rc',
      expected_hex: '0x0e',
      actual_hex: '0x0f',
      detail: 'counter stuck',
      timestamp: 4.5,
      repeat_count: 8,
    },
  ]
}

function defaultFrames() {
  return [
    {
      frame_id: 0x11b,
      frame_id_hex: '0x11B',
      frame_name: 'FrameA',
      channel: 1,
      dbc_source: 'demo.dbc',
      pass: 90,
      total: 100,
      fail: 10,
      rate: 0.9,
      signals: [],
    },
    {
      frame_id: 0x421,
      frame_id_hex: '0x421',
      frame_name: 'FrameB',
      channel: 1,
      dbc_source: 'demo.dbc',
      pass: 95,
      total: 100,
      fail: 5,
      rate: 0.95,
      signals: [],
    },
  ]
}

/** 组装挂载用的 result prop;report 支持按字段覆盖。 */
function makeResult({ report = {} } = {}) {
  return {
    trace_name: 'demo.blf',
    project_id: 'demo/basic',
    report_url: '/api/report/demo',
    setup: {
      max_frames: 6000,
      dbc_names: ['demo.dbc'],
      channels: { 1: 'demo.dbc' },
      notes: [],
    },
    reports: [
      {
        total_frames: 100,
        check_total: 10,
        check_pass: 8,
        check_fail: 2,
        crc_pass: 5,
        crc_total: 5,
        crc_rate: 1,
        rc_pass: 3,
        rc_total: 5,
        rc_rate: 0.6,
        rc_trends: [],
        failures: defaultFailures(),
        frames: defaultFrames(),
        ...report,
      },
    ],
  }
}

function mountPanel(result) {
  return mount(ResultPanel, {
    props: { result },
    global: { plugins: [ElementPlus] },
  })
}

function cardValue(wrapper, label) {
  const card = wrapper
    .findAll('.cards .card')
    .find((node) => node.find('.label').text() === label)
  return card?.find('.value').text() ?? ''
}

/** 失败明细 section head 里的「N 组 / M 条」计数(无失败明细时为空串)。 */
function groupCounter(wrapper) {
  const head = wrapper
    .findAll('.section-head')
    .find((node) => node.text().includes('失败明细'))
  return head?.find('.muted')?.text() ?? ''
}

/** 失败明细表的行(第一张 .table);happy-dom 里行存在但单元格内容为空。 */
function failureTableRows(wrapper) {
  const table = wrapper.find('.table')
  return table.findAll('.el-table__row')
}

describe('ResultPanel', () => {
  it('汇总卡片按 report 渲染各项计数与通过率', () => {
    const wrapper = mountPanel(makeResult())
    expect(cardValue(wrapper, '帧数')).toBe('100')
    expect(cardValue(wrapper, '校验项')).toBe('10')
    expect(cardValue(wrapper, '通过')).toBe('8')
    expect(cardValue(wrapper, '失败')).toBe('2')
    expect(cardValue(wrapper, '总通过率')).toBe('80.00%')
    expect(cardValue(wrapper, 'CRC')).toBe('100.00%')
    expect(cardValue(wrapper, 'RollingCounter')).toBe('60.00%')
    wrapper.unmount()
  })

  it('失败行把连续折叠的 repeat_count 累加成一个分组', () => {
    const wrapper = mountPanel(makeResult())
    expect(groupCounter(wrapper)).toBe('3 组 / 4 条')
    expect(failureTableRows(wrapper)).toHaveLength(3)
    // happy-dom 下 Element Plus 表格渲染不出单元格内容(happy-dom 已装 ResizeObserver
    // 仍如此),所以折叠后的次数改从行数据断言——表格「次数/帧」列绑定的就是它。
    const folded = wrapper.vm.filteredFailures.find(
      (row) => row.signal === 'Checksum_A',
    )
    expect(folded.count).toBe(8)
    wrapper.unmount()
  })

  it('过滤框收窄失败行,清空后恢复', async () => {
    const wrapper = mountPanel(makeResult())
    const input = wrapper.find('.search input')
    await input.setValue('RC_A')
    expect(groupCounter(wrapper)).toBe('1 组 / 4 条')
    expect(failureTableRows(wrapper)).toHaveLength(1)
    await input.setValue('')
    expect(groupCounter(wrapper)).toBe('3 组 / 4 条')
    expect(failureTableRows(wrapper)).toHaveLength(3)
    wrapper.unmount()
  })

  it('check_total 为 0 时显示专项提示且没有失败明细', () => {
    const wrapper = mountPanel(
      makeResult({
        report: {
          check_total: 0,
          check_pass: 0,
          check_fail: 0,
          crc_total: 0,
          crc_pass: 0,
          crc_rate: null,
          rc_total: 0,
          rc_pass: 0,
          rc_rate: null,
          failures: [],
          frames: [],
        },
      }),
    )
    expect(wrapper.text()).toContain(
      '没有执行任何校验：DBC 里没有匹配到保护信号，或没有配置 CRC 算法。',
    )
    expect(groupCounter(wrapper)).toBe('')
    wrapper.unmount()
  })

  it('全部通过时显示成功横幅而不是失败明细', () => {
    const wrapper = mountPanel(
      makeResult({
        report: {
          check_pass: 10,
          check_fail: 0,
          rc_pass: 5,
          failures: [],
        },
      }),
    )
    expect(wrapper.text()).toContain('全部通过：10 项校验（CRC 5 / RC 5）')
    expect(groupCounter(wrapper)).toBe('')
    wrapper.unmount()
  })

  it('trace 截断时显示帧上限提示', () => {
    const wrapper = mountPanel(
      makeResult({ report: { trace_truncated: true, trace_frame_limit: 50 } }),
    )
    expect(wrapper.text()).toContain(
      '只校验了前 50 帧（帧上限），其余帧未校验；以下通过率只代表这部分帧。',
    )
    wrapper.unmount()
  })
})
