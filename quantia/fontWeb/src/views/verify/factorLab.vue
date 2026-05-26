<template>
  <div class="factor-lab">
    <div class="feature-tabs">
      <router-link class="feature-tab" to="/verify/compare">策略对比</router-link>
      <router-link class="feature-tab" to="/verify/optimize">买卖点优化</router-link>
      <router-link class="feature-tab" to="/verify/fusion">多维融合</router-link>
      <router-link class="feature-tab" to="/verify/factor-lab">因子实验室</router-link>
    </div>
    <!-- 使用说明 -->
    <UsageGuide
      title="📖 因子实验室 使用说明（点击展开）"
      :steps="guideSteps"
      :example="guideExample"
      :metrics="guideMetrics"
      :tips="guideTips"
    />
    <!-- 顶部工具栏 -->
    <div class="lab-toolbar">
      <div class="toolbar-left">
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          unlink-panels
          range-separator="~"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          format="YYYY-MM-DD"
          value-format="YYYY-MM-DD"
          :disabled-date="(d: Date) => d > new Date()"
          size="small"
          style="width: 240px"
        />
        <el-select v-model="holdingDays" size="small" style="width: 120px">
          <el-option v-for="d in [1,3,5,7,10,15,20,30]" :key="d" :label="`${d}日持仓`" :value="d" />
        </el-select>
        <el-select v-model="fusionMode" size="small" style="width: 150px">
          <el-option label="全部满足(AND)" value="and" />
          <el-option label="满足N项(投票)" value="vote" />
          <el-option label="加权评分(Score)" value="score" />
        </el-select>
        <el-input-number
          v-if="fusionMode === 'vote'"
          v-model="voteThreshold"
          :min="2"
          :max="activeFactors.length"
          size="small"
          style="width: 100px"
          controls-position="right"
        />
      </div>
      <div class="toolbar-right">
        <el-dropdown trigger="click" @command="handleConfigCommand" style="margin-right: 8px">
          <el-button size="small">
            方案 <el-icon class="el-icon--right"><ArrowDown /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="save">💾 保存当前方案</el-dropdown-item>
              <el-dropdown-item command="load" divided>📂 加载方案</el-dropdown-item>
              <el-dropdown-item command="export">📄 导出 Python 代码</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-button type="primary" :loading="running" size="small" @click="runBacktest">
          ▶ 运行回测
        </el-button>
      </div>
    </div>

    <!-- 预设模板 -->
    <div class="preset-bar">
      <span class="preset-label">预设:</span>
      <el-tag
        v-for="p in presets"
        :key="p.id"
        :type="p.id === activePreset ? '' : 'info'"
        size="small"
        class="preset-chip"
        @click="loadPreset(p)"
      >{{ p.name }}</el-tag>
    </div>

    <!-- 三栏布局 -->
    <div class="lab-grid">
      <!-- 左栏: 因子面板 -->
      <div class="lab-col lab-col-left">
        <div class="panel-header">因子面板</div>
        <el-input
          v-model="searchQuery"
          placeholder="搜索因子..."
          size="small"
          clearable
          prefix-icon="Search"
          class="factor-search"
        />
        <div class="factor-categories">
          <div
            v-for="cat in filteredCategories"
            :key="cat.key"
            class="cat-section"
          >
            <div class="cat-header" @click="toggleCategory(cat.key)">
              <span class="cat-icon">{{ cat.icon }}</span>
              <span class="cat-name">{{ cat.name }}</span>
              <span class="cat-count">({{ cat.factors.length }})</span>
              <el-icon class="cat-arrow">
                <ArrowDown v-if="expandedCats.has(cat.key)" />
                <ArrowRight v-else />
              </el-icon>
            </div>
            <div v-show="expandedCats.has(cat.key)" class="cat-items">
              <el-tooltip
                v-for="f in cat.factors"
                :key="f.id"
                placement="right"
                :show-after="300"
                :disabled="!f.description"
              >
                <template #content>
                  <div style="max-width: 280px; line-height: 1.5">
                    <div style="font-weight: 600; margin-bottom: 4px">{{ f.name }}</div>
                    <div style="font-size: 12px; color: #ddd">{{ f.description || '暂无说明' }}</div>
                    <div v-if="f.default_operator || f.default_value != null" style="font-size: 12px; margin-top: 4px; color: #ffd54f">
                      默认: {{ f.default_operator || '' }} {{ Array.isArray(f.default_value) ? f.default_value.join('~') : (f.default_value ?? '') }}
                    </div>
                    <div v-if="f.presets && f.presets.length" style="font-size: 12px; margin-top: 4px; color: #aed581">
                      常用阈值: {{ f.presets.map(p => p.label).join(' / ') }}
                    </div>
                  </div>
                </template>
                <div
                  class="factor-item"
                  :class="{ added: isFactorAdded(f.id) }"
                  @click="addFactor(f)"
                >
                  <span class="fi-icon" :style="{ background: categoryColor(f.category) }">
                    {{ f.icon }}
                  </span>
                  <span class="fi-name">{{ f.name }}</span>
                  <el-icon v-if="!isFactorAdded(f.id)" class="fi-add"><Plus /></el-icon>
                  <el-icon v-else class="fi-check"><Check /></el-icon>
                </div>
              </el-tooltip>
            </div>
          </div>
        </div>
      </div>

      <!-- 中栏: 活跃因子 -->
      <div class="lab-col lab-col-center">
        <div class="panel-header">
          活跃因子
          <span class="factor-count">{{ activeFactors.length }} / 15</span>
        </div>

        <!-- 权重警告 -->
        <div v-if="weightSum !== 100 && activeFactors.length > 0" class="weight-warn">
          <span class="ww-icon">⚠</span>
          <span>当前权重合计 <b>{{ weightSum }}%</b>，建议归一化到 100%</span>
          <el-button size="small" text type="warning" @click="normalizeWeights">
            一键归一化
          </el-button>
        </div>

        <!-- 因子卡片列表 -->
        <div class="active-factors">
          <div
            v-for="(af, idx) in activeFactors"
            :key="af.id"
            class="factor-card"
            :class="{ collapsed: collapsedCards.has(af.id) }"
          >
            <div class="fc-head" @click="toggleCard(af.id)">
              <span class="drag-grip" title="拖拽排序" @click.stop>⠿</span>
              <span class="fc-icon" :style="{ background: categoryColor(af.category) }">
                {{ af.icon }}
              </span>
              <span class="fc-name">
                {{ af.name }}
                <span class="fc-tag" :class="'t-' + af.category">
                  {{ categoryLabel(af.category) }}
                </span>
                <el-tooltip v-if="findFactorMeta(af.id)?.description" placement="top" :show-after="300">
                  <template #content>
                    <div style="max-width: 280px; line-height: 1.5">
                      <div style="font-size: 12px">{{ findFactorMeta(af.id)?.description }}</div>
                      <div v-if="findFactorMeta(af.id)?.presets?.length" style="font-size: 12px; margin-top: 4px; color: #aed581">
                        常用阈值: {{ findFactorMeta(af.id)?.presets?.map(p => p.label).join(' / ') }}
                      </div>
                    </div>
                  </template>
                  <el-icon class="fc-info" style="margin-left: 4px; color: #909399; cursor: help; font-size: 13px">
                    <QuestionFilled />
                  </el-icon>
                </el-tooltip>
              </span>
              <span
                v-if="getContribution(af.id) !== null"
                class="fc-impact"
                :class="(getContribution(af.id) ?? 0) >= 0 ? 'text-pos' : 'text-neg'"
              >
                夏普{{ (getContribution(af.id) ?? 0) >= 0 ? '+' : '' }}{{ getContribution(af.id) }}
              </span>
              <el-switch v-model="af.enabled" size="small" />
              <el-icon class="fc-collapse-icon" :class="{ open: !collapsedCards.has(af.id) }">
                <ArrowDown />
              </el-icon>
              <el-button
                size="small"
                text
                type="danger"
                circle
                @click.stop="removeFactor(idx)"
              >✕</el-button>
            </div>
            <div class="fc-body" v-show="!collapsedCards.has(af.id)">
              <!-- 策略信号: 仅权重 -->
              <template v-if="af.type === 'signal'">
                <div class="param-row">
                  <span class="p-label">权重</span>
                  <el-slider
                    v-model="af.weight"
                    :min="0"
                    :max="100"
                    :show-tooltip="false"
                    size="small"
                    style="flex: 1; margin: 0 8px"
                  />
                  <el-input-number
                    v-model="af.weight"
                    :min="0"
                    :max="100"
                    size="small"
                    controls-position="right"
                    style="width: 80px"
                  />
                  <span class="p-unit">%</span>
                </div>
                <div class="fc-tip">此策略为信号类因子，仅有"是/否"状态。调整权重改变其在融合评分中的占比。</div>
              </template>

              <!-- 连续/区间指标: 条件 + 权重 -->
              <template v-else>
                <div class="param-row">
                  <span class="p-label">条件</span>
                  <el-select v-model="af.operator" size="small" style="width: 80px">
                    <el-option label="<" value="<" />
                    <el-option label="≤" value="<=" />
                    <el-option label=">" value=">" />
                    <el-option label="≥" value=">=" />
                    <el-option label="介于" value="between" />
                  </el-select>
                  <template v-if="af.operator === 'between'">
                    <el-input-number
                      v-model="(af.value as number[])[0]"
                      size="small"
                      controls-position="right"
                      style="width: 90px"
                    />
                    <span class="p-sep">~</span>
                    <el-input-number
                      v-model="(af.value as number[])[1]"
                      size="small"
                      controls-position="right"
                      style="width: 90px"
                    />
                  </template>
                  <template v-else>
                    <el-input-number
                      v-model="af.value as number"
                      size="small"
                      controls-position="right"
                      style="width: 120px"
                      @update:model-value="(v: number | undefined) => af.value = v ?? 0"
                    />
                  </template>
                </div>
                <div class="param-row">
                  <span class="p-label">权重</span>
                  <el-slider
                    v-model="af.weight"
                    :min="0"
                    :max="100"
                    :show-tooltip="false"
                    size="small"
                    style="flex: 1; margin: 0 8px"
                  />
                  <el-input-number
                    v-model="af.weight"
                    :min="0"
                    :max="100"
                    size="small"
                    controls-position="right"
                    style="width: 80px"
                  />
                  <span class="p-unit">%</span>
                </div>
                <!-- 快捷预设 -->
                <div v-if="af.presets && af.presets.length" class="preset-chips">
                  <span class="chips-label">快捷:</span>
                  <el-tag
                    v-for="(ps, pi) in af.presets"
                    :key="pi"
                    size="small"
                    :type="isPresetActive(af, ps) ? '' : 'info'"
                    class="chip"
                    @click="applyFactorPreset(af, ps)"
                  >{{ ps.label }}</el-tag>
                </div>
              </template>
            </div>
          </div>

          <!-- 空状态 -->
          <div v-if="activeFactors.length === 0" class="empty-state">
            ← 从左侧因子面板点击 + 添加因子<br>
            <span class="empty-hint">建议添加 3~8 个因子，不超过 15 个以避免过拟合</span>
          </div>
        </div>

        <!-- 信号稀疏警告 -->
        <div v-if="result && result.signal_sparse_warning" class="signal-warn">
          <span class="sw-icon">⚠</span>
          <div class="sw-body">
            <div class="sw-title">
              <template v-if="result.signal_sparse_reason === 'filtered_out'">
                过滤因子把信号全部过滤掉了 — 基础信号 <b>{{ result.signal_diagnosis?.base_signal_count ?? '?' }}</b> 条 → 过滤后 <b>0</b> 条
              </template>
              <template v-else-if="result.signal_sparse_reason === 'no_base_signal'">
                策略本身在该区间无买入信号（基础池 <b>0</b> 条）
              </template>
              <template v-else-if="result.signal_sparse_reason === 'low_density'">
                日均信号 <b>{{ result.kpi.daily_signal_avg }}</b> 偏低，低于稀疏阈值 3
              </template>
              <template v-else>
                日均信号数仅 <b>{{ result.kpi.daily_signal_avg }}</b>，接近稀疏阈值(3)
              </template>
            </div>
            <div v-if="result.signal_sparse_hint" class="sw-hint">{{ result.signal_sparse_hint }}</div>
          </div>
        </div>
      </div>

      <!-- 右栏: 结果面板 -->
      <div class="lab-col lab-col-right">
        <div class="panel-header">回测结果</div>

        <!-- 首次进入空状态 -->
        <div v-if="!result && !running" class="empty-result">
          <el-empty description="请添加因子并运行回测" :image-size="80" />
        </div>

        <!-- Loading -->
        <div v-if="running" class="loading-state">
          <el-skeleton :rows="6" animated />
        </div>

        <!-- 操作日志 -->
        <div class="card" v-if="changeLog.length" style="margin-top: 8px">
          <div class="card-h">操作日志 <span class="card-sub">本次会话变更记录</span></div>
          <div class="card-b log-list">
            <div v-for="(log, li) in changeLog.slice(-8)" :key="li" class="log-item">
              <span class="log-time">{{ log.time }}</span>
              <span class="log-badge" :class="'lb-' + log.type">{{ logBadgeText(log.type) }}</span>
              <span class="log-text">{{ log.text }}</span>
            </div>
          </div>
        </div>

        <!-- AI 助手面板 -->
        <div class="card ai-panel">
          <div class="card-h">
            AI 助手
            <el-select v-model="aiModel" size="small" style="width: 140px; margin-left: auto" placeholder="使用默认" clearable>
              <el-option label="默认 (依 后端配置)" value="" />
              <el-option label="通义千问 Qwen" value="qwen" />
              <el-option label="OpenAI GPT-4o" value="openai" />
              <el-option label="DeepSeek" value="deepseek" />
              <el-option label="Kimi (Moonshot)" value="kimi" />
              <el-option label="OpenRouter" value="openrouter" />
            </el-select>
          </div>
          <div class="card-b ai-body">
            <div v-if="aiSuggestion" class="ai-msg">
              <div class="ai-msg-text">{{ aiSuggestion }}</div>
              <div v-if="aiPlan.length" style="font-size: 12px; color: #909399; margin-top: 4px">
                可应用 {{ aiPlan.length }} 项操作
              </div>
              <div v-else style="font-size: 12px; color: #e6a23c; margin-top: 4px">
                未解析到结构化操作（AI 返回未包含 JSON），无法自动应用
              </div>
              <div class="ai-actions">
                <el-button
                  size="small"
                  type="primary"
                  text
                  :disabled="!aiPlan.length"
                  @click="applyAiSuggestion"
                >✓ 应用建议</el-button>
                <el-button size="small" text @click="aiSuggestion = ''; aiPlan = []">忽略</el-button>
              </div>
            </div>
            <div v-else class="ai-empty">点击下方按钮获取 AI 优化建议</div>
            <div class="ai-input-row">
              <el-input
                v-model="aiInput"
                size="small"
                placeholder="向 AI 提问或描述需求..."
                @keyup.enter="askAi"
              />
              <el-button size="small" type="primary" :loading="aiLoading" @click="askAi">发送</el-button>
            </div>
          </div>
        </div>

        <!-- 结果内容 -->
        <template v-if="result && !running">
          <!-- KPI 卡片 -->
          <div class="result-kpi">
            <div class="kpi highlight">
              <div class="k-label">夏普比率</div>
              <div class="k-value" :class="kpiColor(result.kpi.sharpe)">
                {{ result.kpi.sharpe ?? '-' }}
              </div>
              <div v-if="sharpeImprovement" class="k-delta text-pos">
                vs 基线 {{ sharpeImprovement }}
              </div>
            </div>
            <div class="kpi">
              <div class="k-label">胜率</div>
              <div class="k-value">{{ result.kpi.win_rate != null ? result.kpi.win_rate + '%' : '-' }}</div>
            </div>
            <div class="kpi">
              <div class="k-label">{{ holdingDays }}日平均收益</div>
              <div class="k-value" :class="(result.kpi.avg_return ?? 0) > 0 ? 'text-pos' : 'text-neg'">
                {{ result.kpi.avg_return != null ? (result.kpi.avg_return > 0 ? '+' : '') + result.kpi.avg_return + '%' : '-' }}
              </div>
            </div>
            <div class="kpi">
              <div class="k-label">最大回撤</div>
              <div class="k-value" :class="kpiColor(-(result.kpi.max_drawdown ?? 0))">
                {{ result.kpi.max_drawdown != null ? result.kpi.max_drawdown + '%' : '-' }}
              </div>
            </div>
            <div class="kpi">
              <div class="k-label">日均信号数</div>
              <div class="k-value">{{ result.kpi.daily_signal_avg }}</div>
              <div v-if="result.kpi.filter_rate" class="k-delta" style="color: #999">
                筛选率 {{ result.kpi.filter_rate }}%
              </div>
            </div>
            <div class="kpi">
              <div class="k-label">Calmar</div>
              <div class="k-value">{{ result.kpi.calmar ?? '-' }}</div>
            </div>
          </div>

          <!-- 迷你收益曲线 -->
          <div ref="chartRef" class="result-chart" />

          <!-- 因子贡献排名 -->
          <div v-if="result.factor_contributions.length" class="card">
            <div class="card-h">因子贡献排名 <span class="card-sub">对夏普的边际贡献</span></div>
            <div class="card-b">
              <div
                v-for="fc in result.factor_contributions"
                :key="fc.id"
                class="contrib-row"
              >
                <span class="cr-icon" :style="{ background: categoryColor(fc.category) }">
                  {{ fc.name[0] }}
                </span>
                <span class="cr-name">{{ fc.name }}</span>
                <div class="cr-bar">
                  <div
                    class="cr-fill"
                    :style="{
                      width: contribBarWidth(fc.impact) + '%',
                      background: (fc.impact ?? 0) >= 0 ? categoryColor(fc.category) : '#ff4d4f'
                    }"
                  />
                </div>
                <span
                  class="cr-val"
                  :class="(fc.impact ?? 0) >= 0 ? 'text-pos' : 'text-neg'"
                >{{ fc.impact != null ? ((fc.impact >= 0 ? '+' : '') + fc.impact) : '-' }}</span>
              </div>
            </div>
          </div>

          <!-- 对比表 -->
          <div class="card">
            <div class="card-h">与基线对比</div>
            <div class="card-b" style="padding: 0; overflow-x: auto">
              <table class="compare-table">
                <thead>
                  <tr>
                    <th>指标</th>
                    <th>纯策略信号</th>
                    <th class="best-col">当前方案</th>
                    <th>变化</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>{{ holdingDays }}日收益</td>
                    <td>{{ fmtPct(result.baseline.avg_return) }}</td>
                    <td class="best-cell">{{ fmtPct(result.kpi.avg_return) }}</td>
                    <td>{{ fmtDelta(result.kpi.avg_return, result.baseline.avg_return) }}</td>
                  </tr>
                  <tr>
                    <td>胜率</td>
                    <td>{{ fmtPct(result.baseline.win_rate) }}</td>
                    <td class="best-cell">{{ fmtPct(result.kpi.win_rate) }}</td>
                    <td>{{ fmtDeltaPP(result.kpi.win_rate, result.baseline.win_rate) }}</td>
                  </tr>
                  <tr>
                    <td>夏普</td>
                    <td>{{ result.baseline.sharpe ?? '-' }}</td>
                    <td class="best-cell">{{ result.kpi.sharpe ?? '-' }}</td>
                    <td>{{ fmtDelta(result.kpi.sharpe, result.baseline.sharpe) }}</td>
                  </tr>
                  <tr>
                    <td>最大回撤</td>
                    <td>{{ fmtPct(result.baseline.max_drawdown) }}</td>
                    <td class="best-cell">{{ fmtPct(result.kpi.max_drawdown) }}</td>
                    <td>{{ fmtDelta(result.kpi.max_drawdown, result.baseline.max_drawdown) }}</td>
                  </tr>
                  <tr>
                    <td>信号数</td>
                    <td>{{ result.baseline.signal_count }}</td>
                    <td>{{ result.kpi.signal_count }}</td>
                    <td>{{ fmtDelta(result.kpi.signal_count, result.baseline.signal_count) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </template>
      </div>
    </div>

    <!-- 保存方案弹窗 -->
    <el-dialog v-model="saveDialogVisible" title="保存因子方案" width="min(420px, 92vw)" destroy-on-close>
      <el-form :model="saveForm" label-width="80px" size="small">
        <el-form-item label="方案名称">
          <el-input v-model="saveForm.name" placeholder="例如：技术+价值多因子" maxlength="200" show-word-limit />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="saveForm.description" type="textarea" :rows="2"
            placeholder="可选，简要描述该方案的用途" maxlength="500" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="saveDialogVisible = false">取消</el-button>
        <el-button type="primary" size="small" :loading="saving" @click="doSaveConfig">保存</el-button>
      </template>
    </el-dialog>

    <!-- 加载方案抽屉 -->
    <el-drawer v-model="loadDrawerVisible" title="我的方案" size="400px" destroy-on-close>
      <div v-if="myConfigs.length === 0" style="text-align: center; padding: 32px; color: #999">
        暂无保存的方案
      </div>
      <div v-for="cfg in myConfigs" :key="cfg.id" class="config-card">
        <div class="cfg-head">
          <span class="cfg-name">{{ cfg.name }}</span>
          <span class="cfg-time">{{ cfg.updated_at }}</span>
        </div>
        <div class="cfg-meta">
          {{ cfg.factors.length }} 个因子 · {{ cfg.fusion_mode }}
          · {{ cfg.holding_days }}日持仓
        </div>
        <div v-if="cfg.description" class="cfg-desc">{{ cfg.description }}</div>
        <div class="cfg-actions">
          <el-button size="small" type="primary" text @click="loadConfig(cfg)">加载</el-button>
          <el-button size="small" type="danger" text @click="doDeleteConfig(cfg.id)">删除</el-button>
        </div>
      </div>
    </el-drawer>

    <!-- 导出代码弹窗 -->
    <el-dialog v-model="exportDialogVisible" title="导出 Python 策略代码" width="min(680px, 92vw)" destroy-on-close>
      <div v-if="exportCode" class="export-code-wrapper">
        <div class="export-toolbar">
          <span class="export-filename">{{ exportFilename }}</span>
          <el-button size="small" type="primary" text @click="copyExportCode">复制代码</el-button>
          <el-button size="small" text @click="downloadExportCode">下载 .py 文件</el-button>
        </div>
        <pre class="export-code"><code>{{ exportCode }}</code></pre>
      </div>
      <div v-else style="text-align: center; padding: 24px; color: #999">正在生成代码...</div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick, onUnmounted, watch } from 'vue'
import { ArrowDown, ArrowRight, Plus, Check, QuestionFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import dayjs from 'dayjs'
import {
  getFactorCatalog,
  getFactorPresets,
  runFactorLab,
  saveFactorConfig,
  getMyConfigs,
  deleteFactorConfig,
  exportFactorCode,
  type FactorMeta,
  type FactorCategory,
  type Preset,
  type FactorLabRunResult,
  type FactorLabConfig,
} from '@/api/factorLab'
import UsageGuide from '@/components/verify/UsageGuide.vue'
import { aiChat } from '@/api/ai'

const guideSteps = [
  '从左侧 <b>因子面板</b> 点击 "+" 添加因子到中间栏（支持搜索和分类浏览）',
  '在中间栏 <b>活跃因子</b> 卡片中设置每个因子的 <b>条件</b> 和 <b>权重</b>',
  '信号类因子（策略信号）只需设置权重；连续指标可设置过滤条件（>、<、介于）',
  '确保权重合计 = 100%（可点击 <b>"一键归一化"</b> 自动调整）',
  '选择顶部的 <b>日期范围</b>、<b>持仓天数</b>、<b>融合模式</b>',
  '点击 <b>"▶运行回测"</b>，右栏显示 KPI、收益曲线和因子贡献排名',
  '使用 <b>预设模板</b>（顶部chip）快速加载推荐因子组合',
  '使用 <b>"方案"</b> 下拉保存/加载/导出当前配置',
  '底部 <b>AI助手</b> 可输入需求获取智能优化建议',
]
const guideExample = `<b>场景：</b>构建"技术+基本面"多因子选股模型<br/>
<b>操作：</b>点击预设"技术+基本面(推荐)" → 系统自动添加均线多头、放量上涨、PE、ROE等因子 → 调整权重 → 运行回测<br/>
<b>或手动：</b>搜索"RSI" → 添加RSI因子 → 设条件"介于 30~70" → 权重20% → 再添加"放量上涨"信号 → 权重30% → 一键归一化 → 运行`
const guideMetrics = [
  { name: '夏普比率', desc: '风险调整后收益的核心指标', range: '-∞ ~ +∞', good: '> 1.5 为良好，> 2.5 为优秀' },
  { name: '胜率', desc: '产生买入信号后持仓盈利的概率', range: '0% ~ 100%', good: '> 55% 为较好' },
  { name: '平均收益', desc: '持仓期内的平均涨跌幅', range: '-∞ ~ +∞', good: '> 1.5% (5日持仓) 为良好' },
  { name: '最大回撤', desc: '从历史最高点下跌的最大幅度', range: '-100% ~ 0%', good: '> -20% 为可接受' },
  { name: '日均信号数', desc: '每日平均发出的买入信号数量', range: '0 ~ 5000', good: '3~30 为理想（太少不可靠，太多无法精选）' },
  { name: 'Calmar', desc: '年化收益 / 最大回撤的绝对值', range: '0 ~ +∞', good: '> 2.0 为优秀' },
  { name: '因子贡献(Shapley)', desc: '每个因子对整体夏普的边际贡献', range: '-∞ ~ +∞', good: '正值=有效因子，负值=建议移除' },
  { name: '筛选率', desc: '通过所有因子条件的股票占全市场比例', range: '0% ~ 100%', good: '5%~30% 为合理筛选力度' },
]
const guideTips = [
  '因子数量建议 3~8 个，过多(>10)容易过拟合，过少(<3)覆盖维度不足',
  '同类因子（如RSI_6和RSI_12）相关性高，同时加入收益递减',
  '"全部满足(AND)"模式最严格但信号少；"加权评分"模式信号多但噪音也多',
  '权重归一化后修改单个权重会导致总和 ≠ 100%，需再次归一化',
  '如果日均信号 < 3 且闪烁稀疏警告，建议放宽条件阈值或移除高过滤因子',
  '因子贡献为负值的因子不一定要删除——它可能在极端市场中起保护作用',
]

// ── 状态 ──────────────────────────────────────────────────────────────

const dateRange = ref<[string, string]>([
  dayjs().subtract(3, 'month').format('YYYY-MM-DD'),
  dayjs().format('YYYY-MM-DD'),
])
const holdingDays = ref(10)
const fusionMode = ref<'and' | 'vote' | 'score'>('score')
const voteThreshold = ref(3)
const running = ref(false)
const searchQuery = ref('')

// 因子目录
const categories = ref<FactorCategory[]>([])
const expandedCats = ref(new Set(['tech_signal']))
const presets = ref<Preset[]>([])
const activePreset = ref('')

// 活跃因子
interface ActiveFactorItem {
  id: string
  name: string
  category: string
  type: string
  icon: string
  weight: number
  enabled: boolean
  operator?: string
  value?: number | number[]
  presets?: { label: string; operator: string; value: number | number[] }[]
}
const activeFactors = ref<ActiveFactorItem[]>([])

// 回测结果
const result = ref<FactorLabRunResult | null>(null)
const chartRef = ref<HTMLDivElement | null>(null)
let chartInstance: echarts.ECharts | null = null

// 折叠状态
const collapsedCards = ref(new Set<string>())
function toggleCard(id: string) {
  if (collapsedCards.value.has(id)) {
    collapsedCards.value.delete(id)
  } else {
    collapsedCards.value.add(id)
  }
}

// 操作日志
interface LogEntry { time: string; text: string; type: 'add' | 'del' | 'mod' | 'ai' }
const changeLog = ref<LogEntry[]>([])
function addLog(text: string, type: LogEntry['type'] = 'mod') {
  changeLog.value.push({ time: dayjs().format('HH:mm:ss'), text, type })
}

// AI 助手
const aiModel = ref('')
const aiInput = ref('')
const aiSuggestion = ref('')
// AI 返回的结构化操作清单（与 aiSuggestion 文本同步生成）
interface AiOp {
  action: 'add' | 'remove' | 'set_weight' | 'set_condition' | 'set_fusion'
  factor_id?: string
  weight?: number
  operator?: string
  value?: number | number[]
  fusion_mode?: 'and' | 'vote' | 'score'
  vote_threshold?: number
}
const aiPlan = ref<AiOp[]>([])
const aiLoading = ref(false)

function _extractAiPlan(content: string): AiOp[] {
  // 兼容 ```json ... ``` 或裸 JSON 数组段
  const m = content.match(/```(?:json)?\s*(\[[\s\S]*?\])\s*```/i)
  let raw = m ? m[1] : ''
  if (!raw) {
    const lo = content.indexOf('[')
    const hi = content.lastIndexOf(']')
    if (lo >= 0 && hi > lo) raw = content.slice(lo, hi + 1)
  }
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter((op: any) => op && typeof op.action === 'string') as AiOp[]
  } catch {
    return []
  }
}

async function askAi() {
  const userInput = aiInput.value.trim()
  if (!userInput && activeFactors.value.length === 0) return
  aiLoading.value = true
  aiSuggestion.value = ''
  aiPlan.value = []

  // 构建上下文 prompt
  const factorsDesc = activeFactors.value.length > 0
    ? activeFactors.value.map(f => {
        const op = f.operator || '='
        const val = Array.isArray(f.value) ? f.value.join('~') : (f.value ?? '')
        return `- ${f.id} (${f.name}, ${f.category}) ${op} ${val}，权重 ${f.weight}%`
      }).join('\n')
    : '（当前未添加任何因子）'

  const availIds = categories.value
    .flatMap(c => c.factors.map(f => `${f.id}(${f.name})`))
    .slice(0, 80)
    .join(', ')

  const r = result.value?.kpi
  const kpiDesc = r ? `\n最近一次回测结果：\n- 平均收益 ${r.avg_return?.toFixed(2) ?? '--'}%\n- 夏普比率 ${r.sharpe?.toFixed(2) ?? '--'}\n- 最大回撤 ${r.max_drawdown?.toFixed(2) ?? '--'}%\n- 胜率 ${r.win_rate?.toFixed(2) ?? '--'}%` : ''

  const prompt = `你是量化因子策略顾问。请基于以下因子组合给出简洁建议（不超过 200 字），并在末尾附上一段 \`\`\`json ... \`\`\` 结构化操作清单，前端将据此自动调整：

可选 action：
- {"action":"add","factor_id":"rsi_6","weight":15,"operator":"<","value":70}
- {"action":"remove","factor_id":"rsi_12"}
- {"action":"set_weight","factor_id":"pe9","weight":20}
- {"action":"set_condition","factor_id":"pe9","operator":"between","value":[0,30]}
- {"action":"set_fusion","fusion_mode":"score","vote_threshold":3}

factor_id 必须来自可选因子集合（节选）：${availIds} ...

当前因子组合：
${factorsDesc}
${kpiDesc}

用户问题：${userInput || '请给出整体优化建议'}`

  const providerOverride = aiModel.value || undefined

  try {
    const res = await aiChat({
      prompt,
      scene: 'factor_lab',
      ...(providerOverride ? { provider: providerOverride } : {}),
    })
    const content = (res as any)?.data?.content || ''
    if (!content) {
      ElMessage.warning('AI 未返回有效建议')
      return
    }
    aiSuggestion.value = content
    aiPlan.value = _extractAiPlan(content)
    addLog(`AI建议: ${content.slice(0, 30)}...`, 'ai')
  } catch (e: any) {
    const msg = e?.response?.data?.msg || e?.message || 'AI 请求失败'
    ElMessage.error(msg)
  } finally {
    aiLoading.value = false
    aiInput.value = ''
  }
}
function applyAiSuggestion() {
  const ops = aiPlan.value
  if (!ops.length) {
    ElMessage.warning('AI 未返回可执行的结构化操作（缺少 JSON 操作清单）')
    return
  }
  let applied = 0
  let skipped = 0
  for (const op of ops) {
    try {
      if (op.action === 'set_fusion') {
        if (op.fusion_mode && ['and', 'vote', 'score'].includes(op.fusion_mode)) {
          fusionMode.value = op.fusion_mode
          applied++
        }
        if (typeof op.vote_threshold === 'number') {
          voteThreshold.value = Math.max(2, Math.min(15, op.vote_threshold))
        }
        continue
      }
      const fid = op.factor_id
      if (!fid) { skipped++; continue }
      if (op.action === 'add') {
        const meta = findFactorMeta(fid)
        if (!meta) { skipped++; continue }
        if (isFactorAdded(fid)) {
          // 已存在 → 视作 set_weight / set_condition
          const af = activeFactors.value.find(f => f.id === fid)!
          if (typeof op.weight === 'number') af.weight = Math.max(0, Math.min(100, op.weight))
          if (op.operator) af.operator = op.operator
          if (op.value != null) af.value = Array.isArray(op.value) ? [...op.value] : op.value
        } else {
          addFactor(meta)
          const af = activeFactors.value[activeFactors.value.length - 1]
          if (typeof op.weight === 'number') af.weight = Math.max(0, Math.min(100, op.weight))
          if (op.operator) af.operator = op.operator
          if (op.value != null) af.value = Array.isArray(op.value) ? [...op.value] : op.value
        }
        applied++
      } else if (op.action === 'remove') {
        const idx = activeFactors.value.findIndex(f => f.id === fid)
        if (idx >= 0) { removeFactor(idx); applied++ } else skipped++
      } else if (op.action === 'set_weight') {
        const af = activeFactors.value.find(f => f.id === fid)
        if (af && typeof op.weight === 'number') {
          af.weight = Math.max(0, Math.min(100, op.weight))
          applied++
        } else skipped++
      } else if (op.action === 'set_condition') {
        const af = activeFactors.value.find(f => f.id === fid)
        if (af) {
          if (op.operator) af.operator = op.operator
          if (op.value != null) af.value = Array.isArray(op.value) ? [...op.value] : op.value
          applied++
        } else skipped++
      } else {
        skipped++
      }
    } catch {
      skipped++
    }
  }
  addLog(`应用AI建议: ${applied} 项${skipped ? `（跳过 ${skipped}）` : ''}`, 'ai')
  if (applied > 0) {
    ElMessage.success(`已应用 ${applied} 项 AI 建议${skipped ? `，跳过 ${skipped} 项` : ''}`)
  } else {
    ElMessage.warning(`未生效（${skipped} 项均无法应用）`)
  }
  aiSuggestion.value = ''
  aiPlan.value = []
}

function logBadgeText(type: string): string {
  const map: Record<string, string> = { add: '添加', del: '删除', mod: '修改', ai: 'AI' }
  return map[type] || type
}

// ── 初始化 ────────────────────────────────────────────────────────────

onMounted(async () => {
  try {
    const [catRes, presetRes] = await Promise.all([
      getFactorCatalog(),
      getFactorPresets(),
    ])
    categories.value = (catRes as any).categories
    presets.value = (presetRes as any).presets
  } catch {
    ElMessage.error('加载因子目录失败')
  }
})

onUnmounted(() => {
  chartInstance?.dispose()
  chartInstance = null
})

// ── 因子操作 ──────────────────────────────────────────────────────────

const filteredCategories = computed(() => {
  const q = searchQuery.value.toLowerCase().trim()
  if (!q) return categories.value
  return categories.value
    .map((cat) => ({
      ...cat,
      factors: cat.factors.filter(
        (f) => f.name.toLowerCase().includes(q) || f.id.toLowerCase().includes(q)
      ),
    }))
    .filter((cat) => cat.factors.length > 0)
})

// Auto-expand categories when searching
watch(searchQuery, (q) => {
  if (q.trim()) {
    filteredCategories.value.forEach((c) => expandedCats.value.add(c.key))
  }
})

function toggleCategory(key: string) {
  if (expandedCats.value.has(key)) {
    expandedCats.value.delete(key)
  } else {
    expandedCats.value.add(key)
  }
}

function isFactorAdded(id: string) {
  return activeFactors.value.some((f) => f.id === id)
}

function addFactor(meta: FactorMeta) {
  if (isFactorAdded(meta.id)) return
  if (activeFactors.value.length >= 15) {
    ElMessage.warning('最多支持 15 个因子')
    return
  }
  const item: ActiveFactorItem = {
    id: meta.id,
    name: meta.name,
    category: meta.category,
    type: meta.type,
    icon: meta.icon,
    weight: 10,
    enabled: true,
    presets: meta.presets,
  }
  if (meta.type !== 'signal') {
    item.operator = meta.default_operator || '>'
    if (meta.default_value != null) {
      item.value = Array.isArray(meta.default_value)
        ? [...meta.default_value]
        : meta.default_value
    } else {
      item.value = 0
    }
  }
  activeFactors.value.push(item)
  addLog(`添加因子: ${meta.name}`, 'add')
}
function removeFactor(idx: number) {
  const name = activeFactors.value[idx]?.name
  activeFactors.value.splice(idx, 1)
  if (name) addLog(`移除因子: ${name}`, 'del')
}

// ── 权重 ──────────────────────────────────────────────────────────────

const weightSum = computed(() =>
  activeFactors.value.reduce((s, f) => s + (f.enabled ? f.weight : 0), 0)
)

function normalizeWeights() {
  const enabled = activeFactors.value.filter((f) => f.enabled)
  if (enabled.length === 0) return
  const total = enabled.reduce((s, f) => s + f.weight, 0)
  if (total === 0) {
    const each = Math.floor(100 / enabled.length)
    enabled.forEach((f) => (f.weight = each))
    enabled[0].weight += 100 - each * enabled.length
    addLog('权重自动归一化(全0→均分)', 'mod')
    return
  }
  let assigned = 0
  enabled.forEach((f, i) => {
    if (i === enabled.length - 1) {
      f.weight = 100 - assigned
    } else {
      f.weight = Math.round((f.weight / total) * 100)
      assigned += f.weight
    }
  })
  addLog(`权重归一化: ${total}% → 100%`, 'mod')
}

// ── 预设 ──────────────────────────────────────────────────────────────

function loadPreset(preset: Preset) {
  activePreset.value = preset.id
  fusionMode.value = (preset.fusion_mode || 'and') as 'and' | 'vote' | 'score'
  if (preset.vote_threshold) voteThreshold.value = preset.vote_threshold

  activeFactors.value = preset.factors.map((pf) => {
    const meta = findFactorMeta(pf.id)
    return {
      id: pf.id,
      name: pf.name || meta?.name || pf.id,
      category: pf.category || meta?.category || 'tech_signal',
      type: pf.type || meta?.type || 'signal',
      icon: pf.icon || meta?.icon || '?',
      weight: pf.weight,
      enabled: pf.enabled,
      operator: pf.operator || meta?.default_operator,
      value: pf.value != null
        ? (Array.isArray(pf.value) ? [...pf.value] : pf.value)
        : meta?.default_value,
      presets: meta?.presets,
    }
  })
  addLog(`加载预设: ${preset.name}`, 'mod')
}

function findFactorMeta(id: string): FactorMeta | undefined {
  for (const cat of categories.value) {
    const f = cat.factors.find((f) => f.id === id)
    if (f) return f
  }
  return undefined
}

function applyFactorPreset(af: ActiveFactorItem, ps: { operator: string; value: number | number[] }) {
  af.operator = ps.operator
  af.value = Array.isArray(ps.value) ? [...ps.value] : ps.value
  addLog(`修改${af.name}: ${ps.operator} ${Array.isArray(ps.value) ? ps.value.join('~') : ps.value}`, 'mod')
}

function isPresetActive(af: ActiveFactorItem, ps: { operator: string; value: number | number[] }) {
  if (af.operator !== ps.operator) return false
  if (Array.isArray(ps.value)) {
    return Array.isArray(af.value) && af.value[0] === ps.value[0] && af.value[1] === ps.value[1]
  }
  return af.value === ps.value
}

// ── 运行回测 ──────────────────────────────────────────────────────────

async function runBacktest() {
  const enabled = activeFactors.value.filter((f) => f.enabled)
  if (enabled.length === 0) {
    ElMessage.warning('请至少启用 1 个因子')
    return
  }
  if (!enabled.some((f) => f.type === 'signal')) {
    ElMessage.warning('至少需要 1 个策略信号因子')
    return
  }
  if (!dateRange.value || !dateRange.value[0]) {
    ElMessage.warning('请选择日期范围')
    return
  }

  running.value = true
  result.value = null

  try {
    const res = await runFactorLab({
      factors: enabled.map((f) => ({
        id: f.id,
        weight: f.weight,
        enabled: true,
        operator: f.operator,
        value: f.value,
      })),
      fusion_mode: fusionMode.value,
      vote_threshold: voteThreshold.value,
      holding_days: holdingDays.value,
      start_date: dateRange.value[0],
      end_date: dateRange.value[1],
    })
    result.value = res as any
    await nextTick()
    renderChart()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '回测失败')
  } finally {
    running.value = false
  }
}

