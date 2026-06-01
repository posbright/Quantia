#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os.path
import sys
import threading
from abc import ABC

import tornado.escape
import tornado.httpserver
import tornado.ioloop
import tornado.options
import tornado.web
from tornado import gen

# 在项目运行时，临时将项目路径添加到环境变量
cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)
try:
    from quantia.lib.log_config import setup_logging
    setup_logging('web')
except Exception:
    log_path = os.path.join(cpath_current, 'log')
    os.makedirs(log_path, exist_ok=True)
    logging.basicConfig(
        format='%(asctime)s [%(levelname)s] %(message)s',
        filename=os.path.join(log_path, 'stock_web.log'),
        level=logging.WARNING,
    )
import quantia.lib.torndb as torndb
import quantia.lib.database as mdb
import quantia.lib.envconfig as _cfg
import quantia.lib.version as version
import quantia.web.dataTableHandler as dataTableHandler
import quantia.web.dataIndicatorsHandler as dataIndicatorsHandler
import quantia.web.strategyParamsHandler as strategyParamsHandler
import quantia.web.backtestHandler as backtestHandler
import quantia.web.backtestDashboardHandler as backtestDashboardHandler
import quantia.web.klineHandler as klineHandler
import quantia.web.portfolioBacktestHandler as portfolioBacktestHandler
import quantia.web.paperTradingHandler as paperTradingHandler
import quantia.web.tradeSignalHandler as tradeSignalHandler
import quantia.web.notificationAdminHandler as notificationAdminHandler
import quantia.web.notificationConfigHandler as notificationConfigHandler
import quantia.web.aiDecisionConfigHandler as aiDecisionConfigHandler
import quantia.web.aiAssistantHandler as aiAssistantHandler
import quantia.web.aiTokenUsageHandler as aiTokenUsageHandler
import quantia.web.stockReportHandler as stockReportHandler
import quantia.web.stockPatentHandler as stockPatentHandler
import quantia.web.imCommandHandler as imCommandHandler
import quantia.web.liveTradingHandler as liveTradingHandler
import quantia.web.customIndicatorHandler as customIndicatorHandler
import quantia.web.authHandler as authHandler
import quantia.web.verifyOptimizeHandler as verifyOptimizeHandler
import quantia.web.verifyFusionHandler as verifyFusionHandler
import quantia.web.factorLabHandler as factorLabHandler
import quantia.web.fundRankHandler as fundRankHandler
import quantia.web.fundPeerCompareHandler as fundPeerCompareHandler
import quantia.web.fundCompositeAnalysisHandler as fundCompositeAnalysisHandler
import quantia.web.stockFinancialHandler as stockFinancialHandler
import quantia.web.base as webBase

__author__ = 'Quantia'
__date__ = '2026/02/14'


class RobotsTxtHandler(tornado.web.RequestHandler, ABC):
    """返回 robots.txt，避免搜索引擎爬虫产生大量 404 日志"""
    def get(self):
        self.set_header("Content-Type", "text/plain")
        self.write("User-agent: *\nDisallow: /quantia/\nDisallow: /api/\n")


