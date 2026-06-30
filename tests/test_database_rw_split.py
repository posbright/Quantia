"""读写分离（engine_ro / use_master / read_sql_ro）单元测试。

只测试路由/网关/降级逻辑，不建立真实数据库连接：
- SQLAlchemy `create_engine` 是惰性的，不会在创建时连接 MySQL；
- read_sql_ro 的降级通过 monkeypatch `pandas.read_sql` 捕获 con 参数验证。
"""

import time

import pytest

import quantia.lib.database as mdb


@pytest.fixture
def restore_rw_state():
    """保存并恢复读写分离相关的模块级状态，避免污染其它测试。"""
    saved = {
        'RW_SPLIT_ENABLED': mdb.RW_SPLIT_ENABLED,
        '_engine_ro_instance': mdb._engine_ro_instance,
        '_READ_MYSQL_CONN_URL': mdb._READ_MYSQL_CONN_URL,
        '_ro_unhealthy_until': mdb._ro_unhealthy_until,
    }
    # 同时清掉可能残留的线程局部强制主库标记
    if hasattr(mdb._thread_local, 'force_master_reads'):
        delattr(mdb._thread_local, 'force_master_reads')
    yield
    mdb.RW_SPLIT_ENABLED = saved['RW_SPLIT_ENABLED']
    mdb._engine_ro_instance = saved['_engine_ro_instance']
    mdb._READ_MYSQL_CONN_URL = saved['_READ_MYSQL_CONN_URL']
    mdb._ro_unhealthy_until = saved['_ro_unhealthy_until']
    if hasattr(mdb._thread_local, 'force_master_reads'):
        delattr(mdb._thread_local, 'force_master_reads')


def test_engine_ro_returns_master_when_disabled(restore_rw_state):
    """默认（未启用读写分离）：engine_ro() 必须返回与 engine() 完全相同的对象。"""
    mdb.RW_SPLIT_ENABLED = False
    mdb._engine_ro_instance = None
    assert mdb.engine_ro() is mdb.engine()


def test_engine_ro_returns_distinct_slave_when_enabled(restore_rw_state):
    """启用读写分离：engine_ro() 返回独立的从库引擎，且单例缓存（两次调用同一对象）。"""
    mdb.RW_SPLIT_ENABLED = True
    mdb._engine_ro_instance = None
    # MySQL 方言 URL：create_engine 惰性，不会在创建时连接（与 engine() 同理）
    mdb._READ_MYSQL_CONN_URL = 'mysql+pymysql://ro:ro@127.0.0.1:3306/testdb'

    ro1 = mdb.engine_ro()
    ro2 = mdb.engine_ro()
    assert ro1 is ro2                 # 单例缓存
    assert ro1 is not mdb.engine()    # 与主库引擎不同


def test_use_master_forces_master_within_context(restore_rw_state):
    """启用读写分离时，use_master() 上下文内 engine_ro() 强制回主库。"""
    mdb.RW_SPLIT_ENABLED = True
    mdb._engine_ro_instance = None
    mdb._READ_MYSQL_CONN_URL = 'mysql+pymysql://ro:ro@127.0.0.1:3306/testdb'

    # 上下文外走从库
    assert mdb.engine_ro() is not mdb.engine()

    with mdb.use_master():
        assert mdb._force_master_active() is True
        assert mdb.engine_ro() is mdb.engine()

    # 退出后恢复到从库路由
    assert mdb._force_master_active() is False
    assert mdb.engine_ro() is not mdb.engine()


def test_use_master_nesting_restores_previous(restore_rw_state):
    """use_master() 支持嵌套：内层退出后仍保持外层的强制主库状态。"""
    mdb.RW_SPLIT_ENABLED = True
    mdb._engine_ro_instance = None
    mdb._READ_MYSQL_CONN_URL = 'mysql+pymysql://ro:ro@127.0.0.1:3306/testdb'

    assert mdb._force_master_active() is False
    with mdb.use_master():
        assert mdb._force_master_active() is True
        with mdb.use_master():
            assert mdb._force_master_active() is True
        # 内层退出，外层仍生效
        assert mdb._force_master_active() is True
    # 全部退出
    assert mdb._force_master_active() is False


def test_use_master_returns_master_even_when_ro_cached(restore_rw_state):
    """即使从库引擎已缓存，use_master() 上下文内仍返回主库。"""
    mdb.RW_SPLIT_ENABLED = True
    mdb._engine_ro_instance = None
    mdb._READ_MYSQL_CONN_URL = 'mysql+pymysql://ro:ro@127.0.0.1:3306/testdb'

    ro = mdb.engine_ro()              # 先缓存从库引擎
    assert ro is not mdb.engine()
    with mdb.use_master():
        assert mdb.engine_ro() is mdb.engine()
    assert mdb.engine_ro() is ro      # 退出后仍复用同一从库单例


