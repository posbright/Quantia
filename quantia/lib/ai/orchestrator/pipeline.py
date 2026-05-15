#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M10 Pipeline / Step：顺序 agent 管线。

设计要点（对齐 §11.4）：

* 单文件、零新增依赖；不引入 LangGraph / LangChain。
* 每个 Step 委托给现有 `quantia.lib.ai.run_agent`，因此自动复用：
    - 限流 / 审计 / token 统计
    - tool 调用循环（M6）
    - DB 中的 agent 配置（M7：system_prompt + allowed_tools）
* 步与步之间通过 `{input}` 与上一步名 `{<prev_step>}` 占位符串模板拼接。
* `loop_until` 支持"测试 → 修复"循环（如 tester step 校验代码直到通过或 max_iters）。
* PipelineError 在某一步连续 max_iters 仍未满足 loop_until 时抛出，调用方可决定是否回退。

注意：
* 为了线下/单元测试 friendly，`Pipeline.run` 接受 `_run_agent` 注入点，
  生产环境默认走 `quantia.lib.ai.run_agent`。
* 不在框架层做 prompt 缩短 / 摘要；如需控制 token，请在 agent 层面通过
  `ConversationMemory`（M8）处理。
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

__author__ = 'Quantia'
__date__ = '2026/05/12'


_DEFAULT_MAX_ITERS = 1
# 防御：单 pipeline 步数硬上限，避免误用导致 50+ 串联调用
_MAX_PIPELINE_STEPS = 16
# 防御：单 step loop 硬上限（即使用户传入更大值也截断）
_MAX_STEP_ITERS = 8


class PipelineError(Exception):
    """管线运行失败（loop_until 在 max_iters 内未满足，或步骤抛出未捕获异常）。"""

    def __init__(self, message: str, *, step_name: Optional[str] = None,
                 partial: Optional['PipelineResult'] = None):
        super().__init__(message)
        self.step_name = step_name
        self.partial = partial


@dataclass
class Step:
    """单个 pipeline 步骤定义。

    Attributes:
        name: 步骤名（在模板中可引用 `{<name>}`）。pipeline 内必须唯一。
        agent: M7 agent 名（从 DB 读 system_prompt + allowed_tools）。
        system: 显式 system prompt；同时给了 agent 与 system 时以 system 为准。
        user_template: f-string 风格模板，可用占位符 `{input}` 与 `{<prev_step>}`；
            为 None 时直接把 `input` 作为 user_message。
        allowed_tools: 显式工具白名单；None 时若 agent 指定则用 agent 的，再否则放行 registry 默认。
        loop_until: 接收当前步输出（str）+ 上下文 dict，返回 True 表示满足终止条件；
            未满足则继续重试，直到 max_iters。
        max_iters: 最大重试次数（含首次执行）；上限 _MAX_STEP_ITERS。
        overrides: 透传给 run_agent 的 overrides（如临时换模型）。
    """

    name: str
    agent: Optional[str] = None
    system: Optional[str] = None
    user_template: Optional[str] = None
    allowed_tools: Optional[List[str]] = None
    loop_until: Optional[Callable[[str, Dict[str, Any]], bool]] = None
    max_iters: int = _DEFAULT_MAX_ITERS
    overrides: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError('Step.name 必须是非空字符串')
        if self.max_iters < 1:
            raise ValueError('Step.max_iters 必须 >= 1')
        if self.max_iters > _MAX_STEP_ITERS:
            self.max_iters = _MAX_STEP_ITERS


@dataclass
class StepResult:
    name: str
    output: str
    iters: int
    ok: bool
    rounds: int = 0
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    error: Optional[str] = None


@dataclass
class PipelineResult:
    final: str
    steps: List[StepResult]
    total_latency_ms: int
    total_tokens: int = 0


