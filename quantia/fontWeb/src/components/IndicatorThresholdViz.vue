<script setup lang="ts">
/**
 * 指标买入/卖出信号 —— 阈值确认逻辑可视化说明。
 *
 * 把「多指标同时满足（AND 逻辑）」的确认机制画成刻度条：
 * 每个指标显示自身值域、阈值位置与「触发区间」，
 * 并配 AND 逻辑徽标 + 追涨/超买（或超卖）风险提示。
 *
 * 数据来源：直接读取策略参数组（paramGroups），
 * 因此用户在本页调整阈值后，可视化会同步更新。
 */
import { computed } from 'vue'

interface ParamItem {
  key: string
  label?: string
  value: number
}
interface ParamGroupLike {
  params: ParamItem[]
}

const props = defineProps<{
  strategyKey: string
  paramGroups: ParamGroupLike[]
}>()

const isBuy = computed(() => props.strategyKey === 'indicator_buy')

// 每个指标的值域与展示信息（base key 去掉 _min/_max 后缀）
const META: Record<string, { label: string; domain: [number, number]; desc: string }> = {
  kdjk: { label: 'KDJ-K', domain: [0, 100], desc: '随机指标快线' },
  kdjd: { label: 'KDJ-D', domain: [0, 100], desc: '随机指标慢线' },
  kdjj: { label: 'KDJ-J', domain: [0, 120], desc: 'KDJ 的 J 值，可超过 100' },
  rsi6: { label: 'RSI(6)', domain: [0, 100], desc: '6 日相对强弱' },
  cci: { label: 'CCI', domain: [-250, 250], desc: '顺势指标' },
  cr: { label: 'CR', domain: [0, 500], desc: '人气能量指标' },
  wr6: { label: 'WR(6)', domain: [-100, 0], desc: '威廉指标，越接近 0 越强' },
  vr: { label: 'VR', domain: [0, 400], desc: '成交量比率' },
}

interface Bar {
  baseKey: string
  label: string
  desc: string
  domain: [number, number]
  threshold: number
  op: string
  thresholdPct: number
  zoneStart: number
  zoneWidth: number
}

const bars = computed<Bar[]>(() => {
  const out: Bar[] = []
  for (const group of props.paramGroups || []) {
    for (const p of group.params || []) {
      const base = p.key.replace(/_(min|max)$/, '')
      const meta = META[base]
      if (!meta || typeof p.value !== 'number') continue
      const [lo, hi] = meta.domain
      const t = Math.min(Math.max(p.value, lo), hi)
      const pct = ((t - lo) / (hi - lo)) * 100
      const buy = isBuy.value
      // 买入：触发区在阈值右侧（>= 阈值）；卖出：触发区在阈值左侧（< 阈值）
      const zoneStart = buy ? pct : 0
      const zoneWidth = buy ? 100 - pct : pct
      out.push({
        baseKey: base,
        label: meta.label,
        desc: meta.desc,
        domain: meta.domain,
        threshold: p.value,
        op: buy ? '≥' : '<',
        thresholdPct: pct,
        zoneStart,
        zoneWidth,
      })
    }
  }
  return out
})
</script>

<template>
  <el-card shadow="never" class="threshold-viz-card">
    <template #header>
      <div class="viz-header">
        <span class="viz-title">
          {{ isBuy ? '📈 指标买入信号 · 阈值确认逻辑' : '📉 指标卖出信号 · 阈值确认逻辑' }}
        </span>
        <el-tag size="small" :type="isBuy ? 'danger' : 'success'" effect="dark">
          AND 逻辑 · {{ bars.length }} 项指标须同时满足
        </el-tag>
      </div>
    </template>

    <!-- 机制说明 -->
    <el-alert
      :type="isBuy ? 'warning' : 'info'"
      :closable="false"
      class="viz-note"
    >
      <template #title>
        <span v-if="isBuy">
          本信号在 <b>所有指标同时进入超买区</b> 时触发——本质是<b>强势股「追涨」/动量确认</b>，
          <b>不是低位抄底</b>。超买不代表立即下跌，需结合趋势方向，注意短线回调风险。
        </span>
        <span v-else>
          本信号在 <b>所有指标同时进入超卖区</b> 时触发，用于超跌反弹或底部确认。
          超卖可能长期持续，不能机械买入。
        </span>
      </template>
    </el-alert>

    <!-- 刻度条 -->
    <div class="bar-list">
      <div v-for="b in bars" :key="b.baseKey" class="bar-row">
        <div class="bar-label">
          <span class="ind-name">{{ b.label }}</span>
          <span class="ind-cond" :class="isBuy ? 'cond-buy' : 'cond-sell'">
            {{ b.op }} {{ b.threshold }}
          </span>
        </div>
        <div class="bar-track">
          <!-- 触发区间高亮 -->
          <div
            class="bar-zone"
            :class="isBuy ? 'zone-buy' : 'zone-sell'"
            :style="{ left: b.zoneStart + '%', width: b.zoneWidth + '%' }"
          ></div>
          <!-- 阈值刻度线 -->
          <div class="bar-marker" :style="{ left: b.thresholdPct + '%' }">
            <span class="marker-val">{{ b.threshold }}</span>
          </div>
        </div>
        <div class="bar-domain">
          <span>{{ b.domain[0] }}</span>
          <span class="domain-desc">{{ b.desc }}</span>
          <span>{{ b.domain[1] }}</span>
        </div>
      </div>
    </div>

    <div class="viz-foot">
      <el-icon><InfoFilled /></el-icon>
      高亮区间为「触发区」：仅当某股票该指标当日值落入<b>全部</b>指标的触发区时，才会被列入{{ isBuy ? '买入' : '卖出' }}信号。
    </div>
  </el-card>
</template>

<style scoped>
.threshold-viz-card {
  margin-top: 12px;
  border: 1px solid var(--el-border-color-light);
}
.viz-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.viz-title {
  font-weight: 600;
  font-size: 14px;
}
.viz-note {
  margin-bottom: 16px;
  line-height: 1.6;
}
.bar-list {
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.bar-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.bar-label {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.ind-name {
  font-weight: 600;
  font-size: 13px;
  min-width: 64px;
}
.ind-cond {
  font-family: 'JetBrains Mono', Consolas, monospace;
  font-size: 13px;
  font-weight: 600;
  padding: 1px 8px;
  border-radius: 4px;
}
.cond-buy {
  color: var(--el-color-danger);
  background: var(--el-color-danger-light-9);
}
.cond-sell {
  color: var(--el-color-success);
  background: var(--el-color-success-light-9);
}
.bar-track {
  position: relative;
  height: 14px;
  background: var(--el-fill-color-light);
  border-radius: 7px;
  overflow: visible;
}
.bar-zone {
  position: absolute;
  top: 0;
  height: 100%;
  border-radius: 7px;
}
.zone-buy {
  background: linear-gradient(90deg, var(--el-color-danger-light-7), var(--el-color-danger-light-5));
}
.zone-sell {
  background: linear-gradient(90deg, var(--el-color-success-light-5), var(--el-color-success-light-7));
}
.bar-marker {
  position: absolute;
  top: -4px;
  width: 2px;
  height: 22px;
  background: var(--el-text-color-primary);
  transform: translateX(-1px);
}
.marker-val {
  position: absolute;
  top: -18px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
  color: var(--el-text-color-primary);
}
.bar-domain {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}
.domain-desc {
  color: var(--el-text-color-placeholder);
}
.viz-foot {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px dashed var(--el-border-color-light);
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
  display: flex;
  align-items: flex-start;
  gap: 6px;
}
</style>
