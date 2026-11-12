<template>
  <div class="page">
    <header class="topbar">
      <div class="brand">
        <h1>CAN CRC Checker</h1>
        <span class="subtitle"
          >DBC 感知的 CRC / Rolling Counter 校验（网页版）</span
        >
      </div>
      <VersionPanel />
    </header>

    <main class="content">
      <el-alert
        v-if="loadError"
        type="error"
        :closable="false"
        class="block"
        :title="`项目列表加载失败：${loadError}`"
      />

      <el-card class="block" shadow="never">
        <div class="mode-bar">
          <el-radio-group v-model="mode">
            <el-radio-button value="project">项目配置</el-radio-button>
            <el-radio-button value="manual"
              >手动上传 DBC + trace</el-radio-button
            >
          </el-radio-group>
          <span class="muted">
            {{
              mode === 'project'
                ? '项目配置来自服务端 projects/ 目录，与 CLI 共用同一校验口径'
                : '无需服务端项目：上传 DBC 与 trace 后，在页面上填写原 config.json 的参数'
            }}
          </span>
        </div>
      </el-card>

      <!-- 1. 项目 / DBC -->
      <el-card v-if="mode === 'project'" class="block" shadow="never">
        <template #header>
          <div class="card-head">
            <span class="step">1</span>
            <span>选择项目</span>
            <span class="muted"
              >项目配置来自服务端扫描的 projects/ 目录，与 CLI
              共用同一校验口径</span
            >
          </div>
        </template>

        <el-select
          v-model="projectId"
          filterable
          clearable
          placeholder="按分组 / 项目选择"
          class="project-select"
        >
          <el-option-group
            v-for="group in projectGroups"
            :key="group.label"
            :label="group.label"
          >
            <el-option
              v-for="projectItem in group.items"
              :key="projectItem.id"
              :label="projectLabel(projectItem)"
              :value="projectItem.id"
            />
          </el-option-group>
        </el-select>
        <div v-if="!projects.length && !loadError" class="empty-projects">
          <span class="muted"
            >服务端没有扫描到项目。可以直接上传 DBC 和 trace 手动校验。</span
          >
          <el-button size="small" type="primary" plain @click="mode = 'manual'">
            切到手动上传
          </el-button>
        </div>

        <div v-if="project" class="project-detail">
          <div class="detail-row">
            <span
              v-for="item in highlights"
              :key="item.label"
              class="detail-item"
            >
              <span class="muted">{{ item.label }}</span>
              <span class="mono">{{ item.value }}</span>
            </span>
          </div>
          <div class="detail-row muted">
            DBC：{{ project.dbc_files.join('、') || '无' }}
          </div>
          <div v-if="project.sample_traces.length" class="detail-row">
            <span class="muted">仓库内示例 trace：</span>
            <el-button
              v-for="traceName in project.sample_traces"
              :key="traceName"
              size="small"
              link
              type="primary"
              :disabled="running"
              @click="runSample(traceName)"
            >
              {{ traceName }}
            </el-button>
            <span class="muted">点击直接校验，无需上传</span>
          </div>
        </div>
      </el-card>

      <el-card v-else class="block" shadow="never">
        <template #header>
          <div class="card-head">
            <span class="step">1</span>
            <span>上传 DBC</span>
            <span class="muted"
              >可多选；校验时按 trace 通道自动选择最匹配的 DBC</span
            >
          </div>
        </template>
        <el-upload
          drag
          multiple
          action="#"
          accept=".dbc"
          :auto-upload="false"
          :limit="limits.maxDbcFiles"
          :on-change="onDbcChange"
          :on-remove="onDbcRemove"
          :on-exceed="onDbcExceed"
          :file-list="dbcList"
        >
          <div class="upload-text">
            把 DBC 文件拖到这里，或<em>点击选择</em>（可多选）
          </div>
          <template #tip>
            <div class="muted">
              上限 {{ limits.maxDbcFiles }} 个；多个 DBC 可用下方「合并所有
              DBC」改成单一映射。
            </div>
          </template>
        </el-upload>
        <div v-if="dbcFiles.length" class="detail-row muted selected-files">
          已选：{{ dbcFiles.map((f) => f.name).join('、') }}
        </div>
      </el-card>

      <!-- 2. trace (+ 手动模式的 DataID) -->
      <el-card class="block" shadow="never">
        <template #header>
          <div class="card-head">
            <span class="step">2</span>
            <span>上传 trace{{ mode === 'manual' ? ' / DataID' : '' }}</span>
            <span class="muted"
              >BLF / ASC / MF4 / TRC / CSV，上限
              {{ limits.maxUploadMb }}MB</span
            >
          </div>
        </template>
        <el-upload
          drag
          action="#"
          accept=".blf,.asc,.mf4,.trc,.csv,.log,.txt"
          :auto-upload="false"
          :limit="1"
          :on-change="onFileChange"
          :on-remove="onFileRemove"
          :on-exceed="onFileExceed"
          :file-list="fileList"
        >
          <div class="upload-text">
            把 trace 文件拖到这里，或<em>点击选择</em>
          </div>
          <template #tip>
            <div class="muted">
              文件只用于本次校验：服务端跑完即删除，仅保留生成的报告。
            </div>
          </template>
        </el-upload>

        <div v-if="mode === 'manual'" class="option dataid-upload">
          <span class="option-label">DataID</span>
          <el-upload
            action="#"
            accept=".json,.xlsx,.xls"
            :auto-upload="false"
            :limit="1"
            :on-change="onDataidChange"
            :on-remove="onDataidRemove"
            :on-exceed="onDataidExceed"
            :file-list="dataidList"
          >
            <el-button size="small">选择 DataID 文件（可选）</el-button>
            <template #tip>
              <div class="muted">
                预处理后的 .json 或 .xlsx/.xls；不传则不使用 DataID。
              </div>
            </template>
          </el-upload>
          <span v-if="dataidFile" class="muted mono">{{
            dataidFile.name
          }}</span>
        </div>
      </el-card>

      <!-- 3. 算法与校验选项 -->
      <el-card class="block" shadow="never">
        <template #header>
          <div class="card-head">
            <span class="step">3</span>
            <span>校验选项</span>
            <span v-if="mode === 'manual'" class="muted"
              >对应 CLI config.json 的 crc / range / dataid / rc / signals
              段</span
            >
          </div>
        </template>

        <ManualOptionsForm
          v-model:config="manualConfig"
          :mode="mode"
          :presets="presets"
          :preset-error="presetError"
        />

        <div class="options">
          <div class="option">
            <span class="option-label">帧数上限</span>
            <el-radio-group v-model="frameMode" size="small">
              <el-radio-button value="config"
                >配置默认{{ frameDefaultLabel }}</el-radio-button
              >
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
            <span
              v-if="frameMode === 'unlimited' && !onlyFailures"
              class="muted"
            >
              大 trace 逐帧报告很大，超上限会自动降级成只写失败项。
            </span>
          </div>
          <div class="option">
            <span class="option-label">HTML 报告</span>
            <el-switch
              v-model="onlyFailures"
              size="small"
              active-text="只写失败项"
            />
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
          <span v-if="!runnable && !running" class="muted">{{
            prerequisite
          }}</span>
          <span v-else-if="running" class="muted">
            大 trace 可能需要几十秒，请勿关闭页面。
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

      <el-card v-if="result" id="result-panel" class="block" shadow="never">
        <template #header>
          <div class="card-head">
            <span class="step">4</span>
            <span>校验结果</span>
            <span class="muted mono">
              {{ result.trace_name }} ·
              {{ resultProjectLabel(result.project_id) }}
            </span>
          </div>
        </template>
        <ResultPanel :result="result" />
      </el-card>
    </main>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import VersionPanel from './components/VersionPanel.vue'