// ── 收益曲线图 ────────────────────────────────────────────────────────

function renderChart() {
  if (!chartRef.value || !result.value?.daily_series?.length) return
  chartInstance?.dispose()
  chartInstance = echarts.init(chartRef.value)

  const dates = result.value.daily_series.map((d) => d.date)
  const cumulative = result.value.daily_series.map((d) => d.cumulative)
  const drawdown = result.value.daily_series.map((d) => d.drawdown)

  chartInstance.setOption({
    grid: [
      { left: 50, right: 16, top: 10, height: '55%' },
      { left: 50, right: 16, top: '72%', height: '22%' },
    ],
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
    },
    xAxis: [
      { type: 'category', data: dates, gridIndex: 0, show: false, boundaryGap: false },
      { type: 'category', data: dates, gridIndex: 1, boundaryGap: false,
        axisLabel: { fontSize: 10 } },
    ],
    yAxis: [
      { type: 'value', gridIndex: 0, name: '累计', axisLabel: { fontSize: 10 },
        splitLine: { lineStyle: { type: 'dashed' } } },
      { type: 'value', gridIndex: 1, name: '回撤%', axisLabel: { fontSize: 10 },
        splitLine: { lineStyle: { type: 'dashed' } } },
    ],
    series: [
      { name: '累计收益', type: 'line', data: cumulative, xAxisIndex: 0, yAxisIndex: 0,
        lineStyle: { width: 1.5, color: '#1890ff' }, symbol: 'none',
        areaStyle: { color: 'rgba(24,144,255,0.08)' } },
      { name: '回撤', type: 'line', data: drawdown, xAxisIndex: 1, yAxisIndex: 1,
        lineStyle: { width: 1, color: '#ff4d4f' }, symbol: 'none',
        areaStyle: { color: 'rgba(255,77,79,0.08)' } },
    ],
  })
}

