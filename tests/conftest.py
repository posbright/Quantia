"""Pytest configuration for this repo.

The `tests/` folder contains a mix of:
- pytest-style unit tests (safe to collect)
- standalone script-style validation scripts (run on import, may hit network/DB)

To keep `pytest` stable and fast, we explicitly ignore script-style files.
They can still be run manually via `python tests/<script>.py`.
"""

import os

# spec §11.3 / §M8：测试环境默认走 inmem 后端，避免命中 MySQL；
# 真正的 DB 行为由 tests/test_ai_m8_conversation_memory.py 中通过 mock 验证。
os.environ.setdefault('QUANTIA_AI_MEMORY_BACKEND', 'inmem')

collect_ignore = [
    'test_bugfixes.py',
    'test_data_fixes.py',
    'test_data_source_consistency.py',
    'test_pagination.py',
    'test_sector_api.py',
]
