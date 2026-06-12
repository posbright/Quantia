#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import json
import logging
import re
from abc import ABC
from tornado import gen
import datetime
import quantia.lib.trade_time as trd
import quantia.core.singleton_stock_web_module_data as sswmd
import quantia.web.base as webBase
from quantia.lib.query_cache import stock_data_cache

__author__ = 'Quantia'
__date__ = '2026/02/14'

# 合法的 SQL 标识符：只允许字母、数字、下划线
_SAFE_IDENTIFIER_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


class MyEncoder(json.JSONEncoder):

    def default(self, obj):
        if isinstance(obj, bytes):
            return "是" if ord(obj) == 1 else "否"
        elif isinstance(obj, datetime.datetime):
            # datetime 对象转为 ISO 格式字符串
            return obj.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(obj, datetime.date):
            # date 对象转为 YYYY-MM-DD 格式字符串
            return obj.strftime("%Y-%m-%d")
        else:
            return json.JSONEncoder.default(self, obj)


# 获得页面数据。
class GetStockHtmlHandler(webBase.BaseHandler, ABC):
    @gen.coroutine
    def get(self):
        name = self.get_argument("table_name", default=None, strip=False)
        web_module_data = sswmd.stock_web_module_data().get_data(name)
        if web_module_data is None:
            self.set_status(404)
            self.write(f"未找到数据模块: {name}")
            return
        run_date, run_date_nph = trd.get_trade_date_last()
        if web_module_data.is_realtime:
            date_now_str = run_date_nph.strftime("%Y-%m-%d")
        else:
            date_now_str = run_date.strftime("%Y-%m-%d")
        self.render("stock_web.html", web_module_data=web_module_data, date_now=date_now_str,
                    leftMenu=webBase.GetLeftMenu(self.request.uri))