// 窗口 resize
const onResize = () => chartInstance?.resize()
onMounted(() => window.addEventListener('resize', onResize))
onUnmounted(() => window.removeEventListener('resize', onResize))

// ── 辅助函数 ──────────────────────────────────────────────────────────

function categoryColor(cat: string) {
  const m: Record<string, string> = {
    tech_signal: '#1890ff',
    tech_indicator: '#40a9ff',
    fundamental: '#52c41a',
    fund_flow: '#faad14',
  }
  return m[cat] || '#999'
}

function categoryLabel(cat: string) {
  const m: Record<string, string> = {
    tech_signal: '策略信号',
    tech_indicator: '技术指标',
    fundamental: '基本面',
    fund_flow: '资金流',
  }
  return m[cat] || cat
}

function getContribution(id: string): number | null {
  if (!result.value) return null
  const c = result.value.factor_contributions.find((fc) => fc.id === id)
  return c?.impact ?? null
}

const sharpeImprovement = computed(() => {
  if (!result.value) return ''
  const curr = result.value.kpi.sharpe
  const base = result.value.baseline.sharpe
  if (curr == null || base == null || base === 0) return ''
  const pct = ((curr - base) / Math.abs(base) * 100).toFixed(1)
  return (Number(pct) > 0 ? '+' : '') + pct + '%'
})

