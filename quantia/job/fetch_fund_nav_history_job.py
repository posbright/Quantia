#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""F8 基金净值历史回填（独立慢 job，不进每日 fetch 主链）。

逐基金抓取「单位净值走势 + 累计净值走势」，合并写 cn_fund_nav_history，
供回撤 / 夏普 / 净值曲线计算。**派生风险/收益指标一律用 acc_nav（累计净值）**。

抓取范围（落地性）：默认仅覆盖各 fund_type 桶按近1年收益的 Top-N（排除货币型、债券型；
货币型无单位/累计净值走势，债券型波动小、回测意义有限），断点续抓（跳过库中已有最新 nav_date 的 code）。
属 fetch 管道（akshare 单源）。低频 cron（cron.workdayly）或手动触发。

用法：
    python fetch_fund_nav_history_job.py [code1 code2 ...]   # 指定基金，直连默认库写入
    python fetch_fund_nav_history_job.py                     # 自动选 Top-N
    python fetch_fund_nav_history_job.py --workers 4         # 并发抓取（抓取并发、写库仍串行）

本地高内存机抓取 → 文件搬运 → 服务器本地入库（避免经公网批量写远程小内存库 OOM）：
    # 裸文件名默认落在 tools/fund/（git 跟踪，便于推送搬运）；也可传绝对路径或含目录的路径
    # ① 本地（16G）：仅并发抓取 + 落盘，不连任何库写入（.csv.gz 零额外依赖；.parquet 需 pyarrow）
    python fetch_fund_nav_history_job.py --export nav_dump.csv.gz --workers 12
    # 各类 Top-600 + 仅近 5 年净值 + 拆成 4 个分片文件（规避 GitHub 单文件 100MB 限制）
    python fetch_fund_nav_history_job.py --export nav_dump.csv.gz --workers 12 --topn 600 --years 5 --parts 4
    # ② git add/commit/push tools/fund/nav_dump.part*.csv.gz（或 scp 到服务器）
    # ③ 服务器（1.6G）：只读文件增量 upsert 到 localhost MySQL，不发任何 API（自动发现分片）
    python fetch_fund_nav_history_job.py --import nav_dump.csv.gz
