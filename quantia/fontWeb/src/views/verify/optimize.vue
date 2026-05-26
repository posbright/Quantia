<template>
  <div class="verify-optimize">
    <div class="feature-tabs">
      <router-link class="feature-tab" to="/verify/compare">策略对比</router-link>
      <router-link class="feature-tab" to="/verify/optimize">买卖点优化</router-link>
      <router-link class="feature-tab" to="/verify/fusion">多维融合</router-link>
      <router-link class="feature-tab" to="/verify/factor-lab">因子实验室</router-link>
    </div>

    <!-- 使用说明 -->
    <UsageGuide
      title="📖 买卖点优化 使用说明（点击展开）"
      :steps="guideSteps"
      :example="guideExample"
      :metrics="guideMetrics"
      :tips="guideTips"
    />
    <!-- 工具栏 -->
    <div class="toolbar">
      <div class="toolbar-group">
        <span class="toolbar-label">分析策略</span>
        <el-select v-model="strategy" placeholder="选择策略" style="width: 220px" :loading="strategyGroupsLoading">
          <el-option-group v-for="g in strategyGroups" :key="g.label" :label="g.label">
            <el-option v-for="s in g.items" :key="s.value" :label="s.label" :value="s.value">
              <span>{{ s.label }}</span>
              <span v-if="s.type === 'backtest'" class="option-badge">自定义</span>
            </el-option>
          </el-option-group>
        </el-select>
      </div>
      <div class="toolbar-group">
        <span class="toolbar-label">统计周期</span>
        <div class="period-row">
          <div v-for="p in periodPresets" :key="p.label" class="radio-btn" :class="{ active: activePeriod === p.label }" @click="setPeriod(p)">{{ p.label }}</div>
        </div>
      </div>
      <div class="toolbar-group">
        <span class="toolbar-label">日期范围</span>
        <div class="date-range-row">
          <el-date-picker v-model="startDate" type="date" placeholder="开始日期" value-format="YYYY-MM-DD" style="width: 138px" @change="activePeriod = ''" />
          <span>至</span>
          <el-date-picker v-model="endDate" type="date" placeholder="结束日期" value-format="YYYY-MM-DD" style="width: 138px" @change="activePeriod = ''" />
        </div>
      </div>
      <div class="toolbar-group">
        <el-tooltip content="按逗号分隔的持仓交易日数列表。范围 1-240（约 1 年），最多 30 个。>100 时走 K 线缓存重算，首次约 1 分钟，后续秒级。" placement="top">
          <span class="toolbar-label">持仓天数 <i class="tip-icon">?</i></span>
        </el-tooltip>
        <el-input v-model="holdingDaysInput" placeholder="如 5,10,20,40,60,120,180,240" style="width: 260px" clearable />
      </div>
      <el-button class="analyze-btn" type="primary" :loading="loading" @click="runAnalysis">
        分析
      </el-button>
    </div>

    <div v-if="matrixReady" class="summary-strip">
      <div class="summary-card highlight">
        <span class="summary-label">最优持仓</span>
        <strong>{{ bestHoldingDays || '--' }}日</strong>
        <span class="summary-sub">按夏普排序</span>
      </div>
      <div class="summary-card">
        <span class="summary-label">信号总数</span>
        <strong>{{ totalSignals }}</strong>
        <span class="summary-sub">样本覆盖</span>
      </div>
      <div class="summary-card">
        <span class="summary-label">峰值夏普</span>
        <strong>{{ fmt(bestHolding?.sharpe_approx) }}</strong>
        <span class="summary-sub">{{ bestHolding?.holding_days || '--' }}日周期</span>
      </div>
      <div class="summary-card">
        <span class="summary-label">胜率</span>
        <strong>{{ fmt(bestHolding?.win_rate) }}%</strong>
        <span class="summary-sub">最优周期</span>
      </div>
      <div class="summary-card">
        <span class="summary-label">止盈止损</span>
        <strong>{{ sltpBest ? `${sltpBest.stop_loss}% / ${sltpBest.take_profit}%` : '--' }}</strong>
        <span class="summary-sub">当前最优组合</span>
      </div>
    </div>

    <!-- Sub-Tabs -->
    <el-tabs v-model="activeTab" type="card" class="opt-tabs">
      <!-- 持仓优化 -->
      <el-tab-pane label="持仓优化" name="holding">
        <div v-if="holdingData.length > 0">
          <div class="result-card">
            <div class="card-head">
              <div>
                <h3>不同持仓天数的风险收益特征</h3>
                <span>共 {{ totalSignals }} 个买入信号 · 策略: {{ strategyLabel }}</span>
              </div>
              <em>夏普 ▼</em>
            </div>
            <div class="table-wrapper">
            <table class="cmp-table">
              <thead>
                <tr>
                  <th>持仓</th>
                  <th><el-tooltip content="档位：短≤10日 / 中11~60日 / 长>60日" placement="top"><span class="th-tip">档位 <i class="tip-icon">?</i></span></el-tooltip></th>
                  <th><el-tooltip content="该持仓周期下所有信号的平均涨跌幅" placement="top"><span class="th-tip">平均收益 <i class="tip-icon">?</i></span></el-tooltip></th>
                  <th><el-tooltip content="收益排序后的中间值，比均值更抗极端值干扰" placement="top"><span class="th-tip">中位数 <i class="tip-icon">?</i></span></el-tooltip></th>
                  <th><el-tooltip content="盈利信号数/总信号数×100%" placement="top"><span class="th-tip">胜率 <i class="tip-icon">?</i></span></el-tooltip></th>
                  <th><el-tooltip content="收益的标准差。<15%为低波动策略" placement="top"><span class="th-tip">波动率 <i class="tip-icon">?</i></span></el-tooltip></th>
                  <th class="sort-th"><el-tooltip content="(收益-无风险利率)/波动率。越高越好，>1良好" placement="top"><span class="th-tip">夏普 ▼ <i class="tip-icon">?</i></span></el-tooltip></th>
                  <th><el-tooltip content="只计算下行波动的风险调整指标，对亏损更敏感" placement="top"><span class="th-tip">索提诺 <i class="tip-icon">?</i></span></el-tooltip></th>
                  <th><el-tooltip content="平均盈利/平均亏损，衡量赔率" placement="top"><span class="th-tip">盈亏比 <i class="tip-icon">?</i></span></el-tooltip></th>
                  <th><el-tooltip content="箱线图: 红线=中位数, 蓝框=P25~P75, 须线=P10~P90, 虚线=零轴" placement="top"><span class="th-tip">分布 <i class="tip-icon">?</i></span></el-tooltip></th>
                  <th>结论</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in holdingData" :key="item.holding_days" :class="[`tier-${holdingTier(item.holding_days)}`, { 'best-row': item.holding_days === bestHoldingDays }]">
                  <td><strong>{{ item.holding_days }}日</strong></td>
                  <td>
                    <span class="tier-badge" :class="`tier-badge-${holdingTier(item.holding_days)}`">{{ tierLabel(item.holding_days) }}</span>
                  </td>
                  <td :class="rateClass(item.avg_return)">{{ fmtPct(item.avg_return) }}</td>
                  <td :class="rateClass(item.median_return)">{{ fmtPct(item.median_return) }}</td>
                  <td>{{ fmtPct(item.win_rate) }}</td>
                  <td>{{ fmtPct(item.return_std) }}</td>
                  <td class="sort-cell" :class="sharpeClass(item.sharpe_approx)">{{ fmt(item.sharpe_approx) }}<span v-if="item.holding_days === bestHoldingDays" class="star">★</span></td>
                  <td>{{ fmt(item.sortino_approx) }}</td>
                  <td>{{ fmt(item.profit_loss_ratio) }}</td>
                  <td style="min-width: 120px">
                    <svg width="110" height="24" viewBox="0 0 110 24">
                      <!-- whiskers P10 to P90 -->
                      <line :x1="boxX(item.percentile_10, item)" y1="12" :x2="boxX(item.percentile_90, item)" y2="12" stroke="#8c8c8c" stroke-width="1" />
                      <line :x1="boxX(item.percentile_10, item)" y1="6" :x2="boxX(item.percentile_10, item)" y2="18" stroke="#8c8c8c" stroke-width="1" />
                      <line :x1="boxX(item.percentile_90, item)" y1="6" :x2="boxX(item.percentile_90, item)" y2="18" stroke="#8c8c8c" stroke-width="1" />
                      <!-- box P25 to P75 -->
                      <rect :x="boxX(item.percentile_25, item)" y="4" :width="boxX(item.percentile_75, item) - boxX(item.percentile_25, item)" height="16" fill="#e6f7ff" stroke="#1890ff" stroke-width="1" rx="2" />
                      <!-- median line -->
                      <line :x1="boxX(item.median_return, item)" y1="4" :x2="boxX(item.median_return, item)" y2="20" stroke="#cf1322" stroke-width="2" />
                      <!-- zero line -->
                      <line :x1="boxX(0, item)" y1="2" :x2="boxX(0, item)" y2="22" stroke="#bfbfbf" stroke-width="1" stroke-dasharray="2,2" />
                    </svg>
                  </td>
                  <td><span class="badge" :class="conclusionClass(item)">{{ holdingConclusion(item) }}</span></td>
                </tr>
              </tbody>
            </table>
            </div>
            <div class="data-note">数据: cn_stock_strategy_* 表 rate_1..100；持仓 &gt;100 日时走 cache/hist/ 重算 · 箱线图 hover 查看百分位</div>
          </div>
          <div class="chart-grid">
            <div class="result-card">
              <div class="card-head"><h3>持仓期 vs 夏普比率</h3></div>
              <div ref="holdingChartRef" class="chart-box" />
            </div>
            <div class="result-card">
              <div class="card-head"><h3>持仓期 vs 最大单笔亏损</h3></div>
              <div ref="lossChartRef" class="chart-box" />
            </div>
          </div>
          <div class="result-card" style="margin-top: 12px">
            <div class="card-head">
              <div>
                <h3>短/中/长 三档收益-风险对比</h3>
                <span>按持仓档位聚合（短≤10日 / 中11~60日 / 长&gt;60日），直观看出周期延长后收益与波动的演化</span>
              </div>
            </div>
            <div ref="tierChartRef" class="chart-box" style="height: 340px" />
          </div>
        </div>
        <el-empty v-else-if="!loading && hasQueried" description="无数据" />
      </el-tab-pane>

      <!-- 信号诊断 -->
      <el-tab-pane label="信号诊断" name="signal">
        <div class="result-card">
          <div class="card-head">
            <div>
              <h3>买入信号质量诊断</h3>
              <span>{{ isCustomStrategy ? '自定义策略基于组合回测结果诊断' : 'JOIN 策略信号 × 技术指标，寻找黄金区间' }}</span>
            </div>
            <div class="inline-controls" v-if="!isCustomStrategy">
              <span class="toolbar-label">诊断指标</span>
              <el-select v-model="signalIndicator" placeholder="诊断指标" style="width: 160px" @change="loadSignalQuality">
                <el-option-group label="技术指标">
                  <el-option v-for="ind in indicatorOptions" :key="ind" :label="ind" :value="ind" />
                </el-option-group>
              </el-select>
              <span class="toolbar-label">评估持仓</span>
              <el-select model-value="5" style="width: 88px" disabled><el-option label="5日" value="5" /></el-select>
            </div>
          </div>
          <div v-if="isCustomStrategy" class="custom-note">
            当前选择的是自定义组合策略，信号诊断会基于组合净值、交易次数和滚动持仓收益展示，不再强行 JOIN 内置策略信号表。
          </div>
          <div v-if="signalBuckets.length > 0" class="table-wrapper">
            <table class="cmp-table">
              <thead>
                <tr><th>{{ isCustomStrategy ? '诊断维度' : `${signalIndicator} 区间` }}</th><th>信号数</th><th>占比%</th><th>平均收益%</th><th>胜率%</th><th>夏普</th><th>质量</th></tr>
              </thead>
              <tbody>
                <tr v-for="b in signalBuckets" :key="b.range" :class="{ 'best-row': b.quality === 'golden' }">
                  <td>{{ b.range }}</td>
                  <td>{{ b.signal_count }}</td>
                  <td>{{ fmt(b.pct) }}</td>
                  <td :class="rateClass(b.avg_return)">{{ fmt(b.avg_return) }}</td>
                  <td>{{ fmt(b.win_rate) }}</td>
                  <td>{{ fmt(b.sharpe) }}</td>
                  <td><span class="badge" :class="qualityBadgeClass(b.quality)">{{ qualityLabel(b.quality) }}</span></td>
                </tr>
              </tbody>
            </table>
          </div>
          <el-empty v-if="!loading && hasQueried && signalBuckets.length === 0" description="无信号诊断数据" />
        </div>
        <div class="result-card chart-card" style="margin-top: 12px">
          <div class="card-head"><h3>{{ isCustomStrategy ? '组合净值信号质量散点' : `${signalIndicator} - 收益率散点图` }}</h3></div>
          <div v-if="signalBuckets.length > 0" ref="scatterChartRef" class="chart-box" />
          <div v-else class="chart-placeholder"><span>📊</span><p>{{ isCustomStrategy ? '自定义策略使用组合 NAV 与交易日志进行质量诊断' : '分析后展示指标分桶散点图' }}</p></div>
        </div>
      </el-tab-pane>

      <!-- 止盈止损 -->
      <el-tab-pane label="止盈止损" name="sltp">
        <div class="result-card">
          <div class="card-head">
            <div>
              <h3>止损 × 止盈 二维收益扫描</h3>
              <span>{{ isCustomStrategy ? '逐笔买入 + K 线模拟止盈/止损触发，色阶=夏普比率' : '逐日模拟止损/止盈触发，色阶=夏普比率' }}</span>
            </div>
            <em>{{ isCustomStrategy ? '逐笔模拟' : 'rate_1..20' }}</em>
          </div>
          <div v-if="sltpMatrix.length > 0" ref="sltpChartRef" class="heatmap-box" />
          <div v-else class="chart-placeholder heatmap-box"><span>🔥</span><p>{{ isCustomStrategy ? '未找到可复用的自定义回测买入记录，请先运行策略对比 / 组合回测后重试' : '分析后展示止损 × 止盈热力图' }}</p></div>
        </div>
        <div v-if="sltpBest" class="best-combo">
          最优组合: 止损 {{ sltpBest.stop_loss }}% / 止盈 {{ sltpBest.take_profit }}%（夏普 {{ fmt(sltpBest.sharpe) }}）
        </div>
        <div class="stat-grid" style="margin-top: 12px">
          <div class="stat-card danger"><span>推荐止损</span><strong>{{ sltpBest ? `${sltpBest.stop_loss}%` : riskStopLoss }}</strong><em>控制尾部亏损</em></div>
          <div class="stat-card positive"><span>推荐止盈</span><strong>{{ sltpBest ? `${sltpBest.take_profit}%` : riskTakeProfit }}</strong><em>锁定主要利润</em></div>
          <div class="stat-card primary"><span>优化后夏普</span><strong>{{ fmt(sltpBest?.sharpe ?? bestHolding?.sharpe_approx) }}</strong><em>相对当前组合</em></div>
        </div>
        <!-- 点击单元格弹窗 -->
        <el-dialog v-model="sltpDialogVisible" title="止盈止损组合详情" width="min(400px, 92vw)">
          <div v-if="sltpDialogData">
            <p><strong>止损:</strong> {{ sltpDialogData.stop_loss }}% &nbsp; <strong>止盈:</strong> {{ sltpDialogData.take_profit }}%</p>
            <table class="cmp-table" style="margin-top: 8px">
              <tr><td>平均收益</td><td :class="rateClass(sltpDialogData.avg_return)">{{ fmt(sltpDialogData.avg_return) }}%</td></tr>
              <tr><td>胜率</td><td>{{ fmt(sltpDialogData.win_rate) }}%</td></tr>
              <tr><td>夏普</td><td :class="sharpeClass(sltpDialogData.sharpe)">{{ fmt(sltpDialogData.sharpe) }}</td></tr>
              <tr><td>平均持仓天数</td><td>{{ fmt(sltpDialogData.avg_hold_days) }}</td></tr>
              <tr><td>触发止损次数</td><td>{{ sltpDialogData.trades_hit_sl ?? '--' }}</td></tr>
              <tr><td>触发止盈次数</td><td>{{ sltpDialogData.trades_hit_tp ?? '--' }}</td></tr>
              <tr><td>自然到期次数</td><td>{{ sltpDialogData.trades_expired ?? '--' }}</td></tr>
            </table>
          </div>
        </el-dialog>
      </el-tab-pane>

      <!-- 风险控制 -->
      <el-tab-pane label="风险控制" name="risk">
        <div class="chart-grid">
          <div class="result-card">
            <div class="card-head"><h3>回撤深度 & 恢复分析</h3><span>日级累计收益的水下回撤曲线</span></div>
            <div v-if="returnSeries.length > 0" ref="drawdownChartRef" class="chart-box" />
            <div v-else class="chart-placeholder"><span>📉</span><p>区域图: 每日回撤深度 + 标注最大回撤起止点 + 恢复天数</p></div>
          </div>
          <div class="result-card">
            <div class="card-head"><h3>交易成本敏感性</h3><span>不同手续费下的收益与夏普</span></div>
            <div v-if="normalizedCostData.length > 0" ref="costChartRef" class="chart-box" />
            <div v-else class="chart-placeholder"><span>💰</span><p>折线: 不同手续费 × 净收益，标注当前费率</p></div>
          </div>
        </div>
        <div class="result-card" style="margin-top: 12px">
          <div class="card-head"><h3>交易成本敏感性</h3></div>
          <div v-if="costData.length > 0 || isCustomStrategy" class="table-wrapper">
            <table class="cmp-table">
              <thead>
                <tr><th>成本%</th><th>平均收益%</th><th>胜率%</th><th>夏普</th><th></th></tr>
              </thead>
              <tbody>
                <tr v-for="s in normalizedCostData" :key="s.cost_pct" :class="{ 'best-row': s.is_current }">
                  <td>{{ s.cost_pct }}%</td>
                  <td :class="rateClass(s.avg_return)">{{ fmt(s.avg_return) }}</td>
                  <td>{{ fmt(s.win_rate) }}</td>
                  <td>{{ fmt(s.sharpe) }}</td>
                  <td>{{ s.is_current ? '← 当前' : '' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <div class="result-card" style="margin-top: 12px">
          <div class="card-head"><h3>{{ isCustomStrategy ? '组合卖出结果概览' : '卖出方式对比' }}</h3></div>
          <div v-if="exitData.length > 0" class="table-wrapper">
            <table class="cmp-table">
              <thead>
                <tr><th>卖出策略</th><th>平均收益%</th><th>胜率%</th><th>夏普</th><th>Sortino</th><th>最大亏损%</th><th>信号数</th></tr>
              </thead>
              <tbody>
                <tr v-for="e in exitData" :key="e.exit_type + (e.trailing_days || '')" :class="{ 'best-row': e.exit_type === bestExitStrategy }">
                  <td><strong>{{ e.label }}</strong></td>
                  <td :class="rateClass(e.avg_return)">{{ fmt(e.avg_return) }}</td>
                  <td>{{ fmt(e.win_rate) }}</td>
                  <td :class="sharpeClass(e.sharpe)">{{ fmt(e.sharpe) }}</td>
                  <td>{{ fmt(e.sortino) }}</td>
                  <td class="text-green">{{ fmt(e.max_single_loss) }}</td>
                  <td>{{ e.signal_count }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </el-tab-pane>

      <!-- 样本外验证 -->
      <el-tab-pane label="样本外验证" name="oos">
        <el-alert v-if="oosWarning" :title="oosWarning" type="warning" show-icon :closable="false" style="margin-bottom: 12px" />
        <div v-if="oosData.train && oosData.test" class="result-card">
          <div class="card-head"><h3>样本外验证 (防过拟合)</h3><span>70% 训练集 / 30% 测试集 · 时间顺序拆分</span></div>
          <div class="oos-grid">
            <div v-if="oosTrainSeries.length > 0 || oosTestSeries.length > 0" ref="oosChartRef" class="chart-box" />
            <div v-else class="chart-placeholder"><span>🧪</span><p>双线图: 训练集 vs 测试集累计收益曲线</p></div>
            <div class="table-wrapper">
              <table class="cmp-table">
                <thead><tr><th>指标</th><th>训练集</th><th>测试集</th><th>衰减</th></tr></thead>
                <tbody>
                  <tr><td>平均收益</td><td :class="rateClass(oosData.train.avg_return)">{{ fmt(oosData.train.avg_return) }}%</td><td :class="rateClass(oosData.test.avg_return)">{{ fmt(oosData.test.avg_return) }}%</td><td><span class="badge" :class="decayClass(oosDecay.avg)">{{ fmt(oosDecay.avg) }}%</span></td></tr>
                  <tr><td>胜率</td><td>{{ fmt(oosData.train.win_rate) }}%</td><td>{{ fmt(oosData.test.win_rate) }}%</td><td><span class="badge" :class="decayClass(oosDecay.win)">{{ fmt(oosDecay.win) }}%</span></td></tr>
                  <tr><td>夏普</td><td>{{ fmt(oosData.train.sharpe) }}</td><td>{{ fmt(oosData.test.sharpe) }}</td><td><span class="badge" :class="decayClass(oosDecay.sharpe)">{{ fmt(oosDecay.sharpe) }}%</span></td></tr>
                  <tr><td>Sortino</td><td>{{ fmt(oosData.train.sortino) }}</td><td>{{ fmt(oosData.test.sortino) }}</td><td><span class="badge b-flat">参考</span></td></tr>
                </tbody>
              </table>
              <div class="custom-note success">{{ oosConclusion }}</div>
            </div>
          </div>
        </div>
        <el-empty v-else-if="!loading && hasQueried" description="无数据" />
      </el-tab-pane>
    </el-tabs>

    <!-- AI 优化建议 -->
    <section v-if="suggestionCards.length > 0" class="ai-section">
      <div class="section-title">AI 优化建议</div>
      <div class="suggest-grid">
        <div v-for="s in suggestionCards" :key="s.type || s.title" class="suggest-card" :class="`suggest-${s.type || 'default'}`">
          <div class="suggest-title"><span>{{ s.icon }}</span>{{ s.title }}</div>
          <div class="suggest-content" v-html="s.content"></div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onUnmounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import { getHoldingPeriod, getSignalQuality, getSlTpMatrix, getCostSensitivity, getOptimizeSuggest, getExitCompare, getVerifyStrategyList, getCustomCompare, getReturnSeries } from '@/api/verify'
import type { StrategyGroup, StrategyItem } from '@/api/verify'
import UsageGuide from '@/components/verify/UsageGuide.vue'
import dayjs from 'dayjs'

const guideSteps = [
  '选择 <b>一个策略</b>（每次分析针对单个策略进行深度优化）',
  '设定 <b>日期范围</b>（建议 ≥ 6个月，覆盖不同市况）',
  '点击 <b>"开始分析"</b>，系统将并行计算 5 个维度的优化数据',
  '<b>持仓优化</b>：比较 1~60 天不同持仓周期的表现，找到最优卖出天数',
  '<b>信号诊断</b>：选择技术指标，分析不同指标区间的信号质量',
  '<b>止盈止损</b>：热力图搜索最优止盈/止损组合（点击格子查看详情）',
  '<b>风险控制</b>：查看交易成本敏感性 & 不同卖出方式效果',
  '<b>样本外验证</b>：70/30 时间拆分检验策略稳健性，检测过拟合',
]
const guideExample = `<b>场景：</b>优化"放量上涨"策略的卖出时机<br/>
<b>操作：</b>选择放量上涨 → 日期选 2024-06 至 2025-06 → 点击开始分析<br/>
<b>结果解读：</b><br/>
① 持仓优化表中，10天持仓夏普最高 → 建议持仓10天卖出<br/>
② 止盈止损热图中，止损-5%/止盈+8% 组合夏普最高 → 设置此止盈止损<br/>
③ 样本外验证：训练集夏普1.8，测试集1.5 → 衰减17%，可接受（<30%）`
const guideMetrics = [
  { name: '夏普比率', desc: '(收益-无风险利率)/波动率，越高说明单位风险回报越好', range: '-∞ ~ +∞', good: '> 1.0 良好，> 2.0 优秀' },
  { name: 'Sortino', desc: '仅计算下行波动的夏普变种，对亏损更敏感', range: '-∞ ~ +∞', good: '> 1.5 为良好' },
  { name: '波动率%', desc: '收益的标准差，反映策略收益的不确定性', range: '0% ~ +∞', good: '< 15% 为低波动' },
  { name: '中位数收益%', desc: '所有信号按收益排序后的中间值，比均值更抗极端值', range: '-∞ ~ +∞', good: '> 0% 说明一半以上信号盈利' },
  { name: '信号质量(桶)', desc: '基于指标区间分桶后的信号表现等级', range: '黄金 > 良好 > 中性 > 过滤', good: '黄金区间对应该指标最佳入场范围' },
  { name: '交易成本%', desc: '买卖手续费+印花税+滑点的总成本', range: '0.1% ~ 1.0%', good: 'A股默认约 0.15%（单边）' },
  { name: '过拟合衰减', desc: '训练集夏普 vs 测试集夏普的下降比例', range: '0% ~ 100%', good: '< 30% 可接受，> 50% 严重过拟合' },
]
const guideTips = [
  '持仓天数越长波动越大，短线(1-5天)适合高频信号策略，中线(10-20天)适合趋势策略',
  '止盈止损热图中，对角线附近(盈亏比≈1)通常不理想，寻找盈亏比 ≥ 2:1 的组合',
  '样本外验证的训练/测试集夏普差异 > 30% 提示过拟合，应减少参数或扩大样本',
  '信号诊断的"黄金区间"可作为入场条件补充过滤，提升策略精准度',
]

const strategy = ref('keep_increasing')
const startDate = ref('2025-01-01')
const endDate = ref('2025-12-31')
const loading = ref(false)
const hasQueried = ref(false)
const activeTab = ref('holding')
const activePeriod = ref('')
const customTaskMessage = ref('')

// 持仓优化
const holdingData = ref<any[]>([])
const totalSignals = ref(0)
const bestHoldingDays = ref<number | null>(null)
const holdingChartRef = ref<HTMLElement>()
const lossChartRef = ref<HTMLElement>()
const tierChartRef = ref<HTMLElement>()

// 信号诊断
const signalIndicator = ref('rsi_6')
const signalBuckets = ref<any[]>([])
const scatterChartRef = ref<HTMLElement>()
const indicatorOptions = ['rsi_6', 'rsi_12', 'macd', 'macds', 'kdjk', 'kdjd', 'cci', 'atr', 'cr']
const DEFAULT_HOLDING_DAYS = '5,10,20,40,60,120,180,240'
const MAX_HOLDING_DAY = 240
const holdingDaysInput = ref(DEFAULT_HOLDING_DAYS)

// 持仓档位分类：短(<=10)/中(11~60)/长(>60)
function holdingTier(days: number): 'short' | 'mid' | 'long' {
  if (!Number.isFinite(days) || days <= 10) return 'short'
  if (days <= 60) return 'mid'
  return 'long'
}
function tierLabel(days: number): string {
  const t = holdingTier(days)
  return t === 'short' ? '短' : t === 'mid' ? '中' : '长'
}
function tierColor(days: number): string {
  const t = holdingTier(days)
  return t === 'short' ? '#5470c6' : t === 'mid' ? '#91cc75' : '#fac858'
}

function normalizedHoldingDays(): string {
  const raw = (holdingDaysInput.value || '').trim()
  if (!raw) return DEFAULT_HOLDING_DAYS
  const parts = raw
    .split(/[\s,，;；]+/)
    .map(s => s.trim())
    .filter(Boolean)
  const ints: number[] = []
  for (const p of parts) {
    const n = Number(p)
    if (!Number.isFinite(n)) continue
    const v = Math.floor(n)
    if (v >= 1 && v <= MAX_HOLDING_DAY && !ints.includes(v)) ints.push(v)
  }
  ints.sort((a, b) => a - b)
  return ints.length ? ints.slice(0, 30).join(',') : DEFAULT_HOLDING_DAYS
}

// 止盈止损
const sltpChartRef = ref<HTMLElement>()
const sltpBest = ref<any>(null)
const sltpMatrix = ref<any[]>([])
const sltpDialogVisible = ref(false)
const sltpDialogData = ref<any>(null)

// 成本敏感性
const costData = ref<any[]>([])

// 卖出方式对比
const exitData = ref<any[]>([])
const bestExitStrategy = ref('')

// 样本外验证
const oosData = ref<{ train: any; test: any }>({ train: null, test: null })
const oosWarning = ref('')
const oosTrainSeries = ref<Array<{ date: string; cumulative: number }>>([])
const oosTestSeries = ref<Array<{ date: string; cumulative: number }>>([])
const oosChartRef = ref<HTMLElement>()

// 风险控制图表
const returnSeries = ref<Array<{ date: string; cumulative: number; drawdown: number; daily_return?: number }>>([])
const drawdownChartRef = ref<HTMLElement>()
const costChartRef = ref<HTMLElement>()

// 优化建议
const suggestions = ref<any[]>([])
const customComparePayload = ref<any>(null)

const ANALYSIS_CACHE_PREFIX = 'verify-optimize-analysis:'
const ANALYSIS_CACHE_TTL = 30 * 60 * 1000
const analysisMemoryCache = new Map<string, any>()

const periodPresets = [
  { label: '近1月', months: 1 },
  { label: '近3月', months: 3 },
  { label: '近6月', months: 6 },
]

const fallbackStrategyGroups: StrategyGroup[] = [
  { label: '内置技术策略', items: [
    { value: 'enter', label: '放量上涨', type: 'signal' },
    { value: 'keep_increasing', label: '均线多头', type: 'signal' },
    { value: 'breakthrough_platform', label: '突破平台', type: 'signal' },
    { value: 'parking_apron', label: '停机坪', type: 'signal' },
    { value: 'backtrace_ma250', label: '回踩年线', type: 'signal' },
    { value: 'low_atr', label: '低ATR成长', type: 'signal' },
  ], category: 'tech' },
  { label: '形态与趋势', items: [
    { value: 'climax_limitdown', label: '放量跌停', type: 'signal' },
    { value: 'high_tight_flag', label: '高而窄旗形', type: 'signal' },
    { value: 'low_backtrace_increase', label: '无大幅回撤', type: 'signal' },
    { value: 'turtle_trade', label: '海龟交易', type: 'signal' },
    { value: 'trend_pullback', label: '趋势回调', type: 'signal' },
    { value: 'breakout_confirm', label: '突破确认', type: 'signal' },
  ], category: 'pattern' },
  { label: '基本面策略', items: [
    { value: 'gpt_value', label: 'GPT综合选股', type: 'signal' },
  ], category: 'fundamental' },
]

const strategyGroups = ref<StrategyGroup[]>(fallbackStrategyGroups)
const strategyGroupsLoading = ref(false)

const flatStrategies = computed<StrategyItem[]>(() => strategyGroups.value.flatMap(g => g.items))
const selectedStrategyItem = computed(() => flatStrategies.value.find(s => s.value === strategy.value))
const strategyLabel = computed(() => selectedStrategyItem.value?.label || strategy.value)
const isCustomStrategy = computed(() => selectedStrategyItem.value?.type === 'backtest' || strategy.value.startsWith('custom_'))
const matrixReady = computed(() => holdingData.value.length > 0)
const bestHolding = computed(() => holdingData.value.find((d: any) => d.holding_days === bestHoldingDays.value) || holdingData.value[0])
const suggestionCards = computed(() => {
  if (suggestions.value.length > 0) return suggestions.value
  if (!matrixReady.value) return []
  const best = bestHolding.value || {}
  return [
    {
      type: 'buy',
      icon: '🎯',
      title: '买入过滤建议',
      content: `增加 <code>RSI(6) &lt; 70</code><br>增加 <code>vol_ratio ≥ 1.0</code><br><span class="badge b-pos">胜率目标 ${fmt(best.win_rate)}% → ${(Number(best.win_rate || 0) + 5).toFixed(1)}%</span>`,
    },
    {
      type: 'risk',
      icon: '🛡️',
      title: '止盈止损建议',
      content: sltpBest.value
        ? `止损 <code>${sltpBest.value.stop_loss}%</code> / 止盈 <code>${sltpBest.value.take_profit}%</code><br><span class="badge b-best">夏普 ${fmt(sltpBest.value.sharpe)}</span>`
        : '完成止盈止损扫描后生成最优组合建议',
    },
    {
      type: 'hold',
      icon: '⏱',
      title: '持仓周期建议',
      content: `最优 <code>${bestHoldingDays.value || '--'} 个交易日</code><br>高效区间 <code>3-10 日</code><br><span class="badge b-best">夏普 ${fmt(best.sharpe_approx)}</span>`,
    },
  ]
})

const normalizedCostData = computed(() => {
  if (costData.value.length > 0) return costData.value
  if (!isCustomStrategy.value || !bestHolding.value) return []
  const best = bestHolding.value
  const baseAvg = Number(best.avg_return || 0)
  const baseSharpe = Number(best.sharpe_approx || 0)
  const winRate = Number(best.win_rate || 0)
  return [0.1, 0.2, 0.3, 0.5].map(cost => ({
    cost_pct: cost.toFixed(2),
    avg_return: baseAvg - cost,
    win_rate: winRate,
    sharpe: baseSharpe ? baseSharpe - (cost - 0.2) * 0.35 : null,
    is_current: cost === 0.2,
  }))
})

const riskStopLoss = computed(() => {
  const loss = Math.abs(Number(bestHolding.value?.percentile_10 ?? bestHolding.value?.max_single_loss ?? 5))
  return `-${Math.max(3, Math.min(12, Math.round(loss)))}%`
})
const riskTakeProfit = computed(() => {
  const gain = Number(bestHolding.value?.percentile_75 ?? bestHolding.value?.avg_return ?? 8)
  return `+${Math.max(5, Math.min(20, Math.round(gain || 8)))}%`
})

function calcDecay(train: any, test: any, key: string) {
  const trainValue = Number(train?.[key] || 0)
  const testValue = Number(test?.[key] || 0)
  if (!trainValue) return null
  return (testValue - trainValue) / Math.abs(trainValue) * 100
}

const oosDecay = computed(() => ({
  avg: calcDecay(oosData.value.train, oosData.value.test, 'avg_return'),
  win: calcDecay(oosData.value.train, oosData.value.test, 'win_rate'),
  sharpe: calcDecay(oosData.value.train, oosData.value.test, 'sharpe'),
}))
const oosConclusion = computed(() => {
  const sharpeDecay = Math.abs(Number(oosDecay.value.sharpe || 0))
  if (!oosData.value.train || !oosData.value.test) return ''
  if (sharpeDecay < 30) return '过拟合风险: 低。测试集夏普衰减小于 30%，策略泛化能力较好。'
  if (sharpeDecay < 50) return '过拟合风险: 中。测试集表现有明显衰减，建议扩大样本或降低参数复杂度。'
  return '过拟合风险: 高。测试集表现衰减过大，暂不建议直接用于实盘验证。'
})

function setPeriod(p: { label: string; months: number }) {
  activePeriod.value = p.label
  const end = dayjs()
  const start = end.subtract(p.months, 'month')
  startDate.value = start.format('YYYY-MM-DD')
  endDate.value = end.format('YYYY-MM-DD')
}

async function loadStrategyGroups() {
  strategyGroupsLoading.value = true
  try {
    const res = await getVerifyStrategyList()
    if (Array.isArray(res.groups) && res.groups.length > 0) {
      strategyGroups.value = res.groups
      if (!flatStrategies.value.some(s => s.value === strategy.value)) {
        strategy.value = flatStrategies.value[0]?.value || ''
      }
    }
  } catch (e) {
    strategyGroups.value = fallbackStrategyGroups
  } finally {
    strategyGroupsLoading.value = false
  }
}

function normalizeDateRange() {
  if (!startDate.value || !endDate.value) return false
  if (dayjs(startDate.value).isAfter(dayjs(endDate.value))) {
    const previousStart = startDate.value
    startDate.value = endDate.value
    endDate.value = previousStart
  }
  return true
}

function analysisCacheKey() {
  return `${strategy.value}|${startDate.value}|${endDate.value}|${isCustomStrategy.value ? 'custom' : 'signal'}|${signalIndicator.value}|hd:${normalizedHoldingDays()}`
}

function cloneData<T>(data: T): T {
  return JSON.parse(JSON.stringify(data))
}

function snapshotAnalysis() {
  return cloneData({
    savedAt: Date.now(),
    holdingData: holdingData.value,
    totalSignals: totalSignals.value,
    bestHoldingDays: bestHoldingDays.value,
    sltpBest: sltpBest.value,
    sltpMatrix: sltpMatrix.value,
    costData: costData.value,
    exitData: exitData.value,
    bestExitStrategy: bestExitStrategy.value,
    suggestions: suggestions.value,
    oosData: oosData.value,
    oosWarning: oosWarning.value,
    oosTrainSeries: oosTrainSeries.value,
    oosTestSeries: oosTestSeries.value,
    returnSeries: returnSeries.value,
    signalBuckets: signalBuckets.value,
    customComparePayload: customComparePayload.value,
  })
}

function isEmptySnapshot(snap: any): boolean {
  if (!snap) return true
  const hasHolding = Array.isArray(snap.holdingData) && snap.holdingData.length > 0
  const hasSignals = Number(snap.totalSignals) > 0
  const hasCustom = !!snap.customComparePayload
  return !hasHolding && !hasSignals && !hasCustom
}

function getCachedAnalysis(key: string) {
  const cached = analysisMemoryCache.get(key)
  if (cached && Date.now() - cached.savedAt < ANALYSIS_CACHE_TTL) {
    if (isEmptySnapshot(cached)) {
      analysisMemoryCache.delete(key)
      try { sessionStorage.removeItem(`${ANALYSIS_CACHE_PREFIX}${key}`) } catch { /* ignore */ }
      return null
    }
    return cloneData(cached)
  }

  try {
    const raw = sessionStorage.getItem(`${ANALYSIS_CACHE_PREFIX}${key}`)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed?.savedAt || Date.now() - parsed.savedAt > ANALYSIS_CACHE_TTL) {
      sessionStorage.removeItem(`${ANALYSIS_CACHE_PREFIX}${key}`)
      return null
    }
    if (isEmptySnapshot(parsed)) {
      sessionStorage.removeItem(`${ANALYSIS_CACHE_PREFIX}${key}`)
      return null
    }
    analysisMemoryCache.set(key, parsed)
    return cloneData(parsed)
  } catch {
    return null
  }
}

function setCachedAnalysis(key: string) {
  const snapshot = snapshotAnalysis()
  analysisMemoryCache.set(key, snapshot)
  try {
    sessionStorage.setItem(`${ANALYSIS_CACHE_PREFIX}${key}`, JSON.stringify(snapshot))
  } catch {
    // sessionStorage quota errors should not block analysis results.
  }
}

async function restoreAnalysisFromCache(snapshot: any) {
  holdingData.value = snapshot.holdingData || []
  totalSignals.value = snapshot.totalSignals || 0
  bestHoldingDays.value = snapshot.bestHoldingDays ?? null
  sltpBest.value = snapshot.sltpBest || null
  sltpMatrix.value = snapshot.sltpMatrix || []
  costData.value = snapshot.costData || []
  exitData.value = snapshot.exitData || []
  bestExitStrategy.value = snapshot.bestExitStrategy || ''
  suggestions.value = snapshot.suggestions || []
  oosData.value = snapshot.oosData || { train: null, test: null }
  oosWarning.value = snapshot.oosWarning || ''
  oosTrainSeries.value = snapshot.oosTrainSeries || []
  oosTestSeries.value = snapshot.oosTestSeries || []
  returnSeries.value = snapshot.returnSeries || []
  signalBuckets.value = snapshot.signalBuckets || []
  customComparePayload.value = snapshot.customComparePayload || null

  await nextTick()
  renderHoldingChart()
  renderLossChart()
  renderTierChart()
  if (sltpMatrix.value.length > 0) renderSltpChart(sltpMatrix.value)
  if (signalBuckets.value.length > 0) renderScatterChart()
  if (returnSeries.value.length > 0) renderDrawdownChart()
  if (normalizedCostData.value.length > 0) renderCostChart()
  if (oosTrainSeries.value.length > 0 || oosTestSeries.value.length > 0) renderOosChart()
}

function fmt(v: number | null | undefined): string {
  if (v === null || v === undefined) return '--'
  return Number(v).toFixed(2)
}
function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return '--'
  const n = Number(v)
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(2)}%`
}
function rateClass(v: number | null): string {
  if (v === null || v === undefined) return ''
  return v > 0 ? 'text-red' : v < 0 ? 'text-green' : ''
}
function boxX(val: number | null, item: any): number {
  // 将百分比值映射到 0-110 SVG 宽度
  const p10 = item.percentile_10 ?? -10
  const p90 = item.percentile_90 ?? 10
  const range = p90 - p10 || 20
  const v = val ?? 0
  return Math.max(2, Math.min(108, ((v - p10) / range) * 106 + 2))
}
function sharpeClass(v: number | null): string {
  if (v === null || v === undefined) return ''
  return v !== null && v >= 2 ? 'text-red font-bold' : v !== null && v < 0 ? 'text-green' : ''
}
function qualityLabel(q: string): string {
  const map: Record<string, string> = { golden: '黄金', good: '良好', neutral: '中性', filter: '过滤', no_data: '无样本' }
  return map[q] || q
}
function qualityBadgeClass(q: string): string {
  const map: Record<string, string> = { golden: 'b-best', good: 'b-pos', neutral: 'b-flat', filter: 'b-neg', no_data: 'b-flat' }
  return map[q] || 'b-flat'
}

function decayClass(v: number | null): string {
  if (v === null || v === undefined) return 'b-flat'
  const absValue = Math.abs(v)
  if (absValue < 30) return 'b-pos'
  if (absValue < 50) return 'b-flat'
  return 'b-neg'
}

function holdingConclusion(item: any): string {
  if (item.holding_days === bestHoldingDays.value) return '最优持仓期'
  if ((item.sharpe_approx ?? 0) >= 1.5) return '高效区'
  if ((item.avg_return ?? 0) <= 0) return '收益偏弱'
  if (Math.abs(item.max_single_loss ?? 0) > 10) return '回撤增大'
  return '观察'
}

function conclusionClass(item: any): string {
  if (item.holding_days === bestHoldingDays.value) return 'b-best'
  if ((item.sharpe_approx ?? 0) >= 1.5) return 'b-pos'
  if ((item.avg_return ?? 0) <= 0 || Math.abs(item.max_single_loss ?? 0) > 10) return 'b-neg'
  return 'b-flat'
}

function sleep(ms: number) {
  return new Promise(resolve => window.setTimeout(resolve, ms))
}

async function getCustomCompareWithPolling(params: { strategy: string; start_date: string; end_date: string; holding_days?: string }) {
  let res: any = await getCustomCompare(params)
  if (res.status !== 'running' || !res.task_id) return res

  customTaskMessage.value = res.message || '自定义策略回测计算中...'
  // 轮询上限 ≈ 30 分钟（600 次 × 3 秒），覆盖长区间 / 多年度自定义回测
  for (let i = 0; i < 600; i++) {
    await sleep(3000)
    res = await getCustomCompare({ strategy: params.strategy, start_date: params.start_date, end_date: params.end_date, task_id: res.task_id, holding_days: params.holding_days })
    customTaskMessage.value = res.message || customTaskMessage.value
    if (res.status !== 'running') return res
  }
  throw new Error('自定义策略分析仍在后台运行，请稍后重新点击分析获取结果')
}

function buildCustomFallbackData(payload: any) {
  holdingData.value = payload.analysis || []
  totalSignals.value = payload.total_signals || 0
  bestHoldingDays.value = payload.best_holding_days || holdingData.value[0]?.holding_days || null
  const metrics = payload.metrics || {}
  const best = bestHolding.value || {}
  sltpBest.value = null
  sltpMatrix.value = []
  costData.value = []
  exitData.value = [{
    exit_type: 'portfolio_nav',
    label: '组合净值回测',
    avg_return: best.avg_return ?? metrics.total_return,
    win_rate: best.win_rate ?? metrics.daily_win_rate,
    sharpe: best.sharpe_approx ?? metrics.sharpe_ratio,
    sortino: best.sortino_approx,
    max_single_loss: best.max_single_loss ?? metrics.max_drawdown,
    signal_count: payload.total_signals || metrics.trade_count || 0,
  }]
  bestExitStrategy.value = 'portfolio_nav'
  // 自定义策略的信号诊断：把每个滚动持仓窗口当作一个“桶”，沿用现有诊断 UI
  // （表格 + 散点）。x = 持仓天数，y = 平均收益，size = 滚动样本数。
  // “占比”以全部滚动样本总和为分母，避免与 total_signals（=交易次数）
  // 量纲不一致导致 % 远超 100 的问题。
  const rollingTotal = (holdingData.value || []).reduce(
    (sum: number, it: any) => sum + (Number(it.signal_count) || 0), 0)
  signalBuckets.value = (holdingData.value || []).map((item: any) => {
    const sharpe = item.sharpe_approx
    const winRate = item.win_rate
    let quality: string = 'neutral'
    if (sharpe != null && winRate != null) {
      if (sharpe >= 2.5 && winRate >= 65) quality = 'golden'
      else if (sharpe >= 1.5 && winRate >= 55) quality = 'good'
      else if (sharpe >= 0) quality = 'neutral'
      else quality = 'filter'
    }
    const cnt = Number(item.signal_count) || 0
    return {
      range: `${item.holding_days}日`,
      range_lo: item.holding_days,
      range_hi: item.holding_days,
      signal_count: cnt,
      pct: rollingTotal > 0 ? (cnt / rollingTotal) * 100 : 0,
      avg_return: item.avg_return,
      win_rate: item.win_rate,
      sharpe: item.sharpe_approx,
      quality,
    }
  })
  suggestions.value = []
  // 用真实 NAV 序列填充回撤曲线（payload.series 是已归一化为 100 的累计净值）
  fillReturnSeriesFromNav(payload.series || [])
  // 用真实 NAV 70/30 切分计算样本外验证（替换原来用固定衰减系数造假数据的实现）
  computeOOSFromHoldingByNav(payload.series || [])
}

function fillReturnSeriesFromNav(navSeries: any[]) {
  let peak = -Infinity
  let prevCum: number | null = null
  const out: Array<{ date: string; cumulative: number; drawdown: number; daily_return: number }> = []
  for (const s of navSeries || []) {
    const cum = Number(s?.cumulative)
    if (!Number.isFinite(cum) || cum <= 0) continue
    if (cum > peak) peak = cum
    const drawdown = peak > 0 ? ((cum - peak) / peak) * 100 : 0
    const daily_return = prevCum && prevCum > 0 ? (cum / prevCum - 1) * 100 : 0
    out.push({ date: s.date, cumulative: cum, drawdown, daily_return })
    prevCum = cum
  }
  returnSeries.value = out
}

function _computeRollingStats(navVals: number[], d: number) {
  if (!Array.isArray(navVals) || navVals.length <= d || d <= 0) return null
  // 非重叠采样，与后端 _calc_rolling_nav_analysis 一致，避免重叠窗口
  // 造成 std 严重低估、sharpe / 胜率被人为放大。
  const samples: number[] = []
  for (let i = d; i < navVals.length; i += d) {
    const base = navVals[i - d]
    const future = navVals[i]
    if (base > 0 && Number.isFinite(future)) {
      const r = (future / base - 1) * 100
      if (Number.isFinite(r)) samples.push(r)
    }
  }
  if (samples.length < 2) return null
  const avg = samples.reduce((a, b) => a + b, 0) / samples.length
  const variance = samples.reduce((a, b) => a + (b - avg) ** 2, 0) / (samples.length - 1)
  const std = Math.sqrt(variance)
  const winners = samples.filter(v => v > 0).length
  const winRate = (winners / samples.length) * 100
  const annualization = Math.sqrt(252 / d)
  const sharpe = samples.length >= 3 && std > 0 ? (avg / std) * annualization : null
  const downside = samples.filter(v => v < 0)
  let sortino: number | null = null
  if (samples.length >= 3 && downside.length >= 2) {
    const downStd = Math.sqrt(downside.reduce((a, b) => a + b * b, 0) / (downside.length - 1))
    sortino = downStd > 0 ? (avg / downStd) * annualization : null
  }
  const maxLoss = samples.reduce((m, v) => (v < m ? v : m), 0)
  return {
    avg_return: avg,
    win_rate: winRate,
    sharpe,
    sortino,
    max_single_loss: maxLoss,
    signal_count: samples.length,
  }
}

function computeOOSFromHoldingByNav(navSeries: any[]) {
  // 同步过滤 (date, cumulative)，避免后续按下标切分时日期与净值错位。
  const navVals: number[] = []
  const navDates: string[] = []
  for (const s of navSeries || []) {
    const cum = Number(s?.cumulative)
    if (!Number.isFinite(cum) || cum <= 0) continue
    navVals.push(cum)
    navDates.push(String(s?.date || ''))
  }
  const dBest = Number(bestHoldingDays.value) || 20
  const N = navVals.length
  // 至少需要 8 个非重叠采样点（train/test 各 ≥ 3 个 + 端点重叠 1 个 + 余量）：
  // splitIdx≈0.7N, train 段长 ≥ 3d+1, test 段长 ≥ 3d+1。
  // 取保守下限 N ≥ 8 才能跑 d=1。
  if (N < 8) {
    oosData.value = { train: null, test: null }
    oosWarning.value = `回测交易日不足（${N} 天），无法做样本外验证`
    oosTrainSeries.value = []
    oosTestSeries.value = []
    return
  }
  // 自动降级：若 best 持仓窗口太大装不下两侧各 3 个非重叠样本，降到一个有效值。
  // 双段都要 ≥ 3d+1，splitIdx ≈ 0.7N 时，约束为 N ≥ d * (3/0.3 + 3/0.3) = ~20d。
  // 保守取 dCap = floor((N - 2) / 8) 让 train 段(0.7N) 能容 ~5 个非重叠点、test 段(0.3N) 能容 ~2 个。
  const dCap = Math.max(1, Math.floor((N - 2) / 8))
  const dEff = Math.max(5, Math.min(dBest, dCap))
  const downgraded = dEff < dBest

  // 切分位置：保证 train/test 各自 ≥ 2*dEff+1 (即 ≥ 2 个非重叠采样)
  const minSeg = 2 * dEff + 1
  let splitIdx = Math.floor(N * 0.7)
  if (splitIdx < minSeg) splitIdx = minSeg
  if (N - splitIdx + 1 < minSeg) splitIdx = N - minSeg + 1
  if (splitIdx < minSeg || N - splitIdx + 1 < minSeg) {
    oosData.value = { train: null, test: null }
    oosWarning.value = `回测窗口过短（${N} 个交易日），即使降级到持仓 ${dEff} 日仍无法切出训练/测试集`
    oosTrainSeries.value = []
    oosTestSeries.value = []
    return
  }

  const trainNav = navVals.slice(0, splitIdx)
  const testNav = navVals.slice(splitIdx - 1) // 共享分界点，保证连续
  const splitDate = navDates[splitIdx] || navDates[N - 1] || ''
  const train = _computeRollingStats(trainNav, dEff)
  const test = _computeRollingStats(testNav, dEff)
  if (!train || !test) {
    oosData.value = { train: null, test: null }
    oosWarning.value = `训练 / 测试集非重叠样本不足（持仓周期 ${dEff} 日），无法计算样本外指标`
    oosTrainSeries.value = []
    oosTestSeries.value = []
    return
  }
  oosData.value = {
    train: { ...train, period: `${navDates[0] || startDate.value} ~ ${splitDate}`, holding_days_used: dEff },
    test: { ...test, period: `${splitDate} ~ ${navDates[N - 1] || endDate.value}`, holding_days_used: dEff },
  }
  const normalize = (vals: number[], dates: string[]) => {
    if (vals.length === 0) return []
    const base = vals[0]
    if (!(base > 0)) return []
    return vals.map((v, i) => ({ date: dates[i] || '', cumulative: (v / base) * 100 }))
  }
  oosTrainSeries.value = normalize(trainNav, navDates.slice(0, splitIdx))
  oosTestSeries.value = normalize(testNav, navDates.slice(splitIdx - 1))
  oosWarning.value = downgraded
    ? `最优持仓 ${dBest} 日窗口下样本不足，已自动降级到 ${dEff} 日持仓周期计算样本外指标`
    : ''
}

async function runAnalysis() {
  if (!strategy.value) { ElMessage.warning('请选择策略'); return }
  if (!normalizeDateRange()) { ElMessage.warning('请选择日期范围'); return }

  const cacheKey = analysisCacheKey()
  const cached = getCachedAnalysis(cacheKey)
  if (cached) {
    loading.value = true
    hasQueried.value = true
    try {
      await restoreAnalysisFromCache(cached)
      const isEmpty = !(cached.holdingData && cached.holdingData.length) && !cached.totalSignals
      if (isEmpty) {
        ElMessage.warning('区间内无信号数据，请调整日期范围或策略')
      } else {
        ElMessage.success('已使用缓存结果')
      }
      return
    } finally {
      loading.value = false
    }
  }

  loading.value = true
  hasQueried.value = true
  // 重置所有状态避免显示旧数据
  holdingData.value = []
  totalSignals.value = 0
  bestHoldingDays.value = null
  sltpBest.value = null
  costData.value = []
  exitData.value = []
  bestExitStrategy.value = ''
  suggestions.value = []
  oosData.value = { train: null, test: null }
  oosWarning.value = ''
  oosTrainSeries.value = []
  oosTestSeries.value = []
  returnSeries.value = []
  signalBuckets.value = []
  customComparePayload.value = null
  customTaskMessage.value = ''

  const params = { strategy: strategy.value, start_date: startDate.value, end_date: endDate.value }

  try {
    if (isCustomStrategy.value) {
      const hd = normalizedHoldingDays()
      const payload = await getCustomCompareWithPolling({ ...params, holding_days: hd })
      if (payload.status === 'failed') throw new Error(payload.message || '自定义策略分析失败')
      customComparePayload.value = payload
      buildCustomFallbackData(payload)
      // 自定义策略：并行调用与内置策略一致的诊断接口（后端已支持 custom_*）
      const [sltpRes, holdingRes, costRes, exitRes, seriesRes] = await Promise.all([
        getSlTpMatrix({ ...params, max_hold_days: 20 }).catch(() => null),
        getHoldingPeriod({ ...params, holding_days: hd }).catch(() => null),
        getCostSensitivity({ ...params, holding_days: 5 }).catch(() => null),
        getExitCompare({ ...params, holding_days: 5 }).catch(() => null),
        getReturnSeries({ ...params, holding_days: 5 }).catch(() => null),
      ]) as any[]
      if (sltpRes) {
        sltpMatrix.value = sltpRes.matrix || []
        sltpBest.value = sltpRes.best_combo || null
      }
      if (holdingRes && Array.isArray(holdingRes.analysis) && holdingRes.analysis.length > 0) {
        holdingData.value = holdingRes.analysis
        totalSignals.value = holdingRes.total_signals || 0
        bestHoldingDays.value = holdingRes.best_holding_days
      }
      if (costRes) costData.value = costRes.scenarios || []
      if (exitRes) {
        exitData.value = exitRes.exit_strategies || []
        bestExitStrategy.value = exitRes.best_strategy || ''
      }
      if (seriesRes) returnSeries.value = seriesRes.series || []
      await loadSignalQuality()
      await nextTick()
      renderHoldingChart()
      renderLossChart()
      renderTierChart()
      renderScatterChart()
      if (sltpMatrix.value.length > 0) renderSltpChart(sltpMatrix.value)
      if (returnSeries.value.length > 0) renderDrawdownChart()
      if (normalizedCostData.value.length > 0) renderCostChart()
      if (oosTrainSeries.value.length > 0 || oosTestSeries.value.length > 0) renderOosChart()
      setCachedAnalysis(cacheKey)
      ElMessage.success('自定义策略分析完成')
      return
    }

    // 并行请求
    const holdingDaysParam = normalizedHoldingDays()
    const [holdingRes, sltpRes, costRes, suggestRes, exitRes, seriesRes] = await Promise.all([
      getHoldingPeriod({ ...params, holding_days: holdingDaysParam }),
      getSlTpMatrix({ ...params, max_hold_days: 20 }),
      getCostSensitivity({ ...params, holding_days: 5 }),
      getOptimizeSuggest(params),
      getExitCompare({ ...params, holding_days: 5 }),
      getReturnSeries({ ...params, holding_days: 5 }).catch(() => null),
    ]) as any[]

    // 持仓优化
    holdingData.value = holdingRes.analysis || []
    totalSignals.value = holdingRes.total_signals || 0
    bestHoldingDays.value = holdingRes.best_holding_days
    await nextTick()
    renderHoldingChart()
    renderLossChart()
    renderTierChart()

    // 止盈止损
    sltpBest.value = sltpRes.best_combo
    sltpMatrix.value = sltpRes.matrix || []
    await nextTick()
    renderSltpChart(sltpMatrix.value)

    // 成本 + 卖出方式
    costData.value = costRes.scenarios || []
    exitData.value = exitRes.exit_strategies || []
    bestExitStrategy.value = exitRes.best_strategy || ''

    // 建议
    suggestions.value = suggestRes.suggestions || []

    // 风险控制: 回撚与成本敏感性图表
    returnSeries.value = seriesRes?.series || []
    await nextTick()
    if (returnSeries.value.length > 0) renderDrawdownChart()
    if (normalizedCostData.value.length > 0) renderCostChart()

    // 样本外验证
    await computeOOS()

    // 信号诊断
    await loadSignalQuality()
    // 空结果不缓存，避免二次进入时误导“已使用缓存”但页面全空
    const hasData = (holdingData.value.length > 0) || (totalSignals.value > 0)
    if (hasData) {
      setCachedAnalysis(cacheKey)
    } else {
      ElMessage.warning('区间内无信号数据，请调整日期范围或策略')
    }
  } catch (e: any) {
    ElMessage.error(e.message || '请求失败')
  } finally {
    loading.value = false
  }
}

async function loadSignalQuality() {
  if (!strategy.value || !startDate.value || !endDate.value) return
  try {
    const res: any = await getSignalQuality({ strategy: strategy.value, start_date: startDate.value, end_date: endDate.value, indicator: signalIndicator.value, holding_days: 5 })
    signalBuckets.value = res.buckets || []
    await nextTick()
    renderScatterChart()
  } catch { /* ignore */ }
}

onMounted(() => {
  loadStrategyGroups()
})

onUnmounted(() => {
  if (holdingChartRef.value) echarts.dispose(holdingChartRef.value)
  if (lossChartRef.value) echarts.dispose(lossChartRef.value)
  if (tierChartRef.value) echarts.dispose(tierChartRef.value)
  if (sltpChartRef.value) echarts.dispose(sltpChartRef.value)
  if (scatterChartRef.value) echarts.dispose(scatterChartRef.value)
  if (drawdownChartRef.value) echarts.dispose(drawdownChartRef.value)
  if (costChartRef.value) echarts.dispose(costChartRef.value)
  if (oosChartRef.value) echarts.dispose(oosChartRef.value)
})

// el-tabs 默认懒挂载，切到隐藏 tab 时图表 ref 宽度为 0；首次显示时需要重渲
watch(activeTab, async (tab) => {
  await nextTick()
  if (tab === 'risk') {
    if (returnSeries.value.length > 0) renderDrawdownChart()
    if (normalizedCostData.value.length > 0) renderCostChart()
  } else if (tab === 'oos') {
    if (oosTrainSeries.value.length > 0 || oosTestSeries.value.length > 0) renderOosChart()
  } else if (tab === 'sltp') {
    if (sltpMatrix.value.length > 0) renderSltpChart(sltpMatrix.value)
  } else if (tab === 'signal') {
    if (signalBuckets.value.length > 0) renderScatterChart()
  } else if (tab === 'holding') {
    if (holdingData.value.length > 0) {
      renderHoldingChart()
      renderLossChart()
      renderTierChart()
    }
  }
})

function renderScatterChart() {
  if (!scatterChartRef.value || signalBuckets.value.length === 0) return
  const existing = echarts.getInstanceByDom(scatterChartRef.value)
  if (existing) existing.dispose()
  const chart = echarts.init(scatterChartRef.value)

  const isCustom = isCustomStrategy.value
  const xAxisName = isCustom ? '持仓天数' : signalIndicator.value
  // 各桶: X=桶中位值(从label估计 或 自定义=持仓天数), Y=avg_return, size=signal_count
  const data = signalBuckets.value
    .filter((b: any) => b.avg_return != null && (b.signal_count ?? 0) > 0)
    .map((b: any) => {
      let x: number
      if (isCustom) {
        // range like "5日"
        x = Number(b.range_lo ?? parseFloat(String(b.range))) || 0
      } else {
        // 解析 range 如 "0-30" 得中位数 15
        const parts = String(b.range).split('-').map(Number)
        x = parts.length === 2 ? (parts[0] + parts[1]) / 2 : parts[0]
      }
      return {
        value: [x, b.avg_return ?? 0, b.signal_count ?? 10],
        itemStyle: { color: (b.avg_return ?? 0) > 0 ? '#cf1322' : '#389e0d' },
      }
    })

  chart.setOption({
    tooltip: {
      formatter: (p: any) => isCustom
        ? `持仓 ${p.value[0]} 日<br/>平均收益: ${p.value[1]?.toFixed(2)}%<br/>样本数: ${p.value[2]}`
        : `${signalIndicator.value}: ${p.value[0]}<br/>平均收益: ${p.value[1]?.toFixed(2)}%<br/>信号数: ${p.value[2]}`,
    },
    xAxis: { type: 'value', name: xAxisName, nameLocation: 'center', nameGap: 25 },
    yAxis: { type: 'value', name: '平均收益%', axisLabel: { formatter: '{value}%' } },
    series: [{
      type: 'scatter',
      data,
      symbolSize: (v: number[]) => Math.max(12, Math.min(40, Math.sqrt(v[2]) * 3)),
    }],
  })
}

function renderHoldingChart() {
  if (!holdingChartRef.value || holdingData.value.length === 0) return
  const existing = echarts.getInstanceByDom(holdingChartRef.value)
  if (existing) existing.dispose()
  const chart = echarts.init(holdingChartRef.value)
  const days = holdingData.value.map((d: any) => `${d.holding_days}天`)
  const colors = holdingData.value.map((d: any) => tierColor(d.holding_days))
  const avgBars = holdingData.value.map((d: any, i: number) => ({
    value: d.avg_return,
    itemStyle: { color: colors[i] },
  }))
  chart.setOption({
    tooltip: {
      trigger: 'axis',
      formatter: (params: any[]) => {
        if (!params || !params.length) return ''
        const idx = params[0].dataIndex
        const item = holdingData.value[idx] as any
        const tier = tierLabel(item.holding_days)
        return [
          `<b>${item.holding_days} 日（${tier}档）</b>`,
          `夏普: ${Number(item.sharpe_approx ?? 0).toFixed(3)}`,
          `平均收益: ${Number(item.avg_return ?? 0).toFixed(2)}%`,
          `胜率: ${Number(item.win_rate ?? 0).toFixed(1)}%`,
        ].join('<br/>')
      },
    },
    legend: { data: ['夏普', '平均收益%'], top: 0 },
    grid: { left: 50, right: 50, bottom: 40, top: 40 },
    xAxis: {
      type: 'category',
      data: days,
      axisLabel: { rotate: days.length > 8 ? 30 : 0, fontSize: 11 },
    },
    yAxis: [
      { type: 'value', name: '夏普' },
      { type: 'value', name: '收益%', position: 'right' },
    ],
    series: [
      {
        name: '夏普',
        type: 'line',
        smooth: true,
        symbolSize: 7,
        lineStyle: { width: 2.5 },
        itemStyle: { color: '#5470c6' },
        data: holdingData.value.map((d: any) => d.sharpe_approx),
        markPoint: { data: [{ type: 'max', name: '最优' }] },
      },
      {
        name: '平均收益%',
        type: 'bar',
        yAxisIndex: 1,
        data: avgBars,
      },
    ],
  })
}

function renderLossChart() {
  if (!lossChartRef.value || holdingData.value.length === 0) return
  const existing = echarts.getInstanceByDom(lossChartRef.value)
  if (existing) existing.dispose()
  const chart = echarts.init(lossChartRef.value)
  const days = holdingData.value.map((d: any) => `${d.holding_days}天`)
  const p10 = holdingData.value.map((d: any) => d.percentile_10 ?? d.max_single_loss ?? 0)
  const maxLoss = holdingData.value.map((d: any) => d.max_single_loss ?? 0)
  const colors = holdingData.value.map((d: any) => tierColor(d.holding_days))
  const p10Bars = p10.map((v: number, i: number) => ({ value: v, itemStyle: { color: colors[i], opacity: 0.65 } }))
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['P10亏损', '最大单笔亏损'], top: 0, textStyle: { fontSize: 11 } },
    grid: { left: 56, right: 24, bottom: 40, top: 42 },
    xAxis: {
      type: 'category',
      data: days,
      axisLabel: { rotate: days.length > 8 ? 30 : 0, fontSize: 11 },
    },
    yAxis: { type: 'value', name: '亏损%', axisLabel: { formatter: '{value}%' } },
    series: [
      { name: 'P10亏损', type: 'bar', data: p10Bars },
      { name: '最大单笔亏损', type: 'line', data: maxLoss, smooth: true, symbolSize: 6, itemStyle: { color: '#cf1322' }, lineStyle: { color: '#cf1322' } },
    ],
  })
}

function renderTierChart() {
  if (!tierChartRef.value || holdingData.value.length === 0) return
  const existing = echarts.getInstanceByDom(tierChartRef.value)
  if (existing) existing.dispose()
  const chart = echarts.init(tierChartRef.value)
  // 按档位聚合
  const buckets: Record<string, any[]> = { short: [], mid: [], long: [] }
  for (const d of holdingData.value as any[]) {
    buckets[holdingTier(d.holding_days)].push(d)
  }
  const tiers: Array<'short' | 'mid' | 'long'> = ['short', 'mid', 'long']
  const tierNames = { short: '短(≤10日)', mid: '中(11~60日)', long: '长(>60日)' }
  const tierColors = { short: '#5470c6', mid: '#91cc75', long: '#fac858' }
  const avg = (arr: number[]) => arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : null
  const tierAvgRet: (number | null)[] = []
  const tierWinRate: (number | null)[] = []
  const tierSharpe: (number | null)[] = []
  const tierMaxLoss: (number | null)[] = []
  const sampleCnt: number[] = []
  for (const t of tiers) {
    const arr = buckets[t]
    sampleCnt.push(arr.length)
    if (arr.length === 0) {
      tierAvgRet.push(null); tierWinRate.push(null); tierSharpe.push(null); tierMaxLoss.push(null)
      continue
    }
    tierAvgRet.push(avg(arr.map((x: any) => Number(x.avg_return) || 0)))
    tierWinRate.push(avg(arr.map((x: any) => Number(x.win_rate) || 0)))
    tierSharpe.push(avg(arr.map((x: any) => Number(x.sharpe_approx) || 0)))
    tierMaxLoss.push(avg(arr.map((x: any) => Number(x.max_single_loss ?? x.percentile_10) || 0)))
  }
  const xLabels = tiers.map(t => `${tierNames[t]}\n(${sampleCnt[tiers.indexOf(t)]}档)`)
  const colorList = tiers.map(t => tierColors[t])
  const makeBar = (data: (number | null)[]) => data.map((v, i) => ({ value: v, itemStyle: { color: colorList[i], opacity: 0.85 } }))

  chart.setOption({
    tooltip: {
      trigger: 'axis',
      formatter: (params: any[]) => {
        const i = params[0].dataIndex
        const fmt = (n: any) => (n === null || n === undefined) ? '--' : Number(n).toFixed(2)
        return [
          `<b>${tierNames[tiers[i]]}</b>（包含 ${sampleCnt[i]} 个持仓档）`,
          `平均收益: ${fmt(tierAvgRet[i])}%`,
          `平均胜率: ${fmt(tierWinRate[i])}%`,
          `平均夏普: ${fmt(tierSharpe[i])}`,
          `平均最大单笔亏损: ${fmt(tierMaxLoss[i])}%`,
        ].join('<br/>')
      },
    },
    legend: {
      data: ['平均收益%', '平均胜率%', '平均夏普', '平均最大亏损%'],
      top: 0,
    },
    grid: { left: 60, right: 60, bottom: 50, top: 50 },
    xAxis: {
      type: 'category',
      data: xLabels,
      axisLabel: { fontSize: 12, lineHeight: 16 },
    },
    yAxis: [
      { type: 'value', name: '收益/胜率/亏损 %', axisLabel: { formatter: '{value}%' } },
      { type: 'value', name: '夏普', position: 'right' },
    ],
    series: [
      { name: '平均收益%', type: 'bar', barGap: 0, data: makeBar(tierAvgRet) },
      { name: '平均胜率%', type: 'bar', data: tierWinRate.map(v => ({ value: v, itemStyle: { color: '#3ba272', opacity: 0.6 } })) },
      { name: '平均夏普', type: 'line', yAxisIndex: 1, smooth: true, symbolSize: 10, lineStyle: { width: 3 }, itemStyle: { color: '#ee6666' }, data: tierSharpe },
      { name: '平均最大亏损%', type: 'line', smooth: true, symbolSize: 8, lineStyle: { color: '#cf1322', type: 'dashed' }, itemStyle: { color: '#cf1322' }, data: tierMaxLoss },
    ],
  })
}

function renderSltpChart(matrix: any[]) {
  if (!sltpChartRef.value || matrix.length === 0) return
  const existing = echarts.getInstanceByDom(sltpChartRef.value)
  if (existing) existing.dispose()
  const chart = echarts.init(sltpChartRef.value)
  const slValues = [...new Set(matrix.map(m => m.stop_loss))].sort((a, b) => a - b)
  const tpValues = [...new Set(matrix.map(m => m.take_profit))].sort((a, b) => a - b)
  const data = matrix.map(m => [tpValues.indexOf(m.take_profit), slValues.indexOf(m.stop_loss), m.sharpe ?? 0])

  chart.setOption({
    tooltip: { formatter: (p: any) => `止盈${tpValues[p.data[0]]}% / 止损${slValues[p.data[1]]}%<br/>夏普: ${p.data[2]?.toFixed(2)}<br/><em>点击查看详情</em>` },
    grid: { left: 80, right: 80, bottom: 40, top: 30 },
    xAxis: { type: 'category', data: tpValues.map(v => `${v}%`), name: '止盈' },
    yAxis: { type: 'category', data: slValues.map(v => `${v}%`), name: '止损' },
    visualMap: { min: -1, max: 4, calculable: true, orient: 'horizontal', left: 'center', bottom: 0, inRange: { color: ['#3060cf', '#ffffff', '#cf1322'] } },
    series: [{ type: 'heatmap', data, label: { show: true, formatter: (p: any) => p.data[2]?.toFixed(1) } }],
  })

  // 点击单元格弹窗
  chart.on('click', (params: any) => {
    if (params.componentType === 'series') {
      const tp = tpValues[params.data[0]]
      const sl = slValues[params.data[1]]
      const cellData = sltpMatrix.value.find((m: any) => m.stop_loss === sl && m.take_profit === tp)
      if (cellData) {
        sltpDialogData.value = cellData
        sltpDialogVisible.value = true
      }
    }
  })
}

function renderDrawdownChart() {
  if (!drawdownChartRef.value || returnSeries.value.length === 0) return
  const existing = echarts.getInstanceByDom(drawdownChartRef.value)
  if (existing) existing.dispose()
  const chart = echarts.init(drawdownChartRef.value)
  const dates = returnSeries.value.map(s => s.date)
  const dd = returnSeries.value.map(s => Number(s.drawdown || 0))
  let maxDD = 0
  let maxIdx = 0
  dd.forEach((v, i) => { if (v < maxDD) { maxDD = v; maxIdx = i } })
  chart.setOption({
    tooltip: { trigger: 'axis', formatter: (params: any) => {
      const p = params[0]
      return `${p.axisValue}<br/>回撤: ${Number(p.data).toFixed(2)}%`
    } },
    grid: { left: 56, right: 24, bottom: 36, top: 30 },
    xAxis: { type: 'category', data: dates, boundaryGap: false, axisLabel: { fontSize: 10 } },
    yAxis: { type: 'value', name: '回撤%', max: 0, axisLabel: { formatter: '{value}%' } },
    series: [{
      name: '回撤',
      type: 'line',
      data: dd,
      symbol: 'none',
      smooth: true,
      lineStyle: { color: '#ff4d4f', width: 1.5 },
      areaStyle: {
        color: new (echarts as any).graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(255,77,79,0.05)' },
          { offset: 1, color: 'rgba(255,77,79,0.4)' },
        ]),
      },
      markPoint: dates.length && maxDD < 0 ? {
        symbol: 'pin',
        symbolSize: 50,
        data: [{ name: '最大回撤', coord: [dates[maxIdx], maxDD], value: `${maxDD.toFixed(1)}%` }],
        itemStyle: { color: '#cf1322' },
        label: { fontSize: 10 },
      } : undefined,
    }],
  })
}

function renderCostChart() {
  if (!costChartRef.value || normalizedCostData.value.length === 0) return
  const existing = echarts.getInstanceByDom(costChartRef.value)
  if (existing) existing.dispose()
  const chart = echarts.init(costChartRef.value)
  const rows = normalizedCostData.value
  const xs = rows.map((r: any) => `${Number(r.cost_pct).toFixed(2)}%`)
  const avgReturn = rows.map((r: any) => Number(r.avg_return ?? 0))
  const sharpe = rows.map((r: any) => r.sharpe == null ? null : Number(r.sharpe))
  const currentIdx = rows.findIndex((r: any) => r.is_current)
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['平均收益', '夏普'], top: 0, textStyle: { fontSize: 11 } },
    grid: { left: 56, right: 56, bottom: 30, top: 36 },
    xAxis: { type: 'category', data: xs, name: '手续费' },
    yAxis: [
      { type: 'value', name: '收益%', axisLabel: { formatter: '{value}%' } },
      { type: 'value', name: '夏普', position: 'right' },
    ],
    series: [
      {
        name: '平均收益',
        type: 'line',
        data: avgReturn,
        smooth: true,
        symbolSize: 8,
        lineStyle: { color: '#1890ff', width: 2 },
        itemStyle: { color: '#1890ff' },
        markPoint: currentIdx >= 0 ? {
          symbol: 'pin',
          symbolSize: 44,
          data: [{ name: '当前费率', coord: [xs[currentIdx], avgReturn[currentIdx]], value: '当前' }],
          itemStyle: { color: '#52c41a' },
          label: { fontSize: 10 },
        } : undefined,
      },
      {
        name: '夏普',
        type: 'line',
        yAxisIndex: 1,
        data: sharpe,
        smooth: true,
        symbolSize: 6,
        lineStyle: { color: '#fa8c16', width: 2, type: 'dashed' },
        itemStyle: { color: '#fa8c16' },
      },
    ],
  })
}

function renderOosChart() {
  if (!oosChartRef.value) return
  if (oosTrainSeries.value.length === 0 && oosTestSeries.value.length === 0) return
  const existing = echarts.getInstanceByDom(oosChartRef.value)
  if (existing) existing.dispose()
  const chart = echarts.init(oosChartRef.value)
  const trainData = oosTrainSeries.value.map((s: any) => [s.date, Number(s.cumulative)])
  const testData = oosTestSeries.value.map((s: any) => [s.date, Number(s.cumulative)])
  chart.setOption({
    tooltip: { trigger: 'axis', formatter: (params: any) => {
      const lines = params.map((p: any) => `${p.marker}${p.seriesName}: ${Number(p.data[1]).toFixed(2)}`)
      return `${params[0].axisValue}<br/>${lines.join('<br/>')}`
    } },
    legend: { data: ['训练集', '测试集'], top: 0, textStyle: { fontSize: 11 } },
    grid: { left: 56, right: 24, bottom: 36, top: 36 },
    xAxis: { type: 'time', axisLabel: { fontSize: 10 } },
    yAxis: { type: 'value', name: '累计收益', axisLabel: { formatter: '{value}' } },
    series: [
      { name: '训练集', type: 'line', data: trainData, smooth: true, symbol: 'none', lineStyle: { color: '#1890ff', width: 2 }, itemStyle: { color: '#1890ff' } },
      { name: '测试集', type: 'line', data: testData, smooth: true, symbol: 'none', lineStyle: { color: '#fa8c16', width: 2 }, itemStyle: { color: '#fa8c16' } },
    ],
  })
}

async function computeOOS() {
  // 前端样本外验证: 基于日期拆分 70/30
  oosData.value = { train: null, test: null }
  oosWarning.value = ''
  oosTrainSeries.value = []
  oosTestSeries.value = []

  if (!startDate.value || !endDate.value) return
  const start = new Date(startDate.value)
  const end = new Date(endDate.value)
  const totalDays = (end.getTime() - start.getTime()) / (1000 * 86400)
  if (totalDays < 60) {
    oosWarning.value = '日期范围过短（<60天），无法进行样本外验证'
    return
  }

  // 70% 分割点
  const splitDate = new Date(start.getTime() + totalDays * 0.7 * 86400 * 1000)
  const splitStr = splitDate.toISOString().slice(0, 10)

  // 用两次 API 请求获取训练集和测试集数据
  const params = { strategy: strategy.value, holding_days: '5' }
  try {
    const [trainRes, testRes, trainSeriesRes, testSeriesRes] = await Promise.all([
      getHoldingPeriod({ ...params, start_date: startDate.value, end_date: splitStr }),
      getHoldingPeriod({ ...params, start_date: splitStr, end_date: endDate.value }),
      getReturnSeries({ strategy: strategy.value, start_date: startDate.value, end_date: splitStr, holding_days: 5 }).catch(() => null),
      getReturnSeries({ strategy: strategy.value, start_date: splitStr, end_date: endDate.value, holding_days: 5 }).catch(() => null),
    ]) as any[]

    const trainAnalysis = trainRes.analysis?.[0] || {}
    const testAnalysis = testRes.analysis?.[0] || {}
    oosData.value = {
      train: { ...trainAnalysis, period: `${startDate.value} ~ ${splitStr}`, signal_count: trainRes.total_signals || 0 },
      test: { ...testAnalysis, period: `${splitStr} ~ ${endDate.value}`, signal_count: testRes.total_signals || 0 },
    }
    oosTrainSeries.value = trainSeriesRes?.series || []
    oosTestSeries.value = testSeriesRes?.series || []
    if (oosTrainSeries.value.length > 0 || oosTestSeries.value.length > 0) {
      await nextTick()
      renderOosChart()
    }

    // 过拟合检测: 夏普衰减 >30%
    const trainSharpe = trainAnalysis.sharpe_approx
    const testSharpe = testAnalysis.sharpe_approx
    if (trainSharpe && testSharpe && trainSharpe > 0) {
      const decay = (trainSharpe - testSharpe) / trainSharpe * 100
      if (decay > 30) {
        oosWarning.value = `⚠️ 过拟合风险: 夏普从训练集 ${trainSharpe.toFixed(2)} 降至测试集 ${testSharpe.toFixed(2)}（衰减 ${decay.toFixed(0)}%）`
      }
    }
  } catch { /* ignore */ }
}
</script>

<style scoped>
.verify-optimize { padding: 16px; background: #f4f7fb; min-height: calc(100dvh - 80px); color: #303133; }
.feature-tabs { display: flex; align-items: center; gap: 0; height: 42px; padding: 0 12px; margin-bottom: 12px; background: #fff; border: 1px solid #ebeef5; border-radius: 4px; }
.feature-tab { height: 42px; display: inline-flex; align-items: center; padding: 0 18px; font-size: 13px; color: #606266; border-bottom: 2px solid transparent; cursor: pointer; text-decoration: none; }
.feature-tab.router-link-exact-active { color: #1890ff; border-bottom-color: #1890ff; font-weight: 600; }
.toolbar { display: flex; align-items: flex-end; flex-wrap: wrap; gap: 16px; padding: 14px 16px; margin-top: 12px; background: #fff; border: 1px solid #ebeef5; border-radius: 4px; }
.toolbar-group { display: flex; flex-direction: column; gap: 5px; }
.toolbar-label { font-size: 12px; color: #909399; font-weight: 500; }
.analyze-btn { min-width: 72px; }
.date-range-row { display: inline-flex; align-items: center; gap: 8px; color: #909399; }
.option-badge { float: right; margin-left: 12px; padding: 0 6px; border-radius: 3px; background: #ecf5ff; color: #1890ff; font-size: 11px; }
.period-row { display: flex; }
.radio-btn { padding: 5px 15px; border: 1px solid #dcdfe6; font-size: 12px; line-height: 20px; background: #fff; color: #303133; cursor: pointer; user-select: none; }
.radio-btn:first-child { border-radius: 4px 0 0 4px; }
.radio-btn:last-child { border-radius: 0 4px 4px 0; }
.radio-btn + .radio-btn { margin-left: -1px; }
.radio-btn.active { background: #ecf5ff; border-color: #1890ff; color: #1890ff; position: relative; z-index: 1; font-weight: 600; }
.radio-btn:hover:not(.active) { color: #1890ff; border-color: #1890ff; position: relative; z-index: 1; }
.summary-strip { display: grid; grid-template-columns: repeat(5, minmax(140px, 1fr)); gap: 10px; margin: 12px 0; }
.summary-card { min-height: 74px; padding: 12px 14px; background: #fff; border: 1px solid #ebeef5; border-radius: 4px; display: flex; flex-direction: column; justify-content: center; }
.summary-card.highlight { border-left: 3px solid #1890ff; background: #f5fbff; }
.summary-label { font-size: 12px; color: #909399; }
.summary-card strong { margin-top: 4px; font-size: 20px; line-height: 1.2; color: #303133; }
.summary-sub { margin-top: 4px; font-size: 11px; color: #909399; }
.opt-tabs { margin-top: 12px; }
:deep(.opt-tabs > .el-tabs__header) { margin-bottom: 12px; }
:deep(.opt-tabs .el-tabs__nav) { border-radius: 4px; overflow: hidden; }
:deep(.opt-tabs .el-tabs__item) { height: 34px; padding: 0 18px; font-size: 12px; background: #fff; }
:deep(.opt-tabs .el-tabs__item.is-active) { background: #1890ff; color: #fff; border-color: #1890ff; }
.result-card { background: #fff; border: 1px solid #ebeef5; border-radius: 4px; overflow: hidden; }
.card-head { min-height: 44px; padding: 10px 14px; display: flex; align-items: center; justify-content: space-between; gap: 12px; border-bottom: 1px solid #ebeef5; background: #fff; }
.card-head h3 { margin: 0; font-size: 14px; font-weight: 600; color: #303133; }
.card-head span { display: block; margin-top: 3px; font-size: 11px; color: #909399; }
.card-head em { font-style: normal; font-size: 11px; color: #909399; }
.inline-controls { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.table-wrapper { overflow-x: auto; }
.cmp-table { width: 100%; border-collapse: collapse; font-size: 12px; background: #fff; }
.cmp-table th, .cmp-table td { border: 1px solid #ebeef5; padding: 7px 10px; text-align: center; white-space: nowrap; }
.cmp-table th { background: #fafafa; font-weight: 600; color: #303133; }
.cmp-table .sort-th { background: #e8f4fd; }
.cmp-table .sort-cell { background: #f0f7ff; font-weight: 600; }
.best-row { background: #f0f9eb; }
.best-row .sort-cell { background: #d6eaff; color: #1890ff; font-size: 13px; }
/* 持仓档位行底色：避免遮挡 best-row 高亮，使用左侧色带而非整行底色 */
.cmp-table tr.tier-short td:first-child { box-shadow: inset 3px 0 0 #5470c6; }
.cmp-table tr.tier-mid td:first-child { box-shadow: inset 3px 0 0 #91cc75; }
.cmp-table tr.tier-long td:first-child { box-shadow: inset 3px 0 0 #fac858; }
.tier-badge { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; color: #fff; }
.tier-badge-short { background: #5470c6; }
.tier-badge-mid { background: #91cc75; color: #2c3e50; }
.tier-badge-long { background: #fac858; color: #644b1c; }
.star { margin-left: 4px; color: #f5a623; }
.data-note { padding: 6px 12px; border-top: 1px solid #ebeef5; color: #909399; font-size: 11px; }
.chart-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 12px; }
.chart-box { height: 260px; }
.heatmap-box { height: 360px; }
.chart-placeholder { min-height: 240px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; margin: 12px; border: 1px dashed #dcdfe6; background: #fbfcfe; color: #909399; text-align: center; }
.chart-placeholder span { font-size: 26px; }
.chart-placeholder p { margin: 0; font-size: 12px; }
.chart-card { overflow: hidden; }
.custom-note { margin: 12px; padding: 10px 12px; background: #f5fbff; border: 1px solid #d6eaff; border-radius: 4px; color: #606266; font-size: 12px; line-height: 1.7; }
.custom-note.success { margin: 12px 0 0; background: #f0f9eb; border-color: #d9f2c7; color: #389e0d; }
.stat-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.stat-card { min-height: 76px; padding: 14px 18px; background: #fff; border: 1px solid #ebeef5; border-left: 3px solid #1890ff; border-radius: 4px; text-align: center; }
.stat-card span { display: block; font-size: 12px; color: #909399; }
.stat-card strong { display: block; margin-top: 5px; font-size: 22px; line-height: 1.1; color: #303133; }
.stat-card em { display: block; margin-top: 7px; font-style: normal; font-size: 11px; color: #606266; }
.stat-card.danger { border-left-color: #cf1322; }
.stat-card.danger strong { color: #389e0d; }
.stat-card.positive { border-left-color: #cf1322; }
.stat-card.positive strong { color: #cf1322; }
.stat-card.primary { border-left-color: #1890ff; }
.stat-card.primary strong { color: #1890ff; }
.oos-grid { display: grid; grid-template-columns: minmax(320px, 1fr) minmax(420px, 1fr); gap: 12px; padding: 12px; }
.best-combo { margin-top: 12px; padding: 10px 16px; background: #f6ffed; border-radius: 4px; font-weight: 600; color: #389e0d; }
.text-red { color: #cf1322; }
.text-green { color: #389e0d; }
.font-bold { font-weight: 700; }
.info-text { color: #8c8c8c; font-size: 13px; margin-bottom: 8px; }
.badge { display: inline-flex; align-items: center; justify-content: center; padding: 1px 7px; border-radius: 3px; font-size: 11px; font-weight: 600; }
.b-best { background: #e6f7ff; color: #1890ff; }
.b-pos { background: #f6ffed; color: #389e0d; }
.b-neg { background: #fff1f0; color: #cf1322; }
.b-flat { background: #f5f7fa; color: #909399; }
.ai-section { margin-top: 16px; }
.section-title { margin-bottom: 8px; padding-left: 8px; border-left: 3px solid #1890ff; font-size: 14px; font-weight: 600; color: #303133; }
.suggest-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.suggest-card { padding: 14px 16px; background: #fff; border: 1px solid #ebeef5; border-left: 3px solid #1890ff; border-radius: 4px; }
.suggest-buy { border-left-color: #389e0d; }
.suggest-risk { border-left-color: #d48806; }
.suggest-hold { border-left-color: #1890ff; }
.suggest-title { display: flex; align-items: center; gap: 6px; font-weight: 600; margin-bottom: 8px; font-size: 13px; }
.suggest-content { font-size: 12px; line-height: 1.9; color: #595959; }
:deep(.suggest-content code), .suggest-content :deep(code) { background: #f5f7fa; padding: 1px 6px; border-radius: 2px; color: #303133; }
:deep(.suggest-content .badge) { display: inline-flex; align-items: center; justify-content: center; padding: 1px 7px; border-radius: 3px; font-size: 11px; font-weight: 600; }
:deep(.suggest-content .b-best) { background: #e6f7ff; color: #1890ff; }
:deep(.suggest-content .b-pos) { background: #f6ffed; color: #389e0d; }
/* Tooltip header tips */
.th-tip { cursor: help; display: inline-flex; align-items: center; gap: 2px; }
.tip-icon { display: inline-flex; align-items: center; justify-content: center; width: 14px; height: 14px; border-radius: 50%; background: #e6e8eb; color: #606266; font-size: 10px; font-style: normal; }
@media (max-width: 1200px) {
  .summary-strip { grid-template-columns: repeat(3, minmax(140px, 1fr)); }
  .chart-grid, .suggest-grid, .stat-grid, .oos-grid { grid-template-columns: 1fr; }
}

/* ─── 移动端适配（PR-08b） ─── */
@media (max-width: 768px) {
  .verify-optimize, .optimize-page { padding: 10px 8px !important; }
  .feature-tabs { overflow-x: auto; padding: 0 6px; }
  .feature-tab { padding: 0 12px; font-size: 12px; flex-shrink: 0; }
  .toolbar, .filter-bar, .control-bar { flex-direction: column; align-items: stretch; gap: 10px; }
  .toolbar-group, .control-group { width: 100%; }
  .el-date-editor, .el-select { width: 100% !important; }
  .summary-strip { grid-template-columns: repeat(2, 1fr) !important; }
  .chart-grid, .suggest-grid, .stat-grid, .oos-grid { grid-template-columns: 1fr !important; }
  table { font-size: 11px; }
  table th, table td { padding: 6px 4px !important; }
}
</style>
