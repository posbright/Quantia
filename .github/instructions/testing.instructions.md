---
description: "Use when writing or editing Python tests under tests/. Covers conftest conventions, fixture patterns, DB mocking, Tornado handler testing, and excluded files."
applyTo: "tests/**/*.py"
---
# 测试编写规范

## 运行方式
- 完整测试：`pytest -q`（≈1700+ 用例）
- 单文件：`pytest tests/test_<name>.py -q`
- 前端：`cd quantia/fontWeb && npm test`

## conftest 排除列表
[tests/conftest.py](../../tests/conftest.py) 已把以下脚本式文件排除出 `pytest -q`，**不要**把它们加回来：
- `test_bugfixes.py`、`test_data_fixes.py`、`test_data_source_consistency.py`、`test_pagination.py`、`test_sector_api.py`

这些文件在 import 时就会访问网络或 DB，只能手动运行。

## 默认环境
- conftest 设 `QUANTIA_AI_MEMORY_BACKEND=inmem`，避免测试连 MySQL。
- 需要 DB 的集成测试必须显式 mock `quantia.lib.database` 或确保 `.env` 里配好了 `QUANTIA_DB_*`。

## fixture 模式
```python
@pytest.fixture
def app():
    """Tornado Application fixture"""
    return tornado.web.Application([(r"/api/xxx", XxxHandler)])

@pytest.fixture
def mock_db(monkeypatch):
    monkeypatch.setattr("quantia.lib.database.engine", MagicMock())
```

## Handler 测试
- Tornado handler 测试继承 `tornado.testing.AsyncHTTPTestCase`。
- 用 `self.get_app()` 返回 `Application` 实例。
- 参考 [tests/test_auth_handler_integration_phase8.py](../../tests/test_auth_handler_integration_phase8.py)。

## Mock 常用模式
- `unittest.mock.patch()` / `MagicMock()` / `PropertyMock()`
- AI 相关：mock `_call_ai_blocking`、task recorder、backtest engine
- 网络请求：mock crawling 函数而非 `requests` 本身
- 确定性数据：`_make_hist()` / `_fake()` 生成固定 DataFrame

## 回测纯逻辑测试
- Position / Portfolio / Context 等回测核心类用纯 Python 测试，不需要 DB。
- 参考 [tests/test_backtest_integrity.py](../../tests/test_backtest_integrity.py)。

## 新增测试须知
- DB 写入路径新增时，同步补 [tests/test_mysql_nonfinite_guard.py](../../tests/test_mysql_nonfinite_guard.py) 用例。
- 综合指标变更时，跑 `pytest tests/test_composite_*.py tests/test_hard_rules_engine.py tests/test_risk_simulator.py tests/test_dynamic_universe.py -q`。
- Smoke 验证脚本（`_verify_pr1_smoke.py`、`_verify_pr2_smoke.py`）是可运行脚本而非 pytest 用例。
