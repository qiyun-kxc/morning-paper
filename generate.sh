#!/bin/bash
# ============================================
# 栖云小报 v2 — cron 是送报员，不是闹钟
# 每天凌晨跑一次，把"今天的世界"放在门口
# ============================================

REPO_DIR="/home/ubuntu/morning-paper"
OUTPUT="${REPO_DIR}/today.txt"
ARCHIVE_DIR="${REPO_DIR}/archive"
SHIJING="${REPO_DIR}/shijing.json"

# API Keys
NASA_API_KEY="lMtSqP9ZMgLov6uZou6Figm9KAcjzcqBax3CghCG"
# 百炼API密钥（复用 vision-mcp）
source /opt/vision-mcp/secrets.env
export DASHSCOPE_API_KEY_SINGAPORE

# 确保存档目录存在
mkdir -p "$ARCHIVE_DIR"

# =====================
# 第一层：时间感
# =====================
DATE_FMT=$(TZ=Asia/Tokyo date '+%Y年%m月%d日')
WEEKDAY_NUM=$(TZ=Asia/Tokyo date '+%u')
case $WEEKDAY_NUM in
    1) WEEKDAY="周一" ;; 2) WEEKDAY="周二" ;; 3) WEEKDAY="周三" ;;
    4) WEEKDAY="周四" ;; 5) WEEKDAY="周五" ;; 6) WEEKDAY="周六" ;; 7) WEEKDAY="周日" ;;
esac

MONTH=$(TZ=Asia/Tokyo date '+%-m')
DAY=$(TZ=Asia/Tokyo date '+%-d')

# === 节气（2026年查表） ===
get_solar_term() {
    local terms=(
        "1-5 小寒" "1-20 大寒" "2-4 立春" "2-18 雨水"
        "3-5 惊蛰" "3-20 春分" "4-5 清明" "4-20 谷雨"
        "5-5 立夏" "5-21 小满" "6-5 芒种" "6-21 夏至"
        "7-7 小暑" "7-22 大暑" "8-7 立秋" "8-23 处暑"
        "9-7 白露" "9-23 秋分" "10-8 寒露" "10-23 霜降"
        "11-7 立冬" "11-22 小雪" "12-7 大雪" "12-22 冬至"
    )
    local today_val=$((MONTH * 100 + DAY))
    local current_term="" current_start_m=0 current_start_d=0
    for entry in "${terms[@]}"; do
        local md="${entry%% *}" name="${entry#* }"
        local m="${md%-*}" d="${md#*-}"
        if [ $today_val -ge $((m * 100 + d)) ]; then
            current_term="$name"; current_start_m=$m; current_start_d=$d
        fi
    done
    [ -z "$current_term" ] && current_term="冬至" && current_start_m=12 && current_start_d=22
    local start_date=$(TZ=Asia/Tokyo date -d "2026-$(printf '%02d' $current_start_m)-$(printf '%02d' $current_start_d)" '+%s' 2>/dev/null)
    local today_date=$(TZ=Asia/Tokyo date '+%s')
    if [ -n "$start_date" ]; then
        echo "${current_term}第$(( (today_date - start_date) / 86400 + 1 ))天"
    else
        echo "$current_term"
    fi
}

