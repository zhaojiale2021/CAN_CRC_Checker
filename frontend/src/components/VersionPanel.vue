<template>
  <div class="version-panel">
    <el-tooltip :content="tooltip" placement="bottom">
      <el-button size="small" :loading="loading" @click="open">
        {{ loading ? '读取版本…' : label }}
      </el-button>
    </el-tooltip>

    <el-dialog v-model="visible" title="部署版本(commit 节点)" width="620px">
      <el-alert
        v-if="error"
        type="error"
        :closable="false"
        :title="`版本不可用:${error}`"
        class="version-alert"
      />
      <template v-else>
        <el-alert
          v-if="changed"
          type="warning"
          :closable="false"
          class="version-alert"
          title="部署目录与服务启动时的版本状态不同"
          description="更新后端代码后需重启服务;仅更新静态页面可能已生效(刷新浏览器即可)。"
        />
        <el-descriptions :column="1" border>
          <el-descriptions-item label="运行 commit(服务启动时)">
            <code class="mono">{{ running.commit || '未知' }}</code>
            <el-tag v-if="running.dirty" type="warning" size="small" class="tag-gap">有修改</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="分支">
            <code class="mono">{{ running.branch || '未知' }}</code>
          </el-descriptions-item>
          <el-descriptions-item label="提交说明">
            {{ running.subject || '未知' }}
            <span v-if="running.committed_at" class="muted">（{{ formatTime(running.committed_at) }}）</span>
          </el-descriptions-item>
          <el-descriptions-item label="服务启动时间">
            {{ formatTime(startedAt) }}
          </el-descriptions-item>
          <el-descriptions-item label="当前部署目录 commit">
            <code class="mono">{{ checkout.commit || '未知' }}</code>
            <el-tag v-if="checkout.dirty" type="warning" size="small" class="tag-gap">有修改</el-tag>
          </el-descriptions-item>
        </el-descriptions>
        <p class="hint">
          运行 commit 在服务加载时固定;部署目录的 commit 每次查询单独读取,因此
          <code>git pull</code> 后未重启服务时两者会不一致。缺少 <code>.git</code> 或
          Git 不可用时显示“版本未知”,不影响校验功能。
        </p>
      </template>
      <template #footer>
        <el-button @click="load">刷新版本</el-button>
        <el-button type="primary" :disabled="!running.commit" @click="copyCommit">
          复制运行 commit
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchVersion } from '../api.js'
import { checkoutChanged, versionLabel } from '../format.js'

const info = ref(null)
const loading = ref(false)
const error = ref('')
const visible = ref(false)

const running = computed(() => info.value?.running || {})
const checkout = computed(() => info.value?.checkout || {})
const changed = computed(() => checkoutChanged(info.value))
const startedAt = computed(() => info.value?.started_at || '')
const label = computed(() => (error.value ? '版本不可用' : versionLabel(running.value)))
const tooltip = computed(() => (changed.value
  ? '部署目录与运行版本不一致,点击查看'
  : '点击查看部署版本(commit)'))

function formatTime(value) {
  if (!value) return '未知'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

async function load() {
  loading.value = true
  try {
    info.value = await fetchVersion()
    error.value = ''
  } catch (err) {
    // 版本信息拿不到不影响校验:仅在按钮与弹窗里如实显示。
    error.value = err.message
    info.value = null
  } finally {
    loading.value = false
  }
}

function open() {
  visible.value = true
  load()
}

async function copyCommit() {
  const commit = running.value.commit
  try {
    await navigator.clipboard.writeText(commit)
  } catch {
    const area = document.createElement('textarea')
    area.value = commit
    document.body.appendChild(area)
    area.select()
    document.execCommand('copy')
    area.remove()
  }
  ElMessage.success(`已复制 ${commit.slice(0, 7)}`)
}

onMounted(load)
</script>

<style scoped>
.version-alert { margin-bottom: 12px; }
.mono { font-family: 'SF Mono', Consolas, monospace; }
.tag-gap { margin-left: 8px; }
.muted { color: var(--el-text-color-secondary); }
.hint { margin-top: 12px; color: var(--el-text-color-secondary);
        font-size: 12px; line-height: 1.7; }
</style>