class Application(tornado.web.Application):
    def __init__(self):
        static_path = os.path.join(os.path.dirname(__file__), "static")
        handlers = [
            # ── robots.txt（避免搜索引擎爬虫产生大量 404 日志） ──
            (r"/robots\.txt", RobotsTxtHandler),
            # ── JSON API 路由（Vue SPA 通过 AJAX 调用）──
            (r"/quantia/api_data", dataTableHandler.GetStockDataHandler),
            (r"/quantia/api/trade_date", dataTableHandler.GetTradeDateHandler),
            # 获得股票指标数据（Bokeh 图表API，返回 HTML 片段）
            (r"/quantia/data/indicators", dataIndicatorsHandler.GetDataIndicatorsHandler),
            # 加入关注
            (r"/quantia/control/attention", dataIndicatorsHandler.SaveCollectHandler),
            # 策略参数管理
            (r"/quantia/api/strategy/params", strategyParamsHandler.GetStrategyParamsHandler),
            (r"/quantia/api/strategy/params/save", strategyParamsHandler.SaveStrategyParamsHandler),
            (r"/quantia/api/strategy/params/reset", strategyParamsHandler.ResetStrategyParamsHandler),
            (r"/quantia/api/strategy/params/history", strategyParamsHandler.GetParamsHistoryHandler),
            (r"/quantia/api/strategy/params/diff", strategyParamsHandler.GetParamsDiffHandler),
            (r"/quantia/api/strategy/filter", strategyParamsHandler.FilterStocksHandler),
            # K线数据JSON API
            (r"/quantia/api/kline", klineHandler.GetKlineDataHandler),
            # 股票财务数据
            (r"/quantia/api/stock/financial_summary", stockFinancialHandler.StockFinancialSummaryHandler),
            # 回测验证
            (r"/quantia/api/backtest/config", backtestHandler.GetBacktestConfigHandler),
            (r"/quantia/api/backtest/run", backtestHandler.RunBacktestHandler),
            (r"/quantia/api/backtest/batch", backtestHandler.RunBatchBacktestHandler),
            # 回测看板
            (r"/quantia/api/backtest/dashboard/overview", backtestDashboardHandler.DashboardOverviewHandler),
            (r"/quantia/api/backtest/dashboard/strategy_detail", backtestDashboardHandler.StrategyDetailHandler),
            (r"/quantia/api/backtest/dashboard/distribution", backtestDashboardHandler.ReturnDistributionHandler),
            (r"/quantia/api/backtest/dashboard/timeline", backtestDashboardHandler.PerformanceTimelineHandler),
            (r"/quantia/api/backtest/dashboard/trade_pairs", backtestDashboardHandler.TradePairHandler),
            # 组合回测 & 策略管理
            (r"/quantia/api/strategy/code", portfolioBacktestHandler.SaveStrategyCodeHandler),
            (r"/quantia/api/strategy/code/list", portfolioBacktestHandler.GetStrategyCodeListHandler),
            (r"/quantia/api/strategy/code/detail", portfolioBacktestHandler.GetStrategyCodeDetailHandler),
            (r"/quantia/api/strategy/code/delete", portfolioBacktestHandler.DeleteStrategyCodeHandler),
            (r"/quantia/api/strategy/templates", portfolioBacktestHandler.GetStrategyTemplatesHandler),
            (r"/quantia/api/strategy/sync_templates", portfolioBacktestHandler.SyncStrategyTemplatesHandler),
            (r"/quantia/api/backtest/portfolio/run", portfolioBacktestHandler.RunPortfolioBacktestHandler),
            (r"/quantia/api/backtest/portfolio/start", portfolioBacktestHandler.StartPortfolioBacktestHandler),
            (r"/quantia/api/backtest/portfolio/log_stream", portfolioBacktestHandler.BacktestLogStreamHandler),
            (r"/quantia/api/backtest/portfolio/task_result", portfolioBacktestHandler.BacktestTaskResultHandler),
            (r"/quantia/api/backtest/portfolio/list", portfolioBacktestHandler.GetPortfolioBacktestListHandler),
            (r"/quantia/api/backtest/portfolio/detail", portfolioBacktestHandler.GetPortfolioBacktestDetailHandler),
            (r"/quantia/api/backtest/portfolio/compare", portfolioBacktestHandler.GetBacktestCompareHandler),
            (r"/quantia/api/backtest/portfolio/delete", portfolioBacktestHandler.DeleteBacktestHandler),
            (r"/quantia/api/backtest/portfolio/list_page", portfolioBacktestHandler.GetPortfolioBacktestListPageHandler),
            # 策略文件夹管理
            (r"/quantia/api/strategy/folder/create", portfolioBacktestHandler.CreateFolderHandler),
            (r"/quantia/api/strategy/folder/rename", portfolioBacktestHandler.RenameFolderHandler),
            (r"/quantia/api/strategy/folder/delete", portfolioBacktestHandler.DeleteFolderHandler),
            # 策略批量操作
            (r"/quantia/api/strategy/move", portfolioBacktestHandler.MoveStrategyHandler),
            (r"/quantia/api/strategy/batch_delete", portfolioBacktestHandler.BatchDeleteStrategyHandler),
            (r"/quantia/api/strategy/rename", portfolioBacktestHandler.RenameStrategyHandler),
            # 模拟交易
            (r"/quantia/api/paper/create", paperTradingHandler.CreatePaperTradingHandler),
            (r"/quantia/api/paper/action", paperTradingHandler.PaperTradingActionHandler),
            (r"/quantia/api/paper/update", paperTradingHandler.UpdatePaperTradingHandler),
            (r"/quantia/api/paper/list", paperTradingHandler.GetPaperTradingListHandler),
            (r"/quantia/api/paper/detail", paperTradingHandler.GetPaperTradingDetailHandler),
            (r"/quantia/api/paper/run", paperTradingHandler.RunPaperTradingHandler),
            (r"/quantia/api/paper/execution_log", paperTradingHandler.GetPaperExecutionLogHandler),
            # Phase 3: 交易信号/决策/指标快照/候选筛选快照统一详情（回测与模拟交易复用）
            (r"/quantia/api/trade/signal/list", tradeSignalHandler.GetTradeSignalListHandler),
            (r"/quantia/api/trade/signal/detail", tradeSignalHandler.GetTradeSignalDetailHandler),
            # Phase 3 扩展：通知事件后台查看（钉钉发送记录、payload、错误信息）
            (r"/quantia/api/notification/event/list", notificationAdminHandler.GetNotificationEventListHandler),
            (r"/quantia/api/notification/event/detail", notificationAdminHandler.GetNotificationEventDetailHandler),
            # Phase 5: 通知配置 CRUD + 测试发送 + 单事件重试（仅引用环境变量名，不存密钥明文）
            (r"/quantia/api/notification/config/list", notificationConfigHandler.GetNotificationConfigListHandler),
            (r"/quantia/api/notification/config/detail", notificationConfigHandler.GetNotificationConfigDetailHandler),
            (r"/quantia/api/notification/config/save", notificationConfigHandler.SaveNotificationConfigHandler),
            (r"/quantia/api/notification/config/delete", notificationConfigHandler.DeleteNotificationConfigHandler),
            (r"/quantia/api/notification/config/test_send", notificationConfigHandler.TestSendNotificationHandler),
            (r"/quantia/api/notification/event/retry", notificationConfigHandler.RetryNotificationEventHandler),
            # Phase 5: AI 决策配置 CRUD（前端调整 prompt/阈值/数据包范围；密钥仅引用环境变量名）
            (r"/quantia/api/ai/config/list", aiDecisionConfigHandler.GetAIDecisionConfigListHandler),
            (r"/quantia/api/ai/config/detail", aiDecisionConfigHandler.GetAIDecisionConfigDetailHandler),
            (r"/quantia/api/ai/config/save", aiDecisionConfigHandler.SaveAIDecisionConfigHandler),
            (r"/quantia/api/ai/config/delete", aiDecisionConfigHandler.DeleteAIDecisionConfigHandler),
            # M2: AI 策略生成助手（lib/ai 统一服务层）
            (r"/quantia/api/ai/strategy/generate", aiAssistantHandler.GenerateStrategyHandler),
            (r"/quantia/api/ai/strategy/generate/stream", aiAssistantHandler.GenerateStrategyStreamHandler),
            (r"/quantia/api/ai/strategy/refine", aiAssistantHandler.RefineStrategyHandler),
            (r"/quantia/api/ai/strategy/repair", aiAssistantHandler.RepairStrategyHandler),
            (r"/quantia/api/ai/chat", aiAssistantHandler.ChatHandler),
            # M5: provider/model/agent 元数据（前端 picker 使用）
            (r"/quantia/api/ai/config", aiAssistantHandler.GetAiConfigHandler),
            (r"/quantia/api/ai/agents", aiAssistantHandler.ListAiAgentsHandler),
            (r"/quantia/api/ai/agents/manage", aiAssistantHandler.AiAgentsManageHandler),
            (r"/quantia/api/ai/agents/detail", aiAssistantHandler.AiAgentDetailHandler),
            # M8: 多轮会话记忆
            (r"/quantia/api/ai/conversations", aiAssistantHandler.AiConversationsHandler),
            (r"/quantia/api/ai/conversations/detail", aiAssistantHandler.AiConversationDetailHandler),
            (r"/quantia/api/ai/conversations/rename", aiAssistantHandler.AiConversationRenameHandler),
            # Token 用量统计 + 功能开关
            (r"/quantia/api/ai/token/summary", aiTokenUsageHandler.TokenSummaryHandler),
            (r"/quantia/api/ai/token/by_model", aiTokenUsageHandler.TokenByModelHandler),
            (r"/quantia/api/ai/token/by_scene", aiTokenUsageHandler.TokenBySceneHandler),
            (r"/quantia/api/ai/token/daily_trend", aiTokenUsageHandler.TokenDailyTrendHandler),
            (r"/quantia/api/ai/token/feature_status", aiTokenUsageHandler.TokenFeatureStatusHandler),
            (r"/quantia/api/ai/token/recent_calls", aiTokenUsageHandler.TokenRecentCallsHandler),
            (r"/quantia/api/ai/token/update_feature", aiTokenUsageHandler.TokenUpdateFeatureHandler),
            # AI 个股分析报告
            (r"/quantia/api/ai/report/generate", stockReportHandler.StockReportGenerateHandler),
            (r"/quantia/api/ai/report/followup", stockReportHandler.StockReportFollowupHandler),
            (r"/quantia/api/ai/report/feedback", stockReportHandler.StockReportFeedbackHandler),
            (r"/quantia/api/ai/report/history", stockReportHandler.StockReportHistoryHandler),
            (r"/quantia/api/ai/report/detail", stockReportHandler.StockReportDetailHandler),
            (r"/quantia/api/ai/report/search_stock", stockReportHandler.StockSearchHandler),
            (r"/quantia/api/ai/report/stock_data", stockReportHandler.StockDataFallbackHandler),
            (r"/quantia/api/ai/report/attention_list", stockReportHandler.StockReportAttentionListHandler),
            (r"/quantia/api/ai/report/batch_summary", stockReportHandler.StockReportBatchHandler),
            (r"/quantia/api/ai/report/score_history", stockReportHandler.StockScoreHistoryHandler),
            (r"/quantia/api/ai/report/timeline", stockReportHandler.StockReportTimelineHandler),
            (r"/quantia/api/ai/report/share", stockReportHandler.StockReportShareHandler),
            (r"/quantia/api/ai/report/shared/([a-f0-9\-]{36})", stockReportHandler.StockReportSharedViewHandler),
            (r"/quantia/api/ai/report/compare", stockReportHandler.StockReportCompareHandler),
            (r"/quantia/api/ai/report/preference", stockReportHandler.StockReportPreferenceHandler),
            (r"/quantia/api/ai/report/translate", stockReportHandler.StockReportTranslateHandler),
            (r"/quantia/api/ai/report/speech_text", stockReportHandler.StockReportSpeechTextHandler),
            (r"/quantia/api/ai/report/industry_percentile", stockReportHandler.StockIndustryPercentileHandler),
            # Phase 3a / 4: 专利数据查询 (cn_stock_patents)
            (r"/quantia/api/stock/patents", stockPatentHandler.StockPatentsHandler),
            (r"/quantia/api/stock/patents/history", stockPatentHandler.StockPatentsHistoryHandler),
            (r"/quantia/api/stock/patents/compare", stockPatentHandler.StockPatentsCompareHandler),
            # Phase 6: IM 指令确认（默认关闭，由 QUANTIA_IM_COMMAND_ENABLED=1 启用；仅落库 trade_command，不直接调券商）
            (r"/quantia/api/im/status", imCommandHandler.IMStatusHandler),
            (r"/quantia/api/im/dingtalk/callback", imCommandHandler.DingtalkCallbackHandler),
            (r"/quantia/api/im/command/list", imCommandHandler.ListTradeCommandsHandler),
            (r"/quantia/api/im/command/detail", imCommandHandler.GetTradeCommandDetailHandler),
            (r"/quantia/api/im/operator/list", imCommandHandler.ListOperatorsHandler),
            (r"/quantia/api/im/operator/save", imCommandHandler.SaveOperatorHandler),
            (r"/quantia/api/im/operator/delete", imCommandHandler.DeleteOperatorHandler),
            # Phase 7: 实盘交易连接（默认关闭，由 QUANTIA_LIVE_TRADING_ENABLED=1 启用；默认 broker=dry_run）
            (r"/quantia/api/live/status", liveTradingHandler.LiveStatusHandler),
            (r"/quantia/api/live/execute_pending", liveTradingHandler.ExecutePendingCommandsHandler),
            # Phase 8: 鉴权（默认关闭，由 QUANTIA_AUTH_ENABLED=1 启用；未启用时 /me 返回 enabled:false）
            (r"/quantia/api/auth/login", authHandler.LoginHandler),
            (r"/quantia/api/auth/logout", authHandler.LogoutHandler),
            (r"/quantia/api/auth/me", authHandler.MeHandler),
            # 自助注册（公开端点，受 QUANTIA_REGISTER_ENABLED 控制，默认开启）
            (r"/quantia/api/auth/register/send-code", authHandler.SendRegisterCodeHandler),
            (r"/quantia/api/auth/register", authHandler.RegisterHandler),
            # Phase 8 Should 8：用户管理（仅 admin）
            (r"/quantia/api/auth/users/list", authHandler.ListUsersHandler),
            (r"/quantia/api/auth/users/save", authHandler.SaveUserHandler),
            (r"/quantia/api/auth/users/delete", authHandler.DeleteUserHandler),
            # Phase 8 Should 7：审计聚合（admin/operator 可读）
            (r"/quantia/api/auth/audit/list", authHandler.AuditListHandler),
            (r"/quantia/api/paper/compare", paperTradingHandler.GetPaperCompareHandler),
            (r"/quantia/api/paper/delete", paperTradingHandler.DeletePaperTradingHandler),
            # Phase 9: 自定义综合指标 CRUD + 回测 + 关注榜 + K 线叠加序列
            (r"/quantia/api/custom_indicator/list", customIndicatorHandler.ListCustomIndicatorHandler),
            (r"/quantia/api/custom_indicator/detail", customIndicatorHandler.GetCustomIndicatorHandler),
            (r"/quantia/api/custom_indicator/save", customIndicatorHandler.SaveCustomIndicatorHandler),
            (r"/quantia/api/custom_indicator/delete", customIndicatorHandler.DeleteCustomIndicatorHandler),
            (r"/quantia/api/custom_indicator/backtest", customIndicatorHandler.BacktestCustomIndicatorHandler),
            (r"/quantia/api/custom_indicator/watchlist", customIndicatorHandler.WatchlistTodayHandler),
            (r"/quantia/api/custom_indicator/series", customIndicatorHandler.IndicatorSeriesHandler),
            # Phase 10: 选股验证中心 — 优化分析（只读）
            (r"/quantia/api/verify/strategy_list", verifyOptimizeHandler.VerifyStrategyListHandler),
            (r"/quantia/api/verify/holding_period", verifyOptimizeHandler.HoldingPeriodAnalysisHandler),
            (r"/quantia/api/verify/custom_compare", verifyOptimizeHandler.CustomStrategyCompareHandler),
            (r"/quantia/api/verify/custom_return_series", verifyOptimizeHandler.CustomStrategyReturnSeriesHandler),
            (r"/quantia/api/verify/signal_quality", verifyOptimizeHandler.SignalQualityHandler),
            (r"/quantia/api/verify/sl_tp_matrix", verifyOptimizeHandler.StopLossTakeProfitMatrixHandler),
            (r"/quantia/api/verify/market_regime", verifyOptimizeHandler.MarketRegimeHandler),
            (r"/quantia/api/verify/signal_decay", verifyOptimizeHandler.SignalDecayHandler),
            (r"/quantia/api/verify/cost_sensitivity", verifyOptimizeHandler.CostSensitivityHandler),
            (r"/quantia/api/verify/exit_compare", verifyOptimizeHandler.ExitCompareHandler),
            (r"/quantia/api/verify/return_series", verifyOptimizeHandler.SignalReturnSeriesHandler),
            (r"/quantia/api/verify/fusion", verifyFusionHandler.StrategyFusionHandler),
            (r"/quantia/api/verify/fusion_export", verifyFusionHandler.FusionExportCodeHandler),
            (r"/quantia/api/verify/fusion_scheme", verifyFusionHandler.FusionSchemeSaveHandler),
            (r"/quantia/api/verify/fusion_scheme/list", verifyFusionHandler.FusionSchemeListHandler),
            (r"/quantia/api/verify/fusion_scheme/(\d+)", verifyFusionHandler.FusionSchemeDeleteHandler),
            (r"/quantia/api/verify/optimize_suggest", verifyFusionHandler.OptimizeSuggestHandler),
            # ── 因子实验室 ──
            (r"/quantia/api/factor_lab/factors", factorLabHandler.FactorCatalogHandler),
            (r"/quantia/api/factor_lab/run", factorLabHandler.FactorLabRunHandler),
            (r"/quantia/api/factor_lab/factor_impact", factorLabHandler.FactorImpactHandler),
            (r"/quantia/api/factor_lab/presets", factorLabHandler.FactorPresetsHandler),
            (r"/quantia/api/factor_lab/save", factorLabHandler.FactorLabSaveHandler),
            (r"/quantia/api/factor_lab/my_configs", factorLabHandler.FactorLabConfigsHandler),
            (r"/quantia/api/factor_lab/configs/(\d+)", factorLabHandler.FactorLabDeleteConfigHandler),
            (r"/quantia/api/factor_lab/export_code", factorLabHandler.FactorLabExportCodeHandler),
            # ── 场外基金排名（F6 方案 A）+ 同类评比 F11 + 综合分析 F13 ──
            (r"/quantia/api/fund/rank/meta", fundRankHandler.FundRankMetaHandler),
            (r"/quantia/api/fund/rank", fundRankHandler.FundRankHandler),
            (r"/quantia/api/fund/peer_compare", fundPeerCompareHandler.FundPeerCompareHandler),
            (r"/quantia/api/fund/composite_analysis", fundCompositeAnalysisHandler.FundCompositeAnalysisHandler),
            # ── 性能监控（前端 web-vitals 上报，仅接收不处理）──
            (r"/quantia/api/metric/web_vitals", WebVitalsHandler),
            # ── Vue SPA 路由 ──
            # 静态资源（assets/）
            (r"/assets/(.*)", tornado.web.StaticFileHandler, {"path": os.path.join(static_path, "assets")}),
            # 所有非 API 路径 fallback 到 Vue SPA 的 index.html（支持前端路由）
            (r"/(.*)", SPAHandler, {"static_path": static_path}),
        ]
        settings = dict(  # 配置
            template_path=os.path.join(os.path.dirname(__file__), "templates"),
            static_path=static_path,
            xsrf_cookies=False,  # True,
            # cookie加密：优先 env QUANTIA_SESSION_SECRET（生产部署必须固化）；
            # 未设置时退回历史硬编码值，保持向后兼容。
            cookie_secret=os.getenv(
                "QUANTIA_SESSION_SECRET",
                "027bb1b670eddf0392cdda8709268a17b58b7",
            ),
            debug=False,
        )
        super(Application, self).__init__(handlers, **settings)
        # Have one global connection to the blog DB across all handlers
        try:
            self.db = torndb.Connection(**mdb.MYSQL_CONN_TORNDB)
        except Exception as e:
            logging.warning(f"数据库连接失败，部分功能不可用: {e}")
            self.db = None