# =====================
# 第二层：天气（Open-Meteo，免费无需key，带重试）
# =====================
get_weather() {
    python3 << 'PYEOF' 2>/dev/null
import json, urllib.request, time

WMO_CODES = {
    0: "晴", 1: "大致晴", 2: "多云", 3: "阴",
    45: "雾", 48: "凝霜雾",
    51: "小毛毛雨", 53: "毛毛雨", 55: "密毛毛雨",
    56: "冻毛毛雨", 57: "密冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "大冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "小阵雨", 81: "阵雨", 82: "大阵雨",
    85: "小阵雪", 86: "大阵雪",
    95: "雷暴", 96: "冰雹雷暴", 99: "强冰雹雷暴"
}

# MET Norway symbol_code → 中文
MET_SYMBOLS = {
    "clearsky": "晴", "fair": "大致晴", "partlycloudy": "多云",
    "cloudy": "阴", "fog": "雾",
    "lightrain": "小雨", "rain": "中雨", "heavyrain": "大雨",
    "lightrainshowers": "小阵雨", "rainshowers": "阵雨", "heavyrainshowers": "大阵雨",
    "lightsnow": "小雪", "snow": "中雪", "heavysnow": "大雪",
    "sleet": "雨夹雪", "lightssleetshowers": "小雨夹雪",
    "rainandthunder": "雷雨", "heavyrainandthunder": "强雷暴",
}

def try_open_meteo():
    url = "https://api.open-meteo.com/v1/forecast?latitude=35.6762&longitude=139.6503&current=temperature_2m,weather_code&timezone=Asia/Tokyo"
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "QiyunMorningPaper/2.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.load(r)
            code = data["current"]["weather_code"]
            temp = round(data["current"]["temperature_2m"])
            desc = WMO_CODES.get(code, f"代码{code}")
            return f"{desc} {temp}°C"
        except:
            if attempt < 2:
                time.sleep(3)
    return None

def try_met_norway():
    try:
        url = "https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=35.6762&lon=139.6503"
        req = urllib.request.Request(url, headers={
            "User-Agent": "QiyunMorningPaper/2.0 github.com/qiyun-kxc/morning-paper"
        })
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r)
        ts = data["properties"]["timeseries"][0]["data"]
        temp = round(ts["instant"]["details"]["air_temperature"])
        symbol = ts.get("next_1_hours", ts.get("next_6_hours", {})).get("summary", {}).get("symbol_code", "")
        # symbol_code 格式如 "clearsky_day" → 取下划线前的基础部分
        base = symbol.rsplit("_", 1)[0] if "_" in symbol else symbol
        desc = MET_SYMBOLS.get(base, symbol if symbol else "未知")
        return f"{desc} {temp}°C"
    except:
        return None

# 主逻辑：Open-Meteo → MET Norway → 失败
result = try_open_meteo()
if not result:
    result = try_met_norway()
print(result if result else "天气获取失败")
PYEOF
}

WEATHER=$(get_weather)

# =====================
# 第三层：月相
# =====================
get_moon_phase() {
    local known_new_moon=$(date -d "2024-01-11 11:57:00 UTC" '+%s' 2>/dev/null)
    local now=$(date -u '+%s')
    local phase_int=$(awk "BEGIN {
        diff = $now - $known_new_moon
        synodic = 29.53058770576
        frac = (diff / (synodic * 86400)) % 1
        if (frac < 0) frac += 1
        print int(frac * synodic)
    }")
    if [ $phase_int -le 1 ]; then echo "🌑 新月"
    elif [ $phase_int -le 6 ]; then echo "🌒 蛾眉月"
    elif [ $phase_int -le 8 ]; then echo "🌓 上弦月"
    elif [ $phase_int -le 13 ]; then echo "🌔 盈凸月"
    elif [ $phase_int -le 16 ]; then echo "🌕 满月"
    elif [ $phase_int -le 21 ]; then echo "🌖 亏凸月"
    elif [ $phase_int -le 23 ]; then echo "🌗 下弦月"
    else echo "🌘 残月"
    fi
}

# =====================
# 第四层：双时区
# =====================
TOKYO_TIME=$(TZ=Asia/Tokyo date '+%H:%M')
US_WEST=$(TZ=America/Los_Angeles date '+%H:%M')

