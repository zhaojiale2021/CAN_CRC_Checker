<template>
  <div class="page">
    <header class="topbar">
      <div class="brand">
        <h1>CAN CRC Checker</h1>
        <span class="subtitle">DBC 感知的 CRC / Rolling Counter 校验(网页版)</span>
      </div>
      <VersionPanel />
    </header>

    <main class="content">
      <el-alert v-if="loadError" type="error" :closable="false" class="block"
                :title="`项目列表加载失败:${loadError}`" />

      <el-card class="block" shadow="never">
        <template #header>
          <div class="card-head">
            <span class="step">1</span>
            <span>选择项目</span>
            <span class="muted">DBC 与算法配置随项目目录一起发布,校验口径与 CLI 完全一致</span>
          </div>
        </template>
        <el-select
          v-model="projectId"
          filterable
          clearable
          placeholder="按客户 / 车型选择"
          class="project-select"
        >
          <el-option-group v-for="group in projectGroups" :key="group.label" :label="group.label">
            <el-option
              v-for="project in group.items"
              :key="project.id"
              :label="projectLabel(project)"
              :value="project.id"
            />
          </el-option-group>
        </el-select>

        <div v-if="project" class="project-detail">
          <div class="detail-row">
            <span v-for="item in highlights" :key="item.label" class="detail-item">
              <span class="muted">{{ item.label }}</span>
              <span class="mono">{{ item.value }}</span>
            </span>
          </div>
          <div class="detail-row muted">
            DBC:{{ project.dbc_files.join('、') || '无' }}
          </div>
          <div v-if="project.sample_traces.length" class="detail-row muted">
            仓库内示例 trace:{{ project.sample_traces.join('、') }}(请下载后用下方上传)
          </div>
        </div>
      </el-card>

      <el-card class="block" shadow="never">
        <template #header>
          <div class="card-head">
            <span class="step">2</span>
            <span>上传 trace</span>
            <span class="muted">BLF / ASC / MF4 / TRC / CSV,上限 {{ uploadLimitMb }}MB</span>
          </div>
        </template>
        <el-upload
          drag
          action="#"
          :auto-upload="false"
          :limit="1"
          :on-change="onFileChange"
          :on-remove="onFileRemove"
          :on-exceed="onFileExceed"
          :file-list="fileList"
        >
          <div class="upload-text">把 trace 文件拖到这里,或<em>点击选择</em></div>
          <template #tip>
            <div class="muted">文件只用于本次校验:服务端跑完即删除,仅保留生成的报告。</div>
          </template>
        </el-upload>
      </el-card>

      <el-card class="block" shadow="never">
        <template #header>
          <div class="card-head">
            <span class="step">3</span>
            <span>校验选项</span>
          </div>
        </template>
        <div class="options">
          <div class="option">
            <span class="option-label">帧数上限</span>
            <el-radio-group v-model="frameMode" size="small">
              <el-radio-button value="config">
                配置默认{{ configMaxFrames ? `(${configMaxFrames})` : '(不限)' }}
              </el-radio-button>
              <el-radio-button value="unlimited">不限</el-radio-button>
              <el-radio-button value="custom">自定义</el-radio-button>
            </el-radio-group>
            <el-input-number
              v-if="frameMode === 'custom'"
              v-model="customFrames"
              :min="1"
              :max="100000000"
              :step="1000"
              size="small"
              controls-position="right"
            />
          </div>
          <div class="option">
            <span class="option-label">HTML 报告</span>
            <el-switch v-model="onlyFailures" size="small" active-text="只写失败项" />
          </div>
        </div>

        <div class="run-bar">
          <el-button
            type="primary"
            size="large"
            :loading="running"
            :disabled="!runnable"
            @click="run"
          >
            {{ running ? '校验中…' : '开始校验' }}
          </el-button>
          <span v-if="!runnable && !running" class="muted">{{ prerequisite }}</span>
          <span v-else-if="running" class="muted">
            大 trace 可能需要几十秒,请勿关闭页面。
          </span>
        </div>
      </el-card>

      <el-alert
        v-if="runError"
        type="error"
        :closable="true"
        class="block"
        :title="runError"
        @close="runError = ''"
      />

      <el-card v-if="result" class="block" shadow="never">
        <template #header>
          <div class="card-head">
            <span class="step">4</span>
            <span>校验结果</span>
            <span class="muted mono">{{ result.trace_name }} · {{ result.project_id }}</span>
          </div>
        </template>
        <ResultPanel :result="result" />
      </el-card>
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import VersionPanel from './components/VersionPanel.vue'
import ResultPanel from './components/ResultPanel.vue'
import { fetchProjects, verifyTrace } from './api.js'
import { canRun, findProject, groupByOem, summaryHighlights } from './projects.js'