import ResultPanel from './components/ResultPanel.vue'
import ManualOptionsForm from './components/ManualOptionsForm.vue'
import {
  fetchLimits,
  fetchPresets,
  fetchProjects,
  verifyManual,
  verifySample,
  verifyTrace,
} from './api.js'
import {
  canRun,
  findProject,
  groupByOem,
  summaryHighlights,
} from './projects.js'
import { manualCanRun, resultProjectLabel } from './manualConfig.js'

// 限额的内置兜底值:/api/limits 拉取失败时页面仍可用。
const DEFAULT_LIMITS = {
  maxUploadMb: 200,
  maxDbcFiles: 10,
  manualDefaultFrames: 6000,
}

const mode = ref('project')

const limits = reactive({ ...DEFAULT_LIMITS })

const projects = ref([])
const projectId = ref('')
const fileList = ref([])
const selectedFile = ref(null)
const frameMode = ref('config')
const customFrames = ref(DEFAULT_LIMITS.manualDefaultFrames)
const onlyFailures = ref(false)
const running = ref(false)
const loadError = ref('')
const runError = ref('')
const result = ref(null)

// 手动模式
const presets = ref([])
const presetError = ref('')
const dbcList = ref([])
const dbcFiles = ref([])
const dataidList = ref([])
const dataidFile = ref(null)
const manualConfig = ref({})

