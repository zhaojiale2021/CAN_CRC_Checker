<template>
  <div v-if="mode === 'manual'" class="options algorithm-form">
    <el-alert
      v-if="presetError"
      type="warning"
      :closable="false"
      :title="`算法列表加载失败：${presetError}（仍可手填配置或按 DBC 注释识别）`"
    />

    <div class="option">
      <span class="option-label">算法</span>
      <el-select
        v-model="form.preset"
        clearable
        filterable
        class="algo-select"
        placeholder="不指定（只校验 RC）"
      >
        <el-option label="不指定（只校验 RC）" value="" />
        <el-option
          v-for="item in presets"
          :key="item.name"
          :label="item.name"
          :value="item.name"
        >
          <span class="mono">{{ item.name }}</span>
          <el-tag
            size="small"
            class="opt-tag"
            :type="item.validated ? 'success' : 'info'"
          >
            {{ item.validated ? '已验证' : '未验证' }}
          </el-tag>
        </el-option>
      </el-select>
      <span class="muted">未验证 = 仓库里没有用真实 trace 跑通过</span>
    </div>

    <div class="option">
      <span class="option-label">开关</span>
      <el-checkbox v-model="form.byteSwap">字节交换（Profile 5）</el-checkbox>
      <el-checkbox v-model="form.autoClassify">按 DBC 注释识别算法</el-checkbox>
      <el-checkbox v-model="form.profileByWidth"
        >按 CRC 宽度选 E2E Profile</el-checkbox
      >
      <el-checkbox v-model="form.dbcMerge">合并所有 DBC</el-checkbox>
    </div>

    <div class="option">
      <span class="option-label">CRC 范围</span>
      <el-radio-group v-model="form.rangeMode" size="small">
        <el-radio-button value="exclude_crc">排除 CRC 字节</el-radio-button>
        <el-radio-button value="full_payload">整帧</el-radio-button>
        <el-radio-button value="custom_range">自定义</el-radio-button>
      </el-radio-group>
      <template v-if="form.rangeMode === 'custom_range'">
        <el-input-number
          v-model="form.rangeStart"
          :min="0"
          :max="64"
          size="small"
          controls-position="right"
        />
        <span class="muted">..</span>
        <el-input-number
          v-model="form.rangeEnd"
          :min="-1"
          :max="64"
          size="small"
          controls-position="right"
        />
        <span class="muted">末字节（-1 = 帧尾）</span>
      </template>
    </div>

    <div class="option">
      <span class="option-label">DataID</span>
      <el-select
        v-model="form.dataidPosition"
        size="small"
        class="small-select"
      >
        <el-option label="前置 prepend" value="prepend" />
        <el-option label="后置 append" value="append" />
      </el-select>
      <el-select
        v-model="form.dataidByteOrder"
        size="small"
        class="small-select"
      >
        <el-option label="低字节在前 lo_hi" value="lo_hi" />
        <el-option label="高字节在前 hi_lo" value="hi_lo" />
      </el-select>
    </div>

    <div class="option">
      <span class="option-label">RC 上限</span>
      <el-input-number
        v-model="form.rcMaxValid"
        :min="0"
        :max="255"
        size="small"
        controls-position="right"
      />
      <span class="muted">留空 = 按计数器位宽自动（2^N - 1）</span>
    </div>

    <el-collapse class="advanced">
      <el-collapse-item
        title="高级：帧过滤 / 信号正则 / DataID 细节"
        name="advanced"
      >
        <div class="options">
          <div class="option">
            <span class="option-label">帧 ID</span>
            <el-input
              v-model="form.frameIds"
              placeholder="0x143, 0x299（留空 = 全部）"
            />
          </div>
          <div class="option">
            <span class="option-label">Checksum 正则</span>
            <el-input
              v-model="form.checksumPattern"
              placeholder="留空 = 内置命名规则"
            />
          </div>
          <div class="option">
            <span class="option-label">RC 正则</span>
            <el-input
              v-model="form.rcPattern"
              placeholder="留空 = 内置命名规则"
            />
          </div>
          <div class="option">
            <span class="option-label">DataID sheet</span>
            <el-input
              v-model="form.dataidSheet"
              placeholder="xlsx 工作表名（留空 = 自动匹配）"
            />
          </div>
          <div class="option">
            <span class="option-label">DataID 映射</span>
            <el-input
              v-model="form.dataidMapping"
              placeholder="如 hi_lo_two_cols（留空 = 默认）"
            />
          </div>
          <div class="option">
            <span class="option-label">DataID 默认值</span>
            <el-input
              v-model="form.dataidDefault"
              placeholder="如 0x0000（留空 = 不使用）"
            />
          </div>
        </div>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<script setup>
import { reactive, watch } from 'vue'
import { buildManualConfig } from '../manualConfig.js'

defineProps({
  mode: { type: String, required: true },
  presets: { type: Array, default: () => [] },
  presetError: { type: String, default: '' },
})

const emit = defineEmits(['update:config'])

const form = reactive({
  preset: '',
  byteSwap: false,
  autoClassify: false,
  profileByWidth: false,
  dbcMerge: false,
  rangeMode: 'exclude_crc',
  rangeStart: 0,
  rangeEnd: -1,
  dataidPosition: 'prepend',
  dataidByteOrder: 'lo_hi',
  dataidSheet: '',
  dataidMapping: '',
  dataidDefault: '',
  rcMaxValid: null,
  frameIds: '',
  checksumPattern: '',
  rcPattern: '',
})

watch(form, (state) => emit('update:config', buildManualConfig(state)), {
  deep: true,
  immediate: true,
})
</script>

<style scoped>
.options {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.algorithm-form {
  margin-bottom: 22px;
  padding-bottom: 18px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.option {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}
.option-label {
  width: 100px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.algo-select {
  width: 280px;
}
.small-select {
  width: 150px;
}
.opt-tag {
  float: right;
  margin-left: 10px;
}
.advanced {
  margin-top: 2px;
}
.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.mono {
  font-family: 'SF Mono', Consolas, monospace;
}
</style>
