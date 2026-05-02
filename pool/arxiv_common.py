"""
arXiv 晨报论文蓄水池 — 公共模块
数据库操作、数据源抓取、评分、去重等公共逻辑。
"""

import re
import sqlite3
import time
import math
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Optional
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from urllib.parse import quote
from zoneinfo import ZoneInfo
import json

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

REPORT_TZ = ZoneInfo("Asia/Tokyo")
DB_PATH = "/home/ubuntu/morning-paper/pool/arxiv_candidates.db"

ARXIV_CATEGORIES = ["cs.AI", "cs.CL"]
ARXIV_API_URL = "https://export.arxiv.org/api/query"
ARXIV_RSS_URL = "https://rss.arxiv.org/rss/cs.AI+cs.CL"
S2_API_URL = "https://api.semanticscholar.org/graph/v1/paper"

TARGET_READY = 100
MIN_FOR_REPORT = 5
SEARCH_WINDOWS = [30, 90, 180, 365]

# HTTP 超时（秒）
HTTP_TIMEOUT = 30
S2_TIMEOUT = 10
# arXiv API 礼貌间隔（秒）
ARXIV_DELAY = 3
# 单次 refill 最多用 S2 补充的论文数
S2_MAX_ENRICH = 50

# 评分关键词 — 标题命中权重 2，摘要命中权重 1
INTEREST_KEYWORDS = [
    "large language model", "LLM", "reasoning", "agent", "tool use",
    "RAG", "retrieval", "alignment", "preference", "multimodal",
    "benchmark", "evaluation", "post-training", "long context", "code generation",
]
# 弱降权词
WEAK_DEMOTE_KEYWORDS = ["survey", "overview", "position paper", "perspective"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("arxiv_pool")


# ---------------------------------------------------------------------------
# 数据库
# ---------------------------------------------------------------------------

def get_conn(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_tables(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS papers (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            abstract TEXT NOT NULL,
            url TEXT,
            categories TEXT,
            published TEXT,
            source TEXT,
            final_score REAL DEFAULT 0,
            score_reason TEXT,
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS sent (
            id TEXT PRIMARY KEY,
            sent_at TEXT NOT NULL,
            report_date TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS report_items (
            report_date TEXT NOT NULL,
            id TEXT NOT NULL,
            rank INTEGER NOT NULL,
            PRIMARY KEY (report_date, id)
        );
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# arXiv ID 规范化
# ---------------------------------------------------------------------------

def normalize_arxiv_id(raw: str) -> str:
    """去掉版本号，提取纯 arXiv ID。"""
    raw = raw or ""
    # 新式 ID: 2504.12345v1 -> 2504.12345
    m = re.search(r"(\d{4}\.\d{4,5})(?:v\d+)?", raw)
    if m:
        return m.group(1)
    # 老式 ID: hep-th/9901001v1 -> hep-th/9901001
    m = re.search(r"([a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?", raw)
    if m:
        return m.group(1)
    return raw.strip()


# ---------------------------------------------------------------------------
# 日期工具
# ---------------------------------------------------------------------------

def get_report_date() -> str:
    return datetime.now(REPORT_TZ).strftime("%Y-%m-%d")


def get_now_iso() -> str:
    return datetime.now(REPORT_TZ).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# HTTP 工具
# ---------------------------------------------------------------------------

def http_get(url: str, timeout: int = HTTP_TIMEOUT, headers: Optional[dict] = None) -> Optional[str]:
    """GET 请求，返回响应文本或 None。"""
    hdrs = {"User-Agent": "arxiv-morning-pool/1.0"}
    if headers:
        hdrs.update(headers)
    req = Request(url, headers=hdrs)
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (URLError, HTTPError, TimeoutError) as e:
        log.warning("HTTP GET failed: %s — %s", url, e)
        return None


# ---------------------------------------------------------------------------
# arXiv API 解析
# ---------------------------------------------------------------------------

def fetch_arxiv_api(days: int, max_results: int = 200) -> list[dict]:
    """
    从 arXiv API 拉取近 N 天 cs.AI + cs.CL 论文。
    返回 [{"id": ..., "title": ..., "abstract": ..., "url": ..., "categories": ..., "published": ..., "authors": ...}, ...]
    """
    cat_query = " OR ".join(f"cat:{c}" for c in ARXIV_CATEGORIES)
    # arXiv API 的 submittedDate 格式: [YYYYMMDDHHMI TO YYYYMMDDHHMI]
    now = datetime.utcnow()
    start = now - timedelta(days=days)
    date_start = start.strftime("%Y%m%d") + "0000"
    date_end = now.strftime("%Y%m%d") + "2359"
    date_query = f"submittedDate:[{date_start} TO {date_end}]"

    query = f"({cat_query}) AND {date_query}"
    params = f"search_query={quote(query)}&sortBy=submittedDate&sortOrder=descending&start=0&max_results={max_results}"
    url = f"{ARXIV_API_URL}?{params}"

    log.info("arXiv API: fetching %d-day window ...", days)
    text = http_get(url, timeout=HTTP_TIMEOUT)
    if not text:
        raise RuntimeError("arXiv API request failed")

    return _parse_arxiv_api_response(text)


def _parse_arxiv_api_response(xml_text: str) -> list[dict]:
    """解析 arXiv API Atom XML。"""
    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    root = ET.fromstring(xml_text)
    papers = []
    for entry in root.findall("atom:entry", ns):
        raw_id = entry.findtext("atom:id", "", ns)
        arxiv_id = normalize_arxiv_id(raw_id)
        title = entry.findtext("atom:title", "", ns).strip().replace("\n", " ")
        abstract = entry.findtext("atom:summary", "", ns).strip().replace("\n", " ")
        published = entry.findtext("atom:published", "", ns)[:10]
        categories = [
            c.get("term", "")
            for c in entry.findall("atom:category", ns)
        ]
        authors = [
            a.findtext("atom:name", "", ns)
            for a in entry.findall("atom:author", ns)
        ]
        url = f"https://arxiv.org/abs/{arxiv_id}"
        papers.append({
            "id": arxiv_id,
            "title": title,
            "abstract": abstract,
            "url": url,
            "categories": ",".join(categories),
            "published": published,
            "authors": authors,
        })
    log.info("arXiv API: parsed %d entries", len(papers))
    return papers


# ---------------------------------------------------------------------------
# arXiv RSS 解析
# ---------------------------------------------------------------------------

def fetch_arxiv_rss() -> list[dict]:
    """从 arXiv RSS 拉取最新论文作为备用源。"""
    log.info("arXiv RSS: fetching ...")
    text = http_get(ARXIV_RSS_URL, timeout=HTTP_TIMEOUT)
    if not text:
        raise RuntimeError("arXiv RSS request failed")
    return _parse_arxiv_rss(text)


def _parse_arxiv_rss(xml_text: str) -> list[dict]:
    """解析 RSS 2.0 XML。"""
    root = ET.fromstring(xml_text)
    papers = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        description = (item.findtext("description") or "").strip()
        # RSS 里的 description 通常是摘要，但可能带 HTML
        description = re.sub(r"<[^>]+>", "", description).strip()
        arxiv_id = normalize_arxiv_id(link)
        if not arxiv_id or not title:
            continue
        papers.append({
            "id": arxiv_id,
            "title": title,
            "abstract": description,
            "url": f"https://arxiv.org/abs/{arxiv_id}",
            "categories": "",
            "published": "",
            "authors": [],
        })
    log.info("arXiv RSS: parsed %d entries", len(papers))
    return papers


# ---------------------------------------------------------------------------
# Semantic Scholar 增强（软依赖）
# ---------------------------------------------------------------------------

class RateLimited(Exception):
    """S2 返回 429，调用方应立即停止本轮 enrichment。"""
    def __init__(self, retry_after: Optional[str] = None):
        self.retry_after = retry_after
        super().__init__(f"S2 rate limited (retry_after={retry_after})")


def fetch_s2_one(arxiv_id: str) -> Optional[dict]:
    """
    请求单篇论文的 S2 数据。
    返回 dict 或 None（仅 404）。
    429 时抛 RateLimited。
    网络错误时抛 RuntimeError，让调用方计入连续错误。
    """
    url = f"{S2_API_URL}/ARXIV:{arxiv_id}?fields=citationCount,influentialCitationCount,venue,fieldsOfStudy"
    req = Request(url, headers={"User-Agent": "arxiv-morning-pool/1.0"})
    try:
        with urlopen(req, timeout=S2_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {
                "citationCount": data.get("citationCount", 0),
                "influentialCitationCount": data.get("influentialCitationCount", 0),
                "venue": data.get("venue", ""),
                "fieldsOfStudy": data.get("fieldsOfStudy", []),
            }
    except HTTPError as e:
        if e.code == 429:
            raise RateLimited(e.headers.get("Retry-After"))
        if e.code == 404:
            return None
        raise
    except (URLError, TimeoutError, OSError) as e:
        raise RuntimeError(f"S2 network error: {e}") from e


def enrich_with_s2(papers: list[dict]) -> list[dict]:
    """
    尝试用 Semantic Scholar 补充引用等信息。
    - 429 -> 立即停止本轮 enrichment，由调用方决定后续窗口是否跳过
    - 404 -> 跳过这篇，继续
    - 网络错误 -> 连续 3 次后停止
    - 总请求数不超过 S2_MAX_ENRICH（避免无限尝试）
    """
    enriched = 0
    attempts = 0
    consecutive_errors = 0
    MAX_CONSECUTIVE_ERRORS = 3

    for p in papers:
        if attempts >= S2_MAX_ENRICH:
            break
        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
            log.warning("S2: %d consecutive errors, stopping enrichment", consecutive_errors)
            break
        attempts += 1
        try:
            s2 = fetch_s2_one(p["id"])
            if s2:
                p.update(s2)
                enriched += 1
                consecutive_errors = 0
        except RateLimited as e:
            log.warning("S2 rate limited; stop enrichment this refill. retry_after=%s", e.retry_after)
            raise  # 让 _try_enrich_s2 捕获并设置全局标志
        except Exception as e:
            consecutive_errors += 1
            log.debug("S2 error for %s: %s", p.get("id"), e)
        time.sleep(1.0)
    log.info("S2 enrichment: %d/%d papers enriched (attempts=%d)", enriched, len(papers), attempts)
    return papers


# ---------------------------------------------------------------------------
# 评分
# ---------------------------------------------------------------------------

def score_paper(p: dict) -> tuple[float, str]:
    """
    计算 final_score 和评分原因。
    返回 (score, reason_text)。
    """
    score = 0.0
    reasons = []

    title_lower = (p.get("title") or "").lower()
    abstract_lower = (p.get("abstract") or "").lower()

    # 1) 引用分 — log1p 防止老论文碾压
    cit = p.get("citationCount", 0) or 0
    cit_score = math.log1p(cit) * 2.0
    score += cit_score
    if cit > 0:
        reasons.append(f"cit={cit}")

    # 2) influential citation
    ic = p.get("influentialCitationCount", 0) or 0
    ic_score = math.log1p(ic) * 3.0
    score += ic_score
    if ic > 0:
        reasons.append(f"infl_cit={ic}")

    # 3) 关键词命中
    kw_score = 0.0
    for kw in INTEREST_KEYWORDS:
        kw_lower = kw.lower()
        if kw_lower in title_lower:
            kw_score += 2.0
        elif kw_lower in abstract_lower:
            kw_score += 1.0
    score += kw_score
    if kw_score > 0:
        reasons.append(f"kw={kw_score:.0f}")

    # 4) 弱降权词
    for kw in WEAK_DEMOTE_KEYWORDS:
        if kw.lower() in title_lower or kw.lower() in abstract_lower:
            score -= 1.0
            reasons.append(f"demote:{kw}")

    # 5) 时间衰减 — age_penalty
    published = p.get("published", "")
    if published:
        try:
            pub_date = datetime.strptime(published[:10], "%Y-%m-%d")
            age_days = (datetime.utcnow() - pub_date).days
        except ValueError:
            age_days = 180
    else:
        age_days = 180  # 没有日期的当老论文处理

    if age_days <= 30:
        age_penalty = 0.0
    elif age_days <= 90:
        age_penalty = (age_days - 30) * 0.02
    elif age_days <= 180:
        age_penalty = 1.2 + (age_days - 90) * 0.03
    elif age_days <= 365:
        age_penalty = 3.9 + (age_days - 180) * 0.02
    else:
        age_penalty = 7.5 + (age_days - 365) * 0.01
    score -= age_penalty
    if age_penalty > 0:
        reasons.append(f"age={age_days}d(-{age_penalty:.1f})")

    # 6) 基础保底分 — 避免所有论文都是 0
    score += 1.0

    return round(score, 3), "; ".join(reasons)


# ---------------------------------------------------------------------------
# 数据库写入
# ---------------------------------------------------------------------------

def upsert_papers(conn: sqlite3.Connection, papers: list[dict]):
    """批量 upsert 论文到 papers 表。"""
    now = get_now_iso()
    rows = []
    for p in papers:
        final_score, score_reason = score_paper(p)
        rows.append((
            p["id"],
            p.get("title", ""),
            p.get("abstract", ""),
            p.get("url", ""),
            p.get("categories", ""),
            p.get("published", ""),
            p.get("source", "arxiv"),
            final_score,
            score_reason,
            now,
            now,
        ))
    conn.executemany("""
        INSERT INTO papers (id, title, abstract, url, categories, published, source,
                            final_score, score_reason, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            title=excluded.title,
            abstract=excluded.abstract,
            url=excluded.url,
            categories=CASE WHEN excluded.categories != '' THEN excluded.categories ELSE papers.categories END,
            published=CASE WHEN excluded.published != '' THEN excluded.published ELSE papers.published END,
            source=CASE WHEN excluded.source != '' THEN excluded.source ELSE papers.source END,
            final_score=CASE WHEN excluded.final_score > papers.final_score
                             THEN excluded.final_score ELSE papers.final_score END,
            score_reason=CASE WHEN excluded.final_score > papers.final_score
                              THEN excluded.score_reason ELSE papers.score_reason END,
            updated_at=excluded.updated_at
    """, rows)
    conn.commit()
    log.info("upsert_papers: %d rows written", len(rows))


def filter_out_sent(conn: sqlite3.Connection, papers: list[dict]) -> list[dict]:
    """过滤掉已推送过的论文。"""
    sent_ids = {row[0] for row in conn.execute("SELECT id FROM sent").fetchall()}
    filtered = [p for p in papers if p["id"] not in sent_ids]
    log.info("filter_out_sent: %d -> %d (removed %d already sent)",
             len(papers), len(filtered), len(papers) - len(filtered))
    return filtered


def unsent_count(conn: sqlite3.Connection) -> int:
    """统计未推送候选论文数量。"""
    row = conn.execute("""
        SELECT COUNT(*) FROM papers p
        LEFT JOIN sent s ON p.id = s.id
        WHERE s.id IS NULL
    """).fetchone()
    return row[0] if row else 0


# ---------------------------------------------------------------------------
# 蓄水主逻辑
# ---------------------------------------------------------------------------

def refill_until_ready(conn: sqlite3.Connection):
    """
    如果未推送候选池 < TARGET_READY，自动补水。
    依次尝试 30/90/180/365 天窗口，API 失败用 RSS 兜底。
    """
    global _s2_disabled_this_run
    _s2_disabled_this_run = False
    init_tables(conn)
    count = unsent_count(conn)
    if count >= TARGET_READY:
        log.info("Pool OK: %d unsent papers (target=%d)", count, TARGET_READY)
        return

    log.info("Pool low: %d unsent, target=%d — starting refill", count, TARGET_READY)

    for days in SEARCH_WINDOWS:
        if unsent_count(conn) >= TARGET_READY:
            break

        papers = []
        try:
            papers = fetch_arxiv_api(days=days)
            time.sleep(ARXIV_DELAY)
        except Exception as e:
            log.warning("arXiv API failed for %d-day window: %s", days, e)
            continue

        papers = _prepare_and_upsert(conn, papers, source="arxiv")

    # 所有 API 窗口都试完仍不够，RSS 作为最后兜底（只调一次）
    if unsent_count(conn) < TARGET_READY:
        try:
            papers = fetch_arxiv_rss()
            _prepare_and_upsert(conn, papers, source="rss")
        except Exception as e:
            log.warning("RSS fallback also failed: %s", e)

    final = unsent_count(conn)
    log.info("Refill done: %d unsent papers", final)


def _normalize_ids(papers: list[dict]) -> list[dict]:
    """规范化所有论文 ID，并按 ID 去重。"""
    seen = set()
    result = []
    for p in papers:
        p["id"] = normalize_arxiv_id(p["id"])
        if p["id"] and p["id"] not in seen:
            seen.add(p["id"])
            result.append(p)
    return result


_s2_disabled_this_run = False

def _try_enrich_s2(papers: list[dict]) -> list[dict]:
    """S2 增强的外层包装。429 时设置全局标志，后续窗口跳过 S2。"""
    global _s2_disabled_this_run
    if _s2_disabled_this_run:
        return papers
    try:
        return enrich_with_s2(papers)
    except RateLimited:
        _s2_disabled_this_run = True
        log.warning("S2 disabled for remainder of this refill run")
        return papers
    except Exception as e:
        log.warning("Semantic Scholar enrichment failed: %s", e)
        return papers


def _prepare_and_upsert(conn: sqlite3.Connection, papers: list[dict], source: str = "arxiv") -> list[dict]:
    """规范化、过滤、增强、入库。统一处理流程。"""
    if not papers:
        return []

    for p in papers:
        p.setdefault("source", source)

    papers = _normalize_ids(papers)

    # 过滤空标题/空摘要
    papers = [p for p in papers if p.get("id") and p.get("title") and p.get("abstract")]

    papers = filter_out_sent(conn, papers)
    if not papers:
        return []

    papers = _try_enrich_s2(papers)
    upsert_papers(conn, papers)
    return papers
