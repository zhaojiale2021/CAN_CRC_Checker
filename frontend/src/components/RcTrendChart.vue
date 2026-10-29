<template>
  <div class="trend-card">
    <div class="trend-head" @click="collapsed = !collapsed">
      <span class="arrow" :class="{ closed: collapsed }">&#9660;</span>
      <span class="mono id">{{ trend.frame_id_hex }}</span>
      <span class="mono name">{{ trend.signal }}</span>
      <span class="muted">({{ trend.frame_name }})</span>
      <el-tag v-if="trend.channel" size="small" type="info" class="tag-gap">
        CH{{ trend.channel }}
      </el-tag>
      <span class="muted stats">
        <template v-if="trend.errors">
          错误: <span class="fail-text">{{ trend.errors }}</span> 帧 /
          <span class="fail-text">{{ trend.episodes }}</span> 段
        </template>
        <template v-else><span class="pass-text">错误: 0</span></template>
        · 采样: {{ trend.samples }}
      </span>
    </div>
    <div v-show="!collapsed" class="trend-body">
      <svg v-if="geo" class="rc-svg" viewBox="0 0 1000 250"
           @pointermove="onMove" @pointerleave="onLeave">
        <template v-for="tick in geo.yTicks" :key="'gy' + tick.y">
          <line class="rc-grid" x1="44" :y1="tick.y" x2="984" :y2="tick.y" />
          <text class="rc-tick" x="38" :y="tick.y + 3" text-anchor="end">{{ tick.label }}</text>
        </template>
        <template v-for="tick in geo.xTicks" :key="'gx' + tick.x">
          <line class="rc-grid" :x1="tick.x" y1="14" :x2="tick.x" y2="210" />
          <text class="rc-tick" :x="tick.x" y="224" :text-anchor="tick.anchor">{{ tick.label }}</text>
        </template>
        <line v-if="geo.thresholdY !== null" class="rc-threshold"
              x1="44" :y1="geo.thresholdY" x2="984" :y2="geo.thresholdY" />
        <text v-if="geo.thresholdY !== null" class="rc-thr-label"
              x="984" :y="geo.thresholdY - 3" text-anchor="end">{{ geo.thresholdLabel }}</text>
        <line class="rc-axis" x1="44" y1="210" x2="984" y2="210" />
        <circle v-if="geo.singlePoint" :cx="singleX" :cy="singleY" r="4"
                fill="#3987e5" stroke="#16213e" stroke-width="2" />
        <polyline v-else class="rc-line" :points="geo.linePoints"
                  marker-start="url(#rc-pt)" marker-mid="url(#rc-pt)" marker-end="url(#rc-pt)" />
        <circle v-for="dot in geo.errDots" :key="'e' + dot.x + '-' + dot.y"
                class="rc-err-dot" :cx="dot.x" :cy="dot.y" r="4" :data-cat="dot.cat">
          <title>{{ trend.signal }} · {{ dot.t.toFixed(6) }}s · value={{ dot.v }} · {{ dot.cat }}</title>
        </circle>
        <line v-if="crossX !== null" class="rc-crosshair" :x1="crossX" y1="14" :x2="crossX" y2="210" />
      </svg>
      <div class="rc-readout" :style="{ visibility: readout ? 'visible' : 'hidden' }">
        {{ readout }}
      </div>
      <div class="rc-note mono">
        t0 = {{ trend.t0.toFixed(6) }}s · span {{ trend.tspan.toFixed(6) }}s
      </div>
    </div>
  </div>
</template>

<script setup>
// 一张 RC 趋势折线图:几何在 rcChart.js(纯函数);悬停走 rAF 节流,
// 最近点在按时间有序的 points 上二分查找(无逐次 DOM 扫描)。
import { computed, onBeforeUnmount, ref } from 'vue'
import { PLOT, rcChartGeometry, rcNearest, rcReadout } from '../rcChart.js'

const props = defineProps({
  trend: { type: Object, required: true },
})

const collapsed = ref(props.trend.errors === 0)   // 有错误的默认展开
const readout = ref('')
const crossX = ref(null)
let raf = 0

