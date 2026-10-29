// RC 趋势图的纯几何:比例、刻度、折线/错误点坐标、悬停定位(无 DOM,可单测)。
// 视觉与 report/html.py 的内联 SVG 图一致:viewBox 0 0 1000 250。

export const PLOT = { x0: 44, x1: 984, y0: 210, y1: 14 }

function niceStep(span, target) {
  if (!(span > 0)) return 1
  const raw = span / target
  const mag = 10 ** Math.floor(Math.log10(raw))
  for (const m of [1, 2, 5, 10]) {
    if (raw <= m * mag) return m * mag
  }
  return 10 * mag
}

function tickDecimals(step) {
  if (step >= 1) return 0
  if (step >= 0.1) return 1
  if (step >= 0.01) return 2
  return 3
}

/**
 * 一张趋势图的几何。trend 形如 webapp 的 rc_trends 行:
 * { points: [[t, v, fail, cat], ...], t0, tspan, bit_max, max_valid, ... }
 */
export function rcChartGeometry(trend) {
  if (!trend || !trend.points || !trend.points.length) return null
  const { points, t0 } = trend
  const span = Math.max(trend.tspan || 0, 1e-9)
  let vSeen = 0
  for (const [, v] of points) vSeen = Math.max(vSeen, v)
  const yTop = Math.max(trend.bit_max || 15, vSeen, trend.max_valid || 0)

  const xOf = (t) => PLOT.x0 + ((t - t0) / span) * (PLOT.x1 - PLOT.x0)
  const yOf = (v) => PLOT.y0 - (v / yTop) * (PLOT.y0 - PLOT.y1)

  const xStep = niceStep(span, 6)
  const xDec = tickDecimals(xStep)
  const xTicks = []
  const n = Math.floor(span / xStep)
  for (let i = 0; i <= n; i++) {
    // 刻度位置覆盖 [t0, t0+span];标签是相对 t0 的时间
    const tRel = i * xStep
    xTicks.push({
      x: xOf(t0 + tRel),
      label: tRel.toFixed(xDec),
      anchor: i === 0 ? 'start' : (i === n ? 'end' : 'middle'),
    })
  }

  const yStep = niceStep(yTop, 5)
  const yDec = tickDecimals(yStep)
  const yTicks = []
  for (let v = 0; v <= yTop + 1e-9; v += yStep) {
    yTicks.push({ y: yOf(v), label: v.toFixed(yDec) })
  }

  const linePoints = points
    .map(([t, v]) => `${xOf(t).toFixed(2)},${yOf(v).toFixed(2)}`)
    .join(' ')
  const errDots = points
    .filter((p) => p[2] === 1)
    .map(([t, v, , cat]) => ({
      x: xOf(t), y: yOf(v), cat: cat || 'ERROR', t, v,
    }))

  const hasThreshold = trend.max_valid && 0 < trend.max_valid && trend.max_valid < yTop
  return {
    xTicks,
    yTicks,
    linePoints,
    errDots,
    thresholdY: hasThreshold ? yOf(trend.max_valid) : null,
    thresholdLabel: hasThreshold ? `max_valid ${trend.max_valid}` : '',
    t0,
    span,
    vmax: yTop,
    singlePoint: points.length === 1,
  }
}

/** 悬停:x(viewBox 坐标)→ 时间,再在按时间有序的 points 里二分找最近采样点。 */
export function rcNearest(points, t) {
  if (!points || !points.length) return null
  let lo = 0
  let hi = points.length - 1
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if (points[mid][0] < t) lo = mid + 1
    else hi = mid
  }
  if (lo > 0 && Math.abs(points[lo - 1][0] - t) < Math.abs(points[lo][0] - t)) lo -= 1
  return points[lo]
}

/** 悬停读数文案:信号名 · 精确时间 · 值(· 错误类别)。 */
export function rcReadout(signal, t, v, cat) {
  return `${signal} · t=${t.toFixed(4)}s · value=${v}${cat ? ` · ${cat}` : ''}`
}
