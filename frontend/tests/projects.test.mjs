// node --test 单测:项目分组 / 结果表行构造 / 运行前置条件。

import test from 'node:test'
import assert from 'node:assert/strict'

import {
  canRun,
  failureRows,
  findProject,
  frameRows,
  groupByOem,
  summaryHighlights,
} from '../src/projects.js'

const projects = [
  { id: 'gac/eea40', oem: 'gac', model: 'eea40', summary: { crc: 'P5', dataid: '无' } },
  { id: 'gac/radar', oem: 'gac', model: 'radar', summary: {} },
  { id: 'baic/b81vs', oem: 'baic', model: 'b81vs', summary: {} },
]

test('groupByOem 按客户分组并保持后端顺序', () => {
  const groups = groupByOem(projects)
  assert.deepEqual(groups.map((g) => g.label), ['GAC', 'BAIC'])
  assert.equal(groups[0].items.length, 2)
  assert.deepEqual(groupByOem([]), [])
})

test('findProject 命中 / 未命中', () => {
  assert.equal(findProject(projects, 'baic/b81vs').model, 'b81vs')
  assert.equal(findProject(projects, 'nope'), null)
})

test('canRun 需要项目 + 文件 + 非运行中', () => {
  const base = { projectId: 'gac/eea40', file: { name: 't.blf' }, running: false }
  assert.equal(canRun(base), true)
  assert.equal(canRun({ ...base, projectId: '' }), false)
  assert.equal(canRun({ ...base, file: null }), false)
  assert.equal(canRun({ ...base, running: true }), false)
})

test('summaryHighlights 跳过默认值,只留值得看的项', () => {
  const items = summaryHighlights({
    summary: { crc: 'CRC16/CCITT', dataid: 'dataid.json', range: 'exclude_crc' },
  })
  assert.deepEqual(items.map((i) => i.label), ['算法', 'DataID'])

  const withRange = summaryHighlights({
    summary: { crc: 'C', range: 'custom_range', range_start: 0, range_end: 56 },
  })
  assert.equal(withRange.find((i) => i.label === '范围').value, 'custom_range_0..56')
})

test('failureRows 按报文+信号合并并累计次数', () => {
  const report = {
    failures: [
      { frame_id: 0x11b, signal: 'Checksum_A', timestamp: 1 },
      { frame_id: 0x11b, signal: 'Checksum_A', timestamp: 2 },
      { frame_id: 0x11b, signal: 'Checksum_B', timestamp: 3 },
    ],
  }
  const rows = failureRows(report)
  assert.equal(rows.length, 2)
  assert.equal(rows[0].count, 2)
  assert.equal(rows[0].last_timestamp, 2)
  assert.equal(rows[1].count, 1)
  assert.deepEqual(failureRows(null), [])
})

test('frameRows 可按只失败筛选', () => {
  const report = { frames: [{ frame_id: 1, fail: 0 }, { frame_id: 2, fail: 3 }] }
  assert.equal(frameRows(report).length, 2)
  assert.deepEqual(frameRows(report, true).map((f) => f.frame_id), [2])
  assert.deepEqual(frameRows(null, true), [])
})
