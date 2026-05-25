#!/usr/bin/env python3
"""验证 stock_profile 工具 + stockReportHandler 模块完整性。"""
import json
import os
import sys

os.environ.setdefault('QUANTIA_DB_HOST', 'localhost')
os.environ.setdefault('QUANTIA_DB_USER', 'root')
os.environ.setdefault('QUANTIA_DB_PASSWORD', '')
os.environ.setdefault('QUANTIA_DB_DATABASE', 'quantia')

errors = []

# === 1. Tool import & schema ===
print("=" * 60)
print("1. StockProfileTool import & schema")
try:
    from quantia.lib.ai.tools.stock_profile import StockProfileTool, _query_kline_30d
    from quantia.lib.ai.tools import ToolError
    tool = StockProfileTool()
    schema = tool.schema()
    assert schema['function']['name'] == 'stock_profile', f"Wrong name: {schema['function']['name']}"
    assert 'code' in schema['function']['parameters']['properties']
    print("   PASS: Tool instantiates, schema correct")
except Exception as e:
    errors.append(f"1. Tool import: {e}")
    print(f"   FAIL: {e}")

# === 2. Input validation ===
print("\n2. Input validation")
try:
    try:
        tool.run({'code': ''})
        errors.append("2a. Empty code not rejected")
    except ToolError:
        pass

    try:
        tool.run({'code': 'abc'})
        errors.append("2b. Non-digit code not rejected")
    except ToolError:
        pass

    try:
        tool.run({'code': '12345'})
        errors.append("2c. 5-digit code not rejected")
    except ToolError:
        pass

    try:
        tool.run({})
        errors.append("2d. Missing code not rejected")
    except ToolError:
        pass

    print("   PASS: All invalid inputs correctly rejected")
except Exception as e:
    errors.append(f"2. Validation: {e}")
    print(f"   FAIL: {e}")

# === 3. K-line cache reading ===
print("\n3. K-line cache reading (000001)")
try:
    result = _query_kline_30d('000001')
    assert isinstance(result, list), f"Expected list, got {type(result)}"
    assert len(result) > 0, "No data for 000001"
    assert len(result) <= 30, f"Got {len(result)} bars, expected <=30"
    bar = result[0]
    assert 'date' in bar, "Missing 'date' key"
    assert 'close' in bar, "Missing 'close' key"
    # Verify no NaN/NaT in output
    for b in result:
        for k, v in b.items():
            assert v is not None, f"None value in bar: {k}"
            if isinstance(v, str):
                assert 'NaT' not in v, f"NaT in {k}: {v}"
                assert 'nan' not in v.lower(), f"nan in {k}: {v}"
            if isinstance(v, float):
                import math
                assert not math.isnan(v), f"NaN float in {k}"
                assert not math.isinf(v), f"Inf float in {k}"
    print(f"   PASS: {len(result)} bars, date range {result[0]['date']} ~ {result[-1]['date']}")
except Exception as e:
    errors.append(f"3. K-line: {e}")
    print(f"   FAIL: {e}")

# === 4. K-line with non-existent stock ===
print("\n4. K-line with non-existent stock (999999)")
try:
    result = _query_kline_30d('999999')
    assert result == [], f"Expected empty list, got {len(result)} items"
    print("   PASS: Returns empty list for missing stock")
except Exception as e:
    errors.append(f"4. Missing stock: {e}")
    print(f"   FAIL: {e}")

# === 5. Handler imports ===
print("\n5. Handler imports")
try:
    from quantia.web.stockReportHandler import (
        StockReportGenerateHandler, StockReportHistoryHandler,
        StockReportDetailHandler, StockSearchHandler,
        _check_cache, _save_report, _write_json, _run_agent_report
    )
    print("   PASS: All handler classes and functions import")
except Exception as e:
    errors.append(f"5. Handler import: {e}")
    print(f"   FAIL: {e}")

# === 6. Web service route registration ===
print("\n6. Web service route check")
try:
    import quantia.web.web_service as ws
    source = open(ws.__file__, 'r', encoding='utf-8').read()
    routes_expected = [
        '/quantia/api/ai/report/generate',
        '/quantia/api/ai/report/history',
        '/quantia/api/ai/report/detail',
        '/quantia/api/ai/report/search_stock',
    ]
    for route in routes_expected:
        assert route in source, f"Route not registered: {route}"
    print(f"   PASS: All {len(routes_expected)} routes found in web_service.py")
except Exception as e:
    errors.append(f"6. Routes: {e}")
    print(f"   FAIL: {e}")

