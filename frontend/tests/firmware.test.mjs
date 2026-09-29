// node --test 单测:固件源码模式的纯逻辑(分组/校验前置/车型文案)。

import test from 'node:test'
import assert from 'node:assert/strict'

import {
  canRunFirmware,
  firmwareModelLabel,
  groupFirmwareModels,
} from '../src/projects.js'

const models = [
  { id: 'cpj_gac/s52', oem: 'cpj_gac', name: 's52', supported: true },
  { id: 'cpj_gac/t09', oem: 'cpj_gac', name: 't09', supported: true },
  { id: 'cpj_gwm/de09g', oem: 'cpj_gwm', name: 'de09g', supported: false },
]

test('groupFirmwareModels 去掉 cpj_ 前缀按 OEM 分组', () => {
  const groups = groupFirmwareModels(models)
  assert.deepEqual(groups.map((g) => g.label), ['GAC', 'GWM'])
  assert.equal(groups[0].items.length, 2)
  assert.deepEqual(groupFirmwareModels([]), [])
})

test('canRunFirmware 需要仓库 + commit + 车型 + 文件', () => {
  const base = {
    repositoryId: 'mcu_app_j6',
    commit: '31bd82bcf',
    modelId: 'cpj_gac/s52',
    file: { name: 't.blf' },
    running: false,
  }
  assert.equal(canRunFirmware(base), true)
  assert.equal(canRunFirmware({ ...base, repositoryId: '' }), false)
  assert.equal(canRunFirmware({ ...base, commit: '   ' }), false)
  assert.equal(canRunFirmware({ ...base, modelId: '' }), false)
  assert.equal(canRunFirmware({ ...base, file: null }), false)
  assert.equal(canRunFirmware({ ...base, running: true }), false)
})

test('firmwareModelLabel 标出暂不支持', () => {
  assert.equal(firmwareModelLabel(models[0]), 's52')
  assert.equal(firmwareModelLabel(models[2]), 'de09g(暂不支持源码模式)')
})