class WebVitalsHandler(tornado.web.RequestHandler):
    """接收前端 web-vitals 性能上报，仅返回 204 不做处理。"""

    def post(self):
        self.set_status(204)
        self.finish()


class SPAHandler(tornado.web.RequestHandler, ABC):
    """Vue SPA 的 fallback handler：所有非 API 路径都返回 index.html"""

    def initialize(self, static_path):
        self.spa_path = static_path

    @gen.coroutine
    def get(self, path=""):
        # 如果请求的是一个实际存在的静态文件，直接返回
        full_path = os.path.join(self.spa_path, path)
        # 安全检查：防止路径遍历攻击（如 ../../etc/passwd）
        real_spa = os.path.realpath(self.spa_path)
        real_full = os.path.realpath(full_path)
        if not real_full.startswith(real_spa + os.sep) and real_full != real_spa:
            self.set_status(403)
            self.write("Forbidden")
            return
        if path and os.path.isfile(full_path):
            # 根据扩展名设置 Content-Type
            import mimetypes
            content_type, _ = mimetypes.guess_type(full_path)
            if content_type:
                self.set_header("Content-Type", content_type)
            with open(full_path, "rb") as f:
                self.write(f.read())
            return
        # 否则返回 Vue SPA 的 index.html（前端路由处理）
        index_path = os.path.join(self.spa_path, "index.html")
        with open(index_path, "r", encoding="utf-8") as f:
            self.write(f.read())


