// node --test 单测:RC 趋势图几何(刻度/折线/错误点/阈值线)+ 悬停定位。

import test from 'node:test'
import assert from 'node:assert/strict'

import { PLOT, rcChartGeometry, rcNearest, rcReadout } from '../src/rcChart.js'

const trend = {
  signal: 'ACC_1_Counter',
  bit_max: 15,
  max_valid: 14,
  t0: 1000,
  tspan: 2.4,
  points: [
    [1000, 0, 0, ''],
    [1000.02, 1, 0, ''],
    [1000.04, 2, 0, ''],
    [1000.06, 15, 1, 'INVALID'],   // 超过 max_valid
    [1000.08, 0, 0, ''],
    [1000.10, 1, 0, ''],
  ],
}

test('rcChartGeometry 比例与折线坐标', () => {
  const geo = rcChartGeometry(trend)
  assert.ok(geo)
  // 第一/最后一点落在绘图区两端
  assert.ok(geo.linePoints.startsWith(`${PLOT.x0.toFixed(2)},`))
  assert.ok(geo.linePoints.endsWith(''), geo.linePoints)
  const parts = geo.linePoints.split(' ')
  assert.equal(parts.length, trend.points.length)
  // value 0 → 底部,value 15 → 顶部
  assert.equal(parts[0], `${PLOT.x0.toFixed(2)},${PLOT.y0.toFixed(2)}`)
  const top = PLOT.y0 - (15 / 15) * (PLOT.y0 - PLOT.y1)
  assert.equal(parts[3], `${(PLOT.x0 + (0.06 / 2.4) * (PLOT.x1 - PLOT.x0)).toFixed(2)},${top.toFixed(2)}`)
})

test('rcChartGeometry 错误点只取 fail=1 的帧', () => {
  const geo = rcChartGeometry(trend)
  assert.equal(geo.errDots.length, 1)
  assert.equal(geo.errDots[0].cat, 'INVALID')
  assert.equal(geo.errDots[0].v, 15)
})

test('rcChartGeometry 阈值线画在 max_valid 高度', () => {
  const geo = rcChartGeometry(trend)
  assert.equal(geo.thresholdY, PLOT.y0 - (14 / 15) * (PLOT.y0 - PLOT.y1))
  assert.equal(geo.thresholdLabel, 'max_valid 14')
  // max_valid 达到 y_top 时不画(与底/顶重合无意义)
  assert.equal(rcChartGeometry({ ...trend, max_valid: 15 }).thresholdY, null)
  assert.equal(rcChartGeometry({ ...trend, max_valid: null }).thresholdY, null)
})

test('rcChartGeometry x 刻度覆盖整个 span 且端点对齐', () => {
  const geo = rcChartGeometry(trend)
  assert.equal(geo.xTicks[0].x, PLOT.x0)
  assert.equal(geo.xTicks[0].anchor, 'start')
  assert.equal(geo.xTicks[geo.xTicks.length - 1].anchor, 'end')
  assert.equal(geo.yTicks[0].y, PLOT.y0)
  // 回归:t0 ≫ 0(epoch 时间戳)时刻度也要落在绘图区内
  assert.ok(geo.xTicks.every((tick) => tick.x >= PLOT.x0 && tick.x <= PLOT.x1),
    JSON.stringify(geo.xTicks.map((t) => t.x)))
})

test('rcChartGeometry t0 很大时刻度仍在绘图区内(epoch trace)', () => {
  const geo = rcChartGeometry({ ...trend, t0: 1780499422.0369 })
  assert.ok(geo.xTicks.length >= 2)
  assert.ok(geo.xTicks.every((tick) => tick.x >= PLOT.x0 && tick.x <= PLOT.x1),
    JSON.stringify(geo.xTicks.map((t) => t.x)))
  // 标签是相对 t0 的时间
  assert.equal(geo.xTicks[0].label, '0.0')
})

test('rcChartGeometry 空数据与单点', () => {
  assert.equal(rcChartGeometry(null), null)
  assert.equal(rcChartGeometry({ ...trend, points: [] }), null)
  const single = rcChartGeometry({ ...trend, points: [[1000, 7, 0, '']], tspan: 0 })
  assert.equal(single.singlePoint, true)
  assert.equal(single.errDots.length, 0)
})

test('rcNearest 二分命中/夹逼/边界', () => {
  const pts = trend.points
  assert.equal(rcNearest(pts, 1000.04)[1], 2)          // 精确命中
  assert.equal(rcNearest(pts, 1000.049)[1], 2)         // 偏向前一点 → 前一个
  assert.equal(rcNearest(pts, 1000.059)[1], 15)        // 偏向后一点 → 后一个
  assert.equal(rcNearest(pts, 1000.05)[1], 15)         // 距离相等时取后一个(严格 <)
  assert.equal(rcNearest(pts, 999)[1], 0)              // 下界夹逼
  assert.equal(rcNearest(pts, 2000)[1], 1)             // 上界夹逼
  assert.equal(rcNearest([], 1), null)
  assert.equal(rcNearest(null, 1), null)
})

test('rcReadout 带信号名与错误类别', () => {
  assert.equal(rcReadout('ACC_1', 1001.16, 13, ''),
    'ACC_1 · t=1001.1600s · value=13')
  assert.equal(rcReadout('ACC_1', 1001.16, 13, 'STALE'),
    'ACC_1 · t=1001.1600s · value=13 · STALE')
})
