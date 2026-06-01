# -*- coding: utf-8 -*-
"""场外基金分析核心（F7 多因子评分 / F11 同类评比 / F13 综合分析）。

纯函数 + 共享阈值常量，只读语义、不触外部 API、不依赖 DB，
便于单测与 analysis/web 复用（管道分离：抓取在 fetch 管道，此处只做计算）。
"""

from . import scoring  # noqa: F401
from . import labels  # noqa: F401
