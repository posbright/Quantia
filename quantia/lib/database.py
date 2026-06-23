#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import math
import numbers
import os
import time
import threading
import pymysql
from sqlalchemy import create_engine, text
from sqlalchemy.types import NVARCHAR
from sqlalchemy import inspect
from sqlalchemy.dialects.mysql import insert as mysql_insert
from urllib.parse import quote_plus

# 集中式 .env 加载（通过 envconfig 模块完成，import 即触发）
import quantia.lib.envconfig as _cfg  # noqa: F401

__author__ = 'Quantia'
__date__ = '2026/02/14'

# 数据库连接重试次数（应用于 get_connection / insert / executeSql）
# 注意：值必须 >= 2 才能让 _is_retryable_error 路径真正生效（attempt < max_retries 条件）。
# 默认 3 次：覆盖远程 MySQL 偶发超时（如 backtest 子进程抢占资源时）+ 失效连接重建。
_DB_CONN_RETRIES = max(_cfg.get_int('QUANTIA_DB_CONN_RETRIES', 3), 1)

# 线程本地连接最大闲置秒数：超过则在下次取用时主动回收重建，避免长期空闲的
# 执行器线程（如 Tornado run_in_executor / 调度器）一直占着服务端连接槽。连接只增不减
# 是 max_connections 打满、新连接握手永久挂起（stock_error.log 中 _get_server_information 超时）
# 的诱因之一。0 表示禁用闲置回收。默认 300s。
_DB_CONN_MAX_IDLE = max(_cfg.get_int('QUANTIA_DB_CONN_MAX_IDLE', 300), 0)

# 批量写入分块大小（避免一次性构造巨大 SQL 语句导致 OOM）
# 默认 500 行/批：4367 行会分 ~9 批执行，单批 SQL 约 10-30 MB
_DB_INSERT_CHUNKSIZE = _cfg.get_int('QUANTIA_DB_INSERT_CHUNKSIZE', 500)

# information_schema 表存在性缓存（降低 Web 热路径/批处理反复探测 MySQL 的压力）
_TABLE_EXISTS_TTL = max(_cfg.get_int('QUANTIA_DB_TABLE_EXISTS_TTL', 30), 0)
_table_exists_cache = {}  # {table_name: (exists_bool, timestamp)}
_table_exists_lock = threading.Lock()

db_host = _cfg.get_str('QUANTIA_DB_HOST', '127.0.0.1')       # 数据库服务主机
db_user = _cfg.get_str('QUANTIA_DB_USER', 'root')            # 数据库访问用户
db_password = _cfg.get_str('QUANTIA_DB_PASSWORD', '')        # 数据库访问密码（生产环境务必配置）
db_database = _cfg.get_str('QUANTIA_DB_DATABASE', 'quantiadb')  # 数据库名称
db_port = _cfg.get_int('QUANTIA_DB_PORT', 3306)              # 数据库服务端口
db_charset = _cfg.get_str('QUANTIA_DB_CHARSET', 'utf8mb4')   # 数据库字符集

# 对密码进行URL编码，处理特殊字符
_encoded_password = quote_plus(db_password)
MYSQL_CONN_URL = "mysql+pymysql://%s:%s@%s:%s/%s?charset=%s" % (
    db_user, _encoded_password, db_host, db_port, db_database, db_charset)
logging.info(f"数据库链接信息：mysql+pymysql://{db_user}:***@{db_host}:{db_port}/{db_database}?charset={db_charset}")

# 超时配置
# connect_timeout（建连/握手）默认 10 秒：服务端卡死时快速失败，避免调度线程在
#   connect_timeout × _DB_CONN_RETRIES（旧 30s×3=90s）期间全部阻塞、反而制造更多并发
#   连接火上浇油（见 stock_error.log：_get_server_information 握手读超时雪崩）。
# read/write_timeout（查询读写）保持较宽：backtest 子进程并发期间长查询需要时间。
_connect_timeout = _cfg.get_int('QUANTIA_DB_CONNECT_TIMEOUT', 10)
_read_timeout = _cfg.get_int('QUANTIA_DB_READ_TIMEOUT', 30)
_write_timeout = _cfg.get_int('QUANTIA_DB_WRITE_TIMEOUT', 60)