const geo = computed(() => rcChartGeometry(props.trend))
const singlePoint = computed(() => (props.trend.points || [])[0])
const singleX = computed(() => (singlePoint.value
  ? ((singlePoint.value[0] - geo.value.t0) / geo.value.span) * (PLOT.x1 - PLOT.x0) + PLOT.x0
  : 0))
const singleY = computed(() => (singlePoint.value
  ? PLOT.y0 - (singlePoint.value[1] / geo.value.vmax) * (PLOT.y0 - PLOT.y1)
  : 0))

function onMove(evt) {
  if (raf) return
  // currentTarget 只在事件派发期间有效,rAF 回调里要先用局部量接住
  const svg = evt.currentTarget
  const clientX = evt.clientX
  raf = requestAnimationFrame(() => {
    raf = 0
    if (!svg || !geo.value) return
    const rect = svg.getBoundingClientRect()
    if (!rect.width) return
    const vx = ((clientX - rect.left) / rect.width) * 1000
    const t = geo.value.t0 + ((vx - PLOT.x0) / (PLOT.x1 - PLOT.x0)) * geo.value.span
    const point = rcNearest(props.trend.points, t)
    if (!point) return
    readout.value = rcReadout(props.trend.signal, point[0], point[1], point[3])
    crossX.value = PLOT.x0 + ((point[0] - geo.value.t0) / geo.value.span) * (PLOT.x1 - PLOT.x0)
  })
}

function onLeave() {
  if (raf) {
    cancelAnimationFrame(raf)
    raf = 0
  }
  readout.value = ''
  crossX.value = null
}

onBeforeUnmount(() => {
  if (raf) cancelAnimationFrame(raf)
})
</script>

<style scoped>
.trend-card { background: var(--el-fill-color-darker); border-radius: 8px;
              margin-bottom: 10px; overflow: hidden; }
.trend-head { display: flex; align-items: center; gap: 10px; padding: 8px 14px;
              background: var(--el-fill-color-dark); cursor: pointer;
              user-select: none; font-size: 13px; }
.trend-head .id { font-weight: 600; min-width: 64px; }
.trend-head .name { font-weight: 600; }
.trend-head .stats { margin-left: auto; }
.arrow { transition: transform .2s; color: var(--el-text-color-secondary); font-size: 11px; }
.arrow.closed { transform: rotate(-90deg); }
.trend-body { position: relative; padding: 10px 12px 4px; }
.rc-svg { width: 100%; height: auto; display: block; }
.rc-line { fill: none; stroke: #3987e5; stroke-width: 2;
           stroke-linejoin: round; stroke-linecap: round; }
.rc-grid { stroke: var(--el-border-color-lighter); stroke-width: 1; }
.rc-axis { stroke: var(--el-border-color); stroke-width: 1; }
.rc-tick { fill: var(--el-text-color-secondary); font-size: 10px;
           font-family: 'SF Mono', Consolas, monospace;
           font-variant-numeric: tabular-nums; }
.rc-threshold { stroke: #fab219; stroke-width: 1; }
.rc-thr-label { fill: var(--el-text-color-secondary); font-size: 9px;
                font-family: 'SF Mono', Consolas, monospace; }
.rc-err-dot { fill: #e74c3c; stroke: var(--el-fill-color-darker); stroke-width: 2;
              cursor: default; }
.rc-crosshair { stroke: var(--el-text-color-secondary); stroke-width: 1; }
.rc-readout { position: absolute; top: 16px; right: 20px; font-size: 11px;
              background: var(--el-mask-color); padding: 3px 8px;
              border-radius: 4px; white-space: nowrap; max-width: 80%;
              overflow: hidden; text-overflow: ellipsis; pointer-events: none;
              font-family: 'SF Mono', Consolas, monospace; }
.rc-note { font-size: 10px; color: var(--el-text-color-secondary);
           padding: 2px 4px 6px; }
.fail-text { color: #e74c3c; font-weight: 600; }
.pass-text { color: #2ecc71; }
.tag-gap { margin-left: 6px; }
</style>