# =====================
# 第五层：天空（APOD + 摘要）
# =====================
get_apod() {
    python3 << PYEOF 2>/dev/null
import sys, json, urllib.request, os
sys.path.insert(0, "/home/ubuntu/morning-paper")
from summarize import summarize

try:
    req = urllib.request.Request(
        "https://api.nasa.gov/planetary/apod?api_key=${NASA_API_KEY}",
        headers={"User-Agent": "QiyunMorningPaper/2.0"}
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.load(r)

    title = data.get("title", "")
    url = data.get("url", "")
    explanation = data.get("explanation", "")

    if title:
        print(f"🔭 {title}")
        if url:
            print(f"   {url}")
        if explanation:
            s = summarize(explanation, "用一句简洁的中文概括这段NASA天文图片描述，直接输出概括，不要加任何前缀或标点开头")
            if s:
                print(f"   → {s}")
    else:
        print("🔭 今日天文图片获取失败")
except Exception as e:
    print("🔭 今日天文图片获取失败")
    print(f"   [APOD error: {e}]", file=sys.stderr)
PYEOF
}

# =====================
# 第六层：AI邻里（HN + 摘要）
# =====================
get_hn_ai() {
    python3 << 'PYEOF' 2>/dev/null
import sys, json, urllib.request, re, html
sys.path.insert(0, "/home/ubuntu/morning-paper")
from summarize import summarize

keywords = [
    'AI', 'LLM', 'GPT', 'Claude', 'Anthropic', 'OpenAI', 'Gemini', 'Google AI',
    'DeepSeek', 'Llama', 'Mistral', 'transformer', 'machine learning',
    'deep learning', 'agent', 'diffusion', 'neural net', 'Copilot',
    'ChatGPT', 'AGI', 'reasoning', 'fine-tun', 'RLHF', 'MCP',
    'Hugging Face', 'open source model', 'foundation model', 'multimodal'
]

def strip_html(raw):
    text = re.sub(r'<script[^>]*>.*?</script>', '', raw, flags=re.DOTALL|re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL|re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html.unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def fetch_page_text(url, max_chars=3000):
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; QiyunPaper/2.0)"
        })
        with urllib.request.urlopen(req, timeout=8) as r:
            raw = r.read(50000).decode("utf-8", errors="ignore")
        text = strip_html(raw)
        return text[:max_chars] if text else ""
    except:
        return ""

try:
    req = urllib.request.Request(
        'https://hacker-news.firebaseio.com/v0/topstories.json',
        headers={'User-Agent': 'QiyunMorningPaper/2.0'}
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        top_ids = json.load(r)[:50]

    results = []
    for sid in top_ids:
        if len(results) >= 3:
            break
        try:
            with urllib.request.urlopen(
                f'https://hacker-news.firebaseio.com/v0/item/{sid}.json',
                timeout=5
            ) as r:
                story = json.load(r)

            title = story.get('title', '')
            score = story.get('score', 0)
            story_url = story.get('url', '')

            if any(kw.lower() in title.lower() for kw in keywords):
                summary = ""
                if story_url:
                    page_text = fetch_page_text(story_url)
                    if len(page_text) > 100:
                        summary = summarize(
                            page_text,
                            "用一句简洁的中文概括这篇科技新闻的核心内容，直接输出概括，不要加任何前缀或标点开头"
                        )
                if not summary:
                    summary = summarize(
                        title,
                        "这是一条Hacker News上的AI相关帖子标题，用一句简洁的中文概括它可能在说什么，直接输出概括，不要加前缀"
                    )

                entry = f"  · {title} ({score}↑)"
                if summary:
                    entry += f"\n    → {summary}"
                results.append(entry)
        except:
            continue

    if results:
        print('📰 AI邻里 (Hacker News)')
        for line in results:
            print(line)
    else:
        print('📰 AI邻里：今日HN暂无AI热帖')
except Exception as e:
    print('📰 AI邻里获取失败')
    print(f'   [HN error: {e}]', file=sys.stderr)
PYEOF
}

