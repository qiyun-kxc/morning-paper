#!/usr/bin/env python3
"""
arXiv 晨报论文蓄水池 — 每日选择脚本

职责：
1. 检查当天是否已有 report_items，有则复用（幂等）。
2. 没有则从候选池中选 top 5 未推送论文。
3. 候选不足时触发紧急 refill。
4. 写入 report_items（选稿记录）。
5. 输出论文文本给后续 Gemini 流程。
6. 晨报发送成功后，由外部调用 mark_report_sent() 写入 sent。
"""

import sys
import logging

from arxiv_common import (
    get_conn, init_tables, refill_until_ready,
    get_report_date, get_now_iso,
    DB_PATH, MIN_FOR_REPORT,
)

log = logging.getLogger("select")


def get_today_papers(conn, report_date: str) -> list[dict]:
    """检查今天是否已选过论文，有则复用。"""
    rows = conn.execute("""
        SELECT p.id, p.title, p.abstract, p.url, p.categories,
               p.final_score, p.score_reason
        FROM report_items r
        JOIN papers p ON p.id = r.id
        WHERE r.report_date = ?
        ORDER BY r.rank
    """, (report_date,)).fetchall()

    if rows:
        log.info("Reusing %d papers for %s", len(rows), report_date)
        return [
            {
                "id": r[0], "title": r[1], "abstract": r[2],
                "url": r[3], "categories": r[4],
                "final_score": r[5], "score_reason": r[6],
            }
            for r in rows
        ]
    return []


def select_new_papers(conn) -> list[dict]:
    """从候选池中选出 top 5 未推送论文。"""
    rows = conn.execute("""
        SELECT p.id, p.title, p.abstract, p.url, p.categories,
               p.final_score, p.score_reason
        FROM papers p
        LEFT JOIN sent s ON p.id = s.id
        WHERE s.id IS NULL
        ORDER BY p.final_score DESC, p.published DESC
        LIMIT ?
    """, (MIN_FOR_REPORT,)).fetchall()

    return [
        {
            "id": r[0], "title": r[1], "abstract": r[2],
            "url": r[3], "categories": r[4],
            "final_score": r[5], "score_reason": r[6],
        }
        for r in rows
    ]


def save_selection(conn, report_date: str, papers: list[dict]):
    """只写 report_items（选稿记录），不写 sent。
    sent 必须在晨报真正发送成功后才写入，避免失败时论文被永久跳过。
    """
    for rank, p in enumerate(papers, start=1):
        conn.execute("""
            INSERT OR IGNORE INTO report_items (report_date, id, rank)
            VALUES (?, ?, ?)
        """, (report_date, p["id"], rank))
    conn.commit()
    log.info("Saved %d selected papers to report_items for %s", len(papers), report_date)


def mark_report_sent(conn, report_date: str):
    """晨报发送成功后调用：把 report_items 中的论文标记为已发送。"""
    now = get_now_iso()
    conn.execute("""
        INSERT OR IGNORE INTO sent (id, sent_at, report_date)
        SELECT id, ?, report_date FROM report_items WHERE report_date = ?
    """, (now, report_date))
    conn.commit()
    count = conn.execute(
        "SELECT COUNT(*) FROM report_items WHERE report_date = ?",
        (report_date,)
    ).fetchone()[0]
    log.info("Marked %d papers as sent for %s", count, report_date)


def format_output(papers: list[dict]) -> str:
    """输出论文文本，供 Gemini 使用。"""
    lines = []
    for i, p in enumerate(papers, start=1):
        lines.append(f"### Paper {i}")
        lines.append(f"Title: {p['title']}")
        lines.append(f"Abstract: {p['abstract']}")
        lines.append(f"URL: {p['url']}")
        lines.append(f"Categories: {p['categories']}")
        lines.append(f"QualityScore: {p['final_score']}")
        lines.append(f"Reason: {p['score_reason']}")
        lines.append("")
    return "\n".join(lines)


def main():
    log.info("=== select_daily_papers start ===")
    conn = get_conn(DB_PATH)
    try:
        init_tables(conn)
        report_date = get_report_date()

        # 1. 检查今天是否已选过
        papers = get_today_papers(conn, report_date)

        # 2. 没有则新选
        if not papers:
            # 检查候选池，不足则紧急 refill
            from arxiv_common import unsent_count
            count = unsent_count(conn)
            if count < MIN_FOR_REPORT:
                log.warning("Only %d unsent, need %d — triggering emergency refill",
                            count, MIN_FOR_REPORT)
                refill_until_ready(conn)

            papers = select_new_papers(conn)

            if not papers:
                log.error("No papers available even after refill!")
                print("ERROR: No papers available for today's report.", file=sys.stderr)
                sys.exit(1)

            if len(papers) < MIN_FOR_REPORT:
                log.warning("Only %d papers available (wanted %d)", len(papers), MIN_FOR_REPORT)

            # 写入 report_items（sent 在发送成功后由 mark_report_sent 写入）
            save_selection(conn, report_date, papers)

        # 3. 输出
        output = format_output(papers)
        print(output)

    except Exception as e:
        log.error("Selection failed: %s", e, exc_info=True)
        sys.exit(1)
    finally:
        conn.close()

    log.info("=== select_daily_papers done ===")


if __name__ == "__main__":
    main()