"""
import argparse
import datetime
import logging
import os.path
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor

cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)
try:
    from quantia.lib.log_config import setup_logging
    setup_logging('fetch')
except Exception:
    log_path = os.path.join(cpath_current, 'log')
    os.makedirs(log_path, exist_ok=True)
    logging.basicConfig(
        format='%(asctime)s [%(levelname)s] %(message)s',
        filename=os.path.join(log_path, 'fund_nav_history_job.log'),
        level=logging.INFO,
    )

import quantia.core.tablestructure as tbs
import quantia.core.crawling.fund_em as fem
import quantia.lib.database as mdb
import quantia.lib.envconfig as _cfg
from quantia.lib.job_tracker import record_task_start, record_task_end

__author__ = 'Quantia'
__date__ = '2026/06/01'

_JOB_NAME = 'run_fund_nav_history'
_RANK_TABLE = tbs.TABLE_CN_FUND_RANK['name']
_NAV_TABLE = tbs.TABLE_CN_FUND_NAV_HISTORY['name']
_MONEY_TYPE = '货币型'
# 抓取时排除的基金类型：货币型（无单位/累计净值走势）、债券型（波动小、回测意义有限）。
_EXCLUDE_TYPES = ('货币型', '债券型')

# export/import 临时净值文件的默认存放目录（git 跟踪，便于推送搬运）。
# 仅含目录名的相对路径会落到此处；绝对路径或含目录的路径按原样使用。
_FUND_DUMP_DIR = os.path.join(cpath, 'tools', 'fund')


def _resolve_dump_path(path):
    """裸文件名（无目录分隔）落到 tools/fund/；绝对路径或显式带目录的路径原样返回。"""
    if os.path.isabs(path) or os.path.dirname(path):
        return path
    return os.path.join(_FUND_DUMP_DIR, path)



def _select_target_codes(limit_per_type):
    """各净值型桶的目标 code（排除货币型、债券型）。

    - limit_per_type > 0：各桶按近1年收益取 Top-N。
    - limit_per_type <= 0：全量回填（不限桶内数量），用于一次性铺底
      （配 QUANTIA_FUND_NAV_TOPN=0）。
    """
    if not mdb.checkTableIsExist(_RANK_TABLE):
        return []
    limit_per_type = int(limit_per_type)
    placeholders = ','.join(['%s'] * len(_EXCLUDE_TYPES))
    if limit_per_type <= 0:
        sql = (
            f"SELECT code FROM `{_RANK_TABLE}` "
            f"WHERE `date` = (SELECT MAX(`date`) FROM `{_RANK_TABLE}`) "
            f"  AND fund_type NOT IN ({placeholders})"
        )
        rows = mdb.executeSqlFetch(sql, tuple(_EXCLUDE_TYPES))
        return [str(r[0]) for r in rows if r and r[0] is not None]
    sql = (
        f"SELECT code FROM ("
        f"  SELECT code, fund_type,"
        f"    ROW_NUMBER() OVER (PARTITION BY fund_type ORDER BY (`rate_1y` IS NULL), `rate_1y` DESC) AS rn"
        f"  FROM `{_RANK_TABLE}`"
        f"  WHERE `date` = (SELECT MAX(`date`) FROM `{_RANK_TABLE}`)"
        f"    AND fund_type NOT IN ({placeholders})"
        f") t WHERE t.rn <= %s"
    )
    rows = mdb.executeSqlFetch(sql, tuple(_EXCLUDE_TYPES) + (limit_per_type,))
    return [str(r[0]) for r in rows if r and r[0] is not None]


def _existing_max_navdate(code):
    """库中该基金已有的最新净值日（断点续抓增量过滤），无则 None。"""
    if not mdb.checkTableIsExist(_NAV_TABLE):
        return None
    rows = mdb.executeSqlFetch(
        f"SELECT MAX(`nav_date`) FROM `{_NAV_TABLE}` WHERE `code` = %s", (code,))
    if rows and rows[0] and rows[0][0] is not None:
        return rows[0][0]
    return None


def _write_hist_incremental(code, hist):
    """对给定的整段净值历史 df 做「增量过滤 + upsert 写库」，返回写入行数。

    增量语义：仅保留库中该基金已有最新 nav_date 之后的行；底层走
    insert_db_from_df 的 append + ON DUPLICATE KEY UPDATE，幂等可重跑（非全量覆盖）。
    """
    if hist is None or len(hist.index) == 0:
        return 0
    max_date = _existing_max_navdate(code)
    if max_date is not None:
        # 仅保留库中最新日之后的增量行
        hist = hist[hist['nav_date'].map(lambda d: d is not None and d > max_date)]
    if len(hist.index) == 0:
        return 0
    cols_type = None
    if not mdb.checkTableIsExist(_NAV_TABLE):
        cols_type = tbs.get_field_types(tbs.TABLE_CN_FUND_NAV_HISTORY['columns'])
    mdb.insert_db_from_df(hist, _NAV_TABLE, cols_type, False, "`code`,`nav_date`")
    return len(hist.index)


def save_fund_nav_history(code):
    """抓取 + 增量写入单只基金净值历史，返回写入行数（0 表示无新增/失败）。"""
    return _write_hist_incremental(code, fem.fund_nav_history(code))


def _fetch_full(code):
    """并发抓取单只完整净值历史（仅网络，不写库）。返回 (code, hist|None)，自带限速。"""
    hist = None
    try:
        hist = fem.fund_nav_history(code)
    except Exception:
        logging.warning(f"fetch_fund_nav_history_job: {code} 抓取失败，跳过", exc_info=True)
    finally:
        time.sleep(random.uniform(0.5, 1.5))  # 限速（并发下每 worker 各自节流）
    return code, hist


def run(codes=None, limit_per_type=None, job_date=None, workers=None):
    job_date = job_date or datetime.date.today()
    if limit_per_type is None:
        limit_per_type = _cfg.get_int('QUANTIA_FUND_NAV_TOPN', 200)
    if workers is None:
        workers = _cfg.get_int('QUANTIA_FUND_NAV_WORKERS', 1)
    workers = max(1, int(workers))
    if not codes:
        codes = _select_target_codes(limit_per_type)
    if not codes:
        logging.warning("fetch_fund_nav_history_job: 无目标基金（cn_fund_rank 为空？）")
        return 0

    start = record_task_start(_JOB_NAME, 'nav_history', job_date)
    total_rows = 0
    ok = 0
    if workers <= 1:
        for code in codes:
            try:
                n = save_fund_nav_history(code)
                total_rows += n
                if n > 0:
                    ok += 1
            except Exception:
                logging.warning(f"fetch_fund_nav_history_job: {code} 处理失败，跳过", exc_info=True)
            finally:
                time.sleep(random.uniform(0.5, 1.5))  # 限速
    else:
        # 进程级并发抓取：akshare 依赖 py_mini_racer(V8) 跑 JS 解密，V8 isolate 非线程安全，
        # 多线程并发会 partition_address_space Check failed 崩溃，故用独立进程隔离。
        # 写库仍在主进程串行，规避共享 engine 的并发问题。
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for code, hist in ex.map(_fetch_full, codes):
                try:
                    n = _write_hist_incremental(code, hist)
                    total_rows += n
                    if n > 0:
                        ok += 1
                except Exception:
                    logging.warning(f"fetch_fund_nav_history_job: {code} 写库失败，跳过", exc_info=True)
    record_task_end(_JOB_NAME, 'nav_history', job_date, start, success=True,
                    message=f"{ok}/{len(codes)} 基金有新增", rows_affected=total_rows)
    logging.info(f"fetch_fund_nav_history_job 完成：{ok}/{len(codes)} 基金，共 {total_rows} 行")
    return total_rows


def _dump_frame(df, out_path):
    """按扩展名落盘：.parquet → parquet（需 pyarrow），否则 csv。"""
    out_path = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    if out_path.lower().endswith('.parquet'):
        df.to_parquet(out_path, index=False)
    else:
        df.to_csv(out_path, index=False, encoding='utf-8-sig')


def _part_path(path, idx, total):
    """在文件名（首个 '.' 之前）插入 .partNN，保留完整扩展名（含 .csv.gz 双扩展）。

    例：nav_dump.csv.gz, idx=1/total=3 → nav_dump.part01.csv.gz
    """
    d = os.path.dirname(path)
    base = os.path.basename(path)
    dot = base.find('.')
    stem, ext = (base[:dot], base[dot:]) if dot > 0 else (base, '')
    width = max(2, len(str(total)))
    return os.path.join(d, f"{stem}.part{idx:0{width}d}{ext}")


def _filter_recent_years(df, years):
    """仅保留最近 years 年的净值行（全局以今日为基准）；years<=0 或 None 不过滤。

    成立不足 years 年的基金保留其全部行（"如果有"）。
    """
    if not years or years <= 0:
        return df
    cutoff = datetime.date.today() - datetime.timedelta(days=int(round(years * 365.25)))
    return df[df['nav_date'].map(lambda d: d is not None and d >= cutoff)]



def _load_frame(in_path):
    """按扩展名读盘并规整类型（nav_date→date，数值列→float）。"""
    import pandas as pd
    if in_path.lower().endswith('.parquet'):
        df = pd.read_parquet(in_path)
    else:
        df = pd.read_csv(in_path, dtype={'code': str})
    df['code'] = df['code'].astype(str)
    df['nav_date'] = pd.to_datetime(df['nav_date'], errors='coerce').dt.date
    for col in ('unit_nav', 'acc_nav', 'day_growth'):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.dropna(subset=['nav_date'])
    return df[['code', 'nav_date', 'unit_nav', 'acc_nav', 'day_growth']]


def _codes_from_akshare(limit_per_type):
    """离线选 code：直接从 akshare 全市场排行抓取（不连数据库），排除货币型、债券型。

    - limit_per_type > 0：各 fund_type 桶按近1年收益（rate_1y）取 Top-N。
    - limit_per_type <= 0：全量（桶内不限）。
    供本地导出场景使用：当数据库不可达（如本机连不上远程 MySQL）时回退到此源。
    """
    rank = fem.fund_rank_all()
    if rank is None or 'code' not in rank.columns:
        return []
    rank = rank[~rank.get('fund_type').isin(_EXCLUDE_TYPES)].copy()
    rank['code'] = rank['code'].astype(str)
    rank = rank.drop_duplicates(subset=['code'])
    limit_per_type = int(limit_per_type)
    if limit_per_type > 0 and 'rate_1y' in rank.columns and 'fund_type' in rank.columns:
        import pandas as pd
        rank['rate_1y'] = pd.to_numeric(rank['rate_1y'], errors='coerce')
        rank = (rank.sort_values('rate_1y', ascending=False, na_position='last')
                    .groupby('fund_type', group_keys=False)
                    .head(limit_per_type))
    return [c for c in rank['code'].tolist() if c]


def export_nav_history(out_path, codes=None, limit_per_type=None, workers=None,
                       years=None, parts=1):
    """并发抓取完整净值历史并落盘，**不写任何数据库**（供本地高内存机抓取后搬运）。

    选 code 优先读 cn_fund_rank（轻量 SELECT）；数据库不可达时自动回退到 akshare 全市场排行，
    实现完全离线导出。如需指定范围可显式传 codes 跳过两种选源。

    - years > 0：仅保留最近 years 年净值（成立不足者保留全部）。
    - parts > 1：按 code 均分成 parts 个文件 name.partNN.ext，规避 GitHub 单文件大小限制。
    """
    import pandas as pd
    if limit_per_type is None:
        limit_per_type = _cfg.get_int('QUANTIA_FUND_NAV_TOPN', 200)
    if workers is None:
        workers = _cfg.get_int('QUANTIA_FUND_NAV_WORKERS', 8)
    if years is None:
        years = _cfg.get_int('QUANTIA_FUND_NAV_YEARS', 0)
    workers = max(1, int(workers))
    parts = max(1, int(parts))
    if not codes:
        # 优先走数据库选源；DB 不可达（本机连不上远程 MySQL）时回退到 akshare 全市场排行。
        # QUANTIA_FUND_NAV_OFFLINE=1 可直接跳过 DB（避免无谓的连库超时重试）。
        offline = _cfg.get_int('QUANTIA_FUND_NAV_OFFLINE', 0)
        if not offline:
            try:
                codes = _select_target_codes(limit_per_type)
            except Exception:
                logging.warning("export_nav_history: 数据库选源失败，回退 akshare 全市场排行", exc_info=True)
                codes = None
        if not codes:
            logging.info("export_nav_history: 改用 akshare 排行选 code（离线模式）")
            codes = _codes_from_akshare(limit_per_type)
    if not codes:
        logging.warning("export_nav_history: 无目标基金（数据库与 akshare 排行均为空）")
        return 0

    frames = []
    ok = 0
    # 进程级并发：akshare/py_mini_racer 的 V8 isolate 非线程安全，必须用独立进程。
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for code, hist in ex.map(_fetch_full, codes):
            if hist is not None and len(hist.index) > 0:
                frames.append(_filter_recent_years(hist, years))
                ok += 1
    frames = [f for f in frames if len(f.index) > 0]
    if not frames:
        logging.warning("export_nav_history: 抓取结果为空，未落盘")
        return 0
    all_df = pd.concat(frames, ignore_index=True)
    out_path = _resolve_dump_path(out_path)

    if parts <= 1:
        _dump_frame(all_df, out_path)
        logging.info(f"export_nav_history 完成：{ok}/{len(codes)} 基金，共 {len(all_df.index)} 行 → {out_path}")
        return len(all_df.index)

    # 按 code 均分成 parts 份，每份独立落盘（整只基金不跨文件，便于按基金增量入库）。
    uniq = list(all_df['code'].drop_duplicates())
    groups = [uniq[i::parts] for i in range(parts)]
    written = 0
    for i, grp in enumerate(groups, start=1):
        if not grp:
            continue
        sub = all_df[all_df['code'].isin(set(grp))]
        p = _part_path(out_path, i, parts)
        _dump_frame(sub, p)
        written += len(sub.index)
        logging.info(f"export_nav_history 分片 {i}/{parts}：{len(grp)} 基金，{len(sub.index)} 行 → {p}")
    logging.info(f"export_nav_history 完成：{ok}/{len(codes)} 基金，共 {written} 行，{parts} 个分片")
    return written


def _resolve_import_paths(in_path):
    """把 import 入参解析为待读文件列表，支持单文件 / 目录 / 通配 / 自动发现分片。

    - 字面文件存在 → [它]
    - 目录 → 目录内 *.csv.gz/*.csv/*.parquet
    - 含通配符 → glob 展开
    - 否则尝试同名分片 name.part*.ext（export --parts 的产物）
    """
    import glob
    if os.path.isfile(in_path):
        return [in_path]
    if os.path.isdir(in_path):
        out = []
        for ext in ('*.csv.gz', '*.csv', '*.parquet'):
            out.extend(glob.glob(os.path.join(in_path, ext)))
        return sorted(out)
    if any(ch in in_path for ch in '*?['):
        return sorted(glob.glob(in_path))
    # 自动发现分片：nav_dump.csv.gz → nav_dump.part*.csv.gz
    base = os.path.basename(in_path)
    dot = base.find('.')
    stem, ext = (base[:dot], base[dot:]) if dot > 0 else (base, '')
    pattern = os.path.join(os.path.dirname(in_path), f"{stem}.part*{ext}")
    return sorted(glob.glob(pattern))


def import_nav_history(in_path, job_date=None):
    """读 export 落盘文件，按 code 增量 upsert 到 localhost MySQL，**不发任何 API**。

    支持单文件、目录、通配符，或自动发现 name.part*.ext 分片（逐文件处理以省内存）。
    """
    job_date = job_date or datetime.date.today()
    in_path = _resolve_dump_path(in_path)
    paths = _resolve_import_paths(in_path)
    if not paths:
        logging.error(f"import_nav_history: 未找到任何可导入文件 {in_path}")
        return 0

    start = record_task_start(_JOB_NAME, 'nav_history', job_date)
    total_rows = 0
    ok = 0
    all_codes = set()
    for path in paths:
        df = _load_frame(path)
        if len(df.index) == 0:
            logging.warning(f"import_nav_history: {path} 无有效行，跳过")
            continue
        codes = list(df['code'].drop_duplicates())
        all_codes.update(codes)
        for code in codes:
            hist = df[df['code'] == code]
            try:
                n = _write_hist_incremental(code, hist)
                total_rows += n
                if n > 0:
                    ok += 1
            except Exception:
                logging.warning(f"import_nav_history: {code} 写库失败，跳过", exc_info=True)
        logging.info(f"import_nav_history: {path} 处理完毕（累计 {total_rows} 行）")
    record_task_end(_JOB_NAME, 'nav_history', job_date, start, success=True,
                    message=f"{ok}/{len(all_codes)} 基金有新增（import，{len(paths)} 文件）",
                    rows_affected=total_rows)
    logging.info(f"import_nav_history 完成：{ok}/{len(all_codes)} 基金，共 {total_rows} 行 ← {len(paths)} 个文件")
    return total_rows


def main():
    parser = argparse.ArgumentParser(description='F8 基金净值历史回填（支持并发抓取 / 本地导出 + 服务器导入）')
    parser.add_argument('codes', nargs='*', help='指定基金代码（缺省时按 cn_fund_rank Top-N 自动选）')
    parser.add_argument('--workers', type=int, default=None,
                        help='并发抓取线程数（默认读 QUANTIA_FUND_NAV_WORKERS，未设为 1=串行）')
    parser.add_argument('--export', dest='export_path', default=None,
                        help='仅并发抓取并落盘到该路径（.csv.gz/.csv/.parquet；裸文件名落在 tools/fund/），不写任何数据库')
    parser.add_argument('--import', dest='import_path', default=None,
                        help='仅读取该文件（裸文件名从 tools/fund/ 查找）增量 upsert 到 localhost MySQL，不发任何 API')
    parser.add_argument('--years', type=int, default=None,
                        help='导出时仅保留最近 N 年净值（成立不足 N 年保留全部）；默认读 QUANTIA_FUND_NAV_YEARS')
    parser.add_argument('--topn', type=int, default=None,
                        help='各 fund_type 桶 Top-N（默认读 QUANTIA_FUND_NAV_TOPN，未设为 200）')
    parser.add_argument('--parts', type=int, default=1,
                        help='导出拆分为 N 个文件 name.partNN.ext，规避 GitHub 单文件大小限制（默认 1=不拆分）')
    args = parser.parse_args([a for a in sys.argv[1:] if a.strip()])

    if args.import_path:
        import_nav_history(args.import_path)
    elif args.export_path:
        export_nav_history(args.export_path, codes=args.codes or None,
                           limit_per_type=args.topn, workers=args.workers,
                           years=args.years, parts=args.parts)
    else:
        run(codes=args.codes or None, workers=args.workers)


if __name__ == '__main__':
    main()
