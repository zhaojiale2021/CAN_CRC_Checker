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
            <span>选择映射来源与车型</span>
            <span class="muted">两种来源共用同一校验口径,可与 CLI 互相验证</span>
          </div>
        </template>

        <el-radio-group v-model="mappingSource" class="source-switch">
          <el-radio-button value="config">配置文件(项目目录)</el-radio-button>
          <el-radio-button value="firmware">固件源码(mcu_app_j6 commit 节点)</el-radio-button>
        </el-radio-group>

        <!-- ============ 配置文件模式 ============ -->
        <template v-if="mappingSource === 'config'">
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
        </template>

        <!-- ============ 固件源码模式 ============ -->
        <template v-else>
          <el-alert v-if="firmwareError" type="error" :closable="true" class="block"
                    :title="firmwareError" @close="firmwareError = ''" />
          <div class="firmware-grid">
            <el-select
              v-model="firmwareRepoId"
              placeholder="固件仓库"
              class="repo-select"
              @change="onFirmwareRepoChange"
            >
              <el-option
                v-for="repo in firmwareRepos"
                :key="repo.id"
                :label="repo.name"
                :value="repo.id"
              />
            </el-select>
            <el-input
              v-model="firmwareCommit"
              placeholder="commit / 分支 / tag(完整或短 SHA)"
              class="commit-input"
              clearable
            />
            <el-button
              type="primary"
              :loading="firmwareScanning"
              :disabled="!firmwareRepoId || !firmwareCommit.trim()"
              @click="scanFirmware"
            >
              扫描源码
            </el-button>
          </div>

          <div v-if="firmwareScanResult" class="project-detail">
            <div class="detail-row">
              <span class="muted">commit 节点</span>
              <span class="mono">{{ firmwareScanResult.resolved_commit.slice(0, 8) }}</span>
              <span v-if="firmwareScanResult.repository" class="muted">
                ({{ firmwareScanResult.repository.source === 'local' ? '本地工作副本' : '镜像克隆' }})
              </span>
              <span class="muted">{{ firmwareScanResult.models.length }} 个车型目录</span>
            </div>
          </div>

          <el-select
            v-model="firmwareModelId"
            filterable
            clearable
            placeholder="按固件车型选择(扫描后可选)"
            class="project-select"
            :disabled="!firmwareScanResult"
          >
            <el-option-group v-for="group in firmwareGroups" :key="group.label" :label="group.label">
              <el-option
                v-for="model in group.items"
                :key="model.id"
                :label="firmwareModelLabel(model)"
                :value="model.id"
                :disabled="!model.supported"
              />
            </el-option-group>
          </el-select>

          <div v-if="firmwareModel" class="project-detail">
            <div class="detail-row">
              <span class="muted">net_cfg</span>
              <span class="mono">{{ firmwareModel.path }}</span>
            </div>
            <div v-if="firmwareModel.last_commit" class="detail-row">
              <span class="muted">该车型 E2E 最近提交</span>
              <el-tag size="small" type="success" class="mono tag-gap">
                {{ firmwareModel.last_commit.commit.slice(0, 8) }}
              </el-tag>
              <span class="mono">{{ firmwareModel.last_commit.subject }}</span>
              <span class="muted">{{ formatCommitDate(firmwareModel.last_commit.committed_at) }}</span>
              <el-button size="small" link type="primary" @click="useModelLastCommit">
                用这个节点
              </el-button>
            </div>
            <div v-if="!firmwareModel.supported" class="detail-row">
              <span class="muted">{{ firmwareModel.reason }}</span>
            </div>
          </div>
        </template>
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
            <el-radio-group v-model="frameMode" size="small" :disabled="mappingSource === 'firmware'">
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
            <span v-if="mappingSource === 'firmware'" class="muted">
              固件模式默认不限(可切回配置文件模式再用配置默认)。
            </span>
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
import {
  fetchFirmwareRepos,
  fetchProjects,
  firmwareScan,
  firmwareVerify,
  verifyTrace,
} from './api.js'
import {
  canRun,
  canRunFirmware,
  firmwareModelLabel,
  findProject,
  groupByOem,
  groupFirmwareModels,
  summaryHighlights,
} from './projects.js'

const UPLOAD_LIMIT_MB = 200

// 映射来源:'config' = 项目目录的 config.json;'firmware' = mcu_app_j6 commit 节点
const mappingSource = ref('config')

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

// 固件源码模式状态
const firmwareRepos = ref([])
const firmwareRepoId = ref('')
const firmwareCommit = ref('')
const firmwareScanning = ref(false)
const firmwareError = ref('')
const firmwareScanResult = ref(null)
const firmwareModelId = ref('')

const uploadLimitMb = UPLOAD_LIMIT_MB
const projectGroups = computed(() => groupByOem(projects.value))
const project = computed(() => findProject(projects.value, projectId.value))
const highlights = computed(() => summaryHighlights(project.value))
const configMaxFrames = computed(() => project.value?.summary?.default_max_frames ?? null)

