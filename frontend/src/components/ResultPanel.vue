<template>
  <div v-if="report" class="result-panel">
    <div class="cards">
      <div class="card">
        <div class="label">帧数</div>
        <div class="value">{{ report.total_frames }}</div>
      </div>
      <div class="card">
        <div class="label">校验项</div>
        <div class="value">{{ report.total_verdicts }}</div>
      </div>
      <div class="card pass">
        <div class="label">通过</div>
        <div class="value">{{ report.pass_count }}</div>
      </div>
      <div class="card" :class="{ fail: report.fail_count > 0 }">
        <div class="label">失败</div>
        <div class="value">{{ report.fail_count }}</div>
      </div>
      <div class="card" :class="report.fail_count ? 'fail' : 'pass'">
        <div class="label">总通过率</div>
        <div class="value">{{ formatPercent(report.pass_rate) }}</div>
      </div>
      <div class="card" :class="rateClass(report.crc_rate)">
        <div class="label">CRC</div>
        <div class="value">{{ formatPercent(report.crc_rate) }}</div>
        <div class="sub">{{ report.crc_pass }}/{{ report.crc_total }}</div>
      </div>
      <div class="card" :class="rateClass(report.rc_rate)">
        <div class="label">RollingCounter</div>
        <div class="value">{{ formatPercent(report.rc_rate) }}</div>
        <div class="sub">{{ report.rc_pass }}/{{ report.rc_total }}</div>
      </div>
      <div class="card">
        <div class="label">耗时</div>
        <div class="value">{{ formatDuration(result.elapsed_ms) }}</div>
      </div>
    </div>

    <div class="toolbar">
      <el-button type="primary" :disabled="!result.report_url" @click="openReport">
        下载 HTML 报告
      </el-button>
      <span class="muted">报告含逐帧十六进制视图与 CRC/RC 字节高亮。</span>
    </div>

    <el-collapse class="setup">
      <el-collapse-item name="setup">
        <template #title>
          <span class="setup-title">运行信息</span>
          <el-tag size="small" type="info" class="tag-gap">{{ setup.max_frames ?? '不限' }} 帧上限</el-tag>
          <el-tag size="small" type="info" class="tag-gap">{{ setup.dbc_names.length }} 个 DBC</el-tag>
          <el-tag v-if="setup.dataid_entries" size="small" type="info" class="tag-gap">
            DataID {{ setup.dataid_entries }} 条
          </el-tag>
        </template>
        <ul class="notes">
          <li v-for="(note, i) in setup.notes" :key="i" class="mono">{{ note }}</li>
        </ul>
        <p v-if="channelList.length" class="muted">
          通道映射:
          <span v-for="ch in channelList" :key="ch.channel" class="mono channel-gap">
            CH{{ ch.channel }} → {{ ch.dbc }}
          </span>
        </p>
      </el-collapse-item>
    </el-collapse>

    <el-alert
      v-if="!report.fail_count"
      type="success"
      :closable="false"
      class="all-pass"
      :title="`全部通过:${report.total_verdicts} 项校验(CRC ${report.crc_total} / RC ${report.rc_total})`"
    />

    <template v-else>
      <div class="section-head">
        <h3>失败明细</h3>
        <el-input
          v-model="failureSearch"
          size="small"
          clearable
          placeholder="按报文 / 信号 / 说明过滤"
          class="search"
        />
        <span class="muted">
          {{ filteredFailures.length }} 组 / {{ report.failures.length }} 条
          <template v-if="report.failures_truncated">(仅列出前 {{ report.failures.length }} 条)</template>
        </span>
      </div>
      <el-table :data="filteredFailures" size="small" class="table" max-height="520">
        <el-table-column label="报文" width="190">
          <template #default="{ row }">
            <span class="mono">{{ row.frame_id_hex }}</span>
            <span class="frame-name">{{ row.frame_name }}</span>
            <el-tag v-if="row.channel" size="small" type="info" class="tag-gap">CH{{ row.channel }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="signal" label="信号" min-width="150" />
        <el-table-column label="算法" width="170">
          <template #default="{ row }">
            <el-tag size="small" :type="row.algorithm === 'crc' ? 'primary' : 'success'">
              {{ row.crc_algorithm || (row.algorithm === 'crc' ? 'CRC' : 'RollingCounter') }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="期望" width="90">
          <template #default="{ row }"><span class="mono">{{ row.expected_hex }}</span></template>
        </el-table-column>
        <el-table-column label="实际" width="90">
          <template #default="{ row }"><span class="mono fail-text">{{ row.actual_hex }}</span></template>
        </el-table-column>
        <el-table-column prop="detail" label="说明" min-width="260" show-overflow-tooltip />
        <el-table-column label="次数" width="70">
          <template #default="{ row }">
            <span :class="{ 'fail-text': row.count > 1 }">{{ row.count }}</span>
          </template>
        </el-table-column>
      </el-table>
      <p v-if="report.failures.length" class="muted mono">
        首次失败时间 {{ formatTimestamp(report.failures[0].timestamp) }} s
      </p>
    </template>

    <div class="section-head">
      <h3>报文汇总</h3>
      <el-switch v-model="onlyFailingFrames" size="small" active-text="只看有失败的报文" />
      <span class="muted">{{ frameList.length }} 个报文</span>
    </div>
    <el-table :data="frameList" size="small" class="table" max-height="520">
      <el-table-column type="expand">
        <template #default="{ row }">
          <div class="signals">
            <div v-for="sig in row.signals" :key="sig.signal" class="signal-row">
              <span class="mono sig-name">{{ sig.signal }}</span>
              <el-tag size="small" :type="sig.algorithm === 'crc' ? 'primary' : 'success'">
                {{ sig.crc_algorithm || sig.algorithm }}
              </el-tag>
              <span class="mono" :class="sig.fail ? 'fail-text' : 'pass-text'">
                {{ sig.pass }}/{{ sig.total }} 通过
              </span>
              <span v-if="sig.last_detail" class="muted small">{{ sig.last_detail }}</span>
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="报文" width="200">
        <template #default="{ row }">
          <span class="mono">{{ row.frame_id_hex }}</span>
          <span class="frame-name">{{ row.frame_name }}</span>
        </template>
      </el-table-column>
      <el-table-column label="通道" width="80">
        <template #default="{ row }">CH{{ row.channel }}</template>
      </el-table-column>
      <el-table-column prop="dbc_source" label="DBC" min-width="180" show-overflow-tooltip />
      <el-table-column label="通过 / 总数" width="130">
        <template #default="{ row }">
          <span class="mono">{{ row.pass }}/{{ row.total }}</span>
        </template>
      </el-table-column>
      <el-table-column label="失败" width="90">
        <template #default="{ row }">
          <span class="mono" :class="{ 'fail-text': row.fail > 0 }">{{ row.fail }}</span>
        </template>
      </el-table-column>
      <el-table-column label="通过率" width="110">
        <template #default="{ row }">{{ formatPercent(row.rate) }}</template>
      </el-table-column>
    </el-table>
    <p v-if="report.frames_truncated" class="muted">
      报文较多,仅列出失败最多的前 {{ report.frames.length }} 个;完整内容见 HTML 报告。
    </p>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { formatDuration, formatPercent, formatTimestamp } from '../format.js'
import { failureRows, frameRows } from '../projects.js'

const props = defineProps({
  result: { type: Object, required: true },
})

const failureSearch = ref('')
const onlyFailingFrames = ref(false)

const report = computed(() => props.result?.reports?.[0] || null)
const setup = computed(() => props.result?.setup || { dbc_names: [] })

const channelList = computed(() => Object.entries(setup.value.channels || {})
  .map(([channel, dbc]) => ({ channel, dbc })))

const failures = computed(() => (report.value ? failureRows(report.value) : []))
const filteredFailures = computed(() => {
  const query = failureSearch.value.trim().toLowerCase()
  if (!query) return failures.value
  return failures.value.filter((row) => [
    row.frame_id_hex, row.frame_name, row.signal, row.detail, row.dbc_source,
  ].some((field) => String(field || '').toLowerCase().includes(query)))
})

const frameList = computed(() => (report.value
  ? frameRows(report.value, onlyFailingFrames.value)
  : []))

function rateClass(rate) {
  if (rate === null || rate === undefined) return ''
  return rate >= 1 ? 'pass' : 'fail'
}

function openReport() {
  // 同源下载:后端返回 Content-Disposition 附件。
  window.location.href = props.result.report_url
}
</script>

<style scoped>
.cards { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; }
.card { background: var(--el-fill-color-darker); border-radius: 8px;
        padding: 10px 18px; min-width: 110px; text-align: center; }
.card .label { font-size: 11px; color: var(--el-text-color-secondary);
               letter-spacing: .4px; }
.card .value { font-size: 22px; font-weight: 600; margin-top: 2px; }
.card .sub { font-size: 11px; color: var(--el-text-color-secondary); }
.card.pass .value { color: #2ecc71; }
.card.fail .value { color: #e74c3c; }
.toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.setup { margin-bottom: 16px; }
.setup-title { font-weight: 600; }
.notes { margin: 0; padding-left: 18px; font-size: 12px; line-height: 1.8;
         color: var(--el-text-color-regular); }
.mono { font-family: 'SF Mono', Consolas, monospace; }
.frame-name { margin-left: 6px; }
.tag-gap { margin-left: 6px; }
.channel-gap { margin-right: 12px; }
.section-head { display: flex; align-items: center; gap: 12px; margin: 18px 0 8px; }
.section-head h3 { margin: 0; font-size: 15px; }
.search { width: 260px; margin-left: auto; }
.table { width: 100%; }
.fail-text { color: #e74c3c; font-weight: 600; }
.pass-text { color: #2ecc71; }
.muted { color: var(--el-text-color-secondary); font-size: 12px; }
.small { font-size: 11px; }
.all-pass { margin-bottom: 8px; }
.signals { padding: 4px 8px; display: flex; flex-direction: column; gap: 6px; }
.signal-row { display: flex; align-items: center; gap: 10px; font-size: 12px; }
.sig-name { min-width: 170px; }
</style>