def test_read_sql_ro_uses_master_when_disabled(restore_rw_state, monkeypatch):
    """未启用读写分离：read_sql_ro 直接用主库引擎，零额外开销。"""
    mdb.RW_SPLIT_ENABLED = False
    captured = {}

    def fake_read_sql(sql, con=None, params=None, **kw):
        captured['con'] = con
        return 'OK'

    monkeypatch.setattr('pandas.read_sql', fake_read_sql)
    assert mdb.read_sql_ro('SELECT 1') == 'OK'
    assert captured['con'] is mdb.engine()


def test_read_sql_ro_uses_slave_when_healthy(restore_rw_state, monkeypatch):
    """启用且从库健康：read_sql_ro 走从库引擎。"""
    mdb.RW_SPLIT_ENABLED = True
    mdb._engine_ro_instance = None
    mdb._READ_MYSQL_CONN_URL = 'mysql+pymysql://ro:ro@127.0.0.1:3306/testdb'
    mdb._ro_unhealthy_until = 0.0
    captured = {}

    def fake_read_sql(sql, con=None, params=None, **kw):
        captured['con'] = con
        return 'OK'

    monkeypatch.setattr('pandas.read_sql', fake_read_sql)
    assert mdb.read_sql_ro('SELECT 1') == 'OK'
    assert captured['con'] is not mdb.engine()   # 从库
    assert captured['con'] is mdb.engine_ro()


def test_read_sql_ro_falls_back_to_master_on_connection_error(restore_rw_state, monkeypatch):
    """从库连接级错误：read_sql_ro 当场降级主库并打开熔断。"""
    from sqlalchemy.exc import OperationalError

    mdb.RW_SPLIT_ENABLED = True
    mdb._engine_ro_instance = None
    mdb._READ_MYSQL_CONN_URL = 'mysql+pymysql://ro:ro@127.0.0.1:3306/testdb'
    mdb._ro_unhealthy_until = 0.0
    master = mdb.engine()
    calls = []

    def fake_read_sql(sql, con=None, params=None, **kw):
        calls.append(con)
        if con is not master:
            raise OperationalError('SELECT 1', None, Exception('Connection refused'))
        return 'OK'

    monkeypatch.setattr('pandas.read_sql', fake_read_sql)
    assert mdb.read_sql_ro('SELECT 1') == 'OK'
    assert len(calls) == 2
    assert calls[0] is not master    # 先尝试从库
    assert calls[1] is master        # 降级到主库
    assert mdb._ro_circuit_open() is True   # 熔断已打开


def test_read_sql_ro_skips_slave_while_circuit_open(restore_rw_state, monkeypatch):
    """熔断打开期间：read_sql_ro 直接走主库，不再尝试从库。"""
    mdb.RW_SPLIT_ENABLED = True
    mdb._engine_ro_instance = None
    mdb._READ_MYSQL_CONN_URL = 'mysql+pymysql://ro:ro@127.0.0.1:3306/testdb'
    mdb._ro_unhealthy_until = time.monotonic() + 100   # 强制熔断打开
    captured = {}

    def fake_read_sql(sql, con=None, params=None, **kw):
        captured['con'] = con
        return 'OK'

    monkeypatch.setattr('pandas.read_sql', fake_read_sql)
    assert mdb.read_sql_ro('SELECT 1') == 'OK'
    assert captured['con'] is mdb.engine()   # 直接主库，未碰从库


def test_read_sql_ro_does_not_catch_query_errors(restore_rw_state, monkeypatch):
    """查询级错误（如 ProgrammingError）不应被降级吞掉，必须原样抛出。"""
    from sqlalchemy.exc import ProgrammingError

    mdb.RW_SPLIT_ENABLED = True
    mdb._engine_ro_instance = None
    mdb._READ_MYSQL_CONN_URL = 'mysql+pymysql://ro:ro@127.0.0.1:3306/testdb'
    mdb._ro_unhealthy_until = 0.0

    def fake_read_sql(sql, con=None, params=None, **kw):
        raise ProgrammingError('SELECT bad', None, Exception("Unknown column 'bad'"))

    monkeypatch.setattr('pandas.read_sql', fake_read_sql)
    with pytest.raises(ProgrammingError):
        mdb.read_sql_ro('SELECT bad')
    assert mdb._ro_circuit_open() is False   # 查询错误不触发熔断