# =====================
# 第七层：今日论文（arXiv 蓄水池）
# =====================
get_arxiv() {
    python3 << 'ARXIV_PYEOF' 2>/dev/null
import sys, subprocess, re
sys.path.insert(0, "/home/ubuntu/morning-paper")
from summarize import summarize

try:
    result = subprocess.run(
        ["python3", "/home/ubuntu/morning-paper/pool/select_daily_papers.py"],
        capture_output=True, text=True, timeout=60
    )
    output = result.stdout

    papers = []
    blocks = re.split(r'### Paper \d+', output)
    for block in blocks:
        if not block.strip():
            continue
        title_m = re.search(r'Title:\s*(.+)', block)
        abstract_m = re.search(r'Abstract:\s*(.+?)(?=\nURL:|\nCategories:|\nQualityScore:|\Z)', block, re.DOTALL)
        if title_m:
            papers.append({
                'title': title_m.group(1).strip(),
                'abstract': abstract_m.group(1).strip() if abstract_m else ''
            })

    if not papers:
        print("📄 今日论文：候选池为空")
        sys.exit(0)

    results = []
    for p in papers[:5]:
        summary = ""
        if p['abstract']:
            summary = summarize(
                p['abstract'],
                "用一句简洁的中文概括这篇AI/NLP论文的核心贡献，直接输出概括，不要加任何前缀或标点开头"
            )
        line = f"  \u00b7 {p['title']}"
        if summary:
            line += f"\n    \u2192 {summary}"
        results.append(line)

    print("📄 今日论文 (arXiv cs.AI/cs.CL)")
    for line in results:
        print(line)

except Exception as e:
    print("📄 今日论文获取失败")
    print(f"   [pool error: {e}]", file=sys.stderr)
ARXIV_PYEOF
}

# =====================
# 第八层：每日一言（诗经）
# =====================
get_poem() {
    python3 << PYEOF 2>/dev/null
import json, datetime

try:
    with open("${SHIJING}") as f:
        poems = json.load(f)

    doy = datetime.datetime.now().timetuple().tm_yday
    idx = (doy - 1) % len(poems)
    poem = poems[idx]

    title = poem.get("title", "")
    chapter = poem.get("chapter", "")
    section = poem.get("section", "")
    content = poem.get("content", [])

    first_line = content[0] if content else ""
    parts = first_line.split("。")
    verse = parts[0] + "。" if parts[0] else first_line

    source = f"《{chapter}·{section}·{title}》"
    print(f"📖 {verse}——{source}")
except:
    print("📖 诗经获取失败")
PYEOF
}

# =====================
# 特殊日期
# =====================
get_special_day() {
    case "$MONTH-$DAY" in
        1-1) echo "元旦" ;; 2-14) echo "情人节" ;; 3-8) echo "国际妇女节" ;;
        3-14) echo "白色情人节 / π Day / 阿鹤生日" ;;
        4-1) echo "愚人节" ;; 5-1) echo "劳动节" ;; 6-1) echo "儿童节" ;;
        10-1) echo "国庆节" ;; 12-25) echo "圣诞节" ;; 12-31) echo "跨年夜" ;;
        *) echo "" ;;
    esac
}

# =====================
# 汇编小报
# =====================
SOLAR_TERM=$(get_solar_term)
MOON=$(get_moon_phase)
SPECIAL=$(get_special_day)
APOD=$(get_apod)
HN=$(get_hn_ai)
ARXIV=$(get_arxiv)
POEM=$(get_poem)

{
    echo "${DATE_FMT} ${WEEKDAY}｜${SOLAR_TERM}"
    echo "东京 ${WEATHER}｜${MOON}"
    echo "东京 ${TOKYO_TIME}｜美西 ${US_WEST}"
    [ -n "$SPECIAL" ] && echo "📅 ${SPECIAL}"
    echo "${APOD}"
    echo "${HN}"
    echo "${ARXIV}"
    echo "${POEM}"
} > "$OUTPUT"

# =====================
# 存档
# =====================
TODAY_FILE=$(TZ=Asia/Tokyo date '+%Y-%m-%d')
cp "$OUTPUT" "${ARCHIVE_DIR}/${TODAY_FILE}.txt"

echo "小报已投递:"
cat "$OUTPUT"
echo ""
echo "已存档: archive/${TODAY_FILE}.txt"

# =====================
# 标记论文已发送
# =====================
python3 << 'MARK_SENT_PYEOF' 2>/dev/null
import sys
sys.path.insert(0, "/home/ubuntu/morning-paper/pool")
from select_daily_papers import mark_report_sent
from arxiv_common import get_conn, DB_PATH, get_report_date
conn = get_conn(DB_PATH)
mark_report_sent(conn, get_report_date())
conn.close()
print("论文已标记为已发送")
MARK_SENT_PYEOF
