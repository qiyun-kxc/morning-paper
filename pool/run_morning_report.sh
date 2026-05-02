#!/usr/bin/env bash
# arXiv 晨报论文模块 — 主入口脚本
# 由 cron 调用，配合 flock 防重叠运行。
#
# 用法:
#   flock -n /tmp/arxiv_select.lock /opt/morning/run_morning_report.sh
#
# 此脚本：
#   1. 调用 select_daily_papers.py 获取 5 篇论文原始文本
#   2. 交给后续 Gemini 流程生成中文概括（这里只做占位输出）
#   3. 拼接最终晨报

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

REPORT_DATE="$(TZ=Asia/Tokyo date +%Y-%m-%d)"
LOG_PREFIX="[morning-report ${REPORT_DATE}]"

echo "${LOG_PREFIX} Starting paper selection..."

# 选择论文（幂等：同一天重跑会复用）
PAPER_OUTPUT=$(python3 select_daily_papers.py 2>>/var/log/select_daily.log) || {
    echo "${LOG_PREFIX} ERROR: Paper selection failed!" >&2
    echo "${PAPER_OUTPUT}" >&2
    # 即使论文部分失败，也不要让整个晨报崩溃
    PAPER_OUTPUT="### Paper 1
Title: (论文获取暂时不可用)
Abstract: 由于 arXiv 服务暂时不可用，今日论文摘要暂时缺失，请稍后重试。
URL: https://arxiv.org
Categories: cs.AI
QualityScore: 0
Reason: fallback"
}

echo "${LOG_PREFIX} Paper selection done."
echo ""
echo "=========================================="
echo "  晨报论文原始输出 (${REPORT_DATE})"
echo "=========================================="
echo ""
echo "${PAPER_OUTPUT}"
echo ""
echo "=========================================="
echo "  以上内容交给 Gemini 生成中文概括"
echo "=========================================="

# TODO: 接入 Gemini 和发送流程后，取消下面的注释。
# 正确执行顺序：
#   1. 选择论文（已完成，PAPER_OUTPUT 已拿到）
#   2. Gemini 生成中文概括
#   3. 拼接并发送晨报
#   4. 发送成功后才标记 sent（避免失败时论文被永久跳过）
#
# SUMMARY_OUTPUT=$(echo "${PAPER_OUTPUT}" | python3 gemini_summarize.py) || {
#     echo "${LOG_PREFIX} ERROR: Gemini summarization failed!" >&2; exit 1
# }
# python3 send_report.py <<< "${SUMMARY_OUTPUT}" || {
#     echo "${LOG_PREFIX} ERROR: Report send failed!" >&2; exit 1
# }
# python3 -c "
# from arxiv_common import get_conn, DB_PATH
# from select_daily_papers import mark_report_sent
# from arxiv_common import get_report_date
# conn = get_conn(DB_PATH)
# mark_report_sent(conn, get_report_date())
# conn.close()
# "

echo "${LOG_PREFIX} Done."