function kpiColor(v: number | null) {
  if (v == null) return ''
  return v > 0 ? 'text-pos' : v < 0 ? 'text-neg' : ''
}

function contribBarWidth(impact: number | null) {
  if (!result.value || impact == null) return 0
  const maxAbs = Math.max(
    ...result.value.factor_contributions.map((c) => Math.abs(c.impact ?? 0)),
    0.01
  )
  return Math.min(100, (Math.abs(impact) / maxAbs) * 100)
}

function fmtPct(v: number | null) {
  if (v == null) return '-'
  return (v > 0 ? '+' : '') + v + '%'
}

function fmtDelta(curr: number | null, base: number | null) {
  if (curr == null || base == null || base === 0) return '-'
  const pct = ((curr - base) / Math.abs(base) * 100).toFixed(1)
  return (Number(pct) > 0 ? '+' : '') + pct + '%'
}

function fmtDeltaPP(curr: number | null, base: number | null) {
  if (curr == null || base == null) return '-'
  const pp = (curr - base).toFixed(1)
  return (Number(pp) > 0 ? '+' : '') + pp + 'pp'
}

// ── 保存/加载/导出 ────────────────────────────────────────────────────

const saveDialogVisible = ref(false)
const loadDrawerVisible = ref(false)
const exportDialogVisible = ref(false)
const saving = ref(false)
const saveForm = ref({ name: '', description: '' })
const myConfigs = ref<FactorLabConfig[]>([])
const exportCode = ref('')
const exportFilename = ref('')
const currentConfigId = ref<number | undefined>(undefined)

