<template>
  <el-dialog
    v-model="visible"
    title="交易决策依据"
    :fullscreen="isMobile"
    :width="isMobile ? '100%' : 'min(720px, 92vw)'"
    :top="isMobile ? '0' : '6vh'"
    destroy-on-close
  >
    <div v-loading="loading" class="trade-decision-dialog">
      <div v-if="row" class="td-summary">
        <div class="td-row">
          <span>日期</span><b>{{ row.date }}</b>
          <span>方向</span>
          <b :style="{ color: row.direction === 'buy' ? '#f56c6c' : '#67c23a' }">
            {{ row.direction === 'buy' ? '买入' : '卖出' }}
          </b>
          <span>标的</span><b>{{ row.code }} {{ row.name || '' }}</b>
        </div>
        <div class="td-row">
          <span>成交价</span><b>{{ Number(row.price ?? 0).toFixed(2) }}</b>
          <span>成交量</span><b>{{ Number(row.amount ?? 0).toLocaleString() }}</b>
          <span>成交额</span><b>{{ formatters.formatMoneyFull(row.value) }}</b>
        </div>
        <div class="td-reason">
          <span>策略理由</span>
          <div class="td-reason-body">
            <div class="reason-headline">{{ reason.headline }}</div>
            <ul v-if="reason.logs.length" class="reason-logs">
              <li v-for="(line, i) in reason.logs" :key="i">{{ line }}</li>
            </ul>
            <div class="reason-tags">
              <el-tag v-if="row.reason_source === 'generated'" size="small" type="warning" effect="plain">系统兜底说明（非策略显式提供）</el-tag>
              <el-tag v-else-if="row.reason_source === 'derived'" size="small" type="info" effect="plain">系统派生（来自策略日志/订单参数）</el-tag>
              <el-tag v-else-if="row.reason_source === 'strategy'" size="small" type="success" effect="plain">策略真实理由</el-tag>
              <el-tag v-else-if="row.reason_source" size="small" type="info" effect="plain">
                来源：{{ row.reason_source }}
              </el-tag>
            </div>
          </div>
        </div>
      </div>
      <div v-if="ai" class="td-ai">
        <span class="td-block-title">AI 综合评分</span>
        <el-tag :type="ai.gate === 'reject' ? 'danger' : 'success'" effect="plain" size="small">
          {{ ai.action || '--' }}
          <span v-if="ai.score != null"> · {{ Number(ai.score).toFixed(2) }}</span>
          <span v-if="ai.gate"> · gate: {{ ai.gate }}</span>
        </el-tag>
        <div v-if="ai.reason" class="td-ai-reason">
          <div v-if="ai.reason.reason_summary" class="ai-reason-summary">
            <strong>理由：</strong>{{ ai.reason.reason_summary }}
          </div>
          <div v-if="ai.reason.evidence" class="ai-reason-evidence">
            <strong>证据：</strong>{{ ai.reason.evidence }}
          </div>
          <div v-if="ai.reason.risk_flags" class="ai-reason-risk">
            <strong>风险标记：</strong>
            <el-tag type="danger" size="small" effect="plain" style="margin-left: 4px;">
              {{ ai.reason.risk_flags }}
            </el-tag>
          </div>
        </div>
      </div>
      <div v-if="strategyExplain" class="td-block td-strategy-explain">
        <span class="td-block-title">
          策略说明
          <span v-if="strategyExplain.name" class="td-block-sub">{{ strategyExplain.name }}</span>
          <el-tag :type="strategyExplain.isBuy ? 'danger' : 'success'" size="small" effect="plain" style="margin-left:6px;">
            {{ strategyExplain.isBuy ? '买入条件' : '卖出条件' }}
          </el-tag>
          <span v-if="strategyExplain.source" class="td-block-source">{{ strategyExplain.source }}</span>
        </span>
        <div class="strategy-explain-body">{{ strategyExplain.text }}</div>
      </div>
      <div class="td-block">
        <span class="td-block-title">决策规则对比</span>
        <el-table
          :data="rules"
          size="small"
          border
          empty-text="该策略未输出结构化决策规则（仅有理由文本，请参见上方'策略理由'与下方'指标快照'）"
          class="td-rules-table"
        >
          <el-table-column prop="name" label="指标/规则" min-width="160" show-overflow-tooltip />
          <el-table-column prop="threshold" label="阈值/判定" min-width="160" show-overflow-tooltip />
          <el-table-column prop="actual" label="实际数据" min-width="160" show-overflow-tooltip />
          <el-table-column label="结果" width="70" align="center">
            <template #default="{ row: ruleRow }">
              <el-tag :type="formatters.ruleResultTagType(ruleRow.pass)" size="small" effect="plain">
                {{ formatters.ruleResultLabel(ruleRow.pass) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="weight" label="权重" width="70" align="right">
            <template #default="{ row: ruleRow }">{{ ruleRow.weight != null ? Number(ruleRow.weight).toFixed(2) : '--' }}</template>
          </el-table-column>
        </el-table>
      </div>
      <div v-if="indicator" class="td-block">
        <span class="td-block-title">
          指标快照
          <span class="td-block-sub">{{ indicator.trade_date }}</span>
        </span>
        <el-descriptions :column="isMobile ? 1 : 4" border size="small" class="td-indicators">
          <el-descriptions-item label="开盘">{{ formatters.fmtNumDp(indicator.open_price) }}</el-descriptions-item>
          <el-descriptions-item label="收盘">{{ formatters.fmtNumDp(indicator.close_price) }}</el-descriptions-item>
          <el-descriptions-item label="最低">{{ formatters.fmtNumDp(indicator.low_price) }}</el-descriptions-item>
          <el-descriptions-item label="最高">{{ formatters.fmtNumDp(indicator.high_price) }}</el-descriptions-item>
          <el-descriptions-item label="成交量" :span="isMobile ? 1 : 4">{{ formatters.fmtVolumeHuman(indicator.volume) }}</el-descriptions-item>
          <el-descriptions-item label="MA" :span="isMobile ? 1 : 4">{{ formatters.fmtIndicatorDictMA(indicator.ma) }}</el-descriptions-item>
          <el-descriptions-item label="BOLL" :span="isMobile ? 1 : 4">{{ formatters.fmtIndicatorBOLL(indicator.boll) }}</el-descriptions-item>
          <el-descriptions-item label="RSI" :span="isMobile ? 1 : 4">{{ formatters.fmtIndicatorRSI(indicator.rsi) }}</el-descriptions-item>
          <el-descriptions-item label="MACD" :span="isMobile ? 1 : 4">{{ formatters.fmtIndicatorMACD(indicator.macd) }}</el-descriptions-item>
        </el-descriptions>
      </div>
    </div>
    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
interface ReasonParsed { headline: string; logs: string[] }
interface AiBlock {
  score: number | null
  action: string
  gate: string
  reason: { reason_summary?: string; evidence?: string; risk_flags?: string } | null
}
interface StrategyExplain { name: string; isBuy: boolean; text: string; source: string }
interface RuleRow {
  name: string
  threshold: string
  actual: string
  pass: boolean | null
  weight: number | null
  note?: string
}
interface IndicatorSnapshot {
  trade_date: string
  open_price: any
  close_price: any
  low_price: any
  high_price: any
  volume: any
  ma: any
  boll: any
  rsi: any
  macd: any
}
interface Formatters {
  formatMoneyFull: (v: number) => string
  fmtNumDp: (v: any, d?: number) => string
  fmtVolumeHuman: (v: any) => string
  fmtIndicatorDictMA: (v: any) => string
  fmtIndicatorBOLL: (v: any) => string
  fmtIndicatorRSI: (v: any) => string
  fmtIndicatorMACD: (v: any) => string
  ruleResultLabel: (pass: boolean | null) => string
  ruleResultTagType: (pass: boolean | null) => 'success' | 'warning' | 'info'
}

defineProps<{
  loading: boolean
  isMobile: boolean
  row: any
  reason: ReasonParsed
  ai: AiBlock | null
  strategyExplain: StrategyExplain | null
  rules: RuleRow[]
  indicator: IndicatorSnapshot | null
  formatters: Formatters
}>()

const visible = defineModel<boolean>('visible', { required: true })
</script>

<style scoped>
.trade-decision-dialog { display: flex; flex-direction: column; gap: 12px; }
.trade-decision-dialog .td-summary { background: #f7f8fa; padding: 10px 12px; border-radius: 4px; }
.trade-decision-dialog .td-row { display: flex; flex-wrap: wrap; gap: 14px; align-items: center; margin-bottom: 4px; font-size: 12px; }
.trade-decision-dialog .td-row > span { color: #909399; }
.trade-decision-dialog .td-row > b { color: #303133; font-weight: 600; margin-right: 12px; }
.trade-decision-dialog .td-reason { font-size: 12px; margin-top: 4px; display: flex; gap: 8px; align-items: flex-start; }
.trade-decision-dialog .td-reason > span { color: #909399; flex-shrink: 0; padding-top: 1px; }
.trade-decision-dialog .td-reason-body { flex: 1; min-width: 0; }
.trade-decision-dialog .td-reason-body .reason-headline {
  color: #303133; font-weight: 600; line-height: 1.6; word-break: break-all;
}
.trade-decision-dialog .td-reason-body .reason-logs {
  margin: 6px 0 0 0; padding: 8px 12px 8px 24px; list-style: disc;
  background: var(--el-fill-color-lighter, #f5f7fa); border-radius: 4px;
  font-size: 12px; line-height: 1.7; color: #606266;
}
.trade-decision-dialog .td-reason-body .reason-logs li { word-break: break-all; }
.trade-decision-dialog .td-reason-body .reason-tags { margin-top: 6px; display: flex; flex-wrap: wrap; gap: 4px; }
.trade-decision-dialog .td-block { display: flex; flex-direction: column; gap: 6px; }
.trade-decision-dialog .td-block-title { font-size: 13px; font-weight: 600; color: #303133; }
.trade-decision-dialog .td-block-title .td-block-sub {
  font-size: 12px; font-weight: 400; color: #909399; margin-left: 8px;
}
.trade-decision-dialog .td-block-title .td-block-source {
  font-size: 11px; font-weight: 400; color: #b1b3b8; margin-left: 8px;
}
.trade-decision-dialog .td-rules-table { font-size: 12px; }
.trade-decision-dialog .td-indicators { font-size: 12px; }
.trade-decision-dialog .td-indicators :deep(.el-descriptions__label) { width: 64px; color: #909399; font-weight: 500; }
.trade-decision-dialog .td-indicators :deep(.el-descriptions__content) {
  font-variant-numeric: tabular-nums; color: #303133; word-break: break-all;
}
.trade-decision-dialog .td-strategy-explain .strategy-explain-body {
  padding: 8px 12px; background: var(--el-fill-color-lighter, #f5f7fa);
  border-left: 3px solid var(--el-color-primary, #409eff); border-radius: 4px;
  font-size: 12px; line-height: 1.7; color: #303133; white-space: pre-wrap; word-break: break-all;
}
.trade-decision-dialog .td-ai { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.trade-decision-dialog .td-ai-reason {
  width: 100%;
  margin-top: 6px;
  padding: 8px 12px;
  background: var(--el-fill-color-lighter, #f5f7fa);
  border-radius: 4px;
  font-size: 12px;
  line-height: 1.6;
}
.td-ai-reason .ai-reason-summary,
.td-ai-reason .ai-reason-evidence,
.td-ai-reason .ai-reason-risk { margin-bottom: 4px; }
.td-ai-reason .ai-reason-risk:last-child { margin-bottom: 0; }
</style>