const firmwareGroups = computed(() => groupFirmwareModels(firmwareScanResult.value?.models))
const firmwareModel = computed(() => (firmwareScanResult.value?.models || [])
  .find((m) => m.id === firmwareModelId.value) || null)

const runnable = computed(() => {
  const base = {
    file: selectedFile.value,
    running: running.value,
  }
  if (mappingSource.value === 'firmware') {
    return canRunFirmware({
      ...base,
      repositoryId: firmwareRepoId.value,
      commit: firmwareCommit.value,
      modelId: firmwareModelId.value,
    })
  }
  return canRun({ ...base, projectId: projectId.value })
})

const prerequisite = computed(() => {
  if (mappingSource.value === 'firmware') {
    if (!firmwareRepoId.value) return '请先选择固件仓库。'
    if (!firmwareCommit.value.trim()) return '请填写固件 commit / 分支。'
    if (!firmwareScanResult.value) return '请先点击「扫描源码」。'
    if (!firmwareModelId.value) return '请选择车型。'
    if (!selectedFile.value) return '请先上传 trace 文件。'
    return ''
  }
  if (!projectId.value) return '请先选择项目。'
  if (!selectedFile.value) return '请先上传 trace 文件。'
  return ''
})

function projectLabel(item) {
  return `${item.oem.toUpperCase()} / ${item.model}`
}

function formatCommitDate(value) {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
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

function onFirmwareRepoChange() {
  firmwareScanResult.value = null
  firmwareModelId.value = ''
}

function useModelLastCommit() {
  const node = firmwareModel.value?.last_commit
  if (node?.commit) {
    firmwareCommit.value = node.commit
    ElMessage.success(`已切换到 ${node.commit.slice(0, 8)},请重新扫描`)
  }
}

async function scanFirmware() {
  firmwareScanning.value = true
  firmwareError.value = ''
  try {
    const scan = await firmwareScan({
      repositoryId: firmwareRepoId.value,
      commit: firmwareCommit.value,
    })
    firmwareScanResult.value = scan
    firmwareModelId.value = ''
    const supported = scan.models.filter((m) => m.supported).length
    ElMessage.success(
      `扫描完成:${scan.models.length} 个车型目录,其中 ${supported} 个支持源码模式`)
  } catch (err) {
    firmwareError.value = err.message
    firmwareScanResult.value = null
  } finally {
    firmwareScanning.value = false
  }
}

function maxFramesPayload() {
  if (mappingSource.value === 'firmware') return 0
  if (frameMode.value === 'unlimited') return 0
  if (frameMode.value === 'custom') return customFrames.value || null
  return null
}

async function run() {
  running.value = true
  runError.value = ''
  try {
    const common = {
      file: selectedFile.value,
      maxFrames: maxFramesPayload(),
      onlyFailures: onlyFailures.value,
    }
    result.value = mappingSource.value === 'firmware'
      ? await firmwareVerify({
        repositoryId: firmwareRepoId.value,
        commit: firmwareCommit.value,
        modelId: firmwareModelId.value,
        ...common,
      })
      : await verifyTrace({ projectId: projectId.value, ...common })
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

async function loadFirmwareRepos() {
  try {
    const data = await fetchFirmwareRepos()
    firmwareRepos.value = data.repositories || []
    if (firmwareRepos.value.length === 1) {
      firmwareRepoId.value = firmwareRepos.value[0].id
    }
  } catch {
    // 固件源码模式不可用不阻塞配置文件模式;选择时才提示。
    firmwareRepos.value = []
  }
}

onMounted(() => {
  loadProjects()
  loadFirmwareRepos()
})
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
.source-switch { margin-bottom: 16px; }
.project-select { width: 420px; max-width: 100%; margin-top: 8px; }
.firmware-grid { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 8px; }
.repo-select { width: 280px; }
.commit-input { width: 420px; max-width: 100%; font-family: 'SF Mono', Consolas, monospace; }
.project-detail { margin-top: 14px; display: flex; flex-direction: column; gap: 6px; }
.detail-row { display: flex; flex-wrap: wrap; gap: 18px; font-size: 12px;
              align-items: baseline; }
.detail-item { display: inline-flex; gap: 6px; align-items: baseline; }
.mono { font-family: 'SF Mono', Consolas, monospace; }
.muted { color: var(--el-text-color-secondary); font-size: 12px; }
.tag-gap { margin-left: 4px; }
.upload-text { color: var(--el-text-color-regular); }
.options { display: flex; flex-direction: column; gap: 14px; }
.option { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.option-label { width: 80px; color: var(--el-text-color-secondary); font-size: 13px; }
.run-bar { display: flex; align-items: center; gap: 14px; margin-top: 20px; }
</style>
