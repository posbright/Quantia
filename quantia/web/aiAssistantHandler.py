#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 助手 HTTP 接口 — 路由前缀 /quantia/api/ai/*。

M2 提供：
  POST /quantia/api/ai/strategy/generate  生成策略代码
  POST /quantia/api/ai/strategy/refine    在已有代码上做局部修改
  POST /quantia/api/ai/strategy/repair    根据失败信息修复代码
  POST /quantia/api/ai/chat               通用聊天（无 strict 校验）

所有调用均通过 quantia.lib.ai.run_chat → audit 落库 → strict 校验。
长耗时任务在共享 ThreadPoolExecutor 中执行，避免阻塞 IOLoop。
"""

import json
import logging
import os
import re
import sys
import queue
import threading
from abc import ABC
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Tuple

from tornado import gen
from tornado.ioloop import IOLoop

import quantia.web.base as webBase
from quantia.core.backtest.strategy_sandbox import validate_code_strict
from quantia.lib.ai import RateLimitError, ProviderError, AIError, run_chat, stream_chat
from quantia.lib.ai import prompt_loader
from quantia.lib.ai.providers.base import ChatMessage
from quantia.lib.ai.memory import get_memory as _get_memory

__author__ = 'Quantia'
__date__ = '2026/05/11'

# ── 共享线程池：所有 AI 调用 handler 共用，限制并发避免上游限流 ──
_AI_EXECUTOR: Optional[ThreadPoolExecutor] = None


def _get_executor() -> ThreadPoolExecutor:
    global _AI_EXECUTOR
    if _AI_EXECUTOR is None:
        _AI_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix='ai-call')
    return _AI_EXECUTOR


_FENCE_RE = re.compile(r'^\s*```(?:python|py)?\s*\n(.*?)\n```\s*$', re.DOTALL | re.IGNORECASE)


def _strip_code_fence(text: str) -> str:
    """如果模型返回了 Markdown 代码围栏，剥离掉只保留代码体。"""
    if not text:
        return ''
    m = _FENCE_RE.match(text.strip())
    if m:
        return m.group(1).strip()
    return text.strip()


# ── M11: 自动记录"踩坑教训"，写入 prompt/strategy_lessons.md，供后续生成参考 ──
_REPAIR_PATTERNS = [
    # (在原始 error_text 中匹配的关键字, severity, title, fix)
    ('not enough values to unpack', 'HIGH',
     'talib 函数返回值数量不匹配',
     '`talib.STOCH` 只返回 (slowk, slowd) 两个值；`MACD/BBANDS` 返回 3 个；'
     '`RSI` 返回 1 个。请按官方文档对齐解包数量，禁止 `k, d, j = talib.STOCH(...)` 写法。'),
    ('NameError', 'HIGH',
     'NameError 中间变量未先赋值',
     '所有 `*_prev` / `*_now` 中间变量必须先无条件赋值再使用，'
     '缺数据时给安全默认值，例如 `boll_middle_prev = boll_middle.iloc[-2] if len(boll_middle) >= 2 else 0`。'),
    ('KeyError', 'MED',
     'KeyError data[code] 未做存在性检查',
     '取 `data[code]` / `context.portfolio.positions[code]` 前先 `if code not in data: continue` 或 `.get(code)`。'),
    ('IndexError', 'MED',
     'IndexError history 数据不足',
     '调用 `closes = history(stock, N+1, "close")` 后必须 `if len(closes) < N+1: continue`。'),
    ('not in data', 'MED',
     '股票未加载到 data 直接索引',
     '若使用 `get_fundamentals` 选股后立刻 `data[code]`，请先 `if code in data:`。'),
    ('division by zero', 'MED',
     '除零错误',
     '比率 / 涨跌幅计算前检查分母 >0，例如 `if pre_close > 0: change = ...`。'),
    ('day == 1', 'HIGH',
     'day==1 触发陷阱',
     '改用 `g.last_select_month` 游标判断"当前月与上次不同"，避开节假日。'),
]


def _record_repair_lesson(error_text: str, original_code: str, fixed_code: str) -> None:
    """根据 error_text 关键字匹配，把对应的踩坑教训写入 strategy_lessons.md（已去重）。"""
    if not error_text:
        return
    try:
        from quantia.lib.ai import prompt_loader as _pl
    except Exception:
        return
    error_text_low = error_text.lower()
    for kw, sev, title, fix in _REPAIR_PATTERNS:
        if kw.lower() in error_text_low:
            try:
                _pl.record_lesson(
                    title=title,
                    problem=f'修复历史: 错误特征 "{kw}" 在生成代码中出现',
                    fix=fix,
                    severity=sev,
                    dedup=True,
                )
            except Exception:
                pass


def _maybe_strict_user_prompt(user_prompt: str) -> str:
    """检测用户原话里的约束限定词（保持/仅/只/不引入等），命中则追加'严格保持模式'提示。

    放在 user prompt 末尾而非 system，以便模型把它当作当前任务的强约束。
    """
    if not user_prompt:
        return user_prompt
    keys = ('保持', '仅', '只 ', '只依赖', '只用', '不引入',
            '不要加', '不变', '维持', '不要改', '严格', 'only', 'keep')
    if not any(k in user_prompt for k in keys):
        return user_prompt
    return user_prompt + (
        "\n\n[严格保持模式 — 检测到用户使用了限定词]\n"
        "用户原话里出现了 '保持 / 仅 / 只 / 不引入 / 不要加 / 不变 / 维持' 等限定词。\n"
        "请严格遵守：\n"
        "  1. 用户说'仅依赖 X' / '只用 X' 时，生成的代码里**只能**出现 X 一种触发逻辑；\n"
        "     绝对不允许擅自加入 RSI/BOLL/MACD/量能/止盈止损 等清单外的指标和条件；\n"
        "  2. 用户说'保持原有 X' / 'X 不变' 时，X 部分（如基本面筛选条件、调仓频率）\n"
        "     必须与用户描述/参考代码完全一致，不要改阈值、不要改顺序、不要'优化';\n"
        "  3. 风控（止损/止盈/仓位上限/回撤过滤）默认不加，除非用户明确要求；\n"
        "  4. 写完前自检：每一行代码能否对应到用户原话里的一条具体要求？不能 → 删掉。"
    )


def _client_ip(handler) -> str:
    return handler.request.remote_ip or ''


def _validate_or_msg(code: str) -> Tuple[bool, str]:
    ok, err = validate_code_strict(code)
    return ok, err if not ok else ''


# ──────────────────────────────────────────────────────────────────────
# 运行期预演（refine / repair 自动闭环的关键升级）
# 静态沙箱校验只能挡住"无法编译 / 危险 import"，但拦不住 NameError /
# AttributeError / 除零等运行期错误。下面这一层在静态校验通过后，再用
# PortfolioBacktestEngine 在一段短窗口里实际跑一次，把"代码能跑起来"
# 作为闭环验收标准，否则把错误反馈给 LLM 继续修。
# ──────────────────────────────────────────────────────────────────────
_PREFLIGHT_DEFAULT_DAYS = 7  # 闭环验收只需"能跑通"，7 天窗口足够触发 NameError / AttributeError 等运行期错误；30 天窗口太慢会让前端 60s axios 超时（即使前端已放宽到 5min，也应保持单轮 < 30s）。
_PREFLIGHT_DEFAULT_CASH = 1_000_000.0
_PREFLIGHT_DEFAULT_BENCHMARK = '000300'


def _should_run_preflight() -> bool:
    """是否在 refine/repair 自动修复闭环中跑一次轻量回测确认运行无误。

    由 QUANTIA_AI_REPAIR_RUN_PREFLIGHT 控制；未设置时：
      - 生产默认 ON；
      - pytest 环境默认 OFF（避免依赖真实数据源；新测试请显式置 '1' 开启）。
    """
    val = os.environ.get('QUANTIA_AI_REPAIR_RUN_PREFLIGHT')
    if val is not None:
        return str(val).lower() not in ('0', 'false', 'no', '')
    if 'PYTEST_CURRENT_TEST' in os.environ or 'pytest' in sys.modules:
        return False
    return True


def _run_runtime_preflight(
    code: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    initial_cash: Optional[float] = None,
    benchmark: Optional[str] = None,
) -> Tuple[bool, str]:
    """轻量预演回测：判断"能否跑完且无运行期异常"，不落 DB。

    返回 (ok, err_text)。
    - ok=True：策略可在窗口内顺利执行，没有引擎错误、没有 per-bar 异常、
      日志里也没有 [ERROR] 行（即未被策略自己的 try/except 吞掉的 NameError 等）。
    - ok=False：err_text 含简短错误描述（含异常类型 / 末行 traceback / 日志样例），
      可直接拼到 LLM 的修复 prompt 里。
    """
    import datetime as _dt
    try:
        if not end_date:
            end_date = _dt.date.today().strftime('%Y-%m-%d')
        if not start_date:
            end_dt = _dt.datetime.strptime(end_date, '%Y-%m-%d').date()
            start_date = (end_dt - _dt.timedelta(days=_PREFLIGHT_DEFAULT_DAYS)).strftime('%Y-%m-%d')
    except Exception as exc:
        logging.debug(f'[preflight] 日期解析失败: {exc}')
        return True, ''  # 日期无效 → 跳过预演，避免阻塞 refine
    try:
        cash = float(initial_cash) if initial_cash else _PREFLIGHT_DEFAULT_CASH
    except (TypeError, ValueError):
        cash = _PREFLIGHT_DEFAULT_CASH
    bm = benchmark or _PREFLIGHT_DEFAULT_BENCHMARK

    try:
        from quantia.core.backtest.portfolio_engine import PortfolioBacktestEngine
        engine = PortfolioBacktestEngine()
        result = engine.run(code, start_date, end_date, initial_cash=cash, benchmark=bm)
    except Exception as exc:
        import traceback as _tb
        tb_tail = _tb.format_exc()[-1500:]
        return False, f'回测引擎抛出 {type(exc).__name__}: {exc}\n{tb_tail}'
    finally:
        try:
            import quantia.lib.database as _mdb
            _mdb.close_thread_connection()
        except Exception:
            pass

    status = (result or {}).get('status')
    if status and status != 'completed':
        msg = str(result.get('message') or result.get('error') or 'unknown')[:500]
        return False, f'回测引擎返回 status={status}: {msg}'

    errs = (result or {}).get('errors') or []
    if errs:
        first = errs[0] if isinstance(errs[0], dict) else {'error': str(errs[0])}
        et = first.get('type') or 'Exception'
        em = (first.get('error') or '策略运行错误')[:300]
        tb = (first.get('traceback') or '')[-1000:]
        return False, (
            f'策略运行期共 {len(errs)} 处异常，首条 {et}: {em}\n{tb}'
        )

    # 日志反解：策略 try/except 吞掉的 NameError / AttributeError 等
    logs = (result or {}).get('logs') or []
    error_logs = [L for L in logs if '[ERROR]' in L]
    if error_logs:
        sample = '\n'.join(error_logs[:5])[:1200]
        return False, (
            f'策略日志含 {len(error_logs)} 条 [ERROR]（被策略 try/except 吞掉的异常）:\n{sample}'
        )

    return True, ''


def _verify_strategy_code(code: str, body: Optional[dict] = None) -> Tuple[bool, str, str]:
    """静态沙箱校验 + 运行期预演的组合验收。

    返回 (ok, kind, err)：
      - ok=True 时 kind='' err=''；
      - 静态校验失败 kind='static'；
      - 运行期预演失败 kind='runtime'。

    body 可携带 start_date / end_date / initial_cash / benchmark，
    refine 场景 body 没有这些字段时自动用近 30 自然日窗口。
    """
    ok, err = validate_code_strict(code)
    if not ok:
        return False, 'static', err or '(无错误信息)'
    if not _should_run_preflight():
        return True, '', ''
    body = body or {}
    ok2, err2 = _run_runtime_preflight(
        code,
        start_date=body.get('start_date'),
        end_date=body.get('end_date'),
        initial_cash=body.get('initial_cash'),
        benchmark=body.get('benchmark'),
    )
    if not ok2:
        return False, 'runtime', err2 or '回测预演失败'
    return True, '', ''


def _write_error(handler, code: int, msg: str, **extra):
    body = {'code': code, 'msg': msg}
    body.update(extra)
    handler.set_header('Content-Type', 'application/json')
    # HTTP 状态码语义对齐（前端 axios 拦截器可按 status 区分限流/无权）
    if code == 429:
        handler.set_status(429)
    elif code == 403:
        handler.set_status(403)
    handler.write(json.dumps(body, ensure_ascii=False))


def _write_rate_limit_error(handler, exc: 'RateLimitError'):
    """对上游 429 错误统一文案：区分"模型过载"与"配额超限"两种语义。

    - overloaded=True：Moonshot 的 engine_overloaded_error 等，上游服务器忙；
      文案告诉用户"模型当前繁忙，请稍后重试或切换模型"。
    - overloaded=False：真实配额超限；保留原文案"触发限流"。
    extra 字段 `overloaded` 让前端可以做差异化展示（如换色、加重试按钮）。
    """
    overloaded = bool(getattr(exc, 'overloaded', False))
    if overloaded:
        msg = f'上游模型当前繁忙（服务过载），已自动重试仍未恢复。请稍后再试或切换其它模型。原始错误：{exc}'
    else:
        msg = f'触发限流: {exc}'
    _write_error(handler, 429, msg, overloaded=overloaded)


def _call_ai_blocking(prompt: str, system: str, scene: str, agent: str, user_id: str,
                      overrides: Optional[dict] = None,
                      rate_limit_loop: bool = False,
                      history: Optional[list] = None):
    """在线程池中执行的同步 AI 调用。

    返回 (content, resolved_model) —— 让上层把实际使用的模型回传给前端，
    便于 SaveStrategyCodeHandler 落库 ai_model 字段（N1 修正）。

    rate_limit_loop=True 仅供修复闭环内部重试使用（spec §4.4 / §16.5），
    使该次调用从用户 1 小时滑窗配额中扣除（不计入），避免 max_attempts=3
    把用户 60 calls/h 配额吃光。
    history 可选：spec §11.3 多轮对话历史（已在 ChatHandler 处截断到
    max_tokens 内），元素为 ChatMessage。
    """
    from quantia.lib.ai.config import load_config as _load_cfg
    cfg = _load_cfg(overrides)
    content = run_chat(
        prompt, scene=scene, system=system, agent=agent,
        user_id=user_id, overrides=overrides,
        rate_limit_loop=rate_limit_loop,
        history=history,
    )
    return content, cfg.model


def _get_max_repair_attempts() -> int:
    """M3：strict 校验失败自动重试上限。每次调用读环境变量，便于测试。"""
    try:
        return max(0, int(os.environ.get('QUANTIA_AI_REPAIR_MAX_ATTEMPTS', '3')))
    except (TypeError, ValueError):
        return 3


# 单次生成上限（防止内存/带宽攻击）—— L2
_MAX_GENERATED_CHARS = max(8 * 1024, int(os.environ.get('QUANTIA_AI_MAX_GENERATED_CHARS', str(256 * 1024))))


def _build_repair_prompt(prev_code: str, err: str, original_intent: str) -> str:
    """生成"修复 prompt"：携带上一次代码 + strict 错误 + 用户原始意图。"""
    return (
        f"你上一轮生成的策略代码未通过沙箱安全校验。\n\n"
        f"用户原始需求：\n{original_intent}\n\n"
        f"上一轮代码：\n{prev_code}\n\n"
        f"沙箱校验错误：\n{err}\n\n"
        f"请输出修复后的完整 Python 代码（不要解释、不要 Markdown 围栏），"
        f"要求保留原意图、移除所有 import os/sys/subprocess 等违禁项。"
    )


def _build_runtime_repair_prompt(prev_code: str, runtime_err: str, original_intent: str) -> str:
    """生成"运行期修复 prompt"：上一轮代码通过了静态校验但回测真实跑挂。

    与 _build_repair_prompt 的差异：明确告知错误来自实际回测运行，
    并提示策略沙箱不会自动注入 numpy/pandas/talib 等模块、try/except
    可能吞掉根因等常见坑。
    """
    return (
        f"你上一轮生成的策略代码通过了静态沙箱安全校验，"
        f"但在实际回测中运行失败。\n\n"
        f"用户原始需求：\n{original_intent}\n\n"
        f"上一轮代码：\n{prev_code}\n\n"
        f"回测运行期间的错误（含 traceback 末尾 / [ERROR] 日志样例）：\n"
        f"{runtime_err}\n\n"
        f"请输出修复后的**完整可运行** Python 代码（不要解释、不要 Markdown 围栏）。"
        f"修复要求：\n"
        f"1. 直接定位到上述错误对应的代码行做最小改动；\n"
        f"2. 策略沙箱不会自动注入 numpy / pandas / talib —— "
        f"若需要这些库请在代码顶部用 `import numpy as np` / `import pandas as pd` / "
        f"`import talib`（不要写 `import talib as ta` 之外的简写来用 ta.xxx 又不导入）；\n"
        f"3. 若错误来自 try/except 吞掉的 NameError / AttributeError，"
        f"必须修复根因（补 import / 改正确的 API 名称），而不是继续把异常吞掉；\n"
        f"4. 严禁引入新的未导入模块，禁止使用 eval / exec / open / 文件 IO / 网络 IO；\n"
        f"5. 不要重复使用上一轮已经被验证失败的写法。"
    )


# ──────────────────────────────────────────────────────────────────────
# 1) 策略生成
# ──────────────────────────────────────────────────────────────────────
class GenerateStrategyHandler(webBase.BaseHandler, ABC):
    """根据自然语言 prompt 生成策略代码。

    请求体: {"prompt": "...", "model": "...", "api_key": "...", "api_base": "..."}
    响应:   {"code":0, "data": {"code": "...", "validated": true}} 或
            {"code":-1, "msg": "...", "data": {"raw": "...", "code": "..."}}
    """

    @gen.coroutine
    def post(self):
        try:
            body = json.loads(self.request.body or b'{}')
        except Exception as exc:
            _write_error(self, -1, f'请求体解析失败: {exc}')
            return

        user_prompt = (body.get('prompt') or '').strip()
        if not user_prompt:
            _write_error(self, -1, 'prompt 不能为空')
            return

        overrides = _build_overrides(body)
        system = prompt_loader.load('strategy_coder')
        # 触发"严格保持"模式：用户明示约束时显式强化
        _STRICT_KEYS = ('保持', '仅', '只 ', '只依赖', '只用', '不引入',
                        '不要加', '不变', '维持', '不要改', '严格', 'only', 'keep')
        if any(k in user_prompt for k in _STRICT_KEYS):
            user_prompt_final = user_prompt + (
                "\n\n[严格保持模式 — 检测到用户使用了限定词]\n"
                "用户原话里出现了 '保持 / 仅 / 只 / 不引入 / 不要加 / 不变 / 维持' 等限定词。\n"
                "请严格遵守：\n"
                "  1. 用户说'仅依赖 X' / '只用 X' 时，生成的代码里**只能**出现 X 一种触发逻辑；\n"
                "     绝对不允许擅自加入 RSI/BOLL/MACD/量能/止盈止损 等清单外的指标和条件；\n"
                "  2. 用户说'保持原有 X' / 'X 不变' 时，X 部分（如基本面筛选条件、调仓频率）\n"
                "     必须与用户描述/参考代码完全一致，不要改阈值、不要改顺序、不要'优化';\n"
                "  3. 风控（止损/止盈/仓位上限/回撤过滤）默认不加，除非用户明确要求；\n"
                "  4. 写完前自检：每一行代码能否对应到用户原话里的一条具体要求？不能 → 删掉。"
            )
        else:
            user_prompt_final = user_prompt
        try:
            raw, resolved_model = yield IOLoop.current().run_in_executor(
                _get_executor(),
                _call_ai_blocking,
                user_prompt_final, system, 'strategy_gen', 'strategy_coder',
                _client_ip(self), overrides,
            )
        except RateLimitError as exc:
            _write_rate_limit_error(self, exc)
            return
        except (ProviderError, AIError) as exc:
            _write_error(self, -1, f'AI 调用失败: {exc}')
            return
        except Exception as exc:
            logging.exception('GenerateStrategyHandler 未知异常')
            _write_error(self, -1, f'内部错误: {exc}')
            return

        code = _strip_code_fence(raw)
        ok, err = _validate_or_msg(code)
        attempts = 0
        repair_status = 'success' if ok else 'unrepaired'
        max_attempts = _get_max_repair_attempts()
        # M3：strict 校验失败自动重试 ≤ N 轮
        if not ok and max_attempts > 0:
            repairer_sys = prompt_loader.load('strategy_repairer')
            prev_signature = (code, err)
            for _ in range(max_attempts):
                attempts += 1
                fix_prompt = _build_repair_prompt(code, err, user_prompt)
                try:
                    raw, resolved_model = yield IOLoop.current().run_in_executor(
                        _get_executor(),
                        _call_ai_blocking,
                        fix_prompt, repairer_sys,
                        'strategy_gen_repair', 'strategy_repairer',
                        _client_ip(self), overrides, True,  # rate_limit_loop
                    )
                except RateLimitError as exc:
                    logging.warning(f'生成自动修复阶段触发限流: {exc}')
                    repair_status = 'rate_limited'
                    break
                except (ProviderError, AIError) as exc:
                    logging.warning(f'生成自动修复阶段 AI 调用失败: {exc}')
                    repair_status = 'provider_error'
                    break
                code = _strip_code_fence(raw)
                ok, err = _validate_or_msg(code)
                if ok:
                    repair_status = 'success'
                    break
                # D1：LLM 返回与上一轮完全相同的错误代码——提前退出避免浪费 token
                signature = (code, err)
                if signature == prev_signature:
                    repair_status = 'no_progress'
                    break
                prev_signature = signature
            else:
                repair_status = 'max_attempts'
        payload = {
            'code': 0 if ok else -2,
            'msg': '' if ok else f'代码沙箱校验失败: {err}',
            'data': {
                'code': code,
                'raw': raw,
                'validated': ok,
                'validation_error': err,
                'model': resolved_model,
                'repair_attempts': attempts,
                'repair_status': repair_status,
            },
        }
        self.set_header('Content-Type', 'application/json')
        self.write(json.dumps(payload, ensure_ascii=False))


# ──────────────────────────────────────────────────────────────────────
# 2) 策略局部修改 (refine)
# ──────────────────────────────────────────────────────────────────────
class RefineStrategyHandler(webBase.BaseHandler, ABC):
    """在已有代码上做局部修改。

    请求体: {"prompt": "把持仓从5只改成10只", "code": "...原代码..."}
    """

    @gen.coroutine
    def post(self):
        try:
            body = json.loads(self.request.body or b'{}')
        except Exception as exc:
            _write_error(self, -1, f'请求体解析失败: {exc}')
            return

        user_prompt = (body.get('prompt') or '').strip()
        original_code = (body.get('code') or '').strip()
        if not user_prompt or not original_code:
            _write_error(self, -1, 'prompt 与 code 均不能为空')
            return

        overrides = _build_overrides(body)
        system = prompt_loader.load('strategy_coder')
        # 命中限定词时，把 strict hint 拼到组合 prompt 末尾
        _hinted = _maybe_strict_user_prompt(user_prompt)
        strict_hint = _hinted[len(user_prompt):] if _hinted != user_prompt else ''
        composed = (
            f"以下是用户当前的策略代码（保持整体结构，按需求局部修改）：\n\n"
            f"{original_code}\n\n"
            f"用户的修改需求：{user_prompt}"
            f"{strict_hint}"
        )
        try:
            raw, resolved_model = yield IOLoop.current().run_in_executor(
                _get_executor(),
                _call_ai_blocking,
                composed, system, 'strategy_refine', 'strategy_coder',
                _client_ip(self), overrides,
            )
        except RateLimitError as exc:
            _write_rate_limit_error(self, exc)
            return
        except (ProviderError, AIError) as exc:
            _write_error(self, -1, f'AI 调用失败: {exc}')
            return
        except Exception as exc:
            logging.exception('RefineStrategyHandler 未知异常')
            _write_error(self, -1, f'内部错误: {exc}')
            return

        code = _strip_code_fence(raw)
        # 闭环验收：静态沙箱 + 运行期预演（preflight），由 _verify_strategy_code 统一执行。
        ok, err_kind, err = _verify_strategy_code(code, body)
        attempts = 0
        repair_status = 'success' if ok else 'unrepaired'
        max_attempts = _get_max_repair_attempts()
        if not ok and max_attempts > 0:
            repairer_sys = prompt_loader.load('strategy_repairer')
            prev_signature = (code, err)
            for _ in range(max_attempts):
                attempts += 1
                # 根据错误类型选择不同 prompt：runtime 错误必须告知 AI 是真实
                # 回测跑挂、提示沙箱不会自动注入 numpy/pandas/talib 等坑。
                if err_kind == 'runtime':
                    fix_prompt = _build_runtime_repair_prompt(code, err, user_prompt)
                else:
                    fix_prompt = _build_repair_prompt(code, err, user_prompt)
                try:
                    raw, resolved_model = yield IOLoop.current().run_in_executor(
                        _get_executor(),
                        _call_ai_blocking,
                        fix_prompt, repairer_sys,
                        'strategy_refine_repair', 'strategy_repairer',
                        _client_ip(self), overrides, True,  # rate_limit_loop
                    )
                except RateLimitError as exc:
                    logging.warning(f'修改自动修复阶段触发限流: {exc}')
                    repair_status = 'rate_limited'
                    break
                except (ProviderError, AIError) as exc:
                    logging.warning(f'修改自动修复阶段 AI 调用失败: {exc}')
                    repair_status = 'provider_error'
                    break
                code = _strip_code_fence(raw)
                ok, err_kind, err = _verify_strategy_code(code, body)
                if ok:
                    repair_status = 'success'
                    break
                signature = (code, err)
                if signature == prev_signature:
                    repair_status = 'no_progress'
                    break
                prev_signature = signature
            else:
                repair_status = 'max_attempts'
        self.set_header('Content-Type', 'application/json')
        self.write(json.dumps({
            'code': 0 if ok else -2,
            'msg': '' if ok else (
                f'代码沙箱校验失败: {err}' if err_kind == 'static'
                else f'代码回测预演失败: {err}' if err_kind == 'runtime'
                else f'代码校验失败: {err}'
            ),
            'data': {'code': code, 'raw': raw, 'validated': ok,
                     'validation_error': err,
                     'validation_kind': err_kind,  # '' / 'static' / 'runtime'
                     'model': resolved_model,
                     'repair_attempts': attempts,
                     'repair_status': repair_status},
        }, ensure_ascii=False))


# ──────────────────────────────────────────────────────────────────────
# 3) 策略修复 (repair) — 基于 task_recorder 的失败信息
# ──────────────────────────────────────────────────────────────────────
class RepairStrategyHandler(webBase.BaseHandler, ABC):
    """根据上一次失败的 backtest 结果（task_recorder.fetch_last_failure）修复代码。

    请求体: {"strategy_id": 123, "code": "...当前代码（可选，为空则从 DB 取）...",
            "auto_backtest": True, "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD",
            "initial_cash": 1000000, "benchmark": "000300"}

    新增（PR）：未找到失败记录时不再直接 404，而是按以下顺序自动回填：
      1. 静态沙箱校验（validate_code_strict）失败 → 当作失败喂给修复 agent；
      2. auto_backtest=True（默认）→ 同步预演回测（默认 60 自然日）失败 → 落库
         record_failed 并作为修复输入；
      3. 均通过 → 返回 "无失败可修复"。
    """

    # 预演回测的默认窗口（自然日），仅用于无失败记录时的兜底
    _PREFLIGHT_DAYS = 60
    _PREFLIGHT_TIMEOUT_S = 60  # 预演最长等待 60 秒，避免阻塞 IOLoop

    def _run_preflight_backtest_sync(
        self, strategy_id, strategy_name, code,
        start_date=None, end_date=None, initial_cash=None, benchmark='000300',
    ):
        """无失败记录时的兜底预演（同步版本，需在线程池中调用）。

        返回 (ok, fail_dict)：
          ok=True  代码顺利跑完 → fail_dict=None
          ok=False 跑挂了       → fail_dict 形态与 fetch_last_failure 返回一致，
                                   并已通过 record_failed 落库（下次直接命中）。
        """
        import datetime as _dt
        import traceback as _tb
        # ── 1. 日期窗口：优先使用前端传入；否则取近 _PREFLIGHT_DAYS 天 ──
        try:
            if not end_date:
                end_date = _dt.date.today().strftime('%Y-%m-%d')
            if not start_date:
                end_dt = _dt.datetime.strptime(end_date, '%Y-%m-%d').date()
                start_date = (end_dt - _dt.timedelta(days=self._PREFLIGHT_DAYS)).strftime('%Y-%m-%d')
        except Exception as exc:
            logging.warning(f'[repair preflight] 日期解析失败: {exc}')
            return True, None  # 日期无效就放弃预演，按"无失败"处理

        try:
            cash = float(initial_cash) if initial_cash else 1_000_000.0
        except Exception:
            cash = 1_000_000.0

        try:
            return self._do_preflight(strategy_id, strategy_name, code,
                                      start_date, end_date, cash, benchmark or '000300')
        finally:
            # 线程池长生存：释放线程局部 DB 连接，避免连接累积。
            try:
                import quantia.lib.database as _mdb
                _mdb.close_thread_connection()
            except Exception:
                pass

    def _do_preflight(self, strategy_id, strategy_name, code,
                      start_date, end_date, cash, benchmark):
        import datetime as _dt
        import traceback as _tb
        # ── 2. 同步跑一次 PortfolioBacktestEngine ──
        try:
            from quantia.core.backtest.portfolio_engine import PortfolioBacktestEngine
            engine = PortfolioBacktestEngine()
            started = _dt.datetime.now()
            result = engine.run(
                code, start_date, end_date,
                initial_cash=cash, benchmark=benchmark,
            )
        except Exception as exc:
            err_text = str(exc)[:500]
            tb_text = _tb.format_exc()
            # 落库失败记录（下次直接命中 fetch_last_failure）
            try:
                from quantia.core.backtest.task_recorder import record_failed as _rf
                rec_id = _rf(
                    strategy_id=strategy_id, strategy_name=strategy_name,
                    start_date=start_date, end_date=end_date,
                    initial_cash=cash, benchmark=benchmark,
                    error_text=err_text, traceback_text=tb_text,
                )
            except Exception as rec_exc:
                logging.warning(f'[repair preflight] record_failed 异常: {rec_exc}')
                rec_id = 0
            return False, {
                'id': rec_id or 0,
                'started_at': started.strftime('%Y-%m-%d %H:%M:%S'),
                'completed_at': _dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'error_message': err_text,
                'traceback': tb_text,
                'error': err_text,
            }

        # 引擎正常返回但 status != completed，同样视为失败
        status = (result or {}).get('status')
        if status and status != 'completed':
            err_text = str(result.get('message') or result.get('error') or 'unknown')[:500]
            tb_text = str(result.get('traceback') or '')
            errs = result.get('errors') or []
            if errs and not tb_text:
                first = errs[0] if isinstance(errs[0], dict) else {'error': str(errs[0])}
                tb_text = first.get('traceback') or ''
                err_text = err_text or first.get('error') or '策略运行错误'
            try:
                from quantia.core.backtest.task_recorder import record_failed as _rf
                rec_id = _rf(
                    strategy_id=strategy_id, strategy_name=strategy_name,
                    start_date=start_date, end_date=end_date,
                    initial_cash=cash, benchmark=benchmark,
                    error_text=err_text, traceback_text=tb_text,
                    extra_result={'preflight': True, 'engine_result': result},
                )
            except Exception as rec_exc:
                logging.warning(f'[repair preflight] record_failed 异常: {rec_exc}')
                rec_id = 0
            return False, {
                'id': rec_id or 0,
                'started_at': str(result.get('start_date') or start_date),
                'completed_at': _dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'error_message': err_text,
                'traceback': tb_text,
                'error': err_text,
            }

        # status=completed 但有运行期 errors（per-bar 异常）也算失败
        errs = (result or {}).get('errors') or []
        if errs:
            first = errs[0] if isinstance(errs[0], dict) else {'error': str(errs[0])}
            err_text = (first.get('error') or '策略运行错误')[:500]
            tb_text = first.get('traceback') or ''
            try:
                from quantia.core.backtest.task_recorder import record_failed as _rf
                rec_id = _rf(
                    strategy_id=strategy_id, strategy_name=strategy_name,
                    start_date=start_date, end_date=end_date,
                    initial_cash=cash, benchmark=benchmark,
                    error_text=f'策略运行期共 {len(errs)} 处错误，首条: {err_text}',
                    traceback_text=tb_text,
                    extra_result={'preflight': True, 'all_errors': errs[:50]},
                )
            except Exception as rec_exc:
                logging.warning(f'[repair preflight] record_failed 异常: {rec_exc}')
                rec_id = 0
            return False, {
                'id': rec_id or 0,
                'started_at': start_date,
                'completed_at': _dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'error_message': f'策略运行期共 {len(errs)} 处错误，首条: {err_text}',
                'traceback': tb_text,
                'error': err_text,
            }

        return True, None

    @gen.coroutine
    def post(self):
        try:
            body = json.loads(self.request.body or b'{}')
        except Exception as exc:
            _write_error(self, -1, f'请求体解析失败: {exc}')
            return

        strategy_id = body.get('strategy_id')
        if not strategy_id:
            _write_error(self, -1, 'strategy_id 不能为空')
            return

        # 获取失败信息（完整 traceback + 最近 N 次失败历史，避免重复同一类修复）
        from quantia.core.backtest.task_recorder import (
            fetch_last_failure, fetch_recent_failures, record_failed,
        )
        try:
            last = fetch_last_failure(int(strategy_id))
            history = fetch_recent_failures(int(strategy_id), limit=5) or []
        except Exception as exc:
            _write_error(self, -1, f'读取失败信息异常: {exc}')
            return

        # 取代码（请求体优先；否则从 DB 当前 cn_stock_strategy_code 取）
        original_code = (body.get('code') or '').strip()
        strategy_name = (body.get('strategy_name') or '').strip()
        if not original_code:
            try:
                import quantia.lib.database as mdb
                rows = mdb.executeSqlFetch(
                    'SELECT name, code FROM cn_stock_strategy_code WHERE id=%s', (int(strategy_id),))
                if rows and rows[0]:
                    row0 = rows[0]
                    if isinstance(row0, (list, tuple)):
                        strategy_name = strategy_name or (row0[0] or '')
                        original_code = row0[1] or ''
                    elif isinstance(row0, dict):
                        strategy_name = strategy_name or row0.get('name', '')
                        original_code = row0.get('code', '')
            except Exception as exc:
                logging.warning(f'读取策略代码失败: {exc}')
        if not original_code:
            _write_error(self, -1, '无法获取策略代码（请在请求体中提供 code 字段）')
            return

        # ── 自动回填失败记录（新生成策略尚未跑过回测时，避免直接拒绝）──
        # 优先级：1) DB 中已有失败记录直接用；
        #        2) 当前代码静态校验失败 → 把校验错误当作"失败"喂给修复 agent；
        #        3) 前端传入 auto_backtest=True（或默认开启）→ 同步跑一次轻量回测，
        #           失败即落 record_failed 并作为修复输入；
        #        4) 三步都过 → 明确告知用户"无失败可修复"。
        preflight_kind = None  # 'static' / 'backtest' / None
        if not last:
            # Step 2: 静态校验
            ok_pre, err_pre = _validate_or_msg(original_code)
            if not ok_pre:
                preflight_kind = 'static'
                last = {
                    'id': 0,
                    'started_at': '(preflight)',
                    'completed_at': '(preflight)',
                    'error_message': f'静态校验失败: {err_pre}',
                    'traceback': f'静态校验失败: {err_pre}',
                    'error': err_pre,
                }
            else:
                # Step 3: 是否同步跑一次预演回测
                auto_bt = body.get('auto_backtest')
                if auto_bt is None:
                    auto_bt = True  # 默认开启；前端可显式传 False 跳过
                if auto_bt:
                    try:
                        pre_ok, pre_fail = yield IOLoop.current().run_in_executor(
                            _get_executor(),
                            self._run_preflight_backtest_sync,
                            int(strategy_id), strategy_name, original_code,
                            body.get('start_date'), body.get('end_date'),
                            body.get('initial_cash'),
                            body.get('benchmark') or '000300',
                        )
                    except Exception as exc:
                        logging.warning(f'[repair preflight] 调度异常: {exc}')
                        pre_ok, pre_fail = True, None
                    if not pre_ok and pre_fail:
                        preflight_kind = 'backtest'
                        last = pre_fail
                        # 同时把这次失败补充进 history 头部，让 LLM 看到上下文
                        history = [pre_fail] + (history or [])
        if not last:
            _write_error(
                self, -1,
                '未找到该策略的失败回测记录；静态校验和预演回测均已通过，'
                '当前代码看起来可以正常运行。如确认存在问题，请在编辑器点"运行"复现失败后再使用该功能。',
            )
            return

        # 优先使用完整 traceback；否则回落 error_message / error
        full_tb = (last.get('traceback') or '').strip()
        err_short = (last.get('error') or '').strip()
        error_message = (last.get('error_message') or '').strip()
        # error_text 用于后续 _record_repair_lesson 的关键字匹配
        error_text = err_short or error_message or full_tb[:500]
        primary_failure = full_tb or error_message or err_short or '(无错误信息)'

        # 历史失败摘要（去掉本次最新一次，最多 4 条）
        history_lines = []
        for idx, h in enumerate(history[1:5], start=1):
            tb = (h.get('traceback') or '').strip()
            em = (h.get('error_message') or '').strip()
            snippet = tb if tb else em
            if not snippet:
                continue
            # 历史每条只保留 error 行 + traceback 末尾 ~600 字，避免 prompt 过长
            tail = snippet[-600:] if len(snippet) > 600 else snippet
            history_lines.append(
                f"[历史失败 #{idx} | task_id={h.get('id')} | started={h.get('started_at')}]\n{tail}"
            )
        history_block = ('\n\n'.join(history_lines)).strip()

        composed_parts = [
            "以下是当前策略代码：",
            "```python",
            original_code,
            "```",
            "",
            f"该代码在最近一次回测中失败（task_id={last.get('id')}, started_at={last.get('started_at')}）。",
            "完整错误堆栈如下：",
            "```",
            primary_failure,
            "```",
        ]
        if history_block:
            composed_parts += [
                "",
                "另外，该策略此前还有以下失败历史（按时间倒序，仅保留堆栈尾部）。"
                "请分析这些历史错误的共同根因，避免输出与历史相同或相似但同样会失败的修复：",
                history_block,
            ]
        composed_parts += [
            "",
            "修复要求：",
            "1. 必须输出**完整可运行**的策略代码（含 initialize 与 handle_data），禁止仅输出 diff 或片段；",
            "2. 必须直接定位到堆栈中报错的那一行做最小改动，并解释根因（可写在代码顶部注释里）；",
            "3. 若历史失败显示同一类错误反复出现，请彻底改换实现思路，不要再用此前已被证明会失败的写法；",
            "4. 严禁引入新的未导入模块，禁止使用 eval/exec/open 等高危 API。",
        ]
        composed = "\n".join(composed_parts)

        overrides = _build_overrides(body)
        system = prompt_loader.load('strategy_repairer')
        try:
            raw, resolved_model = yield IOLoop.current().run_in_executor(
                _get_executor(),
                _call_ai_blocking,
                composed, system, 'strategy_repair', 'strategy_repairer',
                _client_ip(self), overrides,
            )
        except RateLimitError as exc:
            _write_rate_limit_error(self, exc)
            return
        except (ProviderError, AIError) as exc:
            _write_error(self, -1, f'AI 调用失败: {exc}')
            return
        except Exception as exc:
            logging.exception('RepairStrategyHandler 未知异常')
            _write_error(self, -1, f'内部错误: {exc}')
            return

        code = _strip_code_fence(raw)
        # 闭环验收：静态沙箱 + 运行期预演（preflight）。
        ok, err_kind, err = _verify_strategy_code(code, body)
        attempts = 0
        repair_status = 'success' if ok else 'unrepaired'
        max_attempts = _get_max_repair_attempts()
        if not ok and max_attempts > 0:
            repairer_sys = prompt_loader.load('strategy_repairer')
            prev_signature = (code, err)
            for _ in range(max_attempts):
                attempts += 1
                if err_kind == 'runtime':
                    fix_prompt = _build_runtime_repair_prompt(
                        code, err, error_text or '上一轮代码回测期间抛错')
                else:
                    fix_prompt = _build_repair_prompt(
                        code, err, error_text or '原始代码有安全问题')
                try:
                    raw, resolved_model = yield IOLoop.current().run_in_executor(
                        _get_executor(),
                        _call_ai_blocking,
                        fix_prompt, repairer_sys,
                        'strategy_repair_retry', 'strategy_repairer',
                        _client_ip(self), overrides, True,  # rate_limit_loop
                    )
                except RateLimitError as exc:
                    logging.warning(f'修复重试触发限流: {exc}')
                    repair_status = 'rate_limited'
                    break
                except (ProviderError, AIError) as exc:
                    logging.warning(f'修复重试 AI 调用失败: {exc}')
                    repair_status = 'provider_error'
                    break
                code = _strip_code_fence(raw)
                ok, err_kind, err = _verify_strategy_code(code, body)
                if ok:
                    repair_status = 'success'
                    break
                signature = (code, err)
                if signature == prev_signature:
                    repair_status = 'no_progress'
                    break
                prev_signature = signature
            else:
                repair_status = 'max_attempts'
        # M11: 修复成功时把 (原始错误 → 修复成功) 自动记入踩坑知识库
        if ok and error_text:
            try:
                _record_repair_lesson(error_text, original_code, code)
            except Exception as _e:
                logging.debug(f'record_repair_lesson 失败 (忽略): {_e}')
        self.set_header('Content-Type', 'application/json')
        self.write(json.dumps({
            'code': 0 if ok else -2,
            'msg': '' if ok else (
                f'代码沙箱校验失败: {err}' if err_kind == 'static'
                else f'代码回测预演失败: {err}' if err_kind == 'runtime'
                else f'代码校验失败: {err}'
            ),
            'data': {
                'code': code, 'raw': raw,
                'validated': ok, 'validation_error': err,
                'validation_kind': err_kind,  # '' / 'static' / 'runtime'
                'model': resolved_model,
                'repair_attempts': attempts,
                'repair_status': repair_status,
                'failure': {
                    'error_message': error_message,
                    'traceback': full_tb,
                    'error': err_short,
                    'started_at': str(last.get('started_at') or ''),
                    'backtest_id': last.get('id'),
                    # PR：标记失败来源 — 'db' / 'static' / 'backtest'，前端可在
                    # AI 抽屉里展示"该次失败来自实时静态校验/预演回测"。
                    'source': preflight_kind or 'db',
                    'history': [
                        {
                            'id': h.get('id'),
                            'started_at': str(h.get('started_at') or ''),
                            'error_message': (h.get('error_message') or '')[:500],
                        }
                        for h in (history or [])[:5]
                    ],
                },
            },
        }, ensure_ascii=False))


# ──────────────────────────────────────────────────────────────────────
# 4) 通用聊天 — 不做 strict 校验（用于"AI 解释"等场景）
# ──────────────────────────────────────────────────────────────────────
class ChatHandler(webBase.BaseHandler, ABC):
    """通用聊天接口。请求体: {"prompt": "...", "system": "...(可选)", "scene": "...(默认 chat)",
                              "conversation_id": "...(可选 UUID，缺省自动生成)" }。

    spec §11.3 / §M8：传入 conversation_id 时按 ConversationMemory 加载历史 →
    截断到 QUANTIA_AI_MEMORY_MAX_TOKENS（默认 4000）→ 调用 LLM →
    user/assistant 两条消息追加回会话；返回体含
    `data.conversation_id` 与 `data.history_count`。
    """

    @gen.coroutine
    def post(self):
        try:
            body = json.loads(self.request.body or b'{}')
        except Exception as exc:
            _write_error(self, -1, f'请求体解析失败: {exc}')
            return

        user_prompt = (body.get('prompt') or '').strip()
        if not user_prompt:
            _write_error(self, -1, 'prompt 不能为空')
            return

        system = body.get('system') or None
        scene = body.get('scene') or 'chat'
        agent = body.get('agent') or None
        overrides = _build_overrides(body)
        user_ip = _client_ip(self)

        # ── M8：会话记忆 ──
        import uuid as _uuid
        conv_id_in = (body.get('conversation_id') or '').strip()
        conv_id = conv_id_in or _uuid.uuid4().hex
        try:
            max_hist_tokens = max(256, int(os.environ.get(
                'QUANTIA_AI_MEMORY_MAX_TOKENS', '4000')))
        except (TypeError, ValueError):
            max_hist_tokens = 4000

        mem = _get_memory()
        history_msgs: list = []

        # audit-fix-P0-2 + P2-9: get_or_create / load / append 均在线程池执行，
        # 且对用户传入的 conversation_id 在查到记录后校验 ownership
        # （user_id == 当前 client_ip），以免跨 IP 读/写别人会话。
        def _load_history_blocking():
            existing = mem.get(conv_id) if conv_id_in else None
            if existing is not None and existing.user_id and existing.user_id != user_ip:
                return ('forbidden', [])
            mem.get_or_create(conv_id, scene=scene, user_id=user_ip, agent=agent)
            raw_hist = mem.load(conv_id, max_tokens=max_hist_tokens)
            return ('ok', [ChatMessage(role=m.role, content=m.content)
                            for m in raw_hist])
        try:
            status, history_msgs = yield IOLoop.current().run_in_executor(
                _get_executor(), _load_history_blocking)
        except Exception as exc:
            logging.warning(f'ChatHandler load history 失败（忽略）: {exc}')
            status, history_msgs = 'ok', []
        if status == 'forbidden':
            _write_error(self, 403, f'无权访问会话: {conv_id}')
            return

        try:
            raw, resolved_model = yield IOLoop.current().run_in_executor(
                _get_executor(),
                _call_ai_blocking,
                user_prompt, system, scene, agent,
                user_ip, overrides, False, history_msgs,
            )
        except RateLimitError as exc:
            _write_rate_limit_error(self, exc)
            return
        except (ProviderError, AIError) as exc:
            _write_error(self, -1, f'AI 调用失败: {exc}')
            return
        except Exception as exc:
            logging.exception('ChatHandler 未知异常')
            _write_error(self, -1, f'内部错误: {exc}')
            return

        # 追加 user / assistant 两条消息（失败不影响业务返回）
        # audit-fix-P2-9: append 走线程池避免 IOLoop 阻塞
        def _append_blocking():
            mem.append(conv_id, 'user', user_prompt,
                       scene=scene, user_id=user_ip, agent=agent)
            mem.append(conv_id, 'assistant', raw,
                       scene=scene, user_id=user_ip, agent=agent)
        try:
            yield IOLoop.current().run_in_executor(
                _get_executor(), _append_blocking)
        except Exception as exc:
            logging.warning(f'ChatHandler append history 失败（忽略）: {exc}')

        self.set_header('Content-Type', 'application/json')
        self.write(json.dumps({
            'code': 0,
            'data': {
                'content': raw,
                'model': resolved_model,
                'conversation_id': conv_id,
                'history_count': len(history_msgs),
            },
        }, ensure_ascii=False))


# ──────────────────────────────────────────────────────────────────────
# 5) M5：列出 provider/model/agent 可选项
#    GET /quantia/api/ai/config   返回前端 picker 所需数据
#    GET /quantia/api/ai/agents   返回 agent 元数据（含 system_prompt）
# ──────────────────────────────────────────────────────────────────────
class GetAiConfigHandler(webBase.BaseHandler, ABC):
    """暴露 provider profile + agent 列表 + 默认值（不含 api_key）。"""

    def get(self):
        try:
            from quantia.lib.ai.config import list_provider_profiles
            data = list_provider_profiles()
            data['agents'] = [
                {k: v for k, v in a.items() if k != 'system_prompt'}
                for a in prompt_loader.list_agents()
            ]
            self.set_header('Content-Type', 'application/json')
            self.write(json.dumps({'code': 0, 'data': data}, ensure_ascii=False))
        except Exception as exc:
            logging.exception('GetAiConfigHandler 异常')
            _write_error(self, -1, f'读取 AI 配置失败: {exc}')


class ListAiAgentsHandler(webBase.BaseHandler, ABC):
    """列出 agent 详情，可选 ?include_prompt=1 一并返回 system_prompt。"""

    def get(self):
        try:
            include_prompt = self.get_argument('include_prompt', '0').lower() in ('1', 'true', 'yes')
            agents = prompt_loader.list_agents()
            if not include_prompt:
                agents = [{k: v for k, v in a.items() if k != 'system_prompt'} for a in agents]
            self.set_header('Content-Type', 'application/json')
            self.write(json.dumps({'code': 0, 'data': {'agents': agents}},
                                  ensure_ascii=False))
        except Exception as exc:
            logging.exception('ListAiAgentsHandler 异常')
            _write_error(self, -1, f'读取 agent 列表失败: {exc}')


# ──────────────────────────────────────────────────────────────────────
# 6) M7：自定义 Agent CRUD（写入 cn_stock_ai_agent）
#    GET    /quantia/api/ai/agents/manage           列出全部（含 disabled / 内置）
#    POST   /quantia/api/ai/agents/manage           upsert（用户传入 is_builtin 强制忽略）
#    DELETE /quantia/api/ai/agents/manage?name=xxx  删除（内置拒绝）
# ──────────────────────────────────────────────────────────────────────
class AiAgentsManageHandler(webBase.BaseHandler, ABC):
    """自定义 agent 管理。GET 列表，POST 新建/更新，DELETE 删除。"""

    def get(self):
        try:
            from quantia.lib.ai import agent_store
            from quantia.lib.ai import prompt_loader as _pl
            # 触发一次内置 bootstrap 保证内置 agent 在 DB 中可见
            try:
                _pl._bootstrap_builtins()  # type: ignore[attr-defined]
            except Exception:
                pass
            agents = agent_store.list_agents(enabled_only=False)
            include_prompt = self.get_argument('include_prompt', '0').lower() in ('1', 'true', 'yes')
            if not include_prompt:
                agents = [{k: v for k, v in a.items() if k != 'system_prompt'} for a in agents]
            self.set_header('Content-Type', 'application/json')
            self.write(json.dumps({'code': 0, 'data': {'agents': agents}},
                                  ensure_ascii=False))
        except Exception as exc:
            logging.exception('AiAgentsManageHandler.get 异常')
            _write_error(self, -1, f'读取 agent 失败: {exc}')

    def post(self):
        try:
            body = json.loads(self.request.body or b'{}')
        except Exception as exc:
            _write_error(self, -1, f'请求体解析失败: {exc}')
            return
        if not isinstance(body, dict):
            _write_error(self, -1, '请求体必须是对象')
            return
        # 用户接口禁止把 is_builtin 抬升为内置（避免越权）
        body.pop('is_builtin', None)
        try:
            from quantia.lib.ai import agent_store
            existing = agent_store.get_agent(body.get('name') or '')
            # 若已存在且为内置：仅允许修改非关键字段（display_name/description/
            # default_provider/default_model/temperature/max_tokens/enabled），
            # system_prompt 与 allowed_tools 保持原值，避免误改内置行为。
            if existing and existing.get('is_builtin'):
                protected = ('system_prompt', 'allowed_tools', 'name')
                for k in protected:
                    if k in body:
                        body.pop(k, None)
                # 把保护字段补回去以通过 _validate 的必填校验
                body['name'] = existing['name']
                body['system_prompt'] = existing.get('system_prompt') or ''
                # P1（一轮审计）：内置 agent 的 enabled 状态不可被修改，
                # 否则可能被用户禁用后从 chat / config 中消失，破坏 M2/M3/M5 功能。
                body['enabled'] = bool(existing.get('enabled', True))
            saved = agent_store.upsert_agent(body, is_builtin=bool(existing and existing.get('is_builtin')))
            # 写入后清缓存：prompt_loader 下次重新读取
            try:
                prompt_loader.clear_cache()
            except Exception:
                pass
            # 不返回 system_prompt（前端按需再 GET）
            saved_brief = {k: v for k, v in saved.items() if k != 'system_prompt'}
            self.set_header('Content-Type', 'application/json')
            self.write(json.dumps({'code': 0, 'data': saved_brief}, ensure_ascii=False))
        except Exception as exc:
            from quantia.lib.ai.agent_store import AgentStoreError
            if isinstance(exc, AgentStoreError):
                _write_error(self, -1, str(exc))
                return
            logging.exception('AiAgentsManageHandler.post 异常')
            _write_error(self, -1, f'保存 agent 失败: {exc}')

    def delete(self):
        name = (self.get_argument('name', '') or '').strip()
        if not name:
            _write_error(self, -1, 'name 不能为空')
            return
        try:
            from quantia.lib.ai import agent_store
            agent_store.delete_agent(name)
            self.set_header('Content-Type', 'application/json')
            self.write(json.dumps({'code': 0, 'data': {'name': name}},
                                  ensure_ascii=False))
        except Exception as exc:
            from quantia.lib.ai.agent_store import AgentStoreError
            if isinstance(exc, AgentStoreError):
                _write_error(self, -1, str(exc))
                return
            logging.exception('AiAgentsManageHandler.delete 异常')
            _write_error(self, -1, f'删除 agent 失败: {exc}')


class AiAgentDetailHandler(webBase.BaseHandler, ABC):
    """单个 agent 详情（含 system_prompt）。GET /quantia/api/ai/agents/detail?name=xxx"""

    def get(self):
        name = (self.get_argument('name', '') or '').strip()
        if not name:
            _write_error(self, -1, 'name 不能为空')
            return
        try:
            from quantia.lib.ai import agent_store
            agent = agent_store.get_agent(name)
            if not agent:
                _write_error(self, -1, f'agent 不存在: {name}')
                return
            self.set_header('Content-Type', 'application/json')
            self.write(json.dumps({'code': 0, 'data': agent}, ensure_ascii=False))
        except Exception as exc:
            logging.exception('AiAgentDetailHandler 异常')
            _write_error(self, -1, f'读取失败: {exc}')


# ──────────────────────────────────────────────────────────────────────
# 6) M8 多轮对话记忆：会话列表 / 详情 / 删除 / 重命名
#    GET    /quantia/api/ai/conversations            列表（最近 N 条）
#    GET    /quantia/api/ai/conversations/detail     单会话完整 messages
#    POST   /quantia/api/ai/conversations/rename     重命名
#    DELETE /quantia/api/ai/conversations            删除
# ──────────────────────────────────────────────────────────────────────
class AiConversationsHandler(webBase.BaseHandler, ABC):
    """列表 + 删除入口。"""

    def get(self):
        try:
            limit = max(1, min(200, int(self.get_argument('limit', '50'))))
        except (TypeError, ValueError):
            limit = 50
        scene = (self.get_argument('scene', '') or '').strip() or None
        only_mine = (self.get_argument('mine', '0') or '0') in ('1', 'true', 'yes')
        user_id = _client_ip(self) if only_mine else None
        try:
            mem = _get_memory()
            convs = mem.list(user_id=user_id, scene=scene, limit=limit)
            data = [c.to_summary() for c in convs]
            self.set_header('Content-Type', 'application/json')
            self.write(json.dumps({'code': 0, 'data': data}, ensure_ascii=False))
        except Exception as exc:
            logging.exception('AiConversationsHandler.get 异常')
            _write_error(self, -1, f'查询会话失败: {exc}')

    def delete(self):
        cid = (self.get_argument('conversation_id', '') or '').strip()
        if not cid:
            _write_error(self, -1, 'conversation_id 不能为空')
            return
        try:
            mem = _get_memory()
            # audit-fix-P0-2: ownership 校验
            existing = mem.get(cid)
            if existing is not None and existing.user_id and existing.user_id != _client_ip(self):
                _write_error(self, 403, f'无权删除会话: {cid}')
                return
            ok = mem.delete(cid)
            self.set_header('Content-Type', 'application/json')
            self.write(json.dumps({'code': 0, 'data': {'deleted': bool(ok)}},
                                  ensure_ascii=False))
        except Exception as exc:
            logging.exception('AiConversationsHandler.delete 异常')
            _write_error(self, -1, f'删除会话失败: {exc}')


class AiConversationDetailHandler(webBase.BaseHandler, ABC):
    def get(self):
        cid = (self.get_argument('conversation_id', '') or '').strip()
        if not cid:
            _write_error(self, -1, 'conversation_id 不能为空')
            return
        try:
            mem = _get_memory()
            conv = mem.get(cid)
            if conv is None:
                _write_error(self, -1, f'会话不存在: {cid}')
                return
            # audit-fix-P0-2: ownership 校验
            if conv.user_id and conv.user_id != _client_ip(self):
                _write_error(self, 403, f'无权访问会话: {cid}')
                return
            self.set_header('Content-Type', 'application/json')
            self.write(json.dumps({'code': 0, 'data': conv.to_dict()},
                                  ensure_ascii=False))
        except Exception as exc:
            logging.exception('AiConversationDetailHandler 异常')
            _write_error(self, -1, f'读取会话失败: {exc}')


class AiConversationRenameHandler(webBase.BaseHandler, ABC):
    def post(self):
        try:
            body = json.loads(self.request.body or b'{}')
        except Exception as exc:
            _write_error(self, -1, f'请求体解析失败: {exc}')
            return
        cid = (body.get('conversation_id') or '').strip()
        title = (body.get('title') or '').strip()
        if not cid or not title:
            _write_error(self, -1, 'conversation_id 与 title 都不能为空')
            return
        try:
            mem = _get_memory()
            # audit-fix-P0-2: ownership 校验
            existing = mem.get(cid)
            if existing is not None and existing.user_id and existing.user_id != _client_ip(self):
                _write_error(self, 403, f'无权重命名会话: {cid}')
                return
            ok = mem.rename(cid, title)
            self.set_header('Content-Type', 'application/json')
            self.write(json.dumps({'code': 0, 'data': {'renamed': bool(ok)}},
                                  ensure_ascii=False))
        except Exception as exc:
            logging.exception('AiConversationRenameHandler 异常')
            _write_error(self, -1, f'重命名会话失败: {exc}')


# ──────────────────────────────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────────────────────────────
def _build_overrides(body: dict) -> dict:
    """从请求体提取 provider/model/api_key 等覆写项。"""
    keys = ('provider', 'api_base', 'api_key', 'model', 'temperature', 'max_tokens', 'timeout')
    out = {}
    for k in keys:
        if k in body and body[k] not in (None, ''):
            out[k] = body[k]
    return out


# ──────────────────────────────────────────────────────────────────────
# 5) 策略生成（流式 SSE）  —— 文档 §4.1 / B1
#    POST /quantia/api/ai/strategy/generate/stream
#    Content-Type: text/event-stream
#    事件:  data: {"type":"chunk","text":"..."}\n\n
#           data: {"type":"done","code":"...","validated":true,"validation_error":""}\n\n
#           data: {"type":"error","code":429|-1,"msg":"..."}\n\n
# ──────────────────────────────────────────────────────────────────────
_STREAM_SENTINEL = object()


class GenerateStrategyStreamHandler(webBase.BaseHandler, ABC):
    """流式生成。后台线程消费 stream_chat()，IOLoop 协程从队列取出并 flush。"""

    @gen.coroutine
    def post(self):
        try:
            body = json.loads(self.request.body or b'{}')
        except Exception as exc:
            _write_error(self, -1, f'请求体解析失败: {exc}')
            return

        user_prompt = (body.get('prompt') or '').strip()
        if not user_prompt:
            _write_error(self, -1, 'prompt 不能为空')
            return

        overrides = _build_overrides(body)
        system = prompt_loader.load('strategy_coder')
        user_prompt = _maybe_strict_user_prompt(user_prompt)
        user_id = _client_ip(self)
        # 提前解析模型名（与 stream_chat 内部使用同一份合并配置）以回传前端
        from quantia.lib.ai.config import load_config as _load_cfg
        resolved_model = _load_cfg(overrides).model

        # SSE 响应头
        self.set_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.set_header('Cache-Control', 'no-cache')
        self.set_header('X-Accel-Buffering', 'no')

        q: 'queue.Queue' = queue.Queue(maxsize=64)
        cancel_event = threading.Event()  # E1：消费端通知生产端停止

        def _producer():
            try:
                for piece in stream_chat(
                    user_prompt, scene='strategy_gen_stream', system=system,
                    agent='strategy_coder', user_id=user_id, overrides=overrides,
                ):
                    if cancel_event.is_set():
                        break
                    try:
                        # 队列满 1s 仍未被消费 → 视为客户端落后，提前终止以释放上游连接
                        q.put(('chunk', piece), timeout=1.0)
                    except queue.Full:
                        cancel_event.set()
                        break
            except RateLimitError as exc:
                q.put(('error', {'code': 429, 'msg': f'触发限流: {exc}'}))
            except (ProviderError, AIError) as exc:
                q.put(('error', {'code': -1, 'msg': f'AI 调用失败: {exc}'}))
            except Exception as exc:
                logging.exception('GenerateStrategyStreamHandler producer 异常')
                q.put(('error', {'code': -1, 'msg': f'内部错误: {exc}'}))
            finally:
                # P0-K2：sentinel 必须送达消费端，否则消费端 q.get 会无限等待。
                # 队列若已满，先丢弃旧 chunk 释放空间再放入 sentinel。
                while True:
                    try:
                        q.put((_STREAM_SENTINEL, None), timeout=0.5)
                        break
                    except queue.Full:
                        try:
                            q.get_nowait()
                        except queue.Empty:
                            # 极端情况：消费者瞬间清空，下一轮 put 即可成功
                            continue

        threading.Thread(target=_producer, name='ai-stream-producer', daemon=True).start()

        pieces = []
        total_chars = 0
        truncated = False
        loop = IOLoop.current()
        try:
            while True:
                # E2：用共享 _AI_EXECUTOR 而不是默认线程池
                item = yield loop.run_in_executor(_get_executor(), q.get)
                kind, payload = item
                if kind is _STREAM_SENTINEL:
                    break
                if kind == 'chunk':
                    pieces.append(payload)
                    total_chars += len(payload)
                    # L2：单次生成上限 → 标记 truncated 后停止读取，但走正常 done 路径
                    # 让前端能拿到部分代码（用户可手动审阅 / 保存）。
                    if total_chars > _MAX_GENERATED_CHARS:
                        truncated = True
                        cancel_event.set()
                        # 仍写出最后一个 chunk 以便部分内容渲染
                        try:
                            self.write('data: ' + json.dumps(
                                {'type': 'chunk', 'text': payload}, ensure_ascii=False) + '\n\n')
                            yield self.flush()
                        except Exception:
                            return
                        # 排空队列、跳出 while 进入 done 流程
                        break
                    try:
                        self.write('data: ' + json.dumps(
                            {'type': 'chunk', 'text': payload}, ensure_ascii=False) + '\n\n')
                        yield self.flush()
                    except Exception:
                        # E1：客户端断开 → 通知生产端立即结束
                        cancel_event.set()
                        return
                elif kind == 'error':
                    try:
                        self.write('data: ' + json.dumps(
                            {'type': 'error', **payload}, ensure_ascii=False) + '\n\n')
                        yield self.flush()
                    except Exception:
                        pass
                    cancel_event.set()
                    return
        except Exception:
            logging.exception('GenerateStrategyStreamHandler 写出异常')
            cancel_event.set()
            return

        full = ''.join(pieces)
        code = _strip_code_fence(full)
        ok, err = _validate_or_msg(code)
        attempts = 0
        repair_status = 'success' if ok else 'unrepaired'
        max_attempts = _get_max_repair_attempts()
        # M3：流式生成完成后，如沙箱校验失败，串行做最多 N 次修复
        if not ok and not truncated and max_attempts > 0:
            repairer_sys = prompt_loader.load('strategy_repairer')
            prev_signature = (code, err)
            for _ in range(max_attempts):
                attempts += 1
                fix_prompt = _build_repair_prompt(code, err, user_prompt)
                try:
                    raw, _model = yield IOLoop.current().run_in_executor(
                        _get_executor(),
                        _call_ai_blocking,
                        fix_prompt, repairer_sys,
                        'strategy_gen_stream_repair', 'strategy_repairer',
                        _client_ip(self), overrides, True,  # rate_limit_loop
                    )
                except RateLimitError as exc:
                    logging.warning(f'SSE 修复阶段触发限流: {exc}')
                    repair_status = 'rate_limited'
                    break
                except (ProviderError, AIError) as exc:
                    logging.warning(f'SSE 修复阶段 AI 调用失败: {exc}')
                    repair_status = 'provider_error'
                    break
                try:
                    self.write('data: ' + json.dumps(
                        {'type': 'repair', 'attempt': attempts}, ensure_ascii=False) + '\n\n')
                    yield self.flush()
                except Exception:
                    return
                code = _strip_code_fence(raw)
                ok, err = _validate_or_msg(code)
                if ok:
                    repair_status = 'success'
                    full = raw  # D3：让 raw 反映最终被采用的代码来源
                    break
                signature = (code, err)
                if signature == prev_signature:
                    repair_status = 'no_progress'
                    full = raw
                    break
                prev_signature = signature
                full = raw  # 同步累计的 raw，使前端 done.raw 与 done.code 来自同一轮
            else:
                repair_status = 'max_attempts'
        try:
            self.write('data: ' + json.dumps({
                'type': 'done',
                'code': code,
                'raw': full,
                'validated': ok,
                'validation_error': err,
                'model': resolved_model,
                'repair_attempts': attempts,
                'repair_status': repair_status,
                'truncated': truncated,
            }, ensure_ascii=False) + '\n\n')
            yield self.flush()
        except Exception:
            return