const uploadLimitBytes = computed(() => limits.maxUploadMb * 1024 * 1024)
const projectGroups = computed(() => groupByOem(projects.value))
const project = computed(() => findProject(projects.value, projectId.value))
const highlights = computed(() => summaryHighlights(project.value))
const configMaxFrames = computed(
  () => project.value?.summary?.default_max_frames ?? null,
)
const frameDefaultLabel = computed(() => {
  if (mode.value === 'project') {
    return configMaxFrames.value ? `（${configMaxFrames.value}）` : '（不限）'
  }
  return `（${limits.manualDefaultFrames}）`
})

const runnable = computed(() =>
  mode.value === 'project'
    ? canRun({
        projectId: projectId.value,
        file: selectedFile.value,
        running: running.value,
      })
    : manualCanRun({
        dbcFiles: dbcFiles.value,
        traceFile: selectedFile.value,
        running: running.value,
      }),
)

const prerequisite = computed(() => {
  if (mode.value === 'project') {
    if (!projectId.value) return '请先选择项目。'
    if (!selectedFile.value) return '请先上传 trace 文件。'
    return ''
  }
  if (!dbcFiles.value.length) return '请先上传至少一个 DBC 文件。'
  if (!selectedFile.value) return '请先上传 trace 文件。'
  return ''
})

function projectLabel(item) {
  return `${item.oem.toUpperCase()} / ${item.model}`
}

function onFileChange(uploadFile) {
  if (uploadFile.raw && uploadFile.raw.size > uploadLimitBytes.value) {
    ElMessage.error(
      `trace 文件超过 ${limits.maxUploadMb}MB 上限，请截取日志后重试。`,
    )
    selectedFile.value = null
    fileList.value = []
    return
  }
  selectedFile.value = uploadFile.raw || null
  fileList.value = uploadFile.raw ? [uploadFile] : []
}

function onFileRemove() {
  selectedFile.value = null
  fileList.value = []
}

function onFileExceed() {
  ElMessage.warning('一次只能上传一个 trace 文件，请先移除已选文件。')
}

function onDbcChange(_uploadFile, uploadFiles) {
  dbcList.value = [...uploadFiles]
  dbcFiles.value = uploadFiles.map((item) => item.raw).filter(Boolean)
}

function onDbcRemove(_uploadFile, uploadFiles) {
  dbcList.value = [...uploadFiles]
  dbcFiles.value = uploadFiles.map((item) => item.raw).filter(Boolean)
}

function onDbcExceed() {
  ElMessage.warning(`最多一次上传 ${limits.maxDbcFiles} 个 DBC 文件。`)
}

function onDataidChange(uploadFile) {
  dataidFile.value = uploadFile.raw || null
  dataidList.value = uploadFile.raw ? [uploadFile] : []
}

function onDataidRemove() {
  dataidFile.value = null
  dataidList.value = []
}

function onDataidExceed() {
  ElMessage.warning('一次只能上传一个 DataID 文件，请先移除已选文件。')
}

function maxFramesPayload() {
  if (frameMode.value === 'unlimited') return 0
  if (frameMode.value === 'custom') return customFrames.value || null
  return null
}

function reportMessage(payload) {
  const report = payload.reports?.[0]
  if (!report) return
  if (report.check_total === 0) {
    ElMessage.warning(
      '没有执行任何校验：DBC 里没有匹配到保护信号，或没有配置 CRC 算法。',
    )
  } else if (report.check_fail === 0) {
    ElMessage.success(`全部通过：${report.check_total} 项校验`)
  } else {
    ElMessage.warning(`发现 ${report.check_fail} 项失败（按逐帧采样计数）`)
  }
}