MYSQL_CONN_DBAPI = {'host': db_host, 'user': db_user, 'password': db_password, 'database': db_database,
                    'charset': db_charset, 'port': db_port, 'autocommit': True,
                    'connect_timeout': _connect_timeout, 'read_timeout': _read_timeout, 'write_timeout': _write_timeout}

MYSQL_CONN_TORNDB = {'host': f'{db_host}:{str(db_port)}', 'user': db_user, 'password': db_password,
                     'database': db_database, 'charset': db_charset, 'max_idle_time': 3600,
                     'connect_timeout': _connect_timeout, 'read_timeout': _read_timeout}


# 通过数据库链接 engine（单例模式，避免每次调用创建新连接池）
# 2核2G服务器优化：pool_size=2, max_overflow=3, 最多5个连接
_engine_instance = None
_engine_lock = threading.Lock()
_engine_to_db_cache = {}  # {db_name: engine} — 缓存跨库连接池，避免每次创建泄漏连接


def engine():
    global _engine_instance
    if _engine_instance is not None:
        return _engine_instance
    with _engine_lock:
        # 双重检查锁定：避免多线程并发首次调用时创建多个连接池
        if _engine_instance is None:
            _engine_instance = create_engine(
                MYSQL_CONN_URL,
                pool_size=_cfg.get_int('QUANTIA_DB_POOL_SIZE', 2),
                max_overflow=_cfg.get_int('QUANTIA_DB_MAX_OVERFLOW', 3),
                pool_recycle=_cfg.get_int('QUANTIA_DB_POOL_RECYCLE', 600),
                pool_pre_ping=True,
                pool_timeout=_cfg.get_int('QUANTIA_DB_POOL_TIMEOUT', 30)
            )
    return _engine_instance


def engine_to_db(to_db):
    """获取跨库连接引擎（线程安全，带缓存避免连接池泄漏）"""
    if to_db in _engine_to_db_cache:
        return _engine_to_db_cache[to_db]
    with _engine_lock:
        if to_db not in _engine_to_db_cache:
            _engine_to_db_cache[to_db] = create_engine(
                MYSQL_CONN_URL.replace(f'/{db_database}?', f'/{to_db}?'))
    return _engine_to_db_cache[to_db]


# DB Api -数据库连接对象connection
# 使用 threading.local() 实现每线程独立连接，避免多线程共享连接导致协议错乱
# （2026-03-17 故障根因：streaming_analysis ThreadPoolExecutor 中多线程共享
#  _shared_conn 导致 Packet sequence number wrong / read of closed file 雪崩）
_thread_local = threading.local()


class _ReusableConnection:
    """包装 pymysql.Connection，__exit__ 不关闭底层连接（留给复用池管理）"""
    def __init__(self, conn):
        self._conn = conn
    def __enter__(self):
        return self._conn
    def __exit__(self, *exc_info):
        # 不关闭连接，只确保事务状态正确（autocommit=True 时无需 commit/rollback）
        pass
    def __getattr__(self, name):
        return getattr(self._conn, name)