# === 7. Tool registry ===
print("\n7. Tool registry contains stock_profile")
try:
    from quantia.lib.ai.tools import get_registry
    registry = get_registry()
    tool_obj = registry.get('stock_profile')
    assert tool_obj is not None, "stock_profile not in registry"
    assert tool_obj.name == 'stock_profile'
    print("   PASS: stock_profile found in tool registry")
except Exception as e:
    errors.append(f"7. Registry: {e}")
    print(f"   FAIL: {e}")

# === 8. Feature switch config ===
print("\n8. Feature switch for stock_report")
try:
    from quantia.lib.ai.feature_switch import _FEATURE_SCENE_PREFIX
    assert 'stock_report' in _FEATURE_SCENE_PREFIX, \
        f"stock_report not in prefix map: {list(_FEATURE_SCENE_PREFIX.keys())}"
    print("   PASS: stock_report in feature_switch prefix map")
except Exception as e:
    errors.append(f"8. Feature switch: {e}")
    print(f"   FAIL: {e}")

# === 9. Agent prompt file ===
print("\n9. Agent prompt file")
try:
    prompt_path = os.path.join('quantia', 'lib', 'ai', 'prompt', 'stock_analyst.md')
    assert os.path.exists(prompt_path), f"Prompt file missing: {prompt_path}"
    content = open(prompt_path, 'r', encoding='utf-8').read()
    assert len(content) > 100, f"Prompt too short: {len(content)} chars"
    print(f"   PASS: stock_analyst.md exists ({len(content)} chars)")
except Exception as e:
    errors.append(f"9. Prompt: {e}")
    print(f"   FAIL: {e}")

# === 10. Frontend build artifacts ===
print("\n10. Frontend API file check")
try:
    api_path = os.path.join('quantia', 'fontWeb', 'src', 'api', 'report.ts')
    assert os.path.exists(api_path), "report.ts missing"
    api_content = open(api_path, 'r', encoding='utf-8').read()
    # Check for correct path (no double /quantia prefix)
    assert "'/quantia/api/ai/report/search_stock'" not in api_content, \
        "DOUBLE PREFIX BUG: /quantia/api path in report.ts (baseURL already adds /quantia)"
    assert "'/api/ai/report/search_stock'" in api_content, \
        "Correct path /api/ai/report/search_stock not found"
    # Check generateReportStream uses full path (raw fetch, no axios)
    assert "'/quantia/api/ai/report/generate'" in api_content, \
        "generateReportStream should use full /quantia/api path for raw fetch"
    print("   PASS: API paths are correct")
except Exception as e:
    errors.append(f"10. Frontend API: {e}")
    print(f"   FAIL: {e}")

# === 11. Vue component check ===
print("\n11. Vue component (analysis.vue)")
try:
    vue_path = os.path.join('quantia', 'fontWeb', 'src', 'views', 'stock', 'analysis.vue')
    assert os.path.exists(vue_path), "analysis.vue missing"
    vue_content = open(vue_path, 'r', encoding='utf-8').read()
    # Check mdInstance is reactive ref
    assert 'const mdInstance = ref<' in vue_content, "mdInstance should be a ref"
    assert 'let md:' not in vue_content, "Old non-reactive 'let md' should be removed"
    # Check handleGenerate parameter
    assert 'force?: boolean | MouseEvent' in vue_content, "handleGenerate should handle MouseEvent"
    assert 'forceRefresh = force === true' in vue_content, "Should normalize force param"
    # Check no res.data.items bug
    assert 'res.data?.items' not in vue_content, "Bug: res.data?.items should be res.items"
    print("   PASS: Vue component checks OK")
except Exception as e:
    errors.append(f"11. Vue: {e}")
    print(f"   FAIL: {e}")

# === 12. Router check ===
print("\n12. Router registration")
try:
    router_path = os.path.join('quantia', 'fontWeb', 'src', 'router', 'index.ts')
    router_content = open(router_path, 'r', encoding='utf-8').read()
    assert 'ai-report' in router_content or 'stock/analysis' in router_content, \
        "Report route not found in router"
    print("   PASS: Report route registered")
except Exception as e:
    errors.append(f"12. Router: {e}")
    print(f"   FAIL: {e}")

# === Summary ===
print("\n" + "=" * 60)
if errors:
    print(f"FAILED: {len(errors)} error(s)")
    for err in errors:
        print(f"  ✗ {err}")
    sys.exit(1)
else:
    print("ALL 12 CHECKS PASSED ✓")
    sys.exit(0)