function handleConfigCommand(cmd: string) {
  if (cmd === 'save') {
    if (activeFactors.value.length === 0) {
      ElMessage.warning('请先添加因子再保存')
      return
    }
    saveDialogVisible.value = true
  } else if (cmd === 'load') {
    loadConfigs()
    loadDrawerVisible.value = true
  } else if (cmd === 'export') {
    doExportCode()
  }
}

async function doSaveConfig() {
  if (!saveForm.value.name.trim()) {
    ElMessage.warning('请输入方案名称')
    return
  }
  saving.value = true
  try {
    const res = await saveFactorConfig({
      id: currentConfigId.value,
      name: saveForm.value.name.trim(),
      description: saveForm.value.description.trim(),
      factors: activeFactors.value.map((f) => ({
        id: f.id,
        weight: f.weight,
        enabled: f.enabled,
        operator: f.operator,
        value: f.value,
      })),
      fusion_mode: fusionMode.value,
      vote_threshold: voteThreshold.value,
      holding_days: holdingDays.value,
    })
    currentConfigId.value = (res as any).id
    ElMessage.success((res as any).message || '保存成功')
    saveDialogVisible.value = false
    saveForm.value = { name: '', description: '' }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '保存失败')
  } finally {
    saving.value = false
  }
}

async function loadConfigs() {
  try {
    const res = await getMyConfigs()
    myConfigs.value = (res as any).configs || []
  } catch {
    ElMessage.error('加载方案列表失败')
  }
}