def _sync_strategy_templates_in_background():
    try:
        sync_result = portfolioBacktestHandler.sync_strategy_templates_to_db()
        logging.info(f"内置策略模板已同步: {sync_result}")
    except Exception as e:
        logging.warning(f"内置策略模板同步失败（不影响 Web 服务启动）: {e}", exc_info=True)


def main():
    # tornado.options.parse_command_line()
    tornado.options.options.logging = None

    http_server = tornado.httpserver.HTTPServer(Application())
    port = _cfg.get_int('QUANTIA_WEB_PORT', 9988)
    http_server.listen(port)

    logging.info(f"服务已启动，web地址 : http://localhost:{port}/")
    print(f"服务已启动，web地址 : http://localhost:{port}/")  # 控制台通知运维人员

    threading.Thread(target=_sync_strategy_templates_in_background, name="strategy-template-sync", daemon=True).start()

    # Phase 9: 自定义综合指标 — 启动时确保表存在 + seed 内置预设
    try:
        customIndicatorHandler.bootstrap()
    except Exception as e:
        logging.warning(f"自定义指标 bootstrap 失败（不影响其他功能）: {e}")

    # 启动模拟交易自动调度器（每个交易日收盘后自动执行）
    try:
        from quantia.paper_trading.scheduler import PaperTradingScheduler
        _paper_scheduler = PaperTradingScheduler()
        _paper_scheduler.start()
    except Exception as e:
        logging.warning(f"模拟交易调度器启动失败（不影响其他功能）: {e}")

    tornado.ioloop.IOLoop.current().start()


if __name__ == "__main__":
    main()