def _invalidate_shared_conn():
    """安全地废弃当前线程的数据库连接，强制下次 get_connection() 创建新连接。
    解决连接损坏后重试仍复用坏连接导致雪崩式失败的问题（2026-03-17 故障根因）。"""
    conn = getattr(_thread_local, 'conn', None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            logging.debug("_invalidate_shared_conn: 关闭连接异常（已忽略）", exc_info=True)
        _thread_local.conn = None


def close_thread_connection():
    """关闭当前线程的数据库连接。供 ThreadPoolExecutor 工作线程结束时调用，
    避免线程池中的连接泄露导致 MySQL 'Too many connections' (1040) 错误。

    用法示例::

        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(my_task, arg) for arg in args]
            for f in as_completed(futures):
                f.result()
        # 线程池关闭后，清理残留连接
        # 或在 worker 函数内 try/finally 调用
    """
    _invalidate_shared_conn()


def get_connection():
    """获取数据库连接。优先复用当前线程已有连接（ping 检测存活），失败则新建。
    返回 _ReusableConnection 包装器，with 语句不会关闭底层连接。
    线程安全：每个线程有独立的连接实例（threading.local）。
    闲置回收：连接闲置超过 _DB_CONN_MAX_IDLE 秒则主动重建，避免长期占用服务端连接槽。"""
    conn = getattr(_thread_local, 'conn', None)
    # 闲置过久主动回收：长期空闲的执行器线程不再占着服务端连接槽
    if conn is not None and _DB_CONN_MAX_IDLE:
        last_used = getattr(_thread_local, 'conn_last_used', 0.0)
        if time.monotonic() - last_used > _DB_CONN_MAX_IDLE:
            logging.debug("DB 连接闲置超过 %ds，主动回收重建", _DB_CONN_MAX_IDLE)
            try:
                conn.close()
            except Exception:
                logging.debug("关闭闲置连接异常", exc_info=True)
            _thread_local.conn = None
            conn = None
    if conn is not None:
        try:
            conn.ping(reconnect=True)
            _thread_local.conn_last_used = time.monotonic()
            return _ReusableConnection(conn)
        except Exception:
            logging.debug("DB ping 失败，将重建连接", exc_info=True)
            try:
                conn.close()
            except Exception:
                logging.debug("关闭失效连接异常", exc_info=True)
            _thread_local.conn = None

    max_retries = _DB_CONN_RETRIES
    for attempt in range(1, max_retries + 1):
        try:
            _thread_local.conn = pymysql.connect(**MYSQL_CONN_DBAPI)
            _thread_local.conn_last_used = time.monotonic()
            return _ReusableConnection(_thread_local.conn)
        except Exception as e:
            if attempt < max_retries and _is_retryable_error(e):
                logging.warning(f"database.get_connection瞬态错误（第{attempt}/{max_retries}次重试）：{type(e).__name__}")
                time.sleep(1 * attempt)
            else:
                logging.error(f"database.get_connection处理异常", exc_info=True)
                raise


# MySQL upsert方法：INSERT ... ON DUPLICATE KEY UPDATE
# 解决并发写入时的主键冲突、死锁等问题
def _mysql_upsert(table, conn, keys, data_iter):
    """pandas to_sql 的自定义 method，使用 INSERT ... ON DUPLICATE KEY UPDATE"""
    data = [dict(zip(keys, (_mysql_safe_value(value) for value in row))) for row in data_iter]
    if not data:
        return 0
    stmt = mysql_insert(table.table).values(data)
    # 主键冲突时，更新所有非主键列
    update_dict = {k: stmt.inserted[k] for k in keys}
    upsert_stmt = stmt.on_duplicate_key_update(**update_dict)
    result = conn.execute(upsert_stmt)
    return result.rowcount


def _mysql_safe_value(value):
    if value is None:
        return None
    if isinstance(value, numbers.Number) and not math.isfinite(value):
        return None
    return value


def _is_mysql_null_value(value):
    if value is None:
        return True
    if isinstance(value, numbers.Number) and not math.isfinite(value):
        return True
    try:
        return value != value
    except Exception:
        return False


def _sanitize_dataframe_for_mysql(data):
    if data is None:
        return data
    sanitized = data.replace([float('inf'), float('-inf')], None)
    return sanitized.where(sanitized.notnull(), None)


def _cache_table_exists(table_name, exists):
    if _TABLE_EXISTS_TTL <= 0:
        return
    with _table_exists_lock:
        _table_exists_cache[str(table_name)] = (bool(exists), time.time())


def _get_cached_table_exists(table_name):
    if _TABLE_EXISTS_TTL <= 0:
        return None
    with _table_exists_lock:
        item = _table_exists_cache.get(str(table_name))
        if not item:
            return None
        exists, ts = item
        if (time.time() - ts) > _TABLE_EXISTS_TTL:
            _table_exists_cache.pop(str(table_name), None)
            return None
        return bool(exists)


def invalidate_table_exists_cache(table_name=None):
    """清除"表是否存在"的 TTL 缓存。

    在 DROP/CREATE/RENAME TABLE 等 DDL 之后必须调用，否则 checkTableIsExist
    会返回过期的缓存值，导致：
      - DELETE/写入命中"已不存在"的表（1146）；
      - 调用方误判表已存在而跳过 cols_type 计算，使 to_sql 把 date 列推断为
        TEXT，后续 ADD PRIMARY KEY 失败（1170）。
    传入 None 时清空整个缓存。
    """
    with _table_exists_lock:
        if table_name is None:
            _table_exists_cache.clear()
        else:
            _table_exists_cache.pop(str(table_name), None)


# 判断是否为可重试的数据库瞬态错误（死锁、锁超时、连接异常等）
def _is_retryable_error(e):
    # 特殊异常类型：连接损坏导致的非数据库异常也应重试
    if isinstance(e, (ValueError, IndexError, OSError, BrokenPipeError)):
        return True
    error_str = str(e)
    retryable_codes = ['1205', '1213', 'Deadlock', 'Lock wait timeout',
                       'Packet sequence', 'PendingRollbackError',
                       'Lost connection', 'Gone away', 'Can\'t connect',
                       'Connection refused', 'broken pipe',
                       'read of closed file', 'not subscriptable',
                       'closed connection', 'server has gone']
    return any(code.lower() in error_str.lower() for code in retryable_codes)


# 定义通用方法函数，插入数据库表，并创建数据库主键，保证重跑数据的时候索引唯一。
def insert_db_from_df(data, table_name, cols_type, write_index, primary_keys, indexs=None):
    # 插入默认的数据库。
    insert_other_db_from_df(None, data, table_name, cols_type, write_index, primary_keys, indexs)


# 增加一个插入到其他数据库的方法。
def insert_other_db_from_df(to_db, data, table_name, cols_type, write_index, primary_keys, indexs=None):
    global _engine_instance
    data = _sanitize_dataframe_for_mysql(data)
    # 定义engine
    if to_db is None:
        engine_mysql = engine()
    else:
        engine_mysql = engine_to_db(to_db)
    ipt = None
    col_name_list = data.columns.tolist()
    # 如果有索引，把索引增加到varchar上面。
    if write_index:
        # 插入到第一个位置：
        col_name_list.insert(0, data.index.name)

    # 检查表是否已存在主键，决定是否使用upsert模式
    has_primary_key = False
    for attempt in range(1, _DB_CONN_RETRIES + 1):
        try:
            # 使用 http://docs.sqlalchemy.org/en/latest/core/reflection.html
            # 检查表是否有主键；连接抖动时这里也可能触发 packet sequence / lost connection。
            ipt = inspect(engine_mysql)
            pk_cols = ipt.get_pk_constraint(table_name)['constrained_columns']
            has_primary_key = bool(pk_cols)
            break
        except Exception as e:
            err = str(e).lower()
            # 表不存在（首次创建）判定要稳健：
            #   - SQLAlchemy 包装为 NoSuchTableError，其 str(e) 仅是表名，匹配不到任何关键字；
            #   - MySQL/PyMySQL 原始错误是 "Table '...' doesn't exist"（错误码 1146），含缩写 doesn't。
            # 命中即 break，让后续 to_sql(if_exists='append') 正常建表，避免误入 else 分支 return 丢数据。
            is_no_such_table = (
                type(e).__name__ == 'NoSuchTableError'
                or 'no such table' in err
                or 'does not exist' in err
                or "doesn't exist" in err
                or '1146' in err
            )
            if is_no_such_table:
                logging.debug(f"检查主键约束异常（表可能不存在，首次创建）：{table_name}", exc_info=True)
                break
            if attempt < _DB_CONN_RETRIES and _is_retryable_error(e):
                logging.warning(f"database.insert_other_db_from_df主键检查瞬态错误（第{attempt}/{_DB_CONN_RETRIES}次重试）：{table_name}表 - {type(e).__name__}")
                try:
                    engine_mysql.dispose()
                except Exception:
                    logging.debug("database.insert_other_db_from_df: dispose引擎异常", exc_info=True)
                if to_db is None:
                    with _engine_lock:
                        _engine_instance = None
                    engine_mysql = engine()
                else:
                    engine_mysql = engine_to_db(to_db)
                time.sleep(1 * attempt)
            else:
                logging.error(f"database.insert_other_db_from_df主键检查异常：{table_name}表", exc_info=True)
                return

    # 选择插入方法：有主键时使用upsert避免重复插入错误，否则普通append
    insert_method = _mysql_upsert if has_primary_key else None

    max_retries = _DB_CONN_RETRIES
    for attempt in range(1, max_retries + 1):
        try:
            if cols_type is None:
                data.to_sql(name=table_name, con=engine_mysql, schema=to_db, if_exists='append',
                            index=write_index, method=insert_method, chunksize=_DB_INSERT_CHUNKSIZE)
            elif not cols_type:
                data.to_sql(name=table_name, con=engine_mysql, schema=to_db, if_exists='append',
                            dtype={col_name: NVARCHAR(255) for col_name in col_name_list},
                            index=write_index, method=insert_method, chunksize=_DB_INSERT_CHUNKSIZE)
            else:
                data.to_sql(name=table_name, con=engine_mysql, schema=to_db, if_exists='append',
                            dtype=cols_type, index=write_index, method=insert_method,
                            chunksize=_DB_INSERT_CHUNKSIZE)
            _cache_table_exists(table_name, True)
            break  # 成功则跳出重试循环
        except Exception as e:
            if attempt < max_retries and _is_retryable_error(e):
                logging.warning(f"database.insert_other_db_from_df瞬态错误（第{attempt}/{max_retries}次重试）：{table_name}表 - {type(e).__name__}")
                # 清理连接池中可能损坏的连接
                try:
                    engine_mysql.dispose()
                except Exception:
                    logging.debug(f"database.insert_other_db_from_df: dispose引擎异常", exc_info=True)
                # 重新获取engine（单例模式下dispose后需要重建）
                if to_db is None:
                    with _engine_lock:
                        _engine_instance = None
                    engine_mysql = engine()
                else:
                    engine_mysql = engine_to_db(to_db)
                time.sleep(2 * attempt)  # 递增等待时间
            else:
                logging.error(f"database.insert_other_db_from_df处理异常：{table_name}表", exc_info=True)
                return

    # 判断是否存在主键（仅在首次创建表时添加）
    if ipt is None:
        try:
            ipt = inspect(engine_mysql)
        except Exception:
            logging.error(f"database.insert_other_db_from_df检查主键异常：{table_name}表", exc_info=True)
            return
    try:
        pk_exists = ipt.get_pk_constraint(table_name)['constrained_columns']
    except Exception as e:
        logging.error(f"database.insert_other_db_from_df检查主键异常：{table_name}表", exc_info=True)
        return
    if not pk_exists:
        try:
            # 执行数据库插入数据。
            with get_connection() as conn:
                with conn.cursor() as db:
                    db.execute(f'ALTER TABLE `{table_name}` ADD PRIMARY KEY ({primary_keys});')
                    if indexs is not None:
                        for k in indexs:
                            db.execute(f'ALTER TABLE `{table_name}` ADD INDEX IN{k}({indexs[k]});')
        except Exception as e:
            _invalidate_shared_conn()  # 废弃可能损坏的连接
            logging.error(f"database.insert_other_db_from_df处理异常：{table_name}表", exc_info=True)


# 更新数据
def update_db_from_df(data, table_name, where):
    data = _sanitize_dataframe_for_mysql(data)
    update_string = f'UPDATE `{table_name}` set '
    where_string = ' where '
    cols = tuple(data.columns)
    max_retries = _DB_CONN_RETRIES
    for attempt in range(1, max_retries + 1):
        try:
            with get_connection() as conn:
                with conn.cursor() as db:
                    for row in data.values:
                        set_parts = []
                        set_params = []
                        where_parts = []
                        where_params = []
                        for index, col in enumerate(cols):
                            val = row[index]
                            is_null = _is_mysql_null_value(val)
                            if col in where:
                                if is_null:
                                    where_parts.append(f'`{col}` IS NULL')
                                else:
                                    where_parts.append(f'`{col}` = %s')
                                    where_params.append(val)
                            else:
                                if is_null:
                                    set_parts.append(f'`{col}` = NULL')
                                else:
                                    set_parts.append(f'`{col}` = %s')
                                    set_params.append(val)
                        if not set_parts or not where_parts:
                            continue
                        sql = update_string + ', '.join(set_parts) + where_string + ' and '.join(where_parts)
                        params = set_params + where_params
                        db.execute(sql, params)
            break  # 成功则跳出重试循环
        except Exception as e:
            if attempt < max_retries and _is_retryable_error(e):
                logging.warning(f"database.update_db_from_df瞬态错误（第{attempt}/{max_retries}次重试）：{table_name}表 - {type(e).__name__}")
                _invalidate_shared_conn()
                time.sleep(2 * attempt)
            else:
                _invalidate_shared_conn()
                logging.error(f"database.update_db_from_df处理异常：{table_name}表", exc_info=True)
                return


# 检查表是否存在
def checkTableIsExist(tableName):
    cached = _get_cached_table_exists(tableName)
    if cached is not None:
        return cached
    max_retries = _DB_CONN_RETRIES
    for attempt in range(1, max_retries + 1):
        try:
            with get_connection() as conn:
                with conn.cursor() as db:
                    db.execute("""
                        SELECT COUNT(*)
                        FROM information_schema.tables
                        WHERE table_schema = %s AND table_name = %s
                        """, (db_database, tableName))
                    row = db.fetchone()
                    if row is not None and row[0] >= 1:
                        _cache_table_exists(tableName, True)
                        return True
                    _cache_table_exists(tableName, False)
                    return False
        except Exception as e:
            _invalidate_shared_conn()  # 废弃损坏连接，避免重试时雪崩
            if attempt < max_retries and _is_retryable_error(e):
                logging.warning(f"database.checkTableIsExist瞬态错误（第{attempt}/{max_retries}次重试）：{type(e).__name__}")
                time.sleep(1 * attempt)
            else:
                logging.error(f"database.checkTableIsExist处理异常", exc_info=True)
    return False


def checkTablesExist(tableNames):
    """一次性检查多个表是否存在，返回 {table_name: bool}。

    会先命中/回填单表 TTL 缓存，再对未命中的表做一次 information_schema 批量查询。
    """
    names = [str(name) for name in (tableNames or []) if name]
    if not names:
        return {}
    result = {}
    pending = []
    for name in names:
        cached = _get_cached_table_exists(name)
        if cached is None:
            pending.append(name)
        else:
            result[name] = cached
    if not pending:
        return result

    placeholders = ', '.join(['%s'] * len(pending))
    max_retries = _DB_CONN_RETRIES
    for attempt in range(1, max_retries + 1):
        try:
            with get_connection() as conn:
                with conn.cursor() as db:
                    db.execute(
                        f"SELECT table_name FROM information_schema.tables "
                        f"WHERE table_schema = %s AND table_name IN ({placeholders})",
                        (db_database, *pending))
                    rows = db.fetchall() or []
                    exists_set = {str(r[0]) for r in rows if r and r[0] is not None}
                    for name in pending:
                        exists = name in exists_set
                        _cache_table_exists(name, exists)
                        result[name] = exists
                    return result
        except Exception as e:
            _invalidate_shared_conn()
            if attempt < max_retries and _is_retryable_error(e):
                logging.warning(f"database.checkTablesExist瞬态错误（第{attempt}/{max_retries}次重试）：{type(e).__name__}")
                time.sleep(1 * attempt)
            else:
                logging.error("database.checkTablesExist处理异常", exc_info=True)
                break
    for name in pending:
        result.setdefault(name, False)
    return result

# 增删改数据
def executeSql(sql, params=()):
    max_retries = _DB_CONN_RETRIES
    for attempt in range(1, max_retries + 1):
        try:
            with get_connection() as conn:
                with conn.cursor() as db:
                    db.execute(sql, params)
                    return
        except Exception as e:
            _invalidate_shared_conn()  # 废弃损坏连接，避免重试时雪崩
            if attempt < max_retries and _is_retryable_error(e):
                logging.warning(f"database.executeSql瞬态错误（第{attempt}/{max_retries}次重试）：{type(e).__name__}")
                time.sleep(1 * attempt)
            else:
                logging.error(f"database.executeSql处理异常：{sql}", exc_info=True)
                raise


# 为单条查询设置会话级超时（执行后重置），避免慢 SQL 长时间阻塞回测线程。
def _apply_query_timeout(db, query_timeout_ms):
    if query_timeout_ms is None:
        return False
    try:
        timeout_ms = int(query_timeout_ms)
    except Exception:
        return False
    if timeout_ms <= 0:
        return False

    # MySQL 5.7+/8.0: MAX_EXECUTION_TIME（单位毫秒）
    try:
        db.execute("SET SESSION MAX_EXECUTION_TIME = %s", (timeout_ms,))
        return True
    except Exception:
        pass

    # MariaDB: max_statement_time（单位秒）
    try:
        db.execute("SET SESSION max_statement_time = %s", (timeout_ms / 1000.0,))
        return True
    except Exception:
        return False


def _reset_query_timeout(db):
    # 忽略重置失败，避免影响主查询结果返回。
    try:
        db.execute("SET SESSION MAX_EXECUTION_TIME = 0")
    except Exception:
        pass
    try:
        db.execute("SET SESSION max_statement_time = 0")
    except Exception:
        pass


# 查询数据
def executeSqlFetch(sql, params=(), query_timeout_ms=None):
    max_retries = _DB_CONN_RETRIES
    for attempt in range(1, max_retries + 1):
        try:
            with get_connection() as conn:
                with conn.cursor() as db:
                    timeout_applied = _apply_query_timeout(db, query_timeout_ms)
                    try:
                        db.execute(sql, params)
                        return db.fetchall()
                    finally:
                        if timeout_applied:
                            _reset_query_timeout(db)
        except Exception as e:
            _invalidate_shared_conn()  # 废弃损坏连接，避免重试时雪崩
            if attempt < max_retries and _is_retryable_error(e):
                logging.warning(f"database.executeSqlFetch瞬态错误（第{attempt}/{max_retries}次重试）：{type(e).__name__}")
                time.sleep(1 * attempt)
            else:
                logging.error(f"database.executeSqlFetch处理异常：{sql}", exc_info=True)
    return None


# 计算数量
def executeSqlCount(sql, params=()):
    max_retries = _DB_CONN_RETRIES
    for attempt in range(1, max_retries + 1):
        try:
            with get_connection() as conn:
                with conn.cursor() as db:
                    db.execute(sql, params)
                    result = db.fetchall()
                    if len(result) == 1:
                        return int(result[0][0])
                    else:
                        return 0
        except Exception as e:
            _invalidate_shared_conn()  # 废弃损坏连接，避免重试时雪崩
            if attempt < max_retries and _is_retryable_error(e):
                logging.warning(f"database.executeSqlCount瞬态错误（第{attempt}/{max_retries}次重试）：{type(e).__name__}")
                time.sleep(1 * attempt)
            else:
                logging.error(f"database.executeSqlCount处理异常", exc_info=True)
    return 0