function loadConfig(cfg: FactorLabConfig) {
  currentConfigId.value = cfg.id
  fusionMode.value = (cfg.fusion_mode || 'and') as 'and' | 'vote' | 'score'
  if (cfg.vote_threshold) voteThreshold.value = cfg.vote_threshold
  if (cfg.holding_days) holdingDays.value = cfg.holding_days

  activeFactors.value = cfg.factors.map((pf) => {
    const meta = findFactorMeta(pf.id)
    return {
      id: pf.id,
      name: meta?.name || pf.id,
      category: meta?.category || 'tech_signal',
      type: meta?.type || 'signal',
      icon: meta?.icon || '?',
      weight: pf.weight,
      enabled: pf.enabled,
      operator: pf.operator || meta?.default_operator,
      value: pf.value != null
        ? (Array.isArray(pf.value) ? [...pf.value] : pf.value)
        : meta?.default_value,
      presets: meta?.presets,
    }
  })
  loadDrawerVisible.value = false
  ElMessage.success(`已加载方案: ${cfg.name}`)
}

async function doDeleteConfig(id: number) {
  try {
    await deleteFactorConfig(id)
    myConfigs.value = myConfigs.value.filter((c) => c.id !== id)
    if (currentConfigId.value === id) currentConfigId.value = undefined
    ElMessage.success('已删除')
  } catch {
    ElMessage.error('删除失败')
  }
}