const UPLOAD_LIMIT_MB = 200

const projects = ref([])
const projectId = ref('')
const fileList = ref([])
const selectedFile = ref(null)
const frameMode = ref('config')
const customFrames = ref(10000)
const onlyFailures = ref(false)
const running = ref(false)
const loadError = ref('')
const runError = ref('')
const result = ref(null)

const uploadLimitMb = UPLOAD_LIMIT_MB
const projectGroups = computed(() => groupByOem(projects.value))
const project = computed(() => findProject(projects.value, projectId.value))
const highlights = computed(() => summaryHighlights(project.value))
const configMaxFrames = computed(() => project.value?.summary?.default_max_frames ?? null)
const runnable = computed(() => canRun({
  projectId: projectId.value,
  file: selectedFile.value,
  running: running.value,
}))
const prerequisite = computed(() => {
  if (!projectId.value) return '请先选择项目。'
  if (!selectedFile.value) return '请先上传 trace 文件。'
  return ''
})

function projectLabel(item) {
  return `${item.oem.toUpperCase()} / ${item.model}`
}

function onFileChange(uploadFile) {
  selectedFile.value = uploadFile.raw || null
  fileList.value = uploadFile.raw ? [uploadFile] : []
}

function onFileRemove() {
  selectedFile.value = null
  fileList.value = []
}

function onFileExceed() {
  ElMessage.warning('一次只能上传一个 trace 文件,请先移除已选文件。')
}

function maxFramesPayload() {
  if (frameMode.value === 'unlimited') return 0
  if (frameMode.value === 'custom') return customFrames.value || null
  return null
}

async function run() {
  running.value = true
  runError.value = ''
  try {
    result.value = await verifyTrace({
      projectId: projectId.value,
      file: selectedFile.value,
      maxFrames: maxFramesPayload(),
      onlyFailures: onlyFailures.value,
    })
    const report = result.value.reports?.[0]
    if (report && report.fail_count === 0) {
      ElMessage.success(`全部通过:${report.total_verdicts} 项校验`)
    } else if (report) {
      ElMessage.warning(`发现 ${report.fail_count} 项失败`)
    }
  } catch (err) {
    runError.value = err.message
    result.value = null
  } finally {
    running.value = false
  }
}

async function loadProjects() {
  try {
    const data = await fetchProjects()
    projects.value = data.projects || []
    loadError.value = ''
  } catch (err) {
    loadError.value = err.message
  }
}

onMounted(loadProjects)
</script>

<style scoped>
.page { min-height: 100vh; }
.topbar { display: flex; align-items: center; justify-content: space-between;
          padding: 14px 24px; border-bottom: 1px solid var(--el-border-color);
          background: var(--el-bg-color-overlay); }
.brand { display: flex; align-items: baseline; gap: 12px; }
.brand h1 { margin: 0; font-size: 18px; }
.subtitle { color: var(--el-text-color-secondary); font-size: 12px; }
.content { max-width: 1180px; margin: 0 auto; padding: 20px 24px 48px; }
.block { margin-bottom: 16px; }
.card-head { display: flex; align-items: center; gap: 10px; }
.card-head .muted { margin-left: auto; }
.step { display: inline-flex; align-items: center; justify-content: center;
        width: 20px; height: 20px; border-radius: 50%; font-size: 12px;
        background: var(--el-color-primary); color: #fff; }
.project-select { width: 420px; max-width: 100%; }
.project-detail { margin-top: 14px; display: flex; flex-direction: column; gap: 6px; }
.detail-row { display: flex; flex-wrap: wrap; gap: 18px; font-size: 12px; }
.detail-item { display: inline-flex; gap: 6px; align-items: baseline; }
.mono { font-family: 'SF Mono', Consolas, monospace; }
.muted { color: var(--el-text-color-secondary); font-size: 12px; }
.upload-text { color: var(--el-text-color-regular); }
.options { display: flex; flex-direction: column; gap: 14px; }
.option { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.option-label { width: 80px; color: var(--el-text-color-secondary); font-size: 13px; }
.run-bar { display: flex; align-items: center; gap: 14px; margin-top: 20px; }
</style>
