#!/usr/bin/env python3
"""
arXiv 晨报论文蓄水池 — 后台补水脚本

定时运行（推荐 cron 每 6 小时），自动补充候选池到 TARGET_READY 水位。
不输出晨报，只负责蓄水。
"""

import sys
import logging

from arxiv_common import (
    get_conn, init_tables, refill_until_ready, DB_PATH,
)

log = logging.getLogger("refill")


def main():
    log.info("=== refill_arxiv_pool start ===")
    conn = get_conn(DB_PATH)
    try:
        init_tables(conn)
        refill_until_ready(conn)
    except Exception as e:
        log.error("Refill failed: %s", e, exc_info=True)
        sys.exit(1)
    finally:
        conn.close()
    log.info("=== refill_arxiv_pool done ===")


if __name__ == "__main__":
    main()
