<template>
  <div class="paper-trading">
    <!-- ═══════════ 列表视图 ═══════════ -->
    <template v-if="!detailId">
      <div class="page-header">
        <div class="header-left">
          <h2>模拟交易</h2>
          <el-tag type="info" size="small" class="count-tag">{{ paperList.length }} 个策略</el-tag>
        </div>
        <div class="header-right">
          <el-button :disabled="selectedRows.length < 2" @click="goCompare">
            <el-icon><DataAnalysis /></el-icon>对比 ({{ selectedRows.length }})
          </el-button>
          <el-button type="primary" @click="openCreateDialog" :icon="Plus">创建模拟盘</el-button>
        </div>
      </div>

      <!-- 聚宽风格表格 -->
      <el-table :data="paperList" v-loading="loading" stripe
                @selection-change="onSelectionChange"
                class="jq-table" header-cell-class-name="jq-header-cell"
                table-layout="auto">
        <el-table-column type="selection" width="40" />
        <el-table-column prop="name" label="名称" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="jq-name-link" @click="viewDetail(row.id)">
              {{ row.name || `模拟盘-${row.id}` }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="回测收益" width="95" align="center">
          <template #default="{ row }">
            <span v-if="hasBacktest(row)" :class="retCls(row.backtest_return)">
              {{ fmtPct(row.backtest_return) }}
            </span>
            <span v-else>--</span>
          </template>
        </el-table-column>
        <el-table-column prop="run_frequency" label="频率" width="80" align="center">
          <template #default="{ row }">{{ frequencyLabel(row.run_frequency) }}</template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="70" align="center">
          <template #default="{ row }">
            <span :class="'jq-status-' + row.status">{{ statusLabel(row.status) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="started_at" label="开始时间" width="100" align="center">
          <template #default="{ row }">{{ row.start_at || row.started_at || row.last_run_date || '--' }}</template>
        </el-table-column>
        <el-table-column label="累计收益" width="90" align="center">
          <template #default="{ row }">
            <span :class="retCls(row.profit_rate)">{{ fmtPct(row.profit_rate) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="年化收益" width="90" align="center">
          <template #default="{ row }">
            <span :class="retCls(row.annual_return)">{{ fmtPctDash(row.annual_return) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="今日收益" width="90" align="center">
          <template #default="{ row }">
            <span :class="retCls(row.today_return)">{{ fmtPctDash(row.today_return) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="最大回撤" width="90" align="center">
          <template #default="{ row }">
            <span class="val-green">{{ row.max_drawdown ? '-' + row.max_drawdown.toFixed(2) + '%' : '——' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="详情" width="72" align="center">
          <template #default="{ row }">
            <a class="jq-op jq-op-primary" @click="viewDetail(row.id)">查看</a>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="190" align="center" fixed="right">
          <template #default="{ row }">
            <div class="jq-ops">
              <a class="jq-op" :class="{ 'jq-op-disabled': row.status === 'stopped' }"
                 @click="row.status !== 'stopped' && doAction(row.id, row.status === 'paused' ? 'resume' : 'pause')">
                {{ row.status === 'paused' ? '恢复' : '暂停' }}
              </a>
              <span class="jq-op-sep">|</span>
              <a class="jq-op jq-op-danger" :class="{ 'jq-op-disabled': row.status === 'stopped' }"
                 @click="row.status !== 'stopped' && doAction(row.id, 'stop')">停止</a>
              <span class="jq-op-sep">|</span>
              <a class="jq-op jq-op-primary" :class="{ 'jq-op-disabled': row.status !== 'running' }"
                 @click="row.status === 'running' && doRun(row.id)">
                {{ runningId === row.id ? '执行中...' : '执行' }}
              </a>
              <span class="jq-op-sep">|</span>
              <a class="jq-op jq-op-danger" @click="doDelete(row.id, row.name)">删除</a>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && paperList.length === 0"
                 description="还没有模拟盘，点击「创建模拟盘」开始">
        <el-button type="primary" @click="openCreateDialog">创建模拟盘</el-button>
      </el-empty>
    </template>

    <!-- ═══════════ 详情视图（聚宽实盘风格） ═══════════ -->
    <template v-else>
      <div class="detail-page" v-loading="detailLoading">
        <!-- ▸ 顶部标题条 -->
        <div class="jq-detail-header">
          <div class="jq-detail-title">
            <el-button text size="small" @click="goBackToList" class="back-btn">
              <el-icon><ArrowLeft /></el-icon>
            </el-button>
            <span class="jq-title-text">模拟交易</span>
            <span class="jq-title-name">{{ detailData?.info?.name || '' }}</span>
            <el-tag :type="statusType(detailData?.info?.status)" size="small"
                    v-if="detailData?.info?.status" style="margin-left: 8px;">
              {{ statusLabel(detailData?.info?.status) }}
            </el-tag>
          </div>
          <div class="jq-detail-actions" v-if="detailData?.info">
            <el-button size="small" type="primary" v-if="detailData.info.status === 'running'"
                       @click="doRun(detailId!)" :loading="runningId === detailId">
              <el-icon><CaretRight /></el-icon>手动执行
            </el-button>
            <el-dropdown trigger="click" @command="(cmd: string) => doAction(detailId!, cmd as any)">
              <el-button size="small">其他操作 <el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="pause" v-if="detailData.info.status === 'running'">暂停</el-dropdown-item>
                  <el-dropdown-item command="resume" v-if="detailData.info.status === 'paused'">恢复运行</el-dropdown-item>
                  <el-dropdown-item command="stop" v-if="detailData.info.status !== 'stopped'" divided>
                    <span style="color:#f56c6c;">停止</span>
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>

        <template v-if="detailData">
          <!-- ▸ 顶部指标条（聚宽风格横排） -->
          <div class="jq-metrics-bar">
            <div class="jq-metric-cell">
              <span class="jq-mc-value" :class="retCls(detailData.info.profit_rate)">
                {{ fmtPctDash(detailData.info.profit_rate) }}
              </span>
              <span class="jq-mc-label" :class="retCls(detailData.info.profit_rate)">累计收益</span>
            </div>
            <div class="jq-metric-sep"></div>
            <div class="jq-metric-cell">
              <span class="jq-mc-value" :class="retCls(detailData.info.annual_return)">
                {{ fmtPctDash(detailData.info.annual_return) }}
              </span>
              <span class="jq-mc-label" :class="retCls(detailData.info.annual_return)">年化收益</span>
            </div>
            <div class="jq-metric-sep"></div>
            <div class="jq-metric-cell">
              <span class="jq-mc-value">¥{{ formatMoneyFull(detailData.info.current_value) }}</span>
              <span class="jq-mc-label">总资产</span>
            </div>
            <div class="jq-metric-sep"></div>
            <div class="jq-metric-cell">
              <span class="jq-mc-value">¥{{ formatMoneyFull(detailData.info.current_cash) }}</span>
              <span class="jq-mc-label">可用资金</span>
            </div>
            <div class="jq-metric-sep"></div>
            <div class="jq-metric-cell">
              <span class="jq-mc-value">{{ positionRatio }}%</span>
              <span class="jq-mc-label">仓位占比</span>
            </div>
            <div class="jq-metric-sep"></div>
            <div class="jq-metric-cell">
              <span class="jq-mc-value">{{ detailData.info.trade_count ?? 0 }}</span>
              <span class="jq-mc-label">累计换手</span>
            </div>
            <div class="jq-metric-sep"></div>
            <div class="jq-metric-cell">
              <span class="jq-mc-value val-green">{{ detailData.info.max_drawdown ? '-' + detailData.info.max_drawdown.toFixed(2) + '%' : '——' }}</span>
              <span class="jq-mc-label">最大回撤</span>
            </div>
            <div class="jq-metric-sep"></div>
            <el-popover placement="bottom-end" :width="320" trigger="click">
              <template #reference>
                <div class="jq-metric-cell jq-metric-more">
                  <span class="jq-mc-value">其他指标 <el-icon><InfoFilled /></el-icon></span>
                </div>
              </template>
              <div class="jq-extra-metrics">
                <div class="jq-em-row">
                  <span>初始资金</span><span>¥{{ formatMoneyFull(detailData.info.initial_cash) }}</span>
                </div>
                <div class="jq-em-row">
                  <span>夏普比率</span><span>{{ fmtNum(detailData.info.sharpe_ratio) }}</span>
                </div>
                <div class="jq-em-row">
                  <span>索提诺比率</span><span>{{ fmtNum(detailData.info.sortino_ratio) }}</span>
                </div>
                <div class="jq-em-row">
                  <span>胜率</span><span>{{ detailData.info.win_rate != null ? detailData.info.win_rate.toFixed(1) + '%' : '--' }}</span>
                </div>
                <div class="jq-em-row">
                  <span>盈亏比</span><span>{{ fmtNum(detailData.info.profit_loss_ratio) }}</span>
                </div>
                <div class="jq-em-row">
                  <span>运行天数</span><span>{{ detailData.info.running_days ?? 0 }} 天</span>
                </div>
                <div class="jq-em-row">
                  <span>开始日期</span><span>{{ detailData.info.started_at || '--' }}</span>
                </div>
              </div>
            </el-popover>
          </div>

          <!-- ▸ 左侧Tab + 右侧内容（聚宽侧边栏风格） -->
          <div class="jq-detail-body">
            <el-tabs v-model="sideTab" tab-position="left" class="jq-side-tabs">
              <!-- ──── 概述 ──── -->
              <el-tab-pane name="overview">
                <template #label><el-icon><Document /></el-icon><span>概述</span></template>
                <!-- 历史收益 -->
                <div class="jq-section">
                  <el-tabs v-model="chartTab" class="jq-inner-tabs">
                    <el-tab-pane label="历史收益" name="returns">
                      <div class="jq-chart-toolbar" v-if="detailData.nav && detailData.nav.length">
                        <el-radio-group v-model="benchmarkStartMode" size="small" @change="onBenchmarkStartModeChange">
                          <el-radio-button label="paper_start">模拟开始</el-radio-button>
                          <el-radio-button label="first_trade">首次成交</el-radio-button>
                        </el-radio-group>
                        <el-checkbox-group v-model="visibleReturnSeries" size="small" @change="initNavChart">
                          <el-checkbox-button v-for="item in returnSeriesOptions" :key="item.key" :label="item.key">
                            {{ item.label }}
                          </el-checkbox-button>
                        </el-checkbox-group>
                      </div>
                      <div v-if="detailData.nav && detailData.nav.length">
                        <div ref="navChartRef" style="height: 320px; width: 100%;"></div>
                      </div>
                      <div v-else class="jq-empty-chart">未开始，暂无数据</div>
                    </el-tab-pane>
                  </el-tabs>
                </div>

                <!-- 持仓详情 -->
                <div class="jq-section">
                  <div class="jq-section-header">
                    <span class="jq-section-title">持仓详情({{ posHistDate || '--' }})</span>
                    <div class="jq-section-actions">
                      <span class="jq-export-link">导出全部</span>
                      <span class="jq-date-label">历史持仓:</span>
                      <el-date-picker v-model="posHistDate" type="date" size="small"
                                      value-format="YYYY-MM-DD" style="width: 130px;" />
                    </div>
                  </div>
                  <!-- 列可见性切换（聚宽风格） -->
                  <div class="jq-col-filter">
                    <el-checkbox v-for="col in posColumnDefs" :key="col.key" size="small"
                      :model-value="posVisibleCols.includes(col.key)"
                      @change="(v: any) => togglePosCol(col.key, !!v)">
                      {{ col.label }}
                    </el-checkbox>
                  </div>
                  <el-table :data="detailData.positions" size="small" stripe border
                            style="width: 100%;" empty-text="暂无持仓" table-layout="auto">
                    <el-table-column prop="code" label="标的" width="85">
                      <template #default="{ row }">
                        <el-button link type="primary" @click.stop="openPaperStock(row)">{{ row.code }}</el-button>
                      </template>
                    </el-table-column>
                    <el-table-column v-if="showPosCol('name')" label="名称" width="100" show-overflow-tooltip>
                      <template #default="{ row }">
                        <el-button link type="primary" class="stock-name-link" @click.stop="openPaperStock(row)">
                          {{ stockDisplayName(row) }}
                        </el-button>
                      </template>
                    </el-table-column>
                    <el-table-column v-if="showPosCol('direction')" label="多空" width="60" align="center">
                      <template #default><span style="color: #f56c6c;">做多</span></template>
                    </el-table-column>
                    <el-table-column v-if="showPosCol('amount')" label="数量" width="80" align="right">
                      <template #default="{ row }">{{ Number(row.amount ?? 0).toLocaleString() }}</template>
                    </el-table-column>
                    <el-table-column v-if="showPosCol('available')" label="可用数量" width="80" align="right">
                      <template #default="{ row }">{{ Number(row.amount ?? 0).toLocaleString() }}</template>
                    </el-table-column>
                    <el-table-column v-if="showPosCol('price')" label="现价" width="80" align="right">
                      <template #default="{ row }">{{ (row.price ?? 0).toFixed(2) }}</template>
                    </el-table-column>
                    <el-table-column v-if="showPosCol('value')" label="市值/价值" width="110" align="right">
                      <template #default="{ row }">{{ formatMoneyFull(row.value) }}</template>
                    </el-table-column>
                    <el-table-column v-if="showPosCol('profit')" label="盈亏" width="90" align="right">
                      <template #default="{ row }">
                        <span :class="retCls(row.profit)">{{ fmtMoney(row.profit) }}</span>
                      </template>
                    </el-table-column>
                    <el-table-column v-if="showPosCol('profit_rate')" label="逐笔浮盈" width="100" align="right">
                      <template #default="{ row }">
                        <span :class="retCls(row.profit_rate)">{{ fmtPct(row.profit_rate) }}</span>
                      </template>
                    </el-table-column>
                    <el-table-column v-if="showPosCol('avg_cost')" label="开仓均价" width="90" align="right">
                      <template #default="{ row }">{{ (row.avg_cost ?? 0).toFixed(2) }}</template>
                    </el-table-column>
                    <el-table-column v-if="showPosCol('weight')" label="仓位占比" width="80" align="right">
                      <template #default="{ row }">{{ (row.weight ?? 0).toFixed(1) }}%</template>
                    </el-table-column>
                    <el-table-column v-if="showPosCol('pnl_ratio')" label="盈亏占比" width="80" align="right">
                      <template #default="{ row }">
                        <span :class="retCls(row.profit_rate)">
                          {{ row.profit != null && detailData.info.current_value > 0
                            ? ((row.profit / detailData.info.current_value) * 100).toFixed(2) + '%'
                            : '--' }}
                        </span>
                      </template>
                    </el-table-column>
                  </el-table>
                </div>

                <!-- 下单详情 -->
                <div class="jq-section">
                  <div class="jq-section-header">
                    <span class="jq-section-title">下单详情({{ tradeHistDate || '--' }})</span>
                    <div class="jq-section-actions">
                      <span class="jq-export-link">导出全部</span>
                      <span class="jq-date-label">历史下单:</span>
                      <el-date-picker v-model="tradeHistDate" type="date" size="small"
                                      value-format="YYYY-MM-DD" style="width: 130px;" />
                    </div>
                  </div>
                  <!-- 列可见性切换 -->
                  <div class="jq-col-filter">
                    <el-checkbox v-for="col in tradeColumnDefs" :key="col.key" size="small"
                      :model-value="tradeVisibleCols.includes(col.key)"
                      @change="(v: any) => toggleTradeCol(col.key, !!v)">
                      {{ col.label }}
                    </el-checkbox>
                  </div>
                  <el-table :data="filteredTrades" size="small" stripe border max-height="400"
                            style="width: 100%;" empty-text="暂无交易记录" table-layout="auto">
                    <el-table-column prop="date" label="日期" width="95" />
                    <el-table-column label="标的" width="85">
                      <template #default="{ row }">
                        <el-button link type="primary" @click.stop="openPaperStock(row)">{{ row.code }}</el-button>
                      </template>
                    </el-table-column>
                    <el-table-column v-if="showTradeCol('name')" label="名称" width="100" show-overflow-tooltip>
                      <template #default="{ row }">
                        <el-button link type="primary" class="stock-name-link" @click.stop="openPaperStock(row)">
                          {{ stockDisplayName(row) }}
                        </el-button>
                      </template>
                    </el-table-column>
                    <el-table-column v-if="showTradeCol('direction')" label="交易类型" width="80">
                      <template #default="{ row }">
                        <span :style="{ color: row.direction === 'buy' ? '#f56c6c' : '#67c23a', fontWeight: 600 }">
                          {{ row.direction === 'buy' ? '买入' : '卖出' }}
                        </span>
                      </template>
                    </el-table-column>
                    <el-table-column v-if="showTradeCol('order_type')" label="下单类型" width="80" align="center">
                      <template #default>市价单</template>
                    </el-table-column>
                    <el-table-column v-if="showTradeCol('amount')" label="成交数量" width="85" align="right">
                      <template #default="{ row }">{{ Number(row.amount ?? 0).toLocaleString() }}</template>
                    </el-table-column>
                    <el-table-column v-if="showTradeCol('price')" label="成交价" width="85" align="right">
                      <template #default="{ row }">{{ (row.price ?? 0).toFixed(2) }}</template>
                    </el-table-column>
                    <el-table-column v-if="showTradeCol('value')" label="成交额" width="105" align="right">
                      <template #default="{ row }">{{ formatMoneyFull(row.value) }}</template>
                    </el-table-column>
                    <el-table-column v-if="showTradeCol('commission')" label="手续费" width="80" align="right">
                      <template #default="{ row }">{{ ((row.commission ?? 0) + (row.tax ?? 0)).toFixed(2) }}</template>
                    </el-table-column>
                    <el-table-column v-if="showTradeCol('close_profit')" label="最终盈亏额" width="100" align="right">
                      <template #default="{ row }">
                        <span :class="retCls(row.close_profit)">{{ fmtSellMoney(row) }}</span>
                      </template>
                    </el-table-column>
                    <el-table-column v-if="showTradeCol('return_rate')" label="盈亏比" width="90" align="right">
                      <template #default="{ row }">
                        <span :class="retCls(row.return_rate)">{{ fmtSellPct(row) }}</span>
                      </template>
                    </el-table-column>
                    <el-table-column v-if="showTradeCol('status')" label="状态" width="80" align="center">
                      <template #default><el-tag size="small" type="success">全部成交</el-tag></template>
                    </el-table-column>
                    <el-table-column v-if="showTradeCol('reason')" label="交易原因" min-width="200" show-overflow-tooltip>
                      <template #default="{ row }">
                        <span v-if="row.reason">{{ row.reason }}</span>
                        <span v-else style="color:#c0c4cc;">--</span>
                        <el-tag v-if="row.reason_source === 'generated'" size="small" type="warning"
                                effect="plain" style="margin-left:6px;">系统兜底</el-tag>
                        <el-tag v-else-if="row.reason_source === 'derived'" size="small" type="info"
                                effect="plain" style="margin-left:6px;">系统派生</el-tag>
                        <el-tag v-else-if="row.reason_source === 'strategy'" size="small" type="success"
                                effect="plain" style="margin-left:6px;">策略提供</el-tag>
                        <el-tag v-if="row.ai_action" size="small"
                                :type="row.ai_gate_result === 'reject' ? 'danger' : 'info'"
                                effect="plain" style="margin-left:6px;">
                          AI {{ row.ai_action }}{{ row.ai_score != null ? ' ' + Number(row.ai_score).toFixed(1) : '' }}
                        </el-tag>
                      </template>
                    </el-table-column>
                    <el-table-column label="决策依据" width="90" align="center">
                      <template #default="{ row }">
                        <el-button v-if="row.signal_id" link type="primary" size="small"
                                   @click.stop="openTradeDecision(row)">查看</el-button>
                        <span v-else style="color:#c0c4cc;">--</span>
                      </template>
                    </el-table-column>
                  </el-table>
                </div>
              </el-tab-pane>

              <!-- ──── 统计 ──── -->
              <el-tab-pane name="stats">
                <template #label><el-icon><TrendCharts /></el-icon><span>统计</span></template>
                <div class="jq-section">
                  <div class="jq-stats-grid">
                    <div class="jq-stat-card" v-for="m in statMetrics" :key="m.key">
                      <span class="jq-stat-label">{{ m.label }}</span>
                      <span class="jq-stat-value" :class="m.cls ? m.cls(detailData.info[m.key]) : ''">
                        {{ m.fmt(detailData.info[m.key]) }}
                      </span>
                    </div>
                  </div>
                </div>
              </el-tab-pane>

              <!-- ──── 日志 ──── -->
              <el-tab-pane name="log">
                <template #label><el-icon><Notebook /></el-icon><span>日志</span></template>
                <!-- 执行日志 -->
                <div class="jq-section">
                  <div class="jq-section-title">执行日志</div>
                  <div class="jq-log-area">
                    <div class="jq-exec-log-entry" v-for="(el, i) in (detailData.execution_logs || [])" :key="'el-' + i">
                      <span class="jq-log-date">{{ el.trade_date }}</span>
                      <el-tag :type="el.status === 'success' ? 'success' : el.status === 'error' ? 'danger' : el.status === 'skipped' ? 'warning' : 'info'"
                              size="small" style="margin-right: 8px;">{{ el.status }}</el-tag>
                      <span class="jq-exec-log-msg">{{ el.message || '--' }}</span>
                      <span v-if="el.trade_count" class="jq-exec-log-extra">{{ el.trade_count }}笔交易</span>
                      <span v-if="el.total_value" class="jq-exec-log-extra">总资产 ¥{{ Number(el.total_value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }}</span>
                      <span class="jq-exec-log-time">{{ el.started_at?.slice(11, 19) || '' }} ~ {{ el.finished_at?.slice(11, 19) || '' }}</span>
                    </div>
                    <div v-if="!detailData.execution_logs?.length" class="jq-log-empty">暂无执行日志</div>
                  </div>
                </div>
                <!-- 交易记录 -->
                <div class="jq-section" style="margin-top: 16px;">
                  <div class="jq-section-title">交易记录</div>
                  <div class="jq-log-area">
                    <div class="jq-log-entry" v-for="(t, i) in (detailData.trades || []).slice(0, 50)" :key="'t-' + i">
                      <span class="jq-log-date">{{ t.date }}</span>
                      <span :style="{ color: t.direction === 'buy' ? '#f56c6c' : '#67c23a' }">
                        {{ t.direction === 'buy' ? '买入' : '卖出' }}
                      </span>
                      <span>{{ t.code }} {{ t.name || '' }}</span>
                      <span>{{ Number(t.amount ?? 0).toLocaleString() }}股</span>
                      <span>@{{ (t.price ?? 0).toFixed(2) }}</span>
                    </div>
                    <div v-if="!detailData.trades?.length" class="jq-log-empty">暂无交易记录</div>
                  </div>
                </div>
              </el-tab-pane>

              <!-- ──── 代码 ──── -->
              <el-tab-pane name="code">
                <template #label><span class="code-tab-icon">&lt;/&gt;</span><span>代码</span></template>
                <div class="jq-section code-section">
                  <div class="code-toolbar">
                    <div class="code-toolbar-left">
                      <span class="code-strategy-name">{{ detailData?.info?.strategy_name || '策略代码' }}</span>
                      <el-tag v-if="codeStrategyId" size="small" type="info">ID: {{ codeStrategyId }}</el-tag>
                      <span v-if="codeDirty" class="code-dirty-hint">● 未保存</span>
                    </div>
                    <div class="code-toolbar-right">
                      <el-button size="small" @click="doCodeSave" :loading="codeSaving" :disabled="!codeDirty">
                        保存
                      </el-button>
                      <el-button size="small" @click="goEditPage" :disabled="!codeStrategyId">
                        在编辑器中打开
                      </el-button>
                      <el-divider direction="vertical" />
                      <el-date-picker v-model="codeBtStart" type="date" size="small"
                                      placeholder="开始日期" value-format="YYYY-MM-DD" style="width: 125px;" />
                      <span style="margin: 0 4px; color: #909399;">至</span>
                      <el-date-picker v-model="codeBtEnd" type="date" size="small"
                                      placeholder="结束日期" value-format="YYYY-MM-DD" style="width: 125px;" />
                      <el-button size="small" type="primary" @click="doCodeBacktest" :loading="codeRunning"
                                 :disabled="!strategyCodeText">
                        运行回测
                      </el-button>
                    </div>
                  </div>
                  <div v-if="codeLoading" class="code-loading" v-loading="true" style="height: 400px;"></div>
                  <template v-else-if="strategyCodeText !== null">
                    <textarea v-model="strategyCodeText" class="paper-code-editor" spellcheck="false" wrap="off"
                              @input="codeDirty = true" @keydown.ctrl.s.prevent="doCodeSave" />
                  </template>
                  <div v-else class="code-empty">
                    <el-icon :size="48" color="#c0c4cc"><EditPen /></el-icon>
                    <p style="color: #909399; margin-top: 12px;">该模拟盘未关联策略</p>
                  </div>
                  <!-- 回测结果 -->
                  <div v-if="codeBtResult" class="code-bt-result">
                    <div class="code-bt-header">
                      <span class="code-bt-title">回测结果</span>
                      <el-button size="small" text @click="codeBtResult = null">关闭</el-button>
                    </div>
                    <div class="code-bt-metrics">
                      <div class="code-bt-metric">
                        <span class="label">总收益</span>
                        <span class="value" :class="retCls(codeBtResult.total_return)">{{ fmtPct(codeBtResult.total_return) }}</span>
                      </div>
                      <div class="code-bt-metric">
                        <span class="label">年化收益</span>
                        <span class="value" :class="retCls(codeBtResult.annual_return)">{{ fmtPctDash(codeBtResult.annual_return) }}</span>
                      </div>
                      <div class="code-bt-metric">
                        <span class="label">最大回撤</span>
                        <span class="value val-green">{{ codeBtResult.max_drawdown != null ? '-' + codeBtResult.max_drawdown.toFixed(2) + '%' : '--' }}</span>
                      </div>
                      <div class="code-bt-metric">
                        <span class="label">夏普比率</span>
                        <span class="value">{{ codeBtResult.sharpe_ratio != null ? codeBtResult.sharpe_ratio.toFixed(2) : '--' }}</span>
                      </div>
                      <div class="code-bt-metric">
                        <span class="label">交易次数</span>
                        <span class="value">{{ codeBtResult.trade_count ?? '--' }}</span>
                      </div>
                    </div>
                    <div v-if="codeBtLogs.length" class="code-bt-logs">
                      <div class="code-bt-log" v-for="(l, i) in codeBtLogs.slice(-30)" :key="i">{{ l }}</div>
                    </div>
                  </div>
                </div>
              </el-tab-pane>

              <!-- ──── 设置 ──── -->
              <el-tab-pane name="settings">
                <template #label><el-icon><Setting /></el-icon><span>设置</span></template>
                <div class="jq-section">
                  <el-form class="jq-settings-form" label-width="96px" size="default">
                    <el-form-item label="模拟盘名称" required>
                      <el-input v-model="settingsForm.name" maxlength="100" show-word-limit />
                    </el-form-item>
                    <el-form-item label="运行频率" required>
                      <el-select v-model="settingsForm.run_frequency" style="width: 180px;">
                        <el-option v-for="item in frequencyOptions" :key="item.value" :label="item.label" :value="item.value" />
                      </el-select>
                    </el-form-item>
                    <el-form-item label="开始日期" required>
                      <el-date-picker v-model="settingsForm.start_at" type="datetime"
                                      value-format="YYYY-MM-DD HH:mm:ss" format="YYYY-MM-DD HH:mm"
                                      style="width: 220px;" />
                    </el-form-item>
                    <el-form-item label="初始资金" required>
                      <div class="settings-inline-control">
                        <el-input-number v-model="settingsForm.initial_cash" :min="10000" :step="100000"
                                         :disabled="paperHasStarted" style="width: 220px;" />
                        <span v-if="paperHasStarted" class="settings-help">模拟盘已开始运行，初始资金不可修改</span>
                      </div>
                    </el-form-item>
                    <el-form-item label="策略名称">
                      <span class="jq-readonly-value">{{ detailData.info.strategy_name }}</span>
                    </el-form-item>
                    <el-form-item label="回测版本">
                      <span class="jq-readonly-value">{{ hasBacktest(detailData.info) ? backtestLabel(detailData.info) : '未绑定' }}</span>
                    </el-form-item>
                    <el-form-item label="最后运行">
                      <span class="jq-readonly-value">{{ detailData.info.last_run_date || '--' }}</span>
                    </el-form-item>
                    <el-form-item label="当前状态">
                      <el-tag :type="statusType(detailData.info.status)" size="small">
                        {{ statusLabel(detailData.info.status) }}
                      </el-tag>
                    </el-form-item>
                    <el-form-item>
                      <el-button type="primary" :loading="settingsSaving" @click="saveSettings">保存设置</el-button>
                      <el-button @click="resetSettingsForm">重置</el-button>
                    </el-form-item>
                  </el-form>
                </div>
              </el-tab-pane>
            </el-tabs>
          </div>
        </template>
      </div>
    </template>

    <!-- ═══════════ 对比对话框 ═══════════ -->
    <el-dialog v-model="showCompare" title="模拟盘对比" width="90%">
      <div v-loading="compareLoading">
        <div v-if="compareData.length">
          <h4>收益走势对比</h4>
          <div ref="compareChartRef" style="height: 320px; width: 100%;"></div>
          <h4 style="margin-top: 16px;">绩效指标对比</h4>
          <el-table :data="compareMetricRows" size="small" stripe border>
            <el-table-column prop="label" label="指标" width="120" fixed />
            <el-table-column v-for="p in compareData" :key="p.id" :label="p.name || p.strategy_name" align="right">
              <template #default="{ row }">
                <span :class="row.cls ? row.cls(row.values[p.id]) : ''">{{ row.fmt(row.values[p.id]) }}</span>
              </template>
            </el-table-column>
          </el-table>
        </div>
        <el-empty v-else description="暂无对比数据" />
      </div>
    </el-dialog>

    <!-- ═══════════ 个股模拟买卖点与指标K线 ═══════════ -->
    <el-dialog v-model="stockDialogVisible" :title="stockDialogTitle" width="92vw" top="4vh" destroy-on-close
               @closed="disposeStockCharts">
      <div class="stock-dialog" v-loading="stockLoading">
        <div class="stock-summary" v-if="selectedStock">
          <div class="summary-item"><span>代码</span><b>{{ selectedStock.code }}</b></div>
          <div class="summary-item"><span>名称</span><b>{{ stockDisplayName(selectedStock) }}</b></div>
          <div class="summary-item"><span>持仓日期</span><b>{{ posHistDate || detailData?.info?.last_run_date || '--' }}</b></div>
          <div class="summary-item"><span>相关交易</span><b>{{ selectedStockTrades.length }} 笔</b></div>
          <div class="summary-item wide" v-if="selectedPaperTrade">
            <span>当前标记</span>
            <b :class="selectedPaperTrade.direction === 'buy' ? 'val-red' : 'val-green'">
              {{ selectedPaperTrade.date }} {{ directionLabel(selectedPaperTrade) }} {{ fmtMaybe(selectedPaperTrade.price) }}
            </b>
          </div>
        </div>

        <div class="stock-toolbar">
          <span class="toolbar-label">主图叠加</span>
          <el-checkbox-group v-model="stockOverlayIndicators" size="small" @change="renderActiveStockChart">
            <el-checkbox-button label="MA5">MA5</el-checkbox-button>
            <el-checkbox-button label="MA20">MA20</el-checkbox-button>
            <el-checkbox-button label="MA30">MA30</el-checkbox-button>
            <el-checkbox-button label="MA60">MA60</el-checkbox-button>
            <el-checkbox-button label="BOLL">BOLL</el-checkbox-button>
          </el-checkbox-group>
          <span class="toolbar-hint">指标基于完整历史K线计算，模拟买卖点来自当前模拟盘交易记录。</span>
        </div>

        <CustomIndicatorOverlayBar :state="ciOverlay" />

        <el-tabs v-model="stockActivePeriod" @tab-change="renderActiveStockChart">
          <el-tab-pane label="日K" name="daily">
            <div ref="stockDailyEl" class="stock-chart-box" :class="{ 'has-sub': hasCiSubPanel }"></div>
          </el-tab-pane>
          <el-tab-pane label="周K" name="weekly">
            <div ref="stockWeeklyEl" class="stock-chart-box" :class="{ 'has-sub': hasCiSubPanel }"></div>
          </el-tab-pane>
          <el-tab-pane label="月K" name="monthly">
            <div ref="stockMonthlyEl" class="stock-chart-box" :class="{ 'has-sub': hasCiSubPanel }"></div>
          </el-tab-pane>
        </el-tabs>

        <div class="indicator-panel" v-if="selectedPaperTrade">
          <div class="panel-title">{{ stockPeriodLabel }}指标快照</div>
          <el-descriptions :column="4" size="small" border>
            <el-descriptions-item label="K线日期">{{ activeIndicatorSnapshot.date || '--' }}</el-descriptions-item>
            <el-descriptions-item label="开盘">{{ fmtMaybe(activeIndicatorSnapshot.open) }}</el-descriptions-item>
            <el-descriptions-item label="最高">{{ fmtMaybe(activeIndicatorSnapshot.high) }}</el-descriptions-item>
            <el-descriptions-item label="最低">{{ fmtMaybe(activeIndicatorSnapshot.low) }}</el-descriptions-item>
            <el-descriptions-item label="收盘">{{ fmtMaybe(activeIndicatorSnapshot.close) }}</el-descriptions-item>
            <el-descriptions-item label="MA5">{{ fmtMaybe(activeIndicatorSnapshot.ma5) }}</el-descriptions-item>
            <el-descriptions-item label="MA20">{{ fmtMaybe(activeIndicatorSnapshot.ma20) }}</el-descriptions-item>
            <el-descriptions-item label="MA30">{{ fmtMaybe(activeIndicatorSnapshot.ma30) }}</el-descriptions-item>
            <el-descriptions-item label="MA60">{{ fmtMaybe(activeIndicatorSnapshot.ma60) }}</el-descriptions-item>
            <el-descriptions-item label="BOLL上轨">{{ fmtMaybe(activeIndicatorSnapshot.bollUpper) }}</el-descriptions-item>
            <el-descriptions-item label="BOLL中轨">{{ fmtMaybe(activeIndicatorSnapshot.bollMiddle) }}</el-descriptions-item>
            <el-descriptions-item label="BOLL下轨">{{ fmtMaybe(activeIndicatorSnapshot.bollLower) }}</el-descriptions-item>
            <el-descriptions-item label="RSI14">{{ fmtMaybe(activeIndicatorSnapshot.rsi) }}</el-descriptions-item>
            <el-descriptions-item label="MACD DIF">{{ fmtMaybe(activeIndicatorSnapshot.macdDif) }}</el-descriptions-item>
            <el-descriptions-item label="MACD DEA">{{ fmtMaybe(activeIndicatorSnapshot.macdDea) }}</el-descriptions-item>
            <el-descriptions-item label="MACD柱">{{ fmtMaybe(activeIndicatorSnapshot.macdHist) }}</el-descriptions-item>
            <el-descriptions-item label="成交量">{{ Number(activeIndicatorSnapshot.volume || 0).toLocaleString() }}</el-descriptions-item>
          </el-descriptions>
        </div>

        <el-table :data="selectedStockTrades" size="small" max-height="220" stripe class="stock-trade-table"
                  @row-click="selectTradeInDialog">
          <el-table-column prop="date" label="日期" width="100" />
          <el-table-column label="方向" width="70">
            <template #default="{ row }">
              <span :class="row.direction === 'buy' ? 'val-red' : 'val-green'">{{ directionLabel(row) }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="code" label="代码" width="75" />
          <el-table-column label="名称" width="110" show-overflow-tooltip>
            <template #default="{ row }">{{ stockDisplayName(row) }}</template>
          </el-table-column>
          <el-table-column label="价格" width="85" align="right"><template #default="{ row }">{{ fmtMaybe(row.price) }}</template></el-table-column>
          <el-table-column label="数量" width="95" align="right"><template #default="{ row }">{{ Number(row.amount || 0).toLocaleString() }}</template></el-table-column>
          <el-table-column label="成交额" width="120" align="right"><template #default="{ row }">{{ formatMoneyFull(row.value) }}</template></el-table-column>
          <el-table-column label="手续费" width="90" align="right"><template #default="{ row }">{{ fmtMaybe((row.commission || 0) + (row.tax || 0)) }}</template></el-table-column>
        </el-table>
      </div>
    </el-dialog>

    <!-- ═══════════ 创建对话框 ═══════════ -->
    <el-dialog v-model="showCreateDialog" title="新建模拟交易" width="520px">
      <el-form label-width="120px" class="paper-create-form">
        <el-form-item label="交易名称">
          <el-input v-model="createForm.name" placeholder="模拟交易名称（可选）" />
        </el-form-item>
        <el-form-item label="选择策略" required>
          <el-select v-model="createForm.strategy_id" placeholder="请选择一个策略" style="width: 100%;"
                     filterable @change="onCreateStrategyChange">
            <el-option v-for="s in strategies" :key="s.id" :label="s.name" :value="s.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="选择回测" required>
          <el-select v-model="createForm.backtest_id" placeholder="请选择该策略的一个回测版本"
                     style="width: 100%;" filterable :loading="backtestsLoading"
                     :disabled="!createForm.strategy_id">
            <el-option v-for="bt in strategyBacktests" :key="bt.id"
                       :label="backtestOptionLabel(bt)" :value="bt.id">
              <div class="bt-option">
                <span class="bt-option-name">{{ bt.strategy_name || `回测-${bt.id}` }}</span>
                <span :class="retCls(bt.total_return)">{{ fmtPct(bt.total_return) }}</span>
              </div>
            </el-option>
          </el-select>
          <div v-if="createForm.strategy_id && !backtestsLoading && strategyBacktests.length === 0"
               class="form-tip">该策略暂无已完成回测，请先运行一次组合回测。</div>
        </el-form-item>
        <el-form-item label="初始资金">
          <el-input-number v-model="createForm.initial_cash" :min="10000" :step="100000" style="width: 100%;" />
        </el-form-item>
        <el-form-item label="运行频率" required>
          <div class="form-inline-row">
            <el-select v-model="createForm.run_frequency" style="width: 130px;">
              <el-option v-for="f in frequencyOptions" :key="f.value" :label="f.label" :value="f.value" />
            </el-select>
            <span class="inline-label">开始时间</span>
            <el-date-picker v-model="createForm.start_at" type="datetime"
                            value-format="YYYY-MM-DD HH:mm:ss"
                            format="YYYY-MM-DD HH:mm" style="flex: 1;" />
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="doCreate" :loading="creating">确定</el-button>
      </template>
    </el-dialog>

    <!-- ═══════════ 交易决策依据弹窗 (Phase 3) ═══════════ -->
    <el-dialog v-model="tradeDecisionVisible" title="交易决策依据" width="720px" top="6vh" destroy-on-close>
      <div v-loading="tradeDecisionLoading" class="trade-decision-dialog">
        <div v-if="tradeDecisionRow" class="td-summary">
          <div class="td-row">
            <span>日期</span><b>{{ tradeDecisionRow.date }}</b>
            <span>方向</span>
            <b :style="{ color: tradeDecisionRow.direction === 'buy' ? '#f56c6c' : '#67c23a' }">
              {{ tradeDecisionRow.direction === 'buy' ? '买入' : '卖出' }}
            </b>
            <span>标的</span><b>{{ tradeDecisionRow.code }} {{ tradeDecisionRow.name || '' }}</b>
          </div>
          <div class="td-row">
            <span>成交价</span><b>{{ Number(tradeDecisionRow.price ?? 0).toFixed(2) }}</b>
            <span>成交量</span><b>{{ Number(tradeDecisionRow.amount ?? 0).toLocaleString() }}</b>
            <span>成交额</span><b>{{ formatMoneyFull(tradeDecisionRow.value) }}</b>
          </div>
          <div class="td-reason">
            <span>策略理由</span>
            <div class="td-reason-body">
              <div class="reason-headline">{{ tradeReasonParsed.headline }}</div>
              <ul v-if="tradeReasonParsed.logs.length" class="reason-logs">
                <li v-for="(line, i) in tradeReasonParsed.logs" :key="i">{{ line }}</li>
              </ul>
              <div class="reason-tags">
                <el-tag v-if="tradeDecisionRow.reason_source === 'generated'" size="small" type="warning"
                        effect="plain">系统兜底说明（非策略显式提供）</el-tag>
                <el-tag v-else-if="tradeDecisionRow.reason_source === 'derived'" size="small" type="info"
                        effect="plain">系统派生（来自策略日志/订单参数）</el-tag>
                <el-tag v-else-if="tradeDecisionRow.reason_source === 'strategy'" size="small" type="success"
                        effect="plain">策略真实理由</el-tag>
                <el-tag v-else-if="tradeDecisionRow.reason_source" size="small" type="info" effect="plain">
                  来源：{{ tradeDecisionRow.reason_source }}
                </el-tag>
              </div>
            </div>
          </div>
        </div>
        <div v-if="tradeDecisionAi" class="td-ai">
          <span class="td-block-title">AI 综合评分</span>
          <el-tag :type="tradeDecisionAi.gate === 'reject' ? 'danger' : 'success'" effect="plain" size="small">
            {{ tradeDecisionAi.action || '--' }}
            <span v-if="tradeDecisionAi.score != null"> · {{ Number(tradeDecisionAi.score).toFixed(2) }}</span>
            <span v-if="tradeDecisionAi.gate"> · gate: {{ tradeDecisionAi.gate }}</span>
          </el-tag>
          <div v-if="tradeDecisionAi.reason" class="td-ai-reason">
            <div v-if="tradeDecisionAi.reason.reason_summary" class="ai-reason-summary">
              <strong>理由：</strong>{{ tradeDecisionAi.reason.reason_summary }}
            </div>
            <div v-if="tradeDecisionAi.reason.evidence" class="ai-reason-evidence">
              <strong>证据：</strong>{{ tradeDecisionAi.reason.evidence }}
            </div>
            <div v-if="tradeDecisionAi.reason.risk_flags" class="ai-reason-risk">
              <strong>风险标记：</strong>
              <el-tag type="danger" size="small" effect="plain" style="margin-left: 4px;">
                {{ tradeDecisionAi.reason.risk_flags }}
              </el-tag>
            </div>
          </div>
        </div>
        <div v-if="tradeStrategyExplain" class="td-block td-strategy-explain">
          <span class="td-block-title">
            策略说明
            <span v-if="tradeStrategyExplain.name" class="td-block-sub">{{ tradeStrategyExplain.name }}</span>
            <el-tag :type="tradeStrategyExplain.isBuy ? 'danger' : 'success'" size="small" effect="plain"
                    style="margin-left:6px;">
              {{ tradeStrategyExplain.isBuy ? '买入条件' : '卖出条件' }}
            </el-tag>
            <span v-if="tradeStrategyExplain.source" class="td-block-source">{{ tradeStrategyExplain.source }}</span>
          </span>
          <div class="strategy-explain-body">{{ tradeStrategyExplain.text }}</div>
        </div>
        <div class="td-block">
          <span class="td-block-title">决策规则对比</span>
          <el-table :data="tradeDecisionRules" size="small" border empty-text="该策略未输出结构化决策规则（仅有理由文本，请参见上方'策略理由'与下方'指标快照'）"
                    class="td-rules-table">
            <el-table-column prop="name" label="指标/规则" min-width="160" show-overflow-tooltip />
            <el-table-column prop="threshold" label="阈值/判定" min-width="160" show-overflow-tooltip />
            <el-table-column prop="actual" label="实际数据" min-width="160" show-overflow-tooltip />
            <el-table-column label="结果" width="70" align="center">
              <template #default="{ row }">
                <el-tag :type="ruleResultTagType(row.pass)" size="small" effect="plain">
                  {{ ruleResultLabel(row.pass) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="weight" label="权重" width="70" align="right">
              <template #default="{ row }">{{ row.weight != null ? Number(row.weight).toFixed(2) : '--' }}</template>
            </el-table-column>
          </el-table>
        </div>
        <div v-if="tradeDecisionIndicator" class="td-block">
          <span class="td-block-title">
            指标快照
            <span class="td-block-sub">{{ tradeDecisionIndicator.trade_date }}</span>
          </span>
          <el-descriptions :column="4" border size="small" class="td-indicators">
            <el-descriptions-item label="开盘">{{ fmtNumDp(tradeDecisionIndicator.open_price) }}</el-descriptions-item>
            <el-descriptions-item label="收盘">{{ fmtNumDp(tradeDecisionIndicator.close_price) }}</el-descriptions-item>
            <el-descriptions-item label="最低">{{ fmtNumDp(tradeDecisionIndicator.low_price) }}</el-descriptions-item>
            <el-descriptions-item label="最高">{{ fmtNumDp(tradeDecisionIndicator.high_price) }}</el-descriptions-item>
            <el-descriptions-item label="成交量" :span="4">{{ fmtVolumeHuman(tradeDecisionIndicator.volume) }}</el-descriptions-item>
            <el-descriptions-item label="MA" :span="4">{{ fmtIndicatorDictMA(tradeDecisionIndicator.ma) }}</el-descriptions-item>
            <el-descriptions-item label="BOLL" :span="4">{{ fmtIndicatorBOLL(tradeDecisionIndicator.boll) }}</el-descriptions-item>
            <el-descriptions-item label="RSI" :span="4">{{ fmtIndicatorRSI(tradeDecisionIndicator.rsi) }}</el-descriptions-item>
            <el-descriptions-item label="MACD" :span="4">{{ fmtIndicatorMACD(tradeDecisionIndicator.macd) }}</el-descriptions-item>
          </el-descriptions>
        </div>
      </div>
      <template #footer>
        <el-button @click="tradeDecisionVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Plus, DataAnalysis, ArrowLeft, CaretRight, ArrowDown,
  InfoFilled, Document, TrendCharts, Notebook, Setting, EditPen,
} from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import {
  getPaperTradingList, getPaperTradingDetail, createPaperTrading,
  paperTradingAction, runPaperTrading, getStrategyCodeList, getPaperCompare,
  deletePaperTrading, getPortfolioBacktestList, getKlineData, updatePaperTrading,
  getStrategyCodeDetail, saveStrategyCode, startPortfolioBacktest,
} from '@/api/stock'
import request from '@/api/request'
import { useCustomIndicatorOverlay } from '@/composables/useCustomIndicatorOverlay'
import CustomIndicatorOverlayBar from '@/components/CustomIndicatorOverlayBar.vue'

const route = useRoute()
const router = useRouter()

// ── 详情ID：基于路由query，侧栏导航点击会清除query回到列表 ──
const detailId = computed(() => {
  const id = route.query.id
  return id ? Number(id) : null
})

const paperList = ref<any[]>([])
const strategies = ref<any[]>([])
const strategyBacktests = ref<any[]>([])
const backtestsLoading = ref(false)
const loading = ref(false)
const showCreateDialog = ref(false)
const showCompare = ref(false)
const detailData = ref<any>(null)
const detailLoading = ref(false)
const sideTab = ref('overview')
const chartTab = ref('returns')
const benchmarkStartMode = ref<'paper_start' | 'first_trade'>('paper_start')
const benchmarkReturnLabel = computed(() => detailData.value?.info?.benchmark_return_label || '基准收益')
const returnSeriesOptions = computed(() => [
  { key: 'strategy_return', label: '策略收益', color: '#e6a23c', yAxisIndex: 0, unit: '%' },
  { key: 'benchmark_return', label: benchmarkReturnLabel.value, color: '#409eff', yAxisIndex: 0, unit: '%' },
  { key: 'excess_return', label: '超额收益', color: '#f56c6c', yAxisIndex: 0, unit: '%' },
  { key: 'total_value', label: '总资产', color: '#67c23a', yAxisIndex: 1, unit: ' 元' },
])
const visibleReturnSeries = ref(['strategy_return', 'benchmark_return', 'excess_return'])
const compareData = ref<any[]>([])
const compareLoading = ref(false)
const creating = ref(false)
const settingsSaving = ref(false)
const runningId = ref<number | null>(null)
const selectedRows = ref<any[]>([])
const frequencyOptions = [
  { label: '每天', value: 'daily' as const },
  { label: '每小时', value: 'hourly' as const },
  { label: '每15分钟', value: '15m' as const },
]

function defaultCreateForm() {
  return {
    strategy_id: null as number | null,
    backtest_id: null as number | null,
    name: '',
    initial_cash: 1000000,
    run_frequency: 'daily' as 'daily' | 'hourly' | '15m',
    start_at: formatDateTime(new Date()),
  }
}

const createForm = ref(defaultCreateForm())
const settingsForm = ref({
  name: '',
  initial_cash: 1000000,
  run_frequency: 'daily' as 'daily' | 'hourly' | '15m',
  start_at: '',
})
const paperHasStarted = computed(() => {
  const info = detailData.value?.info || {}
  return Boolean(info.last_run_date || detailData.value?.nav?.length || detailData.value?.trades?.length)
})

// ── 代码 tab 状态 ──
const strategyCodeText = ref<string | null>(null)
const codeStrategyId = ref<number | null>(null)
const codeDirty = ref(false)
const codeLoading = ref(false)
const codeSaving = ref(false)
const codeRunning = ref(false)
const codeBtStart = ref('')
const codeBtEnd = ref('')
const codeBtResult = ref<any>(null)
const codeBtLogs = ref<string[]>([])

const navChartRef = ref<HTMLElement | null>(null)
const compareChartRef = ref<HTMLElement | null>(null)
const stockDailyEl = ref<HTMLElement | null>(null)
const stockWeeklyEl = ref<HTMLElement | null>(null)
const stockMonthlyEl = ref<HTMLElement | null>(null)
let navChart: echarts.ECharts | null = null
let stockDailyChart: echarts.ECharts | null = null
let stockWeeklyChart: echarts.ECharts | null = null
let stockMonthlyChart: echarts.ECharts | null = null
// 跟踪活跃 SSE 连接，组件卸载时统一关闭，避免后台连接泄漏
const activeEvtSources = new Set<EventSource>()

const stockDialogVisible = ref(false)
const stockLoading = ref(false)
const stockActivePeriod = ref<'daily' | 'weekly' | 'monthly'>('daily')
const selectedStock = ref<any>(null)
const selectedPaperTrade = ref<any>(null)
const stockKlines = ref<Record<string, any>>({})
const stockOverlayIndicators = ref(['MA5', 'MA20', 'MA30', 'MA60', 'BOLL'])

// ── PR-5 自定义指标叠加 ──
const ciCodeRef = computed(() => {
  const c = selectedStock.value?.code
  return c ? String(c).padStart(6, '0') : ''
})
const ciDatesRef = computed<string[]>(() => stockKlines.value[stockActivePeriod.value]?.dates || [])
const ciOverlay = useCustomIndicatorOverlay(
  ciCodeRef as any,
  stockActivePeriod as any,
  ciDatesRef as any,
)
const hasCiSubPanel = computed(() => !!ciOverlay.extension.value.subPanel)
watch(
  () => ciOverlay.extension.value,
  async () => {
    // 等待 :class 切换后容器高度更新（has-sub 增高），再 dispose+init
    await nextTick()
    renderActiveStockChart()
  },
  { deep: true },
)

// ── 列可见性（聚宽风格列筛选） ──
const posColumnDefs = [
  { key: 'name', label: '名称' },
  { key: 'direction', label: '多空' },
  { key: 'amount', label: '数量' },
  { key: 'available', label: '可用数量' },
  { key: 'price', label: '现价' },
  { key: 'value', label: '市值/价值' },
  { key: 'profit', label: '盈亏' },
  { key: 'profit_rate', label: '逐笔浮盈' },
  { key: 'avg_cost', label: '开仓均价' },
  { key: 'weight', label: '仓位占比' },
  { key: 'pnl_ratio', label: '盈亏占比' },
]
const posVisibleCols = ref(['name', 'amount', 'price', 'profit', 'profit_rate', 'avg_cost', 'value', 'weight', 'pnl_ratio'])

const tradeColumnDefs = [
  { key: 'name', label: '名称' },
  { key: 'direction', label: '交易类型' },
  { key: 'order_type', label: '下单类型' },
  { key: 'amount', label: '成交数量' },
  { key: 'price', label: '成交价' },
  { key: 'value', label: '成交额' },
  { key: 'commission', label: '手续费' },
  { key: 'close_profit', label: '最终盈亏额' },
  { key: 'return_rate', label: '盈亏比' },
  { key: 'status', label: '状态' },
  { key: 'reason', label: '交易原因' },
]
const tradeVisibleCols = ref(['direction', 'amount', 'price', 'value', 'commission', 'close_profit', 'return_rate', 'reason'])

// ── Phase 3 交易决策依据弹窗 ──
const tradeDecisionVisible = ref(false)
const tradeDecisionLoading = ref(false)
const tradeDecisionRow = ref<any>(null)
const tradeDecisionDetail = ref<any>(null)
async function openTradeDecision(row: any) {
  tradeDecisionRow.value = row
  tradeDecisionDetail.value = null
  tradeDecisionVisible.value = true
  if (!row?.signal_id) return
  tradeDecisionLoading.value = true
  try {
    const r: any = await request.get('/api/trade/signal/detail', { params: { signal_id: row.signal_id } })
    if (r && r.code === 0) tradeDecisionDetail.value = r.data
    else ElMessage.warning(r?.msg || '决策详情加载失败')
  } catch (e: any) {
    ElMessage.error(e?.message || '决策详情加载失败')
  } finally {
    tradeDecisionLoading.value = false
  }
}
function _fmtVal(v: any) {
  if (v == null || v === '') return '--'
  if (typeof v === 'object') {
    try { return JSON.stringify(v) } catch { return String(v) }
  }
  return String(v)
}
const tradeDecisionRules = computed(() => {
  const d = tradeDecisionDetail.value
  if (!d || !Array.isArray(d.rules)) return []
  return d.rules.map((r: any) => {
    // 三态：true=通过 / false=未通过 / null=事实快照（不做评判）
    let passState: boolean | null
    if (r.passed === 1 || r.passed === true) passState = true
    else if (r.passed === 0 || r.passed === false) passState = false
    else passState = null
    return {
      name: r.rule_name || r.name || '--',
      threshold: _fmtVal(r.threshold_expr ?? r.threshold_value ?? r.threshold),
      actual: _fmtVal(r.actual_value ?? r.actual),
      pass: passState,
      weight: r.weight ?? null,
      note: r.note || '',
    }
  })
})
// "结果"标签：tri-state（事实/通过/未通过）
function ruleResultLabel(pass: boolean | null): string {
  if (pass === true) return '通过'
  if (pass === false) return '未通过'
  return '事实'
}
function ruleResultTagType(pass: boolean | null): 'success' | 'warning' | 'info' {
  if (pass === true) return 'success'
  if (pass === false) return 'warning'
  return 'info'
}
function fmtNumDp(v: any, d = 2): string {
  if (v == null || v === '' || v === '--') return '--'
  const n = Number(v)
  if (!Number.isFinite(n)) return '--'
  return n.toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d })
}
function fmtIndicatorDictMA(v: any): string {
  if (!v || typeof v !== 'object') return '--'
  const parts = Object.entries(v)
    .filter(([, val]) => val != null && val !== '')
    .map(([k, val]) => `${k.toUpperCase()} ${fmtNumDp(val, 2)}`)
  return parts.length ? parts.join(' / ') : '--'
}
function fmtIndicatorBOLL(v: any): string {
  if (!v || typeof v !== 'object') return '--'
  const u = v.upper ?? v.ub ?? v.up
  const m = v.mid ?? v.middle ?? v.mb
  const l = v.lower ?? v.lb ?? v.dn
  return `上 ${fmtNumDp(u)} / 中 ${fmtNumDp(m)} / 下 ${fmtNumDp(l)}`
}
function fmtIndicatorRSI(v: any): string {
  if (v == null) return '--'
  if (typeof v === 'object') {
    const parts = Object.entries(v)
      .filter(([, val]) => val != null)
      .map(([k, val]) => `${k.toUpperCase()} ${fmtNumDp(val, 2)}`)
    return parts.length ? parts.join(' / ') : '--'
  }
  return fmtNumDp(v, 2)
}
function fmtIndicatorMACD(v: any): string {
  if (!v || typeof v !== 'object') return '--'
  const dif = v.dif ?? v.DIF
  const dea = v.dea ?? v.DEA
  const hist = v.hist ?? v.bar ?? v.histogram
  return `DIF ${fmtNumDp(dif, 4)} / DEA ${fmtNumDp(dea, 4)} / 柱 ${fmtNumDp(hist, 4)}`
}
function fmtVolumeHuman(v: any): string {
  if (v == null || v === '' || v === '--') return '--'
  const n = Number(v)
  if (!Number.isFinite(n)) return '--'
  if (Math.abs(n) >= 1e8) return `${(n / 1e8).toFixed(2)}亿`
  if (Math.abs(n) >= 1e4) return `${(n / 1e4).toFixed(1)}万`
  return n.toLocaleString('zh-CN', { maximumFractionDigits: 0 })
}
const tradeDecisionAi = computed(() => {
  const d = tradeDecisionDetail.value
  if (!d) return null
  if (d.ai_score == null && !d.ai_action && !d.ai_gate_result) return null
  return {
    score: d.ai_score,
    action: d.ai_action || '',
    gate: d.ai_gate_result || '',
    reason: d.ai_reason || null,
  }
})
// 指标快照后端返回单个 dict，包装为数组方便表格渲染
const tradeDecisionIndicators = computed(() => {
  const ind = tradeDecisionDetail.value?.indicators
  if (!ind || typeof ind !== 'object') return []
  return [{
    trade_date: ind.kline_date || tradeDecisionDetail.value?.signal_date || '--',
    open_price: ind.open ?? '--',
    close_price: ind.close ?? '--',
    low_price: ind.low ?? '--',
    high_price: ind.high ?? '--',
    volume: ind.volume ?? '--',
    ma: ind.ma,
    boll: ind.boll,
    rsi: ind.rsi,
    macd: ind.macd,
  }]
})
// el-descriptions 版快照，取首行即可
const tradeDecisionIndicator = computed(() => tradeDecisionIndicators.value[0] || null)
// 将原始 reason 文本拆成一行总结 + 多行策略日志
const tradeReasonParsed = computed(() => {
  const txt = String(tradeDecisionRow.value?.reason || '').trim()
  if (!txt) return { headline: '--', logs: [] as string[] }
  const segments = txt
    .split(/[\n|]+/)
    .map(s => s.trim().replace(/^[-•·\[\]]\s*/, '').trim())
    .filter(Boolean)
    .filter(s => !/^策略日志[:：]?$/.test(s))
  if (segments.length === 0) return { headline: txt, logs: [] }
  return { headline: segments[0], logs: segments.slice(1) }
})
// 策略说明（买入条件 / 卖出条件）。优先级：
//   后端 cn_stock_strategy_code.description > 父模拟盘 info.description > 内置名称映射 > 通用兜底
const BUILTIN_STRATEGY_DESC: Record<string, { buy: string; sell: string }> = {
  '海龟交易法则': {
    buy: '收盘价创 60 日新高时买入（Donchian 上轨突破）。',
    sell: '收盘价跌破 20 日最低价时卖出（Donchian 下轨退出）。',
  },
  '放量上涨': {
    buy: '涨幅 ≥ 2%、成交额 ≥ 2 亿、量比 ≥ 2 时买入（量价共振突破）。',
    sell: '触发 +15% 止盈 或 -7% 止损时卖出。',
  },
  '趋势回调': {
    buy: 'MA20 > MA60 趋势向上，价格回踩 MA20 附近，RSI 中性、缩量时买入。',
    sell: '跌破 MA20 / 趋势走坏或触发止损时卖出。',
  },
  '超跌反弹': {
    buy: 'RSI < 30 + 近 5 日触及布林下轨 + 当日收回下轨 + 阳线放量时买入。',
    sell: '反弹至布林中轨或触发止损时卖出。',
  },
  '无大幅回撤': {
    buy: '60 日涨幅 ≥ 60% 且无单日大跌、无连续两日大跌的强势趋势股买入。',
    sell: '触发 +20% 止盈 或 -10% 止损时卖出。',
  },
  '均线多头': {
    buy: 'MA30 持续上升且 30 日涨幅超 20% 时买入。',
    sell: '均线走平或触发止损时卖出。',
  },
  '停机坪': {
    buy: '近 15 日内出现涨停 + 放量，随后 3 日高开收涨且振幅 < 3% 时买入。',
    sell: '失守平台或触发止损时卖出。',
  },
  '回踩年线': {
    buy: '突破 MA250 后缩量回踩年线，回踩幅度 ≥ 20% 且量比 > 2 时买入。',
    sell: '跌破年线或触发止损时卖出。',
  },
  '突破平台': {
    buy: '60 日内价格在 MA60 附近整理后放量上穿 MA60 时买入。',
    sell: '跌回平台或触发止损时卖出。',
  },
  '低ATR成长': {
    buy: '上市满 250 日，近 10 日 ATR ≤ 10% 且最高/最低价比 > 1.1 的低波动成长股买入。',
    sell: '趋势走坏或触发止损时卖出。',
  },
  '高而窄的旗形': {
    buy: '短期翻倍且含连续涨停的极端强势形态买入。',
    sell: '触发 +20% 止盈 或 -10% 止损时卖出。',
  },
  '突破确认': {
    buy: '40 日振幅 < 25%、创新高、量比 ≥ 1.5、涨幅 > 2%、站上 MA60 时买入。',
    sell: '跌回 MA60 或触发止损时卖出。',
  },
  '小市值策略': {
    buy: '每月初选出市值最小的 5 只股票等权买入。',
    sell: '月末按市值重新筛选，剔除不再满足条件的股票。',
  },
  '双均线策略': {
    buy: '5 日均线上穿 20 日均线（金叉）时买入。',
    sell: '5 日均线下穿 20 日均线（死叉）时卖出。',
  },
  '动量策略': {
    buy: '买入近 20 日涨幅最大的股票。',
    sell: '持有 20 日后换仓为新的高动量股票。',
  },
  '基本面筛选动量策略': {
    buy: '基本面（ROE、净利润增速、市盈率）筛选后按动量排序取前 10 只买入。',
    sell: '每 20 个交易日按相同规则调仓。',
  },
  '季度基本面Top5+均线交叉': {
    buy: '每季度筛选基本面最优的 5 只作为股票池，MA5 金叉 MA20 时买入。',
    sell: 'MA5 死叉 MA20 时卖出。',
  },
}
function _matchBuiltinDesc(name: string): { buy: string; sell: string } | null {
  if (!name) return null
  if (BUILTIN_STRATEGY_DESC[name]) return BUILTIN_STRATEGY_DESC[name]
  for (const k of Object.keys(BUILTIN_STRATEGY_DESC)) {
    if (name.includes(k)) return BUILTIN_STRATEGY_DESC[k]
  }
  return null
}
const tradeStrategyExplain = computed(() => {
  const row = tradeDecisionRow.value
  if (!row) return null
  const isBuy = String(row.direction || '').toLowerCase() === 'buy' || row.direction === '买入'
  const d = tradeDecisionDetail.value || {}
  const stratName = d.strategy_name || detailData.value?.info?.strategy_name || ''
  const dbDesc = String(d.strategy_description || detailData.value?.info?.description || '').trim()
  // 后端从策略代码里抽取的买/卖说明（注释 + docstring）
  const codeExplain = String((isBuy ? d.strategy_explain_buy : d.strategy_explain_sell) || '').trim()
  const codeExplainOther = String((isBuy ? d.strategy_explain_sell : d.strategy_explain_buy) || '').trim()
  const builtin = _matchBuiltinDesc(stratName)
  let text = ''
  let source = ''
  if (codeExplain) {
    // 优先用代码注释里提取出的对应方向说明
    text = dbDesc ? `${dbDesc}\n\n${isBuy ? '【买入条件】' : '【卖出条件】'}\n${codeExplain}` : codeExplain
    source = '来自策略代码注释 / docstring'
  } else if (builtin) {
    const condText = isBuy ? builtin.buy : builtin.sell
    text = dbDesc ? `${dbDesc}\n\n${isBuy ? '【买入条件】' : '【卖出条件】'}${condText}` : condText
    source = '内置策略说明'
  } else if (codeExplainOther) {
    // 反向有提取到、本方向没有 → 退而展示反向，避免空白
    text = `${isBuy ? '未在策略代码中识别到买入相关注释。' : '未在策略代码中识别到卖出相关注释。'}\n\n${isBuy ? '【已识别的卖出条件】' : '【已识别的买入条件】'}\n${codeExplainOther}`
    source = '来自策略代码注释 / docstring（反向）'
  } else if (dbDesc) {
    text = dbDesc
    source = '策略保存时填写的说明'
  } else {
    text = isBuy
      ? '该策略未提供标准化买入条件说明。请参考下方"决策规则对比"中的"策略决策"/"风控、入场触发"行了解本笔买入的实际触发条件。'
      : '该策略未提供标准化卖出条件说明。请参考下方"决策规则对比"中的"策略决策"/"风控、入场触发"行了解本笔卖出的实际触发条件。'
    source = ''
  }
  return { name: stratName, isBuy, text, source }
})

function showPosCol(key: string) { return posVisibleCols.value.includes(key) }
function showTradeCol(key: string) { return tradeVisibleCols.value.includes(key) }
function togglePosCol(key: string, checked: boolean) {
  if (checked && !posVisibleCols.value.includes(key)) posVisibleCols.value = [...posVisibleCols.value, key]
  else if (!checked) posVisibleCols.value = posVisibleCols.value.filter(k => k !== key)
}
function toggleTradeCol(key: string, checked: boolean) {
  if (checked && !tradeVisibleCols.value.includes(key)) tradeVisibleCols.value = [...tradeVisibleCols.value, key]
  else if (!checked) tradeVisibleCols.value = tradeVisibleCols.value.filter(k => k !== key)
}

// ── 历史日期选择 ──
const posHistDate = ref('')
const tradeHistDate = ref('')

// ── 格式化工具 ──
function formatMoneyFull(v: number) {
  if (v == null) return '--'
  return Number(v).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
function fmtPct(v: number | undefined | null, d = 2) {
  if (v == null) return '--'
  return `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(d)}%`
}
function fmtPctDash(v: number | undefined | null, d = 2) {
  if (v == null || v === 0) return '——'
  return `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(d)}%`
}
function fmtNum(v: number | undefined | null, d = 2) {
  if (v == null) return '--'
  return Number(v).toFixed(d)
}
function fmtMoney(v: number | undefined | null) {
  if (v == null) return '--'
  const n = Number(v)
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}`
}
function fmtSellMoney(row: any) {
  if (row?.direction !== 'sell' || row.close_profit == null) return '--'
  return fmtMoney(row.close_profit)
}
function fmtSellPct(row: any) {
  if (row?.direction !== 'sell' || row.return_rate == null) return '--'
  return fmtPct(row.return_rate)
}
function retCls(v: number | undefined | null) {
  if (v == null || v === 0) return ''
  return Number(v) > 0 ? 'val-red' : 'val-green'
}
function statusType(s: string) {
  return s === 'running' ? 'success' : s === 'paused' ? 'warning' : 'info'
}
function statusLabel(s: string) {
  return s === 'running' ? '运行中' : s === 'paused' ? '已暂停' : '已停止'
}
function frequencyLabel(v: string) {
  return frequencyOptions.find(f => f.value === v)?.label || '每天'
}
function formatDateTime(d: Date) {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:00`
}
function backtestOptionLabel(bt: any) {
  const name = bt.strategy_name || `回测-${bt.id}`
  const range = bt.start_date && bt.end_date ? ` ${bt.start_date}~${bt.end_date}` : ''
  return `${name}${range} ${fmtPct(bt.total_return)}`
}
function backtestLabel(info: any) {
  const name = info.backtest_name || `回测-${info.backtest_id}`
  return `${name} ${info.backtest_return != null ? fmtPct(info.backtest_return) : ''}`.trim()
}
function hasBacktest(info: any) {
  const id = info?.backtest_id
  return id !== null && id !== undefined && String(id).trim() !== ''
}

// ── 持仓占比 ──
const positionRatio = computed(() => {
  if (!detailData.value?.info) return '0.00'
  const { current_value, current_cash } = detailData.value.info
  if (!current_value || current_value <= 0) return '0.00'
  const pos = current_value - (current_cash ?? 0)
  return ((pos / current_value) * 100).toFixed(2)
})

// ── 按日期过滤交易（客户端过滤） ──
const filteredTrades = computed(() => {
  const trades = detailData.value?.trades || []
  if (!tradeHistDate.value) return trades
  return trades.filter((t: any) => t.date === tradeHistDate.value)
})

const stockNameMap = computed(() => {
  const map = new Map<string, string>()
  const add = (row: any) => {
    const code = String(row?.code || '').trim()
    const name = String(row?.name || '').trim()
    if (code && name) map.set(code, name)
  }
  ;(detailData.value?.positions || []).forEach(add)
  ;(detailData.value?.trades || []).forEach(add)
  return map
})

const selectedStockTrades = computed(() => {
  const code = selectedStock.value?.code
  if (!code) return []
  return (detailData.value?.trades || [])
    .filter((t: any) => t.code === code)
    .sort((a: any, b: any) => String(a.date).localeCompare(String(b.date)))
})

const stockDialogTitle = computed(() => {
  if (!selectedStock.value) return '个股模拟买卖点与技术指标'
  const name = stockDisplayName(selectedStock.value)
  return `${selectedStock.value.code}${name && name !== selectedStock.value.code ? ' ' + name : ''} - 模拟买卖点与技术指标`
})

const stockPeriodLabel = computed(() => {
  const map: Record<string, string> = { daily: '日K', weekly: '周K', monthly: '月K' }
  return map[stockActivePeriod.value] || '日K'
})

const activeIndicatorSnapshot = computed<any>(() => {
  if (!selectedPaperTrade.value) return {}
  return indicatorSnapshot(stockActivePeriod.value, selectedPaperTrade.value)
})

// ── 统计指标 ──
const statMetrics = [
  { key: 'total_return', label: '累计收益', fmt: (v: any) => fmtPctDash(v), cls: (v: any) => retCls(v) },
  { key: 'annual_return', label: '年化收益', fmt: (v: any) => fmtPctDash(v), cls: (v: any) => retCls(v) },
  { key: 'max_drawdown', label: '最大回撤', fmt: (v: any) => v ? '-' + Number(v).toFixed(2) + '%' : '——', cls: () => 'val-green' },
  { key: 'sharpe_ratio', label: '夏普比率', fmt: (v: any) => fmtNum(v), cls: undefined },
  { key: 'sortino_ratio', label: '索提诺比率', fmt: (v: any) => fmtNum(v), cls: undefined },
  { key: 'win_rate', label: '胜率', fmt: (v: any) => v != null ? Number(v).toFixed(1) + '%' : '--', cls: undefined },
  { key: 'profit_loss_ratio', label: '盈亏比', fmt: (v: any) => fmtNum(v), cls: undefined },
  { key: 'trade_count', label: '交易笔数', fmt: (v: any) => String(v || 0), cls: undefined },
  { key: 'running_days', label: '运行天数', fmt: (v: any) => `${v || 0} 天`, cls: undefined },
  { key: 'today_return', label: '今日收益', fmt: (v: any) => fmtPctDash(v), cls: (v: any) => retCls(v) },
]

// ── 对比指标行 ──
const compareMetricRows = computed(() => {
  if (!compareData.value.length) return []
  const rows = [
    { label: '总收益', key: 'total_return', fmt: (v: number) => fmtPct(v), cls: (v: number) => retCls(v) },
    { label: '年化收益', key: 'annual_return', fmt: (v: number) => fmtPct(v), cls: (v: number) => retCls(v) },
    { label: '最大回撤', key: 'max_drawdown', fmt: (v: number) => fmtPct(v), cls: () => 'val-green' },
    { label: '夏普比率', key: 'sharpe_ratio', fmt: (v: number) => fmtNum(v), cls: undefined },
    { label: '索提诺', key: 'sortino_ratio', fmt: (v: number) => fmtNum(v), cls: undefined },
    { label: '胜率', key: 'win_rate', fmt: (v: number) => fmtPct(v, 1), cls: undefined },
    { label: '盈亏比', key: 'profit_loss_ratio', fmt: (v: number) => fmtNum(v), cls: undefined },
    { label: '交易笔数', key: 'trade_count', fmt: (v: number) => String(v || 0), cls: undefined },
  ]
  return rows.map(r => ({
    ...r,
    values: Object.fromEntries(compareData.value.map(p => [p.id, p.metrics?.[r.key] ?? 0]))
  }))
})

// ── 列表选择 ──
function onSelectionChange(rows: any[]) {
  selectedRows.value = rows
}

// ── 导航 ──
function viewDetail(id: number) {
  router.push({ path: '/algo/paper', query: { id: String(id) } })
}
function goBackToList() {
  router.push({ path: '/algo/paper' })
}

// ── 图表 ──
function initNavChart() {
  if (!navChartRef.value || !detailData.value?.nav?.length) return
  if (navChart) { navChart.dispose(); navChart = null }
  navChart = echarts.init(navChartRef.value)
  const nav = detailData.value.nav as any[]
  const dates = nav.map((n: any) => n.date)
  const pointSymbol = nav.length === 1 ? 'circle' : 'none'
  const activeKeys = visibleReturnSeries.value.length
    ? visibleReturnSeries.value
    : ['strategy_return']
  const options = returnSeriesOptions.value
  const activeOptions = options.filter(item => activeKeys.includes(item.key))
  const initial = detailData.value.info?.initial_cash || nav[0]?.total_value || 1
  const fallbackStrategyReturns = nav.map((n: any) => +(((n.total_value ?? initial) / initial - 1) * 100).toFixed(2))
  const series = activeOptions.map(item => ({
    name: item.label,
    type: 'line',
    yAxisIndex: item.yAxisIndex,
    data: nav.map((n: any, index: number) => {
      if (item.key === 'strategy_return') return n.strategy_return ?? fallbackStrategyReturns[index]
      if (item.key === 'benchmark_return') return n.benchmark_return ?? 0
      if (item.key === 'excess_return') return n.excess_return ?? ((n.strategy_return ?? fallbackStrategyReturns[index]) - (n.benchmark_return ?? 0))
      return n.total_value ?? 0
    }),
    symbol: pointSymbol,
    smooth: false,
    lineStyle: { width: item.key === 'total_value' ? 1.5 : 2, color: item.color },
    itemStyle: { color: item.color },
    ...(item.key === 'strategy_return' ? {
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(230,162,60,0.22)' },
          { offset: 1, color: 'rgba(230,162,60,0.01)' },
        ]),
      },
    } : {}),
  }))

  navChart.setOption({
    tooltip: {
      trigger: 'axis',
      formatter(p: any) {
        const d = p[0]?.axisValue
        let h = `<b>${d}</b>`
        p.forEach((s: any) => {
          const option = options.find(item => item.label === s.seriesName)
          const unit = option?.unit || '%'
          const prefix = unit === '%' && s.value >= 0 ? '+' : ''
          h += `<br/>${s.marker} ${s.seriesName}: ${prefix}${s.value}${unit}`
        })
        return h
      },
    },
    legend: { data: activeOptions.map(item => item.label), top: 4, textStyle: { fontSize: 11 } },
    grid: { left: 55, right: 60, top: 42, bottom: 30 },
    dataZoom: [{ type: 'inside', start: 0, end: 100 }],
    xAxis: { type: 'category', data: dates, boundaryGap: false, axisLabel: { fontSize: 10 } },
    yAxis: [
      { type: 'value', name: '收益率', axisLabel: { formatter: '{value}%', fontSize: 10 },
        splitLine: { lineStyle: { type: 'dashed', color: '#eee' } } },
      { type: 'value', name: '总资产', axisLabel: { fontSize: 10 }, splitLine: { show: false } },
    ],
    series,
  })
}

function initCompareChart() {
  if (!compareChartRef.value || !compareData.value.length) return
  const chart = echarts.init(compareChartRef.value)
  const colors = ['#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de', '#3ba272', '#fc8452', '#9a60b4']
  const series = compareData.value.map((p: any, i: number) => {
    const nav = p.nav || []
    if (!nav.length) return null
    const initial = p.initial_cash || nav[0].total_value || 1
    return {
      name: p.name || p.strategy_name, type: 'line', smooth: true,
      data: nav.map((n: any) => [n.date, ((n.total_value / initial - 1) * 100).toFixed(2)]),
      itemStyle: { color: colors[i % colors.length] },
    }
  }).filter(Boolean)
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { top: 0 },
    xAxis: { type: 'category' },
    yAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
    series,
    grid: { left: 60, right: 20, top: 40, bottom: 30 },
  })
}

function stockDisplayName(row: any) {
  const code = String(row?.code || '').trim()
  const name = String(row?.name || '').trim() || stockNameMap.value.get(code) || ''
  return name || code || '--'
}

function directionLabel(trade: any) {
  return trade?.direction === 'buy' ? '买入' : '卖出'
}

function fmtMaybe(v: any, digits = 2) {
  const num = Number(v)
  if (!Number.isFinite(num)) return '--'
  return num.toFixed(digits)
}

function disposeStockCharts() {
  stockDailyChart?.dispose(); stockDailyChart = null
  stockWeeklyChart?.dispose(); stockWeeklyChart = null
  stockMonthlyChart?.dispose(); stockMonthlyChart = null
}

function getStockChartRef(period: string) {
  if (period === 'weekly') return stockWeeklyEl.value
  if (period === 'monthly') return stockMonthlyEl.value
  return stockDailyEl.value
}

function getStockChart(period: string) {
  if (period === 'weekly') return stockWeeklyChart
  if (period === 'monthly') return stockMonthlyChart
  return stockDailyChart
}

function setStockChart(period: string, instance: echarts.ECharts | null) {
  if (period === 'weekly') stockWeeklyChart = instance
  else if (period === 'monthly') stockMonthlyChart = instance
  else stockDailyChart = instance
}

async function openPaperStock(row: any) {
  const code = String(row?.code || '').trim()
  if (!code) return
  selectedStock.value = { code, name: stockDisplayName(row) }
  stockActivePeriod.value = 'daily'
  stockDialogVisible.value = true
  stockLoading.value = true
  stockKlines.value = {}
  disposeStockCharts()
  await nextTick()
  const relatedTrades = (detailData.value?.trades || [])
    .filter((trade: any) => trade.code === code)
    .sort((a: any, b: any) => String(a.date).localeCompare(String(b.date)))
  selectedPaperTrade.value = pickNearestTrade(relatedTrades) || relatedTrades[relatedTrades.length - 1] || null
  try {
    const periods: Array<'daily' | 'weekly' | 'monthly'> = ['daily', 'weekly', 'monthly']
    const results = await Promise.all(periods.map(period => getKlineData({
      code,
      name: stockDisplayName(row),
      period,
    }) as Promise<any>))
    periods.forEach((period, index) => {
      stockKlines.value[period] = results[index]?.data || results[index]
    })
    await nextTick()
    renderActiveStockChart()
  } finally {
    stockLoading.value = false
  }
}

function pickNearestTrade(trades: any[]) {
  if (!trades.length) return null
  const anchor = posHistDate.value || detailData.value?.info?.last_run_date || ''
  if (!anchor) return trades[trades.length - 1]
  const before = trades.filter((trade: any) => String(trade.date) <= anchor)
  return before[before.length - 1] || trades[trades.length - 1]
}

function selectTradeInDialog(row: any) {
  selectedPaperTrade.value = row
  renderActiveStockChart()
}

function renderActiveStockChart() {
  setTimeout(() => renderStockChart(stockActivePeriod.value), 80)
}

function renderStockChart(period: 'daily' | 'weekly' | 'monthly') {
  const el = getStockChartRef(period)
  const kline = stockKlines.value[period]
  if (!el || !kline?.dates?.length) return
  if (el.clientWidth === 0) { setTimeout(() => renderStockChart(period), 120); return }
  getStockChart(period)?.dispose()
  const instance = echarts.init(el)
  setStockChart(period, instance)

  const dates = kline.dates as string[]
  const ohlc = kline.ohlc || []
  const volumes = kline.volumes || []
  const ma = kline.ma || {}
  const boll = kline.boll || {}
  const macd = kline.macd || {}
  const range = stockDataZoomRange(dates)
  const tradeMarkers = buildStockTradeMarkers(kline)
  const overlaySeries = buildOverlaySeries(ma, boll)
  const legendData = ['K线', ...overlaySeries.map(s => s.name), '买入', '卖出']

  // PR-5 自定义指标叠加（仅在当前激活的 period 上注入；其他 period 复用默认空 ext）
  const ext = (period === stockActivePeriod.value) ? ciOverlay.extension.value
    : { mainSignalSeries: null, subPanel: null, extraXAxisCount: 0 }

  instance.on('click', (params: any) => {
    const trade = params?.data?.trade
    if (trade) selectedPaperTrade.value = trade
  })

  instance.setOption({
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      formatter(params: any[]) {
        const points = Array.isArray(params) ? params : [params]
        const scatter = points.find(p => p.seriesType === 'scatter' && p.data?.trade)
        if (scatter) return tradeDetailHtml(scatter.data.trade)
        const first = points[0]
        const index = first?.dataIndex ?? dates.indexOf(first?.axisValue)
        const candle = ohlc[index] || []
        let html = `<b>${first?.axisValue || ''}</b><br/>开: ${fmtMaybe(candle[0])} 收: ${fmtMaybe(candle[1])} 低: ${fmtMaybe(candle[2])} 高: ${fmtMaybe(candle[3])}`
        html += `<br/>MA5: ${fmtMaybe(ma.ma5?.[index])} MA20: ${fmtMaybe(ma.ma20?.[index])} MA30: ${fmtMaybe(ma.ma30?.[index])} MA60: ${fmtMaybe(ma.ma60?.[index])}`
        html += `<br/>BOLL: 上 ${fmtMaybe(boll.upper?.[index])} 中 ${fmtMaybe(boll.middle?.[index])} 下 ${fmtMaybe(boll.lower?.[index])}`
        html += `<br/>RSI14: ${fmtMaybe(kline.rsi?.[index])} MACD柱: ${fmtMaybe(macd.histogram?.[index])}`
        html += `<br/>成交量: ${Number(volumes[index] || 0).toLocaleString()}`
        return html
      },
    },
    legend: { data: legendData, top: 2, textStyle: { fontSize: 11 } },
    title: [
      { text: 'K线主图', subtext: '蜡烛+MA/BOLL叠加，散点为模拟交易记录', left: 60, top: 20, textStyle: { fontSize: 11, color: '#303133', fontWeight: 'bold' as const }, subtextStyle: { fontSize: 9, color: '#909399' }, triggerEvent: true },
      { text: '成交量', subtext: '红涨绿跌·按当日K线方向上色', left: 60, top: 312, textStyle: { fontSize: 11, color: '#303133', fontWeight: 'bold' as const }, subtextStyle: { fontSize: 9, color: '#909399' }, triggerEvent: true },
      { text: 'MACD', subtext: 'DIF/DEA交叉+柱状能量，判趋势强弱', left: 60, top: 402, textStyle: { fontSize: 11, color: '#303133', fontWeight: 'bold' as const }, subtextStyle: { fontSize: 9, color: '#909399' }, triggerEvent: true },
      ...(ext.subPanel ? [{ text: '自定义指标', subtext: '快慢线EMA交叉+策略买卖点(点击查看理由)', left: 60, top: 492, textStyle: { fontSize: 11, color: '#303133', fontWeight: 'bold' as const }, subtextStyle: { fontSize: 9, color: '#909399' }, triggerEvent: true }] : []),
    ],
    grid: [
      { left: 58, right: 38, top: 60, height: 248 },
      { left: 58, right: 38, top: 350, height: 40 },
      { left: 58, right: 38, top: 440, height: 40 },
      ...(ext.subPanel ? [{ left: 58, right: 38, top: 530, height: 60 }] : []),
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: ext.subPanel ? [0, 1, 2, 3] : [0, 1, 2], start: range.start, end: range.end },
      { type: 'slider', xAxisIndex: ext.subPanel ? [0, 1, 2, 3] : [0, 1, 2], start: range.start, end: range.end, bottom: 4, height: 20 },
    ],
    xAxis: [
      { type: 'category', data: dates, boundaryGap: true, axisLabel: { fontSize: 10 } },
      { type: 'category', data: dates, gridIndex: 1, axisLabel: { show: false } },
      { type: 'category', data: dates, gridIndex: 2, axisLabel: { fontSize: 10 } },
      ...(ext.subPanel ? [{ type: 'category' as const, data: dates, gridIndex: 3, axisLabel: { fontSize: 10 } }] : []),
    ],
    yAxis: [
      { scale: true, axisLabel: { fontSize: 10 }, splitLine: { lineStyle: { type: 'dashed', color: '#eee' } } },
      {
        scale: true,
        gridIndex: 1,
        axisLabel: {
          fontSize: 10,
          formatter: (value: number) => {
            if (Math.abs(value) >= 1e8) return (value / 1e8).toFixed(1) + '亿'
            if (Math.abs(value) >= 1e4) return (value / 1e4).toFixed(0) + '万'
            return String(value)
          },
        },
        splitLine: { show: false },
      },
      { scale: true, gridIndex: 2, axisLabel: { fontSize: 10 }, splitLine: { show: false } },
      ...(ext.subPanel ? [{ scale: true, gridIndex: 3, min: 0, max: 100, splitNumber: 3, axisLabel: { fontSize: 10 } }] : []),
    ],
    series: [
      { name: 'K线', type: 'candlestick', data: ohlc, itemStyle: { color: '#f56c6c', color0: '#67c23a', borderColor: '#f56c6c', borderColor0: '#67c23a' } },
      ...overlaySeries,
      { name: '买入', type: 'scatter', data: tradeMarkers.buy, symbol: 'triangle', symbolSize: 18, itemStyle: { color: '#f56c6c', borderColor: '#8a1f11', borderWidth: 1 }, label: tradeMarkerLabel('buy'), emphasis: { scale: 1.5 } },
      { name: '卖出', type: 'scatter', data: tradeMarkers.sell, symbol: 'diamond', symbolSize: 17, itemStyle: { color: '#67c23a', borderColor: '#2f6f1f', borderWidth: 1 }, label: tradeMarkerLabel('sell'), emphasis: { scale: 1.5 } },
      { name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: volumes.map((v: any, i: number) => ({
        value: v,
        itemStyle: { color: (ohlc[i] && Number(ohlc[i][1]) >= Number(ohlc[i][0])) ? '#f56c6c' : '#67c23a' },
      })), barMaxWidth: 8 },
      { name: 'MACD柱', type: 'bar', xAxisIndex: 2, yAxisIndex: 2, data: macd.histogram || [], itemStyle: { color: (p: any) => p.value >= 0 ? '#f56c6c' : '#67c23a' }, barMaxWidth: 8 },
      { name: 'DIF', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: macd.dif || [], symbol: 'none', lineStyle: { width: 1, color: '#e6a23c' } },
      { name: 'DEA', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: macd.dea || [], symbol: 'none', lineStyle: { width: 1, color: '#409eff' } },
      ...(ext.mainSignalSeries ? [{ ...ext.mainSignalSeries, xAxisIndex: 0, yAxisIndex: 0 }] : []),
      ...(ext.subPanel ? ext.subPanel.series.map(s => ({ ...s, xAxisIndex: 3, yAxisIndex: 3 })) : []),
    ],
  })
}

function stockDataZoomRange(dates: string[]) {
  if (!dates.length) return { start: 0, end: 100 }
  const tradeDates = selectedStockTrades.value.map((trade: any) => String(trade.date)).filter(Boolean)
  if (!tradeDates.length) return { start: 0, end: 100 }
  const firstTrade = tradeDates[0]
  const lastTrade = tradeDates[tradeDates.length - 1]
  const firstIdx = dates.findIndex(date => date >= firstTrade)
  const lastRaw = dates.findIndex(date => date >= lastTrade)
  const startIdx = Math.max(0, (firstIdx >= 0 ? firstIdx : 0) - 20)
  const endIdx = Math.min(dates.length - 1, (lastRaw >= 0 ? lastRaw : dates.length - 1) + 20)
  return {
    start: Math.max(0, Math.min(100, startIdx / dates.length * 100)),
    end: Math.max(0, Math.min(100, (endIdx + 1) / dates.length * 100)),
  }
}

function buildOverlaySeries(ma: any, boll: any) {
  const selected = new Set(stockOverlayIndicators.value)
  const series: any[] = []
  if (selected.has('MA5')) series.push({ name: 'MA5', type: 'line', data: ma.ma5 || [], symbol: 'none', lineStyle: { width: 1, color: '#e6a23c' } })
  if (selected.has('MA20')) series.push({ name: 'MA20', type: 'line', data: ma.ma20 || [], symbol: 'none', lineStyle: { width: 1, color: '#409eff' } })
  if (selected.has('MA30')) series.push({ name: 'MA30', type: 'line', data: ma.ma30 || [], symbol: 'none', lineStyle: { width: 1, color: '#7f56d9' } })
  if (selected.has('MA60')) series.push({ name: 'MA60', type: 'line', data: ma.ma60 || [], symbol: 'none', lineStyle: { width: 1, color: '#909399' } })
  if (selected.has('BOLL')) {
    series.push(
      { name: 'BOLL上轨', type: 'line', data: boll.upper || [], symbol: 'none', lineStyle: { width: 1, type: 'dashed', color: '#c45656' } },
      { name: 'BOLL中轨', type: 'line', data: boll.middle || [], symbol: 'none', lineStyle: { width: 1, type: 'dashed', color: '#909399' } },
      { name: 'BOLL下轨', type: 'line', data: boll.lower || [], symbol: 'none', lineStyle: { width: 1, type: 'dashed', color: '#529b2e' } },
    )
  }
  return series
}

function buildStockTradeMarkers(kline: any) {
  const dates = kline.dates || []
  const closeValues = (kline.ohlc || []).map((item: any[]) => item?.[1])
  const buy: any[] = []
  const sell: any[] = []
  selectedStockTrades.value.forEach((trade: any) => {
    const idx = findTradeBarIndex(dates, trade.date)
    if (idx < 0) return
    const point = {
      value: [dates[idx], closeValues[idx]],
      trade,
      name: `${directionLabel(trade)} ${trade.code}`,
    }
    if (trade.direction === 'buy') buy.push(point)
    else sell.push(point)
  })
  return { buy, sell }
}

function findTradeBarIndex(dates: string[], tradeDate: string) {
  if (!dates.length) return -1
  const exact = dates.indexOf(tradeDate)
  if (exact >= 0) return exact
  const idx = dates.findIndex(date => date >= tradeDate)
  return idx >= 0 ? idx : dates.length - 1
}

function tradeMarkerLabel(direction: 'buy' | 'sell') {
  return {
    show: true,
    position: direction === 'buy' ? 'bottom' : 'top',
    distance: 6,
    color: direction === 'buy' ? '#a82116' : '#2f6f1f',
    fontSize: 10,
    fontWeight: 600,
    formatter(params: any) {
      const trade = params?.data?.trade
      if (!trade) return direction === 'buy' ? '买' : '卖'
      return `${direction === 'buy' ? '买' : '卖'} ${fmtMaybe(trade.price)}`
    },
  }
}

function indicatorSnapshot(period: string, trade: any) {
  const kline = stockKlines.value[period]
  if (!kline?.dates?.length || !trade) return {}
  const idx = findTradeBarIndex(kline.dates, trade.date)
  if (idx < 0) return {}
  const candle = kline.ohlc?.[idx] || []
  return {
    date: kline.dates[idx],
    open: candle[0],
    close: candle[1],
    low: candle[2],
    high: candle[3],
    volume: kline.volumes?.[idx],
    ma5: kline.ma?.ma5?.[idx],
    ma20: kline.ma?.ma20?.[idx],
    ma30: kline.ma?.ma30?.[idx],
    ma60: kline.ma?.ma60?.[idx],
    bollUpper: kline.boll?.upper?.[idx],
    bollMiddle: kline.boll?.middle?.[idx],
    bollLower: kline.boll?.lower?.[idx],
    rsi: kline.rsi?.[idx],
    macdDif: kline.macd?.dif?.[idx],
    macdDea: kline.macd?.dea?.[idx],
    macdHist: kline.macd?.histogram?.[idx],
  }
}

function tradeDetailHtml(trade: any) {
  const fee = Number(trade.commission || 0) + Number(trade.tax || 0)
  return `<b>${trade.date} ${directionLabel(trade)} ${trade.code} ${stockDisplayName(trade)}</b>`
    + `<br/>成交价: ${fmtMaybe(trade.price)}`
    + `<br/>数量: ${Number(trade.amount || 0).toLocaleString()}`
    + `<br/>成交额: ${formatMoneyFull(trade.value)}`
    + `<br/>费用: ${fmtMaybe(fee)}`
}

// ── 数据加载 ──
async function loadList() {
  loading.value = true
  try {
    const res = await getPaperTradingList()
    if ((res as any)?.code === 0) paperList.value = (res as any).data
    else if (res.data?.code === 0) paperList.value = res.data.data
  } catch (error) {
    console.error('加载模拟盘列表失败', error)
  } finally { loading.value = false }
}

async function loadStrategies() {
  try {
    try { await request({ url: '/api/strategy/sync_templates', method: 'post' }) } catch { /* ignore */ }
    const res = await getStrategyCodeList() as any
    const d = res?.data || res
    strategies.value = d?.strategies || (Array.isArray(d) ? d : [])
  } catch { /* ignore */ }
}

async function loadStrategyBacktests(strategyId: number) {
  backtestsLoading.value = true
  strategyBacktests.value = []
  try {
    const res = await getPortfolioBacktestList({ strategy_id: strategyId }) as any
    const body = res?.code !== undefined ? res : res.data
    const rows = body?.code === 0 ? (body.data || []) : []
    strategyBacktests.value = rows.filter((bt: any) => (bt.status || '').toLowerCase() === 'completed')
  } catch (error) {
    console.error('加载策略回测版本失败', error)
  } finally {
    backtestsLoading.value = false
  }
}

function openCreateDialog() {
  createForm.value = defaultCreateForm()
  strategyBacktests.value = []
  showCreateDialog.value = true
}

// ── 代码 tab 加载/保存/回测 ──
async function loadStrategyCode() {
  const info = detailData.value?.info
  const sid = info?.strategy_id
  if (!sid) {
    strategyCodeText.value = null
    codeStrategyId.value = null
    return
  }
  codeStrategyId.value = sid
  codeLoading.value = true
  codeDirty.value = false
  codeBtResult.value = null
  codeBtLogs.value = []
  try {
    const res = await getStrategyCodeDetail(sid) as any
    const body = res?.code !== undefined ? res : res.data
    if (body?.code === 0) {
      strategyCodeText.value = body.data?.code || ''
      // 设置默认回测日期
      if (!codeBtStart.value) codeBtStart.value = '2026-03-01'
      if (!codeBtEnd.value) {
        const now = new Date()
        codeBtEnd.value = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
      }
    } else {
      strategyCodeText.value = null
    }
  } catch (e) {
    console.error('加载策略代码失败', e)
    strategyCodeText.value = null
  } finally {
    codeLoading.value = false
  }
}

async function doCodeSave() {
  if (!codeStrategyId.value || !codeDirty.value) return
  codeSaving.value = true
  try {
    const res = await saveStrategyCode({
      id: codeStrategyId.value,
      name: detailData.value?.info?.strategy_name || '未命名',
      code: strategyCodeText.value || '',
    }) as any
    const body = res?.code !== undefined ? res : res.data
    if (body?.code === 0) {
      codeDirty.value = false
      ElMessage.success('策略代码已保存')
    } else {
      ElMessage.error(body?.message || '保存失败')
    }
  } catch (e: any) {
    ElMessage.error('保存失败: ' + (e.message || e))
  } finally {
    codeSaving.value = false
  }
}

async function doCodeBacktest() {
  if (!strategyCodeText.value || !codeStrategyId.value) return
  if (codeDirty.value) await doCodeSave()
  codeRunning.value = true
  codeBtResult.value = null
  codeBtLogs.value = []
  try {
    const res = await startPortfolioBacktest({
      code: strategyCodeText.value,
      strategy_id: codeStrategyId.value,
      start_date: codeBtStart.value || '2024-01-01',
      end_date: codeBtEnd.value || new Date().toISOString().slice(0, 10),
      initial_cash: detailData.value?.info?.initial_cash || 1000000,
    }) as any
    const body = res?.code !== undefined ? res : res.data
    if (body?.code === 0 && body.data?.task_id) {
      const taskId = body.data.task_id
      // SSE log stream
      const evtUrl = `/quantia/api/backtest/portfolio/log_stream?task_id=${taskId}`
      const evtSource = new EventSource(evtUrl)
      activeEvtSources.add(evtSource)
      const cleanupEvt = () => {
        try { evtSource.close() } catch {}
        activeEvtSources.delete(evtSource)
      }
      evtSource.onmessage = (event) => {
        if (event.data) codeBtLogs.value.push(event.data)
      }
      evtSource.addEventListener('done', () => {
        cleanupEvt()
        fetchCodeBtResult(taskId)
      })
      evtSource.addEventListener('error_msg', (e: any) => {
        codeBtLogs.value.push('[错误] ' + (e.data || '回测异常'))
        cleanupEvt()
        codeRunning.value = false
      })
      evtSource.onerror = () => {
        cleanupEvt()
        // fallback: poll
        pollCodeBtResult(taskId)
      }
    } else {
      ElMessage.error(body?.message || '启动回测失败')
      codeRunning.value = false
    }
  } catch (e: any) {
    ElMessage.error('启动回测失败: ' + (e.message || e))
    codeRunning.value = false
  }
}

async function fetchCodeBtResult(taskId: string) {
  try {
    const res = await request({ url: '/api/backtest/portfolio/task_result', method: 'get', params: { task_id: taskId } }) as any
    const body = res?.code !== undefined ? res : res.data
    if (body?.code === 0 && body.data) {
      codeBtResult.value = body.data
    } else {
      codeBtLogs.value.push('[完成] 回测结束，但未获取到结果')
    }
  } catch (e) {
    codeBtLogs.value.push('[错误] 获取回测结果失败')
  } finally {
    codeRunning.value = false
  }
}

async function pollCodeBtResult(taskId: string, attempt = 0) {
  if (attempt > 120) { codeRunning.value = false; return }
  await new Promise(r => setTimeout(r, 2000))
  try {
    const res = await request({ url: '/api/backtest/portfolio/task_result', method: 'get', params: { task_id: taskId } }) as any
    const body = res?.code !== undefined ? res : res.data
    if (body?.code === 0 && body.data?.status === 'completed') {
      codeBtResult.value = body.data
      codeRunning.value = false
    } else if (body?.data?.status === 'failed') {
      codeBtLogs.value.push('[失败] ' + (body.data.error || '回测执行失败'))
      codeRunning.value = false
    } else {
      pollCodeBtResult(taskId, attempt + 1)
    }
  } catch {
    pollCodeBtResult(taskId, attempt + 1)
  }
}

function goEditPage() {
  if (codeStrategyId.value) {
    router.push(`/algo/edit/${codeStrategyId.value}`)
  }
}

function resetSettingsForm() {
  const info = detailData.value?.info
  if (!info) return
  settingsForm.value = {
    name: info.name || '',
    initial_cash: Number(info.initial_cash || 1000000),
    run_frequency: (info.run_frequency || 'daily') as 'daily' | 'hourly' | '15m',
    start_at: info.start_at || info.started_at || formatDateTime(new Date()),
  }
}

async function onCreateStrategyChange(strategyId: number) {
  createForm.value.backtest_id = null
  if (strategyId) await loadStrategyBacktests(strategyId)
}

async function loadDetailData(id: number, resetView = true) {
  detailLoading.value = true
  if (resetView) {
    sideTab.value = 'overview'
    chartTab.value = 'returns'
    detailData.value = null
    // 重置代码 tab 状态
    strategyCodeText.value = null
    codeStrategyId.value = null
    codeDirty.value = false
    codeBtResult.value = null
    codeBtLogs.value = []
  }
  try {
    const res = await getPaperTradingDetail(id, undefined, benchmarkStartMode.value)
    if ((res as any)?.code === 0) detailData.value = (res as any).data
    else if (res.data?.code === 0) detailData.value = res.data.data
    resetSettingsForm()
    // 设置日期选择器为最后运行日期
    if (detailData.value?.info?.last_run_date) {
      posHistDate.value = detailData.value.info.last_run_date
      tradeHistDate.value = detailData.value.info.last_run_date
    } else {
      posHistDate.value = ''
      tradeHistDate.value = ''
    }
    await nextTick()
    initNavChart()
    setTimeout(initNavChart, 120)
  } catch (error) {
    console.error('加载模拟盘详情失败', error)
    if (resetView) detailData.value = null
  } finally { detailLoading.value = false }
}

async function saveSettings() {
  if (!detailId.value) return
  const form = settingsForm.value
  if (!form.name.trim()) { ElMessage.warning('请输入模拟盘名称'); return }
  if (!form.start_at) { ElMessage.warning('请选择开始日期'); return }
  if (!form.initial_cash || form.initial_cash < 10000) { ElMessage.warning('初始资金不能低于 10000'); return }
  settingsSaving.value = true
  try {
    const payload: any = {
      id: detailId.value,
      name: form.name.trim(),
      run_frequency: form.run_frequency,
      start_at: form.start_at,
    }
    if (!paperHasStarted.value) payload.initial_cash = form.initial_cash
    const res = await updatePaperTrading(payload)
    const body = (res as any)?.code !== undefined ? (res as any) : res.data
    if (body?.code === 0) {
      ElMessage.success('设置已保存')
      await loadDetailData(detailId.value, false)
      loadList()
    } else {
      ElMessage.error(body?.msg || '保存失败')
    }
  } finally { settingsSaving.value = false }
}

async function onBenchmarkStartModeChange() {
  if (!detailId.value) return
  await loadDetailData(detailId.value, false)
}

// ── 按日期重新加载持仓 ──
async function reloadPositionsByDate(date: string) {
  if (!detailId.value || !detailData.value) return
  try {
    const res = await getPaperTradingDetail(detailId.value, date, benchmarkStartMode.value)
    const body = (res as any)?.code !== undefined ? (res as any) : res.data
    if (body?.code === 0 && body.data?.positions) {
      detailData.value.positions = body.data.positions
    }
  } catch { /* ignore */ }
}

async function goCompare() {
  if (selectedRows.value.length < 2) return
  showCompare.value = true
  compareLoading.value = true
  try {
    const ids = selectedRows.value.map((r: any) => r.id)
    const res = await getPaperCompare(ids)
    const body = (res as any)?.code !== undefined ? (res as any) : res.data
    if (body?.code === 0) {
      compareData.value = body.data
      await nextTick()
      initCompareChart()
    } else { ElMessage.error(body?.msg || '对比失败') }
  } finally { compareLoading.value = false }
}

async function doAction(id: number, action: 'pause' | 'resume' | 'stop') {
  if (action === 'stop') {
    try { await ElMessageBox.confirm('确定要停止此模拟盘？停止后无法恢复。', '确认') }
    catch { return }
  }
  try {
    const res = await paperTradingAction({ id, action })
    if ((res as any)?.code === 0 || res.data?.code === 0) {
      ElMessage.success('操作成功')
      loadList()
      if (detailId.value === id) loadDetailData(id)
    }
  } catch { /* cancelled */ }
}

async function doRun(id: number) {
  runningId.value = id
  try {
    const res = await runPaperTrading(id)
    const body = (res as any)?.code !== undefined ? (res as any) : res.data
    if (body?.code === 0) {
      ElMessage.success(body.data?.message || '执行完成')
      loadList()
      if (detailId.value === id) loadDetailData(id)
    } else { ElMessage.error(body?.msg || '执行失败') }
  } finally { runningId.value = null }
}

async function doDelete(id: number, name: string) {
  try {
    await ElMessageBox.confirm(
      `确定要删除模拟盘「${name || '模拟盘-' + id}」？删除后数据无法恢复。`,
      '确认删除', { type: 'warning', confirmButtonText: '确定删除', cancelButtonText: '取消' })
    const res = await deletePaperTrading(id)
    const body = (res as any)?.code !== undefined ? (res as any) : res.data
    if (body?.code === 0) {
      ElMessage.success('删除成功')
      loadList()
    } else { ElMessage.error(body?.msg || '删除失败') }
  } catch { /* cancelled */ }
}

async function doCreate() {
  if (!createForm.value.strategy_id) { ElMessage.warning('请选择策略'); return }
  if (!createForm.value.backtest_id) { ElMessage.warning('请选择一个回测版本'); return }
  if (!createForm.value.start_at) { ElMessage.warning('请选择开始时间'); return }
  creating.value = true
  try {
    const res = await createPaperTrading({
      strategy_id: createForm.value.strategy_id,
      backtest_id: createForm.value.backtest_id,
      name: createForm.value.name,
      initial_cash: createForm.value.initial_cash,
      run_frequency: createForm.value.run_frequency,
      start_at: createForm.value.start_at,
    })
    const body = (res as any)?.code !== undefined ? (res as any) : res.data
    if (body?.code === 0) {
      ElMessage.success('模拟盘创建成功')
      showCreateDialog.value = false
      createForm.value = defaultCreateForm()
      strategyBacktests.value = []
      loadList()
    } else { ElMessage.error(body?.msg || '创建失败') }
  } finally { creating.value = false }
}

// ── 路由变化时加载详情 ──
// 支持深链 ?signal_id=<id>：详情加载完成后自动定位到该交易并打开决策详情弹窗，
// 用于通知（钉钉等）中点击"信号详情"后跳过列表直接展示决策依据。
watch(detailId, async (newId) => {
  if (newId) {
    await loadDetailData(newId)
    const sigQ = route.query.signal_id
    const sigId = sigQ ? Number(Array.isArray(sigQ) ? sigQ[0] : sigQ) : null
    if (sigId && Number.isFinite(sigId)) {
      await nextTick()
      const trades = detailData.value?.trades || []
      const row = trades.find((t: any) => Number(t?.signal_id) === sigId)
      if (row) {
        openTradeDecision(row)
      } else {
        ElMessage.warning(`未在该模拟盘中找到信号 #${sigId}，可能该交易已被归档`)
      }
    }
  } else {
    detailData.value = null
  }
}, { immediate: true })

// ── Tab切换后重绘图表 ──
watch(sideTab, async (tab) => {
  if (tab === 'overview' && detailData.value?.nav?.length) {
    await nextTick()
    setTimeout(initNavChart, 80)
  }
  if (tab === 'code' && strategyCodeText.value === null && !codeLoading.value) {
    loadStrategyCode()
  }
})

// ── 持仓日期变化时重新加载持仓数据 ──
watch(posHistDate, (newDate) => {
  if (newDate && detailData.value) {
    reloadPositionsByDate(newDate)
  }
})

onMounted(() => { loadList(); loadStrategies() })
onUnmounted(() => {
  // 关闭所有未完结的 SSE 连接，避免卸载后后台连接泄漏
  for (const es of activeEvtSources) {
    try { es.close() } catch {}
  }
  activeEvtSources.clear()
  if (navChart) { navChart.dispose(); navChart = null }
  disposeStockCharts()
})
</script>

<style scoped>
.paper-trading { padding: 16px 20px; }

/* ── Phase 3 交易决策依据弹窗 ── */
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

/* ── 页面头部 ── */
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.header-left { display: flex; align-items: center; gap: 12px; }
.header-left h2 { margin: 0; font-size: 18px; }
.header-right { display: flex; gap: 8px; }
.count-tag { font-variant-numeric: tabular-nums; }

.paper-create-form :deep(.el-form-item) { margin-bottom: 18px; }
.form-inline-row { display: flex; align-items: center; gap: 10px; width: 100%; min-width: 0; }
.inline-label { color: #606266; white-space: nowrap; }
.form-tip { margin-top: 6px; font-size: 12px; color: #909399; line-height: 1.4; }
.bt-option { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.bt-option-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* ══════ 详情页：聚宽实盘风格 ══════ */
.detail-page { min-height: 500px; }

/* 顶部标题条 */
.jq-detail-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 16px; background: #2196f3; color: #fff; border-radius: 4px 4px 0 0;
}
.jq-detail-title { display: flex; align-items: center; gap: 6px; }
.back-btn { color: #fff !important; padding: 4px; }
.back-btn:hover { background: rgba(255,255,255,0.15); }
.jq-title-text { font-size: 15px; font-weight: 600; }
.jq-title-name { font-size: 13px; color: rgba(255,255,255,0.7); margin-left: 4px; }
.jq-detail-actions { display: flex; gap: 8px; }

/* 顶部指标条 */
.jq-metrics-bar {
  display: flex; align-items: center; gap: 0;
  padding: 12px 20px; background: #fff; border: 1px solid #e4e7ed; border-top: none;
  overflow-x: auto;
}
.jq-metric-cell {
  display: flex; flex-direction: column; align-items: center; gap: 2px;
  padding: 0 18px; flex-shrink: 0;
}
.jq-metric-sep { width: 1px; height: 30px; background: #e4e7ed; flex-shrink: 0; }
.jq-mc-value { font-size: 18px; font-weight: 700; color: #303133; font-variant-numeric: tabular-nums; white-space: nowrap; }
.jq-mc-label { font-size: 11px; color: #909399; white-space: nowrap; }
.jq-metric-more { cursor: pointer; }
.jq-metric-more .jq-mc-value { font-size: 13px; font-weight: 400; color: #606266; }
.jq-metric-more:hover .jq-mc-value { color: #409eff; }

/* 其他指标弹出 */
.jq-extra-metrics { display: flex; flex-direction: column; gap: 8px; }
.jq-em-row { display: flex; justify-content: space-between; font-size: 13px; color: #303133; }
.jq-em-row span:first-child { color: #909399; }

/* 左侧Tab + 内容区 */
.jq-detail-body {
  border: 1px solid #e4e7ed; border-top: none; border-radius: 0 0 4px 4px;
  background: #fff; min-height: 400px;
}
.jq-side-tabs { height: 100%; }
:deep(.jq-side-tabs > .el-tabs__header) {
  width: 64px; background: #f5f7fa; border-right: 1px solid #e4e7ed;
}
:deep(.jq-side-tabs > .el-tabs__header .el-tabs__item) {
  display: flex; flex-direction: column; align-items: center; gap: 2px;
  height: 60px; padding: 8px 0 !important; font-size: 11px; color: #606266;
  justify-content: center;
}
:deep(.jq-side-tabs > .el-tabs__header .el-tabs__item .el-icon) { font-size: 18px; }
:deep(.jq-side-tabs > .el-tabs__header .el-tabs__item.is-active) {
  color: #409eff; background: #fff; font-weight: 600;
}
:deep(.jq-side-tabs > .el-tabs__content) { padding: 0; flex: 1; }
:deep(.jq-side-tabs > .el-tabs__content .el-tab-pane) { padding: 0; }

/* 代码Tab图标 */
.code-tab-icon {
  font-size: 14px; font-weight: 700; font-family: monospace;
  line-height: 20px; display: block;
}

/* 内容区段 */
.jq-section { padding: 16px 20px; }
.jq-section + .jq-section { border-top: 1px solid #f0f0f0; }
.jq-section-header {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 12px;
}
.jq-section-title { font-size: 14px; font-weight: 600; color: #303133; }
.jq-section-actions { display: flex; align-items: center; gap: 12px; }
.jq-export-link { font-size: 12px; color: #409eff; cursor: pointer; }
.jq-export-link:hover { text-decoration: underline; }
.jq-date-label { font-size: 12px; color: #909399; white-space: nowrap; }

/* 列筛选复选框 */
.jq-col-filter {
  display: flex; flex-wrap: wrap; gap: 4px 12px;
  padding: 8px 0; margin-bottom: 8px; border-bottom: 1px solid #f0f0f0;
}
:deep(.jq-col-filter .el-checkbox) { margin-right: 0; height: auto; }
:deep(.jq-col-filter .el-checkbox__label) { font-size: 12px; padding-left: 4px; }

/* 图表空态 */
.jq-empty-chart {
  display: flex; align-items: center; justify-content: center;
  height: 280px; color: #909399; font-size: 14px;
}
.jq-inner-tabs { margin: 0; }
:deep(.jq-inner-tabs .el-tabs__header) { margin-bottom: 8px; }
.jq-chart-toolbar {
  display: flex; align-items: center; justify-content: flex-end; gap: 8px; flex-wrap: wrap;
  min-height: 30px; margin: -2px 0 8px;
}
:deep(.jq-chart-toolbar .el-checkbox-button__inner),
:deep(.jq-chart-toolbar .el-radio-button__inner) {
  padding: 5px 10px; font-size: 12px;
}

/* 统计指标网格 */
.jq-stats-grid {
  display: grid; grid-template-columns: repeat(5, 1fr); gap: 16px;
}
.jq-stat-card {
  display: flex; flex-direction: column; gap: 4px;
  padding: 14px; background: #f9fafb; border-radius: 6px; border: 1px solid #ebeef5;
}
.jq-stat-label { font-size: 12px; color: #909399; }
.jq-stat-value { font-size: 16px; font-weight: 600; color: #303133; font-variant-numeric: tabular-nums; }

/* 日志 */
.jq-log-area { max-height: 500px; overflow-y: auto; }
.jq-log-entry {
  display: flex; gap: 12px; padding: 6px 0; font-size: 13px; color: #303133;
  border-bottom: 1px solid #f5f5f5;
}
.jq-exec-log-entry {
  display: flex; align-items: center; gap: 8px; padding: 8px 0; font-size: 13px; color: #303133;
  border-bottom: 1px solid #f5f5f5;
}
.jq-exec-log-msg { flex: 1; color: #606266; }
.jq-exec-log-extra { color: #909399; font-size: 12px; }
.jq-exec-log-time { color: #c0c4cc; font-size: 12px; flex-shrink: 0; }
.jq-section-title { font-size: 14px; font-weight: 600; color: #303133; margin-bottom: 10px; }
.jq-log-date { color: #909399; flex-shrink: 0; }
.jq-log-empty { padding: 40px; text-align: center; color: #909399; }

/* 设置 */
.jq-settings-form { max-width: 620px; }
.settings-inline-control { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.settings-help { color: #909399; font-size: 12px; }
.jq-readonly-value { color: #303133; font-weight: 500; }

/* ── 颜色 ── */
.val-red { color: #f56c6c !important; }
.val-green { color: #67c23a !important; }

/* ── 列表表格 ── */
.jq-table { margin-top: 4px; }
.jq-name-link { color: #409eff; cursor: pointer; font-weight: 500; }
.jq-name-link:hover { text-decoration: underline; }
.jq-status-running { color: #67c23a; font-weight: 500; }
.jq-status-paused { color: #e6a23c; font-weight: 500; }
.jq-status-stopped { color: #909399; }

/* ── 操作列 ── */
.jq-ops { display: flex; align-items: center; justify-content: center; gap: 4px; white-space: nowrap; }
.jq-op { color: #409eff; cursor: pointer; font-size: 13px; text-decoration: none; }
.jq-op:hover { text-decoration: underline; }
.jq-op-sep { color: #dcdfe6; font-size: 12px; margin: 0 1px; user-select: none; }
.jq-op-danger { color: #f56c6c; }
.jq-op-danger:hover { color: #f78989; }
.jq-op-primary { color: #409eff; }
.jq-op-disabled { color: #c0c4cc !important; cursor: not-allowed; pointer-events: none; }

/* ── 个股K线弹窗 ── */
.stock-name-link { max-width: 92px; overflow: hidden; text-overflow: ellipsis; vertical-align: middle; }
.stock-dialog { min-height: 620px; }
.stock-summary {
  display: grid; grid-template-columns: repeat(5, minmax(120px, 1fr)); gap: 8px;
  margin-bottom: 12px;
}
.summary-item {
  display: flex; flex-direction: column; gap: 3px;
  padding: 8px 10px; border: 1px solid #ebeef5; border-radius: 6px; background: #f9fafb;
  min-width: 0;
}
.summary-item.wide { grid-column: span 2; }
.summary-item span { color: #909399; font-size: 12px; }
.summary-item b { color: #303133; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.stock-toolbar {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  padding: 10px 0; border-top: 1px solid #f0f0f0; border-bottom: 1px solid #f0f0f0;
  margin-bottom: 10px;
}
.toolbar-label { font-size: 12px; color: #606266; font-weight: 600; }
.toolbar-hint { color: #909399; font-size: 12px; }
.stock-chart-box { height: 520px; width: 100%; }
.stock-chart-box.has-sub { height: 640px; }
.indicator-panel { margin: 12px 0; }
.panel-title { font-size: 13px; font-weight: 600; color: #303133; margin-bottom: 8px; }
.stock-trade-table { margin-top: 12px; }

@media (max-width: 900px) {
  .stock-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .summary-item.wide { grid-column: span 2; }
}

/* ── 代码 tab ── */
.code-section { padding: 0 !important; }
.code-toolbar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 12px; border-bottom: 1px solid #ebeef5; background: #fafafa;
  flex-wrap: wrap; gap: 6px;
}
.code-toolbar-left { display: flex; align-items: center; gap: 8px; }
.code-toolbar-right { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
.code-strategy-name { font-size: 13px; font-weight: 600; color: #303133; }
.code-dirty-hint { color: #e6a23c; font-size: 12px; margin-left: 4px; }
.code-loading { display: flex; align-items: center; justify-content: center; }
.code-empty { text-align: center; padding: 60px 20px; }
.paper-code-editor {
  display: block; width: 100%; min-height: 420px; max-height: 65vh;
  padding: 12px 14px; margin: 0; border: none; outline: none; resize: vertical;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 13px; line-height: 1.6; tab-size: 4;
  background: #1e1e1e; color: #d4d4d4;
  overflow: auto; white-space: pre;
}
.paper-code-editor:focus { box-shadow: inset 0 0 0 1px #409eff; }
.code-bt-result {
  border-top: 1px solid #ebeef5; padding: 12px 14px;
}
.code-bt-header {
  display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;
}
.code-bt-title { font-size: 13px; font-weight: 600; color: #303133; }
.code-bt-metrics {
  display: flex; gap: 20px; flex-wrap: wrap; margin-bottom: 8px;
}
.code-bt-metric { display: flex; flex-direction: column; gap: 2px; }
.code-bt-metric .label { font-size: 11px; color: #909399; }
.code-bt-metric .value { font-size: 14px; font-weight: 600; color: #303133; }
.code-bt-logs {
  max-height: 180px; overflow-y: auto; background: #1e1e1e; color: #d4d4d4;
  font-family: 'Consolas', monospace; font-size: 11px; line-height: 1.5;
  padding: 8px 10px; border-radius: 4px; margin-top: 8px;
}
.code-bt-log { white-space: pre-wrap; word-break: break-all; }
</style>
