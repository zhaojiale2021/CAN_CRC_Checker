// node --test 单测:展示格式化(与 UI 框架解耦的纯函数)。

import test from 'node:test'
import assert from 'node:assert/strict'

import {
  checkoutChanged,
  fileName,
  formatBytes,
  formatDuration,
  formatPercent,
  formatRate,
  formatTimestamp,
  shortCommit,
  versionLabel,
} from '../src/format.js'

test('formatBytes 按 1024 进制并保留一位小数', () => {
  assert.equal(formatBytes(0), '0 B')
  assert.equal(formatBytes(999), '999 B')
  assert.equal(formatBytes(1536), '1.5 KB')
  assert.equal(formatBytes(25 * 1024 * 1024), '25.0 MB')
  assert.equal(formatBytes(null), '-')
})

test('formatDuration 在毫秒/秒/分钟之间切换', () => {
  assert.equal(formatDuration(415), '415 ms')
  assert.equal(formatDuration(2500), '2.50 s')
  assert.equal(formatDuration(63000), '1 min 3 s')
  assert.equal(formatDuration(undefined), '-')
})

test('formatPercent 保留两位小数', () => {
  assert.equal(formatPercent(1), '100.00%')
  assert.equal(formatPercent(0.9771), '97.71%')
  assert.equal(formatPercent(null), '-')
})

test('formatTimestamp 保留微秒', () => {
  assert.equal(formatTimestamp(12.345678), '12.345678')
})

test('versionLabel:commit 短号 + 有修改 / 版本未知', () => {
  assert.equal(versionLabel({ commit: 'abcdef1234567890', dirty: false }), '版本 abcdef1')
  assert.equal(versionLabel({ commit: 'abcdef1234567890', dirty: true }), '版本 abcdef1 · 有修改')
  assert.equal(versionLabel({ commit: null, dirty: null }), '版本未知')
  assert.equal(versionLabel(null), '版本未知')
  assert.equal(shortCommit(null), '')
})

test('checkoutChanged 只有 true 才算不一致(null = 版本未知)', () => {
  assert.equal(checkoutChanged({ checkout_changed: true }), true)
  assert.equal(checkoutChanged({ checkout_changed: false }), false)
  assert.equal(checkoutChanged({ checkout_changed: null }), false)
  assert.equal(checkoutChanged(null), false)
})

test('fileName 同时处理正反斜杠路径', () => {
  assert.equal(fileName('D:\\work\\projects\\demo\\a.dbc'), 'a.dbc')
  assert.equal(fileName('/root/crc/a.dbc'), 'a.dbc')
  assert.equal(fileName(''), '')
})

test('formatRate 有失败时不四舍五入成 100.00%', () => {
  assert.equal(formatRate(3, 3), '100.00%')
  assert.equal(formatRate(4217, 4218), '99.98%')
  assert.equal(formatRate(244587, 244588), '99.9996%')
  assert.equal(formatRate(187556, 187890), '99.82%')
  assert.equal(formatRate(0, 0), '-')
  assert.equal(formatRate(1, null), '-')
})
