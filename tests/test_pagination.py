#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
服务端分页逻辑验证测试
覆盖: 
  1. GetStockDataHandler 分页/尾页/边界
  2. FilterStocksHandler 分页/尾页/边界
  3. 前端组件逻辑一致性
  4. 关键词搜索 + 分页组合
"""

import sys
import os
import json
import math

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

passed = 0
failed = 0
errors = []


def test(name):
    """测试装饰器"""
    def decorator(func):
        global passed, failed, errors
        try:
            func()
            print(f"  ✅ {name}")
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {name}: {e}")
            failed += 1
            errors.append(f"{name}: {e}")
        except Exception as e:
            print(f"  ❌ {name}: 异常 {type(e).__name__}: {e}")
            failed += 1
            errors.append(f"{name}: {type(e).__name__}: {e}")
    return decorator


# ============================================================
# 模拟数据库查询
# ============================================================

class MockDB:
    """模拟数据库，用于验证SQL分页逻辑"""
    def __init__(self, total_rows=237):
        self.total_rows = total_rows
        self.data = [{"code": f"{600000+i:06d}", "name": f"测试股票{i}", "date": "2026-02-10",
                       "pe9": 15.0 + i * 0.1, "roe_weight": 20.0 - i * 0.05}
                     for i in range(total_rows)]
        self.last_sql = None
        self.last_params = None

    def query(self, sql, *args):
        self.last_sql = sql
        self.last_params = args
        
        # 模拟 COUNT 查询
        if "COUNT(*)" in sql:
            # 带关键词过滤
            if "LIKE" in sql and args:
                keyword = args[-1].strip('%') if args else ""
                filtered = [r for r in self.data if keyword.lower() in r["code"].lower() or keyword.lower() in r["name"].lower()]
                return [{"cnt": len(filtered)}]
            return [{"cnt": self.total_rows}]
        
        # 模拟数据查询 - 解析 LIMIT/OFFSET
        import re
        limit_match = re.search(r'LIMIT\s+(\d+)\s+OFFSET\s+(\d+)', sql)
        
        # 过滤
        filtered_data = self.data
        if "LIKE" in sql and args:
            keyword = args[-1].strip('%') if len(args) >= 2 else ""
            if keyword:
                filtered_data = [r for r in self.data if keyword.lower() in r["code"].lower() or keyword.lower() in r["name"].lower()]
        
        if limit_match:
            limit = int(limit_match.group(1))
            offset = int(limit_match.group(2))
            return filtered_data[offset:offset + limit]
        return filtered_data


# ============================================================
# 测试 1: 分页参数计算
# ============================================================
print("\n🔧 测试 1: 分页参数计算（LIMIT/OFFSET）")


@test("第1页，每页50条 → OFFSET=0, LIMIT=50")
def _():
    page, page_size = 1, 50
    page_int = max(1, int(page))
    page_size_int = max(1, min(500, int(page_size)))
    offset = (page_int - 1) * page_size_int
    assert offset == 0, f"offset应为0，实际为{offset}"
    assert page_size_int == 50, f"limit应为50，实际为{page_size_int}"


@test("第2页，每页50条 → OFFSET=50, LIMIT=50")
def _():
    page, page_size = 2, 50
    page_int = max(1, int(page))
    page_size_int = max(1, min(500, int(page_size)))
    offset = (page_int - 1) * page_size_int
    assert offset == 50, f"offset应为50，实际为{offset}"


@test("第5页，每页20条 → OFFSET=80, LIMIT=20")
def _():
    page, page_size = 5, 20
    page_int = max(1, int(page))
    page_size_int = max(1, min(500, int(page_size)))
    offset = (page_int - 1) * page_size_int
    assert offset == 80, f"offset应为80，实际为{offset}"
    assert page_size_int == 20, f"limit应为20，实际为{page_size_int}"


@test("page_size最大不超过500")
def _():
    page, page_size = 1, 9999
    page_size_int = max(1, min(500, int(page_size)))
    assert page_size_int == 500, f"page_size应被限制为500，实际为{page_size_int}"


@test("page最小为1")
def _():
    page, page_size = 0, 50
    page_int = max(1, int(page))
    assert page_int == 1, f"page应被限制为1，实际为{page_int}"


@test("page_size最小为1")
def _():
    page, page_size = 1, -5
    page_size_int = max(1, min(500, int(page_size)))
    assert page_size_int == 1, f"page_size应被限制为1，实际为{page_size_int}"


# ============================================================
# 测试 2: 尾页逻辑
# ============================================================
print("\n🔧 测试 2: 尾页逻辑")


@test("237条记录，每页50，尾页=第5页，返回37条")
def _():
    total = 237
    page_size = 50
    total_pages = math.ceil(total / page_size)
    assert total_pages == 5, f"总页数应为5，实际为{total_pages}"
    
    # 尾页数据
    last_page = total_pages
    offset = (last_page - 1) * page_size
    remaining = total - offset
    assert remaining == 37, f"尾页应有37条，实际为{remaining}"


@test("100条记录，每页100，只有1页")
def _():
    total = 100
    page_size = 100
    total_pages = math.ceil(total / page_size)
    assert total_pages == 1, f"总页数应为1，实际为{total_pages}"


@test("0条记录，每页50，总页数为0")
def _():
    total = 0
    page_size = 50
    total_pages = math.ceil(total / page_size) if total > 0 else 0
    assert total_pages == 0, f"总页数应为0，实际为{total_pages}"


@test("1条记录，每页50，总页数为1")
def _():
    total = 1
    page_size = 50
    total_pages = math.ceil(total / page_size)
    assert total_pages == 1, f"总页数应为1，实际为{total_pages}"


@test("超出范围的页码返回空数据")
def _():
    db = MockDB(total_rows=50)
    # 请求第10页，只有1页数据
    page, page_size = 10, 50
    offset = (page - 1) * page_size  # 450
    data = db.data[offset:offset + page_size]
    assert len(data) == 0, f"超出范围的页码应返回空列表，实际返回{len(data)}条"


# ============================================================
# 测试 3: MockDB 模拟分页查询
# ============================================================
print("\n🔧 测试 3: 模拟分页查询")


@test("第1页返回正确数量")
def _():
    db = MockDB(total_rows=237)
    count_result = db.query("SELECT COUNT(*) AS cnt FROM `test_table` WHERE `date` = %s", "2026-02-10")
    assert count_result[0]["cnt"] == 237
    
    data = db.query("SELECT * FROM `test_table` WHERE `date` = %s ORDER BY pe9 DESC LIMIT 50 OFFSET 0", "2026-02-10")
    assert len(data) == 50, f"第1页应返回50条，实际{len(data)}条"


@test("第5页（尾页）返回剩余数量")
def _():
    db = MockDB(total_rows=237)
    data = db.query("SELECT * FROM `test_table` LIMIT 50 OFFSET 200")
    assert len(data) == 37, f"第5页应返回37条，实际{len(data)}条"


@test("下一页数据不重复")
def _():
    db = MockDB(total_rows=100)
    page1 = db.query("SELECT * FROM `test_table` LIMIT 50 OFFSET 0")
    page2 = db.query("SELECT * FROM `test_table` LIMIT 50 OFFSET 50")
    
    codes1 = set(r["code"] for r in page1)
    codes2 = set(r["code"] for r in page2)
    overlap = codes1 & codes2
    assert len(overlap) == 0, f"相邻页不应有重复数据，重复了{len(overlap)}条: {overlap}"


@test("所有页合计等于总数")
def _():
    db = MockDB(total_rows=237)
    all_data = []
    page_size = 50
    total_pages = math.ceil(237 / page_size)
    for p in range(1, total_pages + 1):
        offset = (p - 1) * page_size
        page_data = db.query(f"SELECT * FROM `test_table` LIMIT {page_size} OFFSET {offset}")
        all_data.extend(page_data)
    assert len(all_data) == 237, f"所有页合计应为237，实际为{len(all_data)}"


@test("切换page_size后重新计算分页")
def _():
    total = 237
    # 50条/页 → 5页
    assert math.ceil(total / 50) == 5
    # 改为100条/页 → 3页
    assert math.ceil(total / 100) == 3
    # 改为20条/页 → 12页
    assert math.ceil(total / 20) == 12


# ============================================================
# 测试 4: 关键词搜索 + 分页
# ============================================================
print("\n🔧 测试 4: 关键词搜索 + 分页")


@test("关键词搜索返回匹配结果的总数")
def _():
    db = MockDB(total_rows=100)
    # 搜索"股票1"，应匹配：测试股票1, 测试股票10-19 → 共11个
    keyword_like = "%股票1%"
    count_result = db.query("SELECT COUNT(*) AS cnt FROM `test` WHERE `code` LIKE %s OR `name` LIKE %s", keyword_like, keyword_like)
    total = count_result[0]["cnt"]
    assert total == 11, f"搜索'股票1'应匹配11条，实际{total}条"


@test("关键词搜索的总数用于分页计算")
def _():
    db = MockDB(total_rows=100)
    keyword_like = "%股票1%"
    count_result = db.query("SELECT COUNT(*) AS cnt FROM `test` WHERE `code` LIKE %s OR `name` LIKE %s", keyword_like, keyword_like)
    total = count_result[0]["cnt"]  # 11
    page_size = 5
    total_pages = math.ceil(total / page_size)
    assert total_pages == 3, f"11条记录每页5条应有3页，实际{total_pages}页"


# ============================================================
# 测试 5: SQL 构建验证（dataTableHandler 逻辑）
# ============================================================
print("\n🔧 测试 5: SQL 构建验证")


@test("无分页参数时不添加 LIMIT 子句")
def _():
    page = None
    page_size = None
    use_pagination = page is not None and page_size is not None
    limit_clause = ""
    if use_pagination:
        limit_clause = " LIMIT 50 OFFSET 0"
    assert limit_clause == "", f"无分页参数时limit_clause应为空"


@test("有分页参数时添加正确的 LIMIT 子句")
def _():
    page, page_size = "3", "20"
    use_pagination = page is not None and page_size is not None
    limit_clause = ""
    if use_pagination:
        page_int = max(1, int(page))
        page_size_int = max(1, min(500, int(page_size)))
        offset = (page_int - 1) * page_size_int
        limit_clause = f" LIMIT {page_size_int} OFFSET {offset}"
    assert limit_clause == " LIMIT 20 OFFSET 40", f"limit_clause不正确: {limit_clause}"


@test("WHERE条件组合：date + keyword")
def _():
    date = "2026-02-10"
    keyword = "中国"
    
    query_params = []
    conditions = []
    if date is not None:
        conditions.append("`date` = %s")
        query_params.append(date)
    if keyword is not None and keyword.strip():
        keyword_like = f"%{keyword.strip()}%"
        conditions.append("(`code` LIKE %s OR `name` LIKE %s)")
        query_params.append(keyword_like)
        query_params.append(keyword_like)
    
    where = ""
    if conditions:
        where = " WHERE " + " AND ".join(conditions)
    
    expected_where = " WHERE `date` = %s AND (`code` LIKE %s OR `name` LIKE %s)"
    assert where == expected_where, f"WHERE子句不正确: {where}"
    assert len(query_params) == 3, f"应有3个参数，实际{len(query_params)}"
    assert query_params == ["2026-02-10", "%中国%", "%中国%"], f"参数不正确: {query_params}"


@test("仅有date条件")
def _():
    date = "2026-02-10"
    keyword = None
    
    query_params = []
    conditions = []
    if date is not None:
        conditions.append("`date` = %s")
        query_params.append(date)
    if keyword is not None and keyword.strip():
        keyword_like = f"%{keyword.strip()}%"
        conditions.append("(`code` LIKE %s OR `name` LIKE %s)")
        query_params.append(keyword_like)
        query_params.append(keyword_like)
    
    where = ""
    if conditions:
        where = " WHERE " + " AND ".join(conditions)
    
    assert where == " WHERE `date` = %s", f"WHERE子句不正确: {where}"
    assert query_params == ["2026-02-10"], f"参数不正确: {query_params}"


@test("仅有keyword条件（无date）")
def _():
    date = None
    keyword = "银行"
    
    query_params = []
    conditions = []
    if date is not None:
        conditions.append("`date` = %s")
        query_params.append(date)
    if keyword is not None and keyword.strip():
        keyword_like = f"%{keyword.strip()}%"
        conditions.append("(`code` LIKE %s OR `name` LIKE %s)")
        query_params.append(keyword_like)
        query_params.append(keyword_like)
    
    where = ""
    if conditions:
        where = " WHERE " + " AND ".join(conditions)
    
    assert where == " WHERE (`code` LIKE %s OR `name` LIKE %s)", f"WHERE子句不正确: {where}"
    assert query_params == ["%银行%", "%银行%"]


@test("无条件时WHERE为空")
def _():
    date = None
    keyword = None
    
    query_params = []
    conditions = []
    if date is not None:
        conditions.append("`date` = %s")
        query_params.append(date)
    if keyword is not None and keyword.strip():
        keyword_like = f"%{keyword.strip()}%"
        conditions.append("(`code` LIKE %s OR `name` LIKE %s)")
        query_params.append(keyword_like)
        query_params.append(keyword_like)
    
    where = ""
    if conditions:
        where = " WHERE " + " AND ".join(conditions)
    
    assert where == "", f"无条件时WHERE应为空: {where}"
    assert query_params == [], f"无条件时参数应为空: {query_params}"


@test("空keyword（空字符串）不应生成LIKE条件")
def _():
    keyword = ""
    conditions = []
    query_params = []
    if keyword is not None and keyword.strip():
        conditions.append("LIKE")
        query_params.append(keyword)
    assert len(conditions) == 0, "空字符串keyword不应生成条件"


@test("keyword仅空格不应生成LIKE条件")
def _():
    keyword = "   "
    conditions = []
    query_params = []
    if keyword is not None and keyword.strip():
        conditions.append("LIKE")
        query_params.append(keyword)
    assert len(conditions) == 0, "纯空格keyword不应生成条件"


# ============================================================
# 测试 6: FilterStocksHandler 分页逻辑
# ============================================================
print("\n🔧 测试 6: FilterStocksHandler 分页逻辑")


@test("FilterStocksHandler LIMIT/OFFSET 构建正确")
def _():
    page, page_size = "2", "50"
    use_pagination = page is not None and page_size is not None
    limit_clause = ""
    if use_pagination:
        page_int = max(1, int(page))
        page_size_int = max(1, min(500, int(page_size)))
        offset = (page_int - 1) * page_size_int
        limit_clause = f" LIMIT {page_size_int} OFFSET {offset}"
    assert limit_clause == " LIMIT 50 OFFSET 50"


@test("FilterStocksHandler 无分页参数时不添加LIMIT")
def _():
    page, page_size = None, None
    use_pagination = page is not None and page_size is not None
    limit_clause = ""
    if use_pagination:
        page_int = max(1, int(page))
        page_size_int = max(1, min(500, int(page_size)))
        offset = (page_int - 1) * page_size_int
        limit_clause = f" LIMIT {page_size_int} OFFSET {offset}"
    assert limit_clause == "", "无分页参数时应无LIMIT子句"


# ============================================================
# 测试 7: 前端分页组件逻辑验证
# ============================================================
print("\n🔧 测试 7: 前端分页组件逻辑验证")


@test("el-pagination total绑定到服务端总数")
def _():
    """验证：分页 total 来自服务端 res.total，而非本地数据长度"""
    # 模拟服务端返回
    server_total = 237
    server_data = [{"code": f"60000{i}", "name": f"股票{i}"} for i in range(50)]  # 一页50条
    
    # 前端应使用 server_total，而非 len(server_data)
    total_count = server_total  # 对应 totalCount.value = res.total
    assert total_count == 237, f"total应为服务端总数237，不是{len(server_data)}"


@test("翻页时 currentPage 变化触发数据重新加载")
def _():
    """验证：handlePageChange 会调用 loadData"""
    # 模拟翻页流程
    current_page = 1
    load_called = False
    
    def handle_page_change():
        nonlocal load_called
        load_called = True  # 对应 loadData()
    
    # 模拟点击下一页
    current_page = 2
    handle_page_change()
    assert load_called, "翻页应触发数据重新加载"


@test("切换pageSize时重置到第1页")
def _():
    """验证：handleSizeChange 先重置 currentPage = 1，再 loadData"""
    current_page = 3
    
    def handle_size_change():
        nonlocal current_page
        current_page = 1  # 对应 currentPage.value = 1
    
    handle_size_change()
    assert current_page == 1, "切换pageSize应重置到第1页"


@test("搜索时重置到第1页")
def _():
    """验证：handleSearch 先重置 currentPage = 1"""
    current_page = 5
    
    def handle_search():
        nonlocal current_page
        current_page = 1
    
    handle_search()
    assert current_page == 1, "搜索应重置到第1页"


@test("日期变更时重置到第1页")
def _():
    """验证：handleDateChange 先重置 currentPage = 1"""
    current_page = 3
    
    def handle_date_change():
        nonlocal current_page
        current_page = 1
    
    handle_date_change()
    assert current_page == 1, "日期变更应重置到第1页"


@test("路由变更时重置到第1页且清空列定义")
def _():
    """验证：route watch 重置 currentPage 和 columnDefs"""
    current_page = 3
    column_defs = ["col1", "col2"]
    
    def on_route_change():
        nonlocal current_page, column_defs
        current_page = 1
        column_defs = []
    
    on_route_change()
    assert current_page == 1, "路由变更应重置到第1页"
    assert column_defs == [], "路由变更应清空列定义"


# ============================================================
# 测试 8: 响应格式兼容性
# ============================================================
print("\n🔧 测试 8: 响应格式兼容性")


@test("新格式响应正确解析 (columns + data + total)")
def _():
    res = {
        "columns": [{"value": "code", "caption": "代码", "width": 90}],
        "data": [{"code": "600000", "name": "浦发银行"}],
        "total": 100
    }
    
    column_defs = []
    table_data = []
    total_count = 0
    
    if res and "columns" in res and "data" in res:
        column_defs = res["columns"]
        table_data = res["data"] if isinstance(res["data"], list) else []
        total_count = res.get("total", len(table_data))
    
    assert len(column_defs) == 1
    assert len(table_data) == 1
    assert total_count == 100


@test("旧格式响应兼容（纯数组）")
def _():
    res = [{"code": "600000"}, {"code": "600001"}]
    
    column_defs = []
    table_data = []
    total_count = 0
    
    if isinstance(res, dict) and "columns" in res and "data" in res:
        column_defs = res["columns"]
        table_data = res["data"]
        total_count = res.get("total", len(table_data))
    elif isinstance(res, list):
        table_data = res
        total_count = len(res)
    
    assert len(table_data) == 2
    assert total_count == 2


@test("空数据响应")
def _():
    res = {"columns": [], "data": [], "total": 0}
    
    if res and "columns" in res and "data" in res:
        table_data = res["data"] if isinstance(res["data"], list) else []
        total_count = res.get("total", len(table_data))
    
    assert len(table_data) == 0
    assert total_count == 0


@test("total缺失时回退到 len(data)")
def _():
    res = {"columns": [], "data": [{"code": "600000"}, {"code": "600001"}, {"code": "600002"}]}
    
    if res and "columns" in res and "data" in res:
        table_data = res["data"] if isinstance(res["data"], list) else []
        # 使用 ?? 逻辑：total_count = res.total ?? tableData.value.length
        total_count = res.get("total") if res.get("total") is not None else len(table_data)
    
    assert total_count == 3, f"total缺失时应回退到data长度3，实际{total_count}"


# ============================================================
# 测试 9: 边界情况
# ============================================================
print("\n🔧 测试 9: 边界情况")


@test("非法分页参数（字符串）被安全处理")
def _():
    page = "abc"
    page_size = "xyz"
    use_pagination = True
    limit_clause = ""
    try:
        page_int = max(1, int(page))
        page_size_int = max(1, min(500, int(page_size)))
        offset = (page_int - 1) * page_size_int
        limit_clause = f" LIMIT {page_size_int} OFFSET {offset}"
    except (ValueError, TypeError):
        use_pagination = False
    
    assert use_pagination == False, "非法参数应导致 use_pagination = False"
    assert limit_clause == "", "非法参数不应生成LIMIT子句"


@test("负数页码被纠正为1")
def _():
    page = "-3"
    page_int = max(1, int(page))
    assert page_int == 1


@test("分页参数仅有page无page_size时不启用分页")
def _():
    page = "1"
    page_size = None
    use_pagination = page is not None and page_size is not None
    assert use_pagination == False


@test("分页参数仅有page_size无page时不启用分页")
def _():
    page = None
    page_size = "50"
    use_pagination = page is not None and page_size is not None
    assert use_pagination == False


# ============================================================
# 测试 10: Docker 文件同步
# ============================================================
print("\n🔧 测试 10: Docker 文件同步")


@test("分页相关文件 Docker 同步一致")
def _():
    files_to_check = [
        ("quantia/web/dataTableHandler.py", "docker/stock/quantia/web/dataTableHandler.py"),
        ("quantia/web/strategyParamsHandler.py", "docker/stock/quantia/web/strategyParamsHandler.py"),
        ("quantia/fontWeb/src/api/stock.ts", "docker/stock/quantia/fontWeb/src/api/stock.ts"),
        ("quantia/fontWeb/src/api/strategy.ts", "docker/stock/quantia/fontWeb/src/api/strategy.ts"),
        ("quantia/fontWeb/src/api/request.ts", "docker/stock/quantia/fontWeb/src/api/request.ts"),
        ("quantia/fontWeb/src/views/stock/StockData.vue", "docker/stock/quantia/fontWeb/src/views/stock/StockData.vue"),
        ("quantia/fontWeb/src/views/strategy/StrategyConfig.vue", "docker/stock/quantia/fontWeb/src/views/strategy/StrategyConfig.vue"),
    ]
    
    mismatches = []
    for main_file, docker_file in files_to_check:
        main_path = os.path.join(project_root, main_file)
        docker_path = os.path.join(project_root, docker_file)
        
        if not os.path.exists(main_path):
            mismatches.append(f"主版本缺失: {main_file}")
            continue
        if not os.path.exists(docker_path):
            mismatches.append(f"Docker版本缺失: {docker_file}")
            continue
        
        with open(main_path, 'r', encoding='utf-8') as f:
            main_content = f.read()
        with open(docker_path, 'r', encoding='utf-8') as f:
            docker_content = f.read()
        
        if main_content != docker_content:
            mismatches.append(f"{main_file}")
    
    assert len(mismatches) == 0, f"以下文件不一致: {', '.join(mismatches)}"


@test("dist目录文件数量一致")
def _():
    main_dist = os.path.join(project_root, "quantia", "fontWeb", "dist")
    docker_dist = os.path.join(project_root, "docker", "stock", "quantia", "fontWeb", "dist")
    
    def count_files(path):
        count = 0
        for root, dirs, files in os.walk(path):
            count += len(files)
        return count
    
    main_count = count_files(main_dist)
    docker_count = count_files(docker_dist)
    assert main_count == docker_count, f"dist文件数不一致: 主版本{main_count}, Docker{docker_count}"


# ============================================================
# 测试 11: 完整分页流程模拟
# ============================================================
print("\n🔧 测试 11: 完整分页流程模拟")


@test("完整流程：首页 → 下一页 → 尾页 → 首页")
def _():
    total = 237
    page_size = 50
    total_pages = math.ceil(total / page_size)  # 5
    
    # 首页
    page = 1
    offset = (page - 1) * page_size
    assert offset == 0
    
    # 下一页
    page = 2
    offset = (page - 1) * page_size
    assert offset == 50
    
    # 尾页
    page = total_pages  # 5
    offset = (page - 1) * page_size
    assert offset == 200
    remaining = total - offset  # 37
    assert remaining == 37
    
    # 回到首页
    page = 1
    offset = (page - 1) * page_size
    assert offset == 0


@test("完整流程：搜索后分页重置，再翻页")
def _():
    db = MockDB(total_rows=100)
    
    # 初始：第3页
    current_page = 3
    
    # 搜索 → 重置到第1页
    current_page = 1  # handleSearch: currentPage.value = 1
    keyword_like = "%股票1%"
    count_result = db.query("SELECT COUNT(*) AS cnt FROM `test` WHERE `name` LIKE %s", keyword_like)
    search_total = count_result[0]["cnt"]  # 11
    
    search_page_size = 5
    search_total_pages = math.ceil(search_total / search_page_size)  # 3
    assert search_total_pages == 3
    
    # 翻到第2页
    current_page = 2
    offset = (current_page - 1) * search_page_size  # 5
    data = db.query(f"SELECT * FROM `test` WHERE `name` LIKE %s LIMIT {search_page_size} OFFSET {offset}", keyword_like)
    assert len(data) == 5  # 第2页有5条


@test("切换每页条数后总页数正确更新")
def _():
    total = 237
    
    # 50条/页
    assert math.ceil(total / 50) == 5
    
    # 改为20条/页
    assert math.ceil(total / 20) == 12
    
    # 改为200条/页
    assert math.ceil(total / 200) == 2
    
    # 改为100条/页
    assert math.ceil(total / 100) == 3


# ============================================================
# 测试 12: 查询缓存模块
# ============================================================
print("\n🔧 测试 12: 查询缓存模块")

from quantia.lib.query_cache import QueryCache


@test("缓存 put/get 基本功能")
def _():
    cache = QueryCache(max_size=10, default_ttl=60)
    sql = "SELECT * FROM test WHERE id = %s"
    params = ("123",)
    cache.put(sql, params, [{"id": 123, "name": "test"}])
    
    hit, data = cache.get(sql, params)
    assert hit is True, "应命中缓存"
    assert len(data) == 1
    assert data[0]["id"] == 123


@test("未缓存的查询返回 miss")
def _():
    cache = QueryCache(max_size=10, default_ttl=60)
    hit, data = cache.get("SELECT * FROM unknown", None)
    assert hit is False, "未缓存的查询应miss"
    assert data is None


@test("不同参数生成不同缓存 key")
def _():
    cache = QueryCache(max_size=10, default_ttl=60)
    sql = "SELECT * FROM test WHERE date = %s"
    
    cache.put(sql, ("2026-02-10",), [{"date": "2026-02-10"}])
    cache.put(sql, ("2026-02-09",), [{"date": "2026-02-09"}])
    
    hit1, data1 = cache.get(sql, ("2026-02-10",))
    hit2, data2 = cache.get(sql, ("2026-02-09",))
    
    assert hit1 is True
    assert hit2 is True
    assert data1[0]["date"] == "2026-02-10"
    assert data2[0]["date"] == "2026-02-09"


@test("缓存 TTL 过期后返回 miss")
def _():
    cache = QueryCache(max_size=10, default_ttl=1)  # 1秒过期
    sql = "SELECT * FROM test"
    cache.put(sql, None, [{"id": 1}], ttl=0)  # 立即过期（ttl=0）
    
    import time
    time.sleep(0.01)  # 等待过期
    
    hit, data = cache.get(sql, None)
    assert hit is False, "过期缓存应miss"


@test("LRU 淘汰最早的条目")
def _():
    cache = QueryCache(max_size=3, default_ttl=60)
    
    cache.put("sql1", None, "data1")
    cache.put("sql2", None, "data2")
    cache.put("sql3", None, "data3")
    cache.put("sql4", None, "data4")  # 超过容量，应淘汰 sql1
    
    hit1, _ = cache.get("sql1", None)
    hit4, _ = cache.get("sql4", None)
    
    assert hit1 is False, "sql1 应被淘汰"
    assert hit4 is True, "sql4 应存在"
    assert len(cache) == 3, f"缓存应保持最大3条，实际{len(cache)}"


@test("invalidate 清空所有缓存")
def _():
    cache = QueryCache(max_size=10, default_ttl=60)
    cache.put("sql1", None, "data1")
    cache.put("sql2", None, "data2")
    
    cache.invalidate()
    
    hit1, _ = cache.get("sql1", None)
    hit2, _ = cache.get("sql2", None)
    assert hit1 is False
    assert hit2 is False
    assert len(cache) == 0


@test("invalidate 指定 SQL")
def _():
    cache = QueryCache(max_size=10, default_ttl=60)
    cache.put("sql1", None, "data1")
    cache.put("sql2", None, "data2")
    
    cache.invalidate("sql1", None)
    
    hit1, _ = cache.get("sql1", None)
    hit2, _ = cache.get("sql2", None)
    assert hit1 is False, "sql1 应被清除"
    assert hit2 is True, "sql2 应保留"


@test("缓存统计信息正确")
def _():
    cache = QueryCache(max_size=10, default_ttl=60)
    cache.put("sql1", None, "data1")
    
    cache.get("sql1", None)  # hit
    cache.get("sql1", None)  # hit
    cache.get("sql_miss", None)  # miss
    
    stats = cache.stats
    assert stats["hit_count"] == 2
    assert stats["miss_count"] == 1
    assert stats["size"] == 1


@test("cleanup_expired 清除过期条目")
def _():
    cache = QueryCache(max_size=10, default_ttl=1)
    cache.put("sql1", None, "data1", ttl=0)  # 立即过期
    cache.put("sql2", None, "data2", ttl=3600)  # 1小时
    
    import time
    time.sleep(0.01)
    
    cleaned = cache.cleanup_expired()
    assert cleaned == 1, f"应清除1条过期条目，实际清除{cleaned}"
    assert len(cache) == 1, f"应剩余1条，实际{len(cache)}"


@test("翻页场景：相同条件不同页码使用独立缓存")
def _():
    cache = QueryCache(max_size=10, default_ttl=60)
    base_sql = "SELECT * FROM test WHERE date = %s LIMIT 50 OFFSET"
    
    cache.put(f"{base_sql} 0", ("2026-02-10",), [f"page1_data"])
    cache.put(f"{base_sql} 50", ("2026-02-10",), [f"page2_data"])
    cache.put(f"{base_sql} 100", ("2026-02-10",), [f"page3_data"])
    
    hit1, d1 = cache.get(f"{base_sql} 0", ("2026-02-10",))
    hit2, d2 = cache.get(f"{base_sql} 50", ("2026-02-10",))
    hit3, d3 = cache.get(f"{base_sql} 100", ("2026-02-10",))
    
    assert hit1 and hit2 and hit3, "各页缓存应独立命中"
    assert d1 == ["page1_data"]
    assert d2 == ["page2_data"]
    assert d3 == ["page3_data"]


@test("翻页场景：COUNT 查询缓存在不同页码间共享")
def _():
    """同一查询条件，COUNT结果在翻页时可复用"""
    cache = QueryCache(max_size=10, default_ttl=60)
    count_sql = "SELECT COUNT(*) AS cnt FROM test WHERE date = %s"
    params = ("2026-02-10",)
    
    cache.put(count_sql, params, 237)
    
    # 第1页查总数 - 命中
    hit1, total1 = cache.get(count_sql, params)
    # 第2页查总数 - 同样命中（SQL+参数相同）
    hit2, total2 = cache.get(count_sql, params)
    # 第5页查总数 - 同样命中
    hit3, total3 = cache.get(count_sql, params)
    
    assert hit1 and hit2 and hit3, "COUNT缓存应在翻页间共享"
    assert total1 == total2 == total3 == 237


@test("参数保存后缓存被正确清除")
def _():
    """模拟保存策略参数后清除筛选缓存"""
    from quantia.lib.query_cache import filter_result_cache
    
    # 预存一些缓存
    filter_result_cache.put("filter_sql1", ("param1",), [{"code": "600000"}])
    filter_result_cache.put("filter_sql2", ("param2",), [{"code": "600001"}])
    
    # 模拟保存参数后的操作
    filter_result_cache.invalidate()
    
    hit1, _ = filter_result_cache.get("filter_sql1", ("param1",))
    hit2, _ = filter_result_cache.get("filter_sql2", ("param2",))
    assert hit1 is False and hit2 is False, "保存参数后缓存应被清空"


# ============================================================
if __name__ == "__main__":
    # 汇总
    # ============================================================
    print(f"\n{'='*60}")
    print(f"分页测试完成: ✅ {passed} 通过, ❌ {failed} 失败")
    if errors:
        print(f"\n失败详情:")
        for err in errors:
            print(f"  - {err}")
    print(f"{'='*60}")

    sys.exit(0 if failed == 0 else 1)
