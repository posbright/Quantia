#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M10 Agent 编排：顺序管线 + 内置预设。

入口：
    from quantia.lib.ai.orchestrator import Pipeline, Step, run_pipeline
    from quantia.lib.ai.orchestrator.presets import STRATEGY_PIPELINE
"""

from quantia.lib.ai.orchestrator.pipeline import (
    Pipeline,
    PipelineError,
    PipelineResult,
    Step,
    StepResult,
    run_pipeline,
)

__all__ = [
    'Pipeline', 'Step', 'StepResult', 'PipelineResult',
    'PipelineError', 'run_pipeline',
]