async function doExportCode() {
  const enabled = activeFactors.value.filter((f) => f.enabled)
  if (enabled.length === 0) {
    ElMessage.warning('请先添加因子')
    return
  }
  exportCode.value = ''
  exportFilename.value = ''
  exportDialogVisible.value = true
  try {
    const res = await exportFactorCode({
      factors: enabled.map((f) => ({
        id: f.id,
        weight: f.weight,
        enabled: true,
        operator: f.operator,
        value: f.value,
      })),
      fusion_mode: fusionMode.value,
      vote_threshold: voteThreshold.value,
      holding_days: holdingDays.value,
    })
    exportCode.value = (res as any).code || ''
    exportFilename.value = (res as any).filename || 'strategy.py'
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '代码生成失败')
    exportDialogVisible.value = false
  }
}

function copyExportCode() {
  navigator.clipboard.writeText(exportCode.value).then(() => {
    ElMessage.success('已复制到剪贴板')
  }).catch(() => {
    ElMessage.warning('复制失败，请手动选择')
  })
}

function downloadExportCode() {
  const blob = new Blob([exportCode.value], { type: 'text/x-python;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = exportFilename.value || 'strategy.py'
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<style scoped>
.feature-tabs { display: flex; align-items: center; gap: 0; height: 42px; padding: 0 12px; margin-bottom: 12px; background: #fff; border: 1px solid #ebeef5; border-radius: 4px; flex-shrink: 0; }
.feature-tab { height: 42px; display: inline-flex; align-items: center; padding: 0 18px; font-size: 13px; color: #606266; border-bottom: 2px solid transparent; cursor: pointer; text-decoration: none; }
.feature-tab.router-link-exact-active { color: #1890ff; border-bottom-color: #1890ff; font-weight: 600; }

.factor-lab {
  padding: 12px 16px;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  font-size: 13px;
}

/* 工具栏 */
.lab-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  flex-shrink: 0;
}
.toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 预设栏 */
.preset-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  flex-shrink: 0;
}
.preset-label {
  font-size: 12px;
  color: #999;
}
.preset-chip {
  cursor: pointer;
}

/* 三栏网格 */
.lab-grid {
  display: grid;
  grid-template-columns: 240px 1fr 320px;
  gap: 12px;
  flex: 1;
  overflow: hidden;
}
.lab-col {
  overflow-y: auto;
  border: 1px solid #eee;
  border-radius: 6px;
  background: #fff;
}
.lab-col-left {
  min-width: 220px;
}
.lab-col-center {
  min-width: 0;
}
.lab-col-right {
  min-width: 300px;
}

.panel-header {
  font-size: 13px;
  font-weight: 600;
  padding: 10px 12px 8px;
  border-bottom: 1px solid #f0f0f0;
  position: sticky;
  top: 0;
  background: #fff;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.factor-count {
  font-weight: normal;
  font-size: 11px;
  color: #999;
}

/* 因子搜索 */
.factor-search {
  margin: 8px 8px 4px;
}

/* 分类 */
.cat-section {
  border-bottom: 1px solid #f5f5f5;
}
.cat-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  user-select: none;
}
.cat-header:hover {
  background: #fafafa;
}
.cat-icon {
  font-size: 14px;
}
.cat-count {
  color: #bbb;
  font-weight: normal;
  font-size: 11px;
}
.cat-arrow {
  margin-left: auto;
  font-size: 12px;
  color: #ccc;
}

/* 因子项 */
.factor-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px 5px 24px;
  cursor: pointer;
  font-size: 12px;
}
.factor-item:hover {
  background: #f6f9ff;
}
.factor-item.added {
  opacity: 0.5;
  cursor: default;
}
.fi-icon {
  width: 20px;
  height: 20px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 10px;
  flex-shrink: 0;
}
.fi-name {
  flex: 1;
}
.fi-add, .fi-check {
  font-size: 14px;
  color: #ccc;
}

/* 活跃因子区 */
.active-factors {
  padding: 8px;
}
.empty-state {
  text-align: center;
  padding: 32px 16px;
  color: #bbb;
  font-size: 12px;
  border: 1px dashed #e0e0e0;
  border-radius: 6px;
  margin: 8px;
}
.empty-hint {
  font-size: 10px;
  margin-top: 6px;
  display: inline-block;
}

/* 权重警告 */
.weight-warn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  margin: 0 8px 6px;
  background: #fff7e6;
  border: 1px solid #ffe58f;
  border-radius: 4px;
  font-size: 11px;
  color: #fa8c16;
}
.ww-icon { font-size: 14px; }

/* 信号稀疏警告 */
.signal-warn {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 12px;
  margin: 6px 8px;
  background: #fff7e6;
  border: 1px solid #ffd591;
  border-radius: 4px;
  font-size: 12px;
  color: #d46b08;
  line-height: 1.5;
}
.sw-icon { font-size: 16px; flex-shrink: 0; margin-top: 1px; }
.sw-body { flex: 1; min-width: 0; }
.sw-title { font-weight: 600; }
.sw-title b { color: #ad4e00; }
.sw-hint { margin-top: 3px; color: #874d00; font-size: 11px; }

/* 因子卡片 */
.factor-card {
  border: 1px solid #f0f0f0;
  border-radius: 6px;
  margin-bottom: 8px;
  overflow: hidden;
  transition: border-color .2s;
}
.factor-card:hover { border-color: #d9d9d9; }
.factor-card.collapsed .fc-head { background: #fff; }
.fc-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  background: #fafafa;
  cursor: pointer;
  user-select: none;
}
.drag-grip {
  font-size: 14px;
  color: #ccc;
  cursor: grab;
  line-height: 1;
}
.drag-grip:hover { color: #999; }
.fc-collapse-icon {
  font-size: 12px;
  color: #ccc;
  transition: transform .2s;
}
.fc-collapse-icon.open { transform: rotate(180deg); }
.fc-icon {
  width: 22px;
  height: 22px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 11px;
  flex-shrink: 0;
}
.fc-name {
  flex: 1;
  font-size: 12px;
  font-weight: 500;
}
.fc-tag {
  font-size: 10px;
  padding: 1px 4px;
  border-radius: 2px;
  margin-left: 4px;
  font-weight: normal;
}
.t-tech_signal { background: #e6f7ff; color: #1890ff; }
.t-tech_indicator { background: #e6f7ff; color: #40a9ff; }
.t-fundamental { background: #f6ffed; color: #52c41a; }
.t-fund_flow { background: #fff7e6; color: #faad14; }
.fc-impact {
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}
.fc-body {
  padding: 8px 10px;
}
.fc-tip {
  font-size: 10px;
  color: #bbb;
  margin-top: 6px;
}
.param-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}
.p-label {
  font-size: 11px;
  color: #666;
  width: 36px;
  flex-shrink: 0;
}
.p-unit {
  font-size: 11px;
  color: #999;
}
.p-sep {
  font-size: 11px;
  color: #999;
}

/* 快捷预设 */
.preset-chips {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
  margin-top: 4px;
}
.chips-label {
  font-size: 10px;
  color: #bbb;
}
.chip {
  cursor: pointer;
  font-size: 10px !important;
}

/* 颜色类 */
.text-pos { color: #52c41a; }
.text-neg { color: #ff4d4f; }

/* 右栏结果 */
.empty-result {
  padding: 32px 0;
}
.loading-state {
  padding: 16px;
}

/* KPI 卡片 */
.result-kpi {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  padding: 10px;
}
.kpi {
  padding: 8px 10px;
  border: 1px solid #f0f0f0;
  border-radius: 6px;
}
.kpi.highlight {
  border-color: #1890ff;
  background: #f0f8ff;
}
.k-label {
  font-size: 11px;
  color: #999;
}
.k-value {
  font-size: 18px;
  font-weight: 700;
  margin: 2px 0;
}
.k-delta {
  font-size: 10px;
}

/* 收益曲线 */
.result-chart {
  height: 200px;
  margin: 0 10px 8px;
}

/* 卡片通用 */
.card {
  margin: 0 10px 10px;
  border: 1px solid #f0f0f0;
  border-radius: 6px;
  overflow: hidden;
}
.card-h {
  font-size: 12px;
  font-weight: 600;
  padding: 8px 12px;
  border-bottom: 1px solid #f5f5f5;
}
.card-sub {
  font-weight: normal;
  color: #bbb;
  margin-left: 6px;
  font-size: 11px;
}
.card-b {
  padding: 8px 12px;
}

/* 因子贡献 */
.contrib-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 5px;
}
.cr-icon {
  width: 18px;
  height: 18px;
  border-radius: 3px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 9px;
  flex-shrink: 0;
}
.cr-name {
  font-size: 11px;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cr-bar {
  width: 70px;
  height: 5px;
  background: #f0f0f0;
  border-radius: 3px;
  overflow: hidden;
  flex-shrink: 0;
}
.cr-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s;
}
.cr-val {
  font-size: 11px;
  font-weight: 600;
  width: 44px;
  text-align: right;
  flex-shrink: 0;
}

/* 对比表 */
.compare-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
}
.compare-table th,
.compare-table td {
  padding: 6px 8px;
  border-bottom: 1px solid #f5f5f5;
  text-align: center;
}
.compare-table th {
  background: #fafafa;
  font-weight: 600;
}
.best-col {
  background: #f0fff0 !important;
}
.best-cell {
  background: #f0fff0;
  font-weight: 600;
}

/* 响应式 */
@media (max-width: 960px) {
  .lab-grid {
    grid-template-columns: 1fr;
    grid-template-rows: auto;
  }
  .lab-col {
    max-height: 400px;
  }
}

/* 方案卡片（加载抽屉） */
.config-card {
  border: 1px solid #f0f0f0;
  border-radius: 6px;
  padding: 12px;
  margin-bottom: 10px;
}
.config-card:hover {
  border-color: #1890ff;
}
.cfg-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}
.cfg-name {
  font-weight: 600;
  font-size: 13px;
}
.cfg-time {
  font-size: 11px;
  color: #bbb;
}
.cfg-meta {
  font-size: 11px;
  color: #666;
  margin-bottom: 4px;
}
.cfg-desc {
  font-size: 11px;
  color: #999;
  margin-bottom: 6px;
}
.cfg-actions {
  display: flex;
  gap: 8px;
}

/* 导出代码 */
.export-code-wrapper {
  border: 1px solid #f0f0f0;
  border-radius: 6px;
  overflow: hidden;
}
.export-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: #fafafa;
  border-bottom: 1px solid #f0f0f0;
}
.export-filename {
  flex: 1;
  font-size: 12px;
  font-weight: 600;
  color: #333;
}
.export-code {
  margin: 0;
  padding: 12px 16px;
  max-height: 400px;
  overflow: auto;
  font-size: 11px;
  line-height: 1.6;
  background: #f9f9f9;
  white-space: pre-wrap;
  word-break: break-all;
}

/* 操作日志 */
.log-list {
  max-height: 140px;
  overflow-y: auto;
}
.log-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 10px;
  padding: 3px 0;
  border-bottom: 1px solid #fafafa;
}
.log-time { color: #bbb; flex-shrink: 0; }
.log-badge {
  padding: 1px 5px;
  border-radius: 8px;
  font-size: 9px;
  font-weight: 600;
  flex-shrink: 0;
}
.lb-add { background: #e6f7ff; color: #1890ff; }
.lb-del { background: #fff1f0; color: #cf1322; }
.lb-mod { background: #fff7e6; color: #fa8c16; }
.lb-ai { background: #f3f0ff; color: #6554c0; }
.log-text { color: #666; }

/* AI 助手 */
.ai-panel { margin-top: 8px; }
.ai-body { padding: 10px 12px !important; }
.ai-msg {
  background: #f0f8ff;
  border: 1px solid #d6e8ff;
  border-radius: 6px;
  padding: 10px;
  margin-bottom: 8px;
}
.ai-msg-text { font-size: 11px; color: #333; line-height: 1.5; }
.ai-actions { margin-top: 6px; display: flex; gap: 6px; }
.ai-empty { font-size: 11px; color: #bbb; text-align: center; padding: 12px 0; }
.ai-input-row { display: flex; gap: 6px; }
</style>
