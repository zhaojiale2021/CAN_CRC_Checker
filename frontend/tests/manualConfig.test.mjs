// node --test 单测:手动上传模式的 config 构造 / 帧 ID 解析 / 运行前置条件。

import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildManualConfig,
  manualCanRun,
  parseFrameIds,
  resultProjectLabel,
} from '../src/manualConfig.js'

test('parseFrameIds 支持逗号/空格/分号,忽略空项', () => {
  assert.deepEqual(parseFrameIds('0x143, 299  0x300'), [
    '0x143',
    '299',
    '0x300',
  ])
  assert.deepEqual(parseFrameIds(' 0x1;0x2 '), ['0x1', '0x2'])
  assert.deepEqual(parseFrameIds(''), [])
  assert.deepEqual(parseFrameIds(null), [])
})

test('buildManualConfig 总是带默认 crc/range/dataid', () => {
  const config = buildManualConfig({})
  assert.deepEqual(config.crc, {
    byte_swap: false,
    auto_classify: false,
    profile_by_width: false,
  })
  assert.deepEqual(config.range, {
    mode: 'exclude_crc',
    start_byte: 0,
    end_byte: -1,
  })
  assert.deepEqual(config.dataid, { position: 'prepend', byte_order: 'lo_hi' })
  // 没有填写的可选项不出现,避免覆盖服务端/框架默认值
  assert.equal('preset' in config.crc, false)
  assert.equal('filter' in config, false)
  assert.equal('rc' in config, false)
  assert.equal('signals' in config, false)
})

test('buildManualConfig 收集算法与范围选项', () => {
  const config = buildManualConfig({
    preset: 'CRC8/SAE-J1850-ZERO',
    byteSwap: true,
    autoClassify: true,
    profileByWidth: true,
    dbcMerge: true,
    rangeMode: 'custom_range',
    rangeStart: 2,
    rangeEnd: 32,
  })
  assert.equal(config.crc.preset, 'CRC8/SAE-J1850-ZERO')
  assert.equal(config.crc.byte_swap, true)
  assert.equal(config.crc.auto_classify, true)
  assert.equal(config.crc.profile_by_width, true)
  assert.equal(config.dbc_merge, true)
  assert.deepEqual(config.range, {
    mode: 'custom_range',
    start_byte: 2,
    end_byte: 32,
  })
})

test('buildManualConfig 收集 DataID / RC / 高级项', () => {
  const config = buildManualConfig({
    dataidPosition: 'append',
    dataidByteOrder: 'hi_lo',
    dataidSheet: 'DBC_V2.5 ADAS1',
    dataidMapping: 'greatwall_j6m',
    dataidDefault: '0x0000',
    rcMaxValid: 14,
    frameIds: '0x143, 0x299',
    checksumPattern: '^Checksum_',
    rcPattern: '^RollingCounter_',
  })
  assert.deepEqual(config.dataid, {
    position: 'append',
    byte_order: 'hi_lo',
    sheet: 'DBC_V2.5 ADAS1',
    mapping: 'greatwall_j6m',
    default: '0x0000',
  })
  assert.deepEqual(config.rc, { max_valid: 14 })
  assert.deepEqual(config.filter, { frame_ids: ['0x143', '0x299'] })
  assert.deepEqual(config.signals, {
    checksum_pattern: '^Checksum_',
    rc_pattern: '^RollingCounter_',
  })
})

test('manualCanRun 需要至少一个 DBC + trace + 非运行中', () => {
  const base = {
    dbcFiles: [{ name: 'a.dbc' }],
    traceFile: { name: 't.blf' },
    running: false,
  }
  assert.equal(manualCanRun(base), true)
  assert.equal(manualCanRun({ ...base, dbcFiles: [] }), false)
  assert.equal(manualCanRun({ ...base, traceFile: null }), false)
  assert.equal(manualCanRun({ ...base, running: true }), false)
})

test('resultProjectLabel 把 manual 显示为手动配置', () => {
  assert.equal(resultProjectLabel('manual'), '手动配置')
  assert.equal(resultProjectLabel('examples/example'), 'examples/example')
})