async function showResult(payload) {
  result.value = payload
  reportMessage(payload)
  await nextTick()
  document.getElementById('result-panel')?.scrollIntoView({
    behavior: 'smooth',
    block: 'start',
  })
}

async function run() {
  running.value = true
  runError.value = ''
  try {
    if (mode.value === 'manual') {
      await showResult(
        await verifyManual({
          dbcs: dbcFiles.value,
          trace: selectedFile.value,
          dataid: dataidFile.value,
          config: manualConfig.value,
          maxFrames: maxFramesPayload(),
          onlyFailures: onlyFailures.value,
        }),
      )
    } else {
      await showResult(
        await verifyTrace({
          projectId: projectId.value,
          file: selectedFile.value,
          maxFrames: maxFramesPayload(),
          onlyFailures: onlyFailures.value,
        }),
      )
    }
  } catch (err) {
    runError.value = err.message
    result.value = null
  } finally {
    running.value = false
  }
}

async function runSample(traceName) {
  running.value = true
  runError.value = ''
  try {
    await showResult(
      await verifySample({
        projectId: projectId.value,
        traceName,
        maxFrames: maxFramesPayload(),
        onlyFailures: onlyFailures.value,
      }),
    )
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
    // A single project is the common local case; preselect it so the page is
    // one upload away from a result instead of asking for a pointless choice.
    if (projects.value.length === 1) {
      projectId.value = projects.value[0].id
    }
    loadError.value = ''
  } catch (err) {
    loadError.value = err.message
  }
}

async function loadPresets() {
  try {
    const data = await fetchPresets()
    presets.value = data.presets || []
    presetError.value = ''
  } catch (err) {
    presetError.value = err.message
  }
}

async function loadLimits() {
  try {
    const data = await fetchLimits()
    if (Number.isFinite(data.max_upload_mb))
      limits.maxUploadMb = data.max_upload_mb
    if (Number.isFinite(data.max_dbc_files))
      limits.maxDbcFiles = data.max_dbc_files
    if (Number.isFinite(data.manual_default_frames)) {
      limits.manualDefaultFrames = data.manual_default_frames
      // 自定义帧数输入框还停在兜底默认值时,跟随服务端默认帧数
      if (customFrames.value === DEFAULT_LIMITS.manualDefaultFrames) {
        customFrames.value = data.manual_default_frames
      }
    }
  } catch {
    // 拉取失败保持兜底值,不打扰用户
  }
}

onMounted(() => {
  loadProjects()
  loadPresets()
  loadLimits()
})
</script>

<style scoped>
.page {
  min-height: 100vh;
}
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 24px;
  border-bottom: 1px solid var(--el-border-color);
  background: var(--el-bg-color-overlay);
}
.brand {
  display: flex;
  align-items: baseline;
  gap: 12px;
}
.brand h1 {
  margin: 0;
  font-size: 18px;
}
.subtitle {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.content {
  max-width: 1180px;
  margin: 0 auto;
  padding: 20px 24px 48px;
}
.block {
  margin-bottom: 16px;
}
.card-head {
  display: flex;
  align-items: center;
  gap: 10px;
}
.card-head .muted {
  margin-left: auto;
}
.step {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  font-size: 12px;
  background: var(--el-color-primary);
  color: #fff;
}
.mode-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}
.project-select {
  width: 420px;
  max-width: 100%;
  margin-top: 8px;
}
.empty-projects {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 12px;
}
.project-detail {
  margin-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.detail-row {
  display: flex;
  flex-wrap: wrap;
  gap: 18px;
  font-size: 12px;
  align-items: baseline;
}
.detail-item {
  display: inline-flex;
  gap: 6px;
  align-items: baseline;
}
.selected-files {
  margin-top: 10px;
}
.mono {
  font-family: 'SF Mono', Consolas, monospace;
}
.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.upload-text {
  color: var(--el-text-color-regular);
}
.run-bar {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 20px;
  position: sticky;
  bottom: 0;
  z-index: 5;
  padding: 12px 0;
  background: var(--el-bg-color);
  border-top: 1px solid var(--el-border-color-lighter);
}
</style>