# 获得股票数据内容。
class GetStockDataHandler(webBase.BaseHandler, ABC):
    def get(self):
        name = self.get_argument("name", default=None, strip=False)
        date = self.get_argument("date", default=None, strip=False)
        page = self.get_argument("page", default=None, strip=True)
        page_size = self.get_argument("page_size", default=None, strip=True)
        keyword = self.get_argument("keyword", default=None, strip=True)
        sort = self.get_argument("sort", default=None, strip=True)
        order = self.get_argument("order", default=None, strip=True)
        self.set_header('Content-Type', 'application/json;charset=UTF-8')

        # 参数验证
        if name is None:
            self.set_status(400)
            self.write(json.dumps({"error": "缺少必要参数 name", "code": 400}))
            return

        web_module_data = sswmd.stock_web_module_data().get_data(name)
        if web_module_data is None:
            self.set_status(404)
            self.write(json.dumps({"error": f"未找到数据模块: {name}", "code": 404}))
            return

        # 白名单验证表名，防止 SQL 注入（即使配置数据源被篡改也安全）
        if not _SAFE_IDENTIFIER_RE.match(web_module_data.table_name):
            self.set_status(400)
            self.write(json.dumps({"error": "非法表名", "code": 400}))
            return

        query_params = []
        conditions = []
        actual_date = date  # 实际使用的日期（可能回退）
        table_missing = False  # 表是否不存在
        if date is not None:
            conditions.append("`date` = %s")
            query_params.append(date)

        # 关键词搜索（代码/名称模糊匹配）
        if keyword is not None and keyword.strip():
            keyword_like = f"%{keyword.strip()}%"
            has_code = 'code' in web_module_data.columns
            has_name = 'name' in web_module_data.columns
            if has_code and has_name:
                conditions.append("(`code` LIKE %s OR `name` LIKE %s)")
                query_params.append(keyword_like)
                query_params.append(keyword_like)
            elif has_code:
                conditions.append("`code` LIKE %s")
                query_params.append(keyword_like)
            elif has_name:
                conditions.append("`name` LIKE %s")
                query_params.append(keyword_like)

        where = ""
        if conditions:
            where = " WHERE " + " AND ".join(conditions)

        # 自定义排序：sort 必须是该表的合法列（白名单 + 标识符校验），防止 SQL 注入；
        # order 仅允许 asc/desc。提供合法 sort 时覆盖默认排序，否则沿用配置的 order_by。
        order_by = ""
        if sort is not None and sort in web_module_data.columns and _SAFE_IDENTIFIER_RE.match(sort):
            direction = "ASC" if (order or "").lower() == "asc" else "DESC"
            order_by = f" ORDER BY `{sort}` {direction}"
        elif web_module_data.order_by is not None:
            order_by = f" ORDER BY {web_module_data.order_by}"

        order_columns = ""
        if web_module_data.order_columns is not None:
            order_columns = f",{web_module_data.order_columns}"

        # 分页参数处理
        use_pagination = page is not None and page_size is not None
        limit_clause = ""
        if use_pagination:
            try:
                page_int = max(1, int(page))
                page_size_int = max(1, min(500, int(page_size)))
                offset = (page_int - 1) * page_size_int
                limit_clause = f" LIMIT {page_size_int} OFFSET {offset}"
            except (ValueError, TypeError):
                use_pagination = False

        # 先查询总数
        count_sql = f"SELECT COUNT(*) AS cnt FROM `{web_module_data.table_name}`{where}"
        data_sql = f"SELECT *{order_columns} FROM `{web_module_data.table_name}`{where}{order_by}{limit_clause}"

        try:
            # 尝试从缓存获取总数
            cache_params = tuple(query_params) if query_params else None
            hit, cached_total = stock_data_cache.get(count_sql, cache_params)
            if hit:
                total = cached_total
            else:
                if query_params:
                    total_result = self.db.query(count_sql, *query_params)
                else:
                    total_result = self.db.query(count_sql)
                total = total_result[0]["cnt"] if total_result else 0
                stock_data_cache.put(count_sql, cache_params, total)

            # 尝试从缓存获取数据
            hit, cached_data = stock_data_cache.get(data_sql, cache_params)
            if hit:
                data = cached_data
            else:
                if query_params:
                    data = self.db.query(data_sql, *query_params)
                else:
                    data = self.db.query(data_sql)
                stock_data_cache.put(data_sql, cache_params, data)
        except Exception as e:
            error_msg = str(e)
            # 表不存在时返回空数据，而非500错误
            if "doesn't exist" in error_msg or "not found" in error_msg.lower():
                data = []
                total = 0
                table_missing = True  # 标记表不存在，跳过后续日期回退
            elif "Unknown column" in error_msg and order_by:
                # ORDER BY 引用了不存在的列（如新增列尚未同步到表），去掉排序重试
                logging.warning(f"GetStockDataHandler: ORDER BY 列不存在，去掉排序重试: {error_msg}")
                data_sql_fallback = f"SELECT *{order_columns} FROM `{web_module_data.table_name}`{where}{limit_clause}"
                try:
                    if query_params:
                        data = self.db.query(data_sql_fallback, *query_params)
                        total_result = self.db.query(count_sql, *query_params)
                    else:
                        data = self.db.query(data_sql_fallback)
                        total_result = self.db.query(count_sql)
                    total = total_result[0]["cnt"] if total_result else 0
                except Exception as e2:
                    logging.error(f"GetStockDataHandler fallback查询异常：{web_module_data.table_name}", exc_info=True)
                    self.set_status(500)
                    self.write(json.dumps({"error": f"查询数据异常: {str(e2)}", "code": 500}))
                    return
            else:
                logging.error(f"GetStockDataHandler查询异常：{web_module_data.table_name}", exc_info=True)
                self.set_status(500)
                self.write(json.dumps({"error": f"查询数据异常: {error_msg}", "code": 500}))
                return

        # 返回包含列定义和数据的响应
        # 日期回退：如果按指定日期查无数据（可能作业尚未完成），自动回退到最近有数据的日期
        # 表不存在时跳过回退，避免再次触发 1146 错误
        if total == 0 and date is not None and not keyword and not table_missing:
            try:
                fallback_result = self.db.query(
                    f"SELECT MAX(`date`) AS latest FROM `{web_module_data.table_name}`"
                )
                latest = fallback_result[0]["latest"] if fallback_result and fallback_result[0]["latest"] else None
                if latest:
                    latest_str = latest.strftime("%Y-%m-%d") if hasattr(latest, 'strftime') else str(latest)
                    if latest_str != date:
                        # 用最新日期重新查询
                        fb_conditions = ["`date` = %s"]
                        fb_params = [latest_str]
                        fb_where = " WHERE " + " AND ".join(fb_conditions)
                        fb_count_sql = f"SELECT COUNT(*) AS cnt FROM `{web_module_data.table_name}`{fb_where}"
                        fb_data_sql = f"SELECT *{order_columns} FROM `{web_module_data.table_name}`{fb_where}{order_by}{limit_clause}"
                        fb_total_result = self.db.query(fb_count_sql, *fb_params)
                        total = fb_total_result[0]["cnt"] if fb_total_result else 0
                        data = self.db.query(fb_data_sql, *fb_params)
                        actual_date = latest_str
                        logging.info(f"GetStockDataHandler日期回退：{date} → {latest_str} ({web_module_data.table_name})")
            except Exception as e:
                logging.warning(f"GetStockDataHandler日期回退查询异常：{e}")

        response = {
            "columns": web_module_data.column_names,
            "data": data,
            "total": total
        }
        if actual_date != date:
            response["actual_date"] = actual_date
        self.write(json.dumps(response, cls=MyEncoder))


# 获取最近交易日期（供前端初始化使用）
class GetTradeDateHandler(webBase.BaseHandler, ABC):
    def get(self):
        self.set_header('Content-Type', 'application/json;charset=UTF-8')
        try:
            run_date, run_date_nph = trd.get_trade_date_last()
            response = {
                "run_date": run_date.strftime("%Y-%m-%d"),
                "run_date_nph": run_date_nph.strftime("%Y-%m-%d")
            }
            self.write(json.dumps(response))
        except Exception as e:
            logging.error(f"GetTradeDateHandler处理异常", exc_info=True)
            today = datetime.date.today().strftime("%Y-%m-%d")
            self.write(json.dumps({"run_date": today, "run_date_nph": today}))
