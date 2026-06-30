"""读写分离（engine_ro / use_master）单元测试。

只测试路由/网关逻辑，不建立真实数据库连接：
- SQLAlchemy `create_engine` 是惰性的，不会在创建时连接 MySQL；
- 启用分支用 in-memory sqlite URL，避免命中网络。
"""

import pytest

import quantia.lib.database as mdb


@pytest.fixture
def restore_rw_state():
    """保存并恢复读写分离相关的模块级状态，避免污染其它测试。"""
    saved = {
        'RW_SPLIT_ENABLED': mdb.RW_SPLIT_ENABLED,
        '_engine_ro_instance': mdb._engine_ro_instance,
        '_READ_MYSQL_CONN_URL': mdb._READ_MYSQL_CONN_URL,
    }
    # 同时清掉可能残留的线程局部强制主库标记
    if hasattr(mdb._thread_local, 'force_master_reads'):
        delattr(mdb._thread_local, 'force_master_reads')
    yield
    mdb.RW_SPLIT_ENABLED = saved['RW_SPLIT_ENABLED']
    mdb._engine_ro_instance = saved['_engine_ro_instance']
    mdb._READ_MYSQL_CONN_URL = saved['_READ_MYSQL_CONN_URL']
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