class Pipeline:
    """顺序 agent 管线。

    用法：
        pl = Pipeline([
            Step('analyst', agent='strategy_analyst'),
            Step('coder',   agent='strategy_coder',
                 user_template='思路：{analyst}\\n\\n请生成代码：{input}'),
        ])
        res = pl.run(user_message='做一个布林带下轨买入策略', user_id='u1')
        print(res.final)
    """

    def __init__(self, steps: List[Step]):
        if not isinstance(steps, (list, tuple)) or not steps:
            raise ValueError('Pipeline 至少需要 1 个 Step')
        if len(steps) > _MAX_PIPELINE_STEPS:
            raise ValueError(f'Pipeline 步数超过硬上限 {_MAX_PIPELINE_STEPS}')
        names = [s.name for s in steps]
        if len(set(names)) != len(names):
            raise ValueError(f'Pipeline 中 Step.name 必须唯一，实际：{names}')
        self.steps: List[Step] = list(steps)

    def _render(self, template: Optional[str], context: Dict[str, Any]) -> str:
        if template is None:
            return str(context.get('input', ''))
        try:
            return template.format(**context)
        except KeyError as exc:
            # audit-fix-1-P3: 提供一个空 partial，避免 caller 拿到 None 踩空指针
            empty = PipelineResult(final='', steps=[], total_latency_ms=0,
                                    total_tokens=0)
            raise PipelineError(
                f'user_template 引用了未知占位符 {exc!s}；可用键：{sorted(context.keys())}',
                partial=empty,
            )

    def run(self, *, user_message: str, scene: str = 'pipeline',
            user_id: Optional[str] = None,
            overrides: Optional[Dict[str, Any]] = None,
            _run_agent=None) -> PipelineResult:
        """顺序执行所有 Step；任一步骤抛 PipelineError 时整体失败并附带 partial 结果。

        Args:
            user_message: 初始 input，也写入 context['input']。
            scene: 用于审计的场景标签；每步会在该值后追加 `:<step.name>`。
            user_id: 限流 / 审计用户标识。
            overrides: 全局 overrides，单步 step.overrides 优先级更高。
            _run_agent: 仅供测试注入；签名与 quantia.lib.ai.run_agent 一致。
        """
        if _run_agent is None:
            from quantia.lib.ai import run_agent as _run_agent  # 惰性导入避免循环

        ctx: Dict[str, Any] = {'input': user_message}
        results: List[StepResult] = []
        started_total = time.time()
        total_tokens = 0
        for step in self.steps:
            user_msg = self._render(step.user_template, ctx)
            iter_n = 0
            last_output = ''
            last_meta: Dict[str, Any] = {}
            ok_flag = False
            err_text: Optional[str] = None
            step_started = time.time()
            while iter_n < step.max_iters:
                iter_n += 1
                step_overrides = dict(overrides or {})
                if step.overrides:
                    step_overrides.update(step.overrides)
                try:
                    res = _run_agent(
                        user_message=user_msg,
                        scene=f'{scene}:{step.name}',
                        agent=step.agent,
                        system=step.system,
                        user_id=user_id,
                        overrides=step_overrides or None,
                        allowed_tools=step.allowed_tools,
                    )
                except Exception as exc:
                    err_text = str(exc)
                    logging.warning(
                        f'[ai.orchestrator] step={step.name} iter={iter_n} 失败: {exc}')
                    last_output = ''
                    break
                # res 兼容 AgentRunResult 与 dict-like
                last_output = getattr(res, 'content', None) or (
                    res.get('content') if isinstance(res, dict) else '')
                last_meta = {
                    'rounds': getattr(res, 'rounds', 0) or 0,
                    'tool_calls': list(getattr(res, 'tool_calls', None) or []),
                    'prompt_tokens': getattr(res, 'prompt_tokens', 0) or 0,
                    'completion_tokens': getattr(res, 'completion_tokens', 0) or 0,
                    'total_tokens': getattr(res, 'total_tokens', 0) or 0,
                }
                ctx[step.name] = last_output
                if step.loop_until is None:
                    ok_flag = True
                    break
                try:
                    if step.loop_until(last_output, ctx):
                        ok_flag = True
                        break
                except Exception as exc:
                    err_text = f'loop_until 抛错: {exc}'
                    logging.warning(f'[ai.orchestrator] step={step.name} {err_text}')
                    break
                # 未满足 → 把上次输出回灌为新一轮输入，附带提示
                user_msg = (
                    f'上一轮输出未通过校验，请基于以下内容继续修正：\n\n{last_output}'
                )
            sr = StepResult(
                name=step.name,
                output=last_output,
                iters=iter_n,
                ok=ok_flag,
                rounds=last_meta.get('rounds', 0),
                tool_calls=last_meta.get('tool_calls', []),
                prompt_tokens=last_meta.get('prompt_tokens', 0),
                completion_tokens=last_meta.get('completion_tokens', 0),
                total_tokens=last_meta.get('total_tokens', 0),
                latency_ms=int((time.time() - step_started) * 1000),
                error=err_text,
            )
            results.append(sr)
            total_tokens += sr.total_tokens
            if not ok_flag:
                partial = PipelineResult(
                    final=last_output,
                    steps=results,
                    total_latency_ms=int((time.time() - started_total) * 1000),
                    total_tokens=total_tokens,
                )
                raise PipelineError(
                    f'pipeline step={step.name} 未通过 loop_until / 抛错（iters={iter_n}）',
                    step_name=step.name,
                    partial=partial,
                )
        return PipelineResult(
            final=results[-1].output if results else '',
            steps=results,
            total_latency_ms=int((time.time() - started_total) * 1000),
            total_tokens=total_tokens,
        )


def run_pipeline(pipeline: Pipeline, *, user_message: str, **kwargs) -> PipelineResult:
    """便捷入口；与 Pipeline.run 等价。"""
    return pipeline.run(user_message=user_message, **kwargs)
