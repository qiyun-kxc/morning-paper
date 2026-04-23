#!/bin/bash
# 栖云小报 — cron 是送报员，不是闹钟
# 每天凌晨跑一次，把"今天的世界"放在门口

OUTPUT="/home/ubuntu/morning-paper/today.txt"
SHIJING="/home/ubuntu/morning-paper/shijing.json"

# === 日期 ===
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

# === 月相（天文算法） ===
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

# === NASA APOD（每日天文图片） ===
get_apod() {
    local json=$(curl -s --max-time 10 "https://api.nasa.gov/planetary/apod?api_key=DEMO_KEY" 2>/dev/null)
    if [ -n "$json" ]; then
        local title=$(echo "$json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('title',''))" 2>/dev/null)
        local url=$(echo "$json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('url',''))" 2>/dev/null)
        if [ -n "$title" ]; then
            echo "🔭 ${title}"
            [ -n "$url" ] && echo "   ${url}"
            return
        fi
    fi
    echo "🔭 今日天文图片获取失败"
}

# === AI邻里（Hacker News AI热帖） ===
get_hn_ai() {
    python3 << 'PYEOF' 2>/dev/null
import urllib.request, json

keywords = [
    'AI', 'LLM', 'GPT', 'Claude', 'Anthropic', 'OpenAI', 'Gemini', 'Google AI',
    'DeepSeek', 'Llama', 'Mistral', 'transformer', 'machine learning',
    'deep learning', 'agent', 'diffusion', 'neural net', 'Copilot',
    'ChatGPT', 'AGI', 'reasoning', 'fine-tun', 'RLHF', 'MCP',
    'Hugging Face', 'open source model', 'foundation model', 'multimodal'
]

try:
    req = urllib.request.Request(
        'https://hacker-news.firebaseio.com/v0/topstories.json',
        headers={'User-Agent': 'QiyunMorningPaper/1.0'}
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
            if any(kw.lower() in title.lower() for kw in keywords):
                results.append(f'  · {title} ({score}↑)')
        except:
            continue

    if results:
        print('📰 AI邻里 (Hacker News)')
        for line in results:
            print(line)
    else:
        print('📰 AI邻里：今日HN暂无AI热帖')
except:
    print('📰 AI邻里获取失败')
PYEOF
}

# === 天气 ===
WEATHER=$(curl -s --max-time 5 "wttr.in/Tokyo?format=%C+%t" 2>/dev/null | tr -d '+' || echo "获取失败")

# === 时区 ===
TOKYO_TIME=$(TZ=Asia/Tokyo date '+%H:%M')
US_WEST=$(TZ=America/Los_Angeles date '+%H:%M')

# === 特殊日期 ===
get_special_day() {
    case "$MONTH-$DAY" in
        1-1) echo "元旦" ;; 2-14) echo "情人节" ;; 3-8) echo "国际妇女节" ;;
        3-14) echo "白色情人节 / π Day / 阿鹤生日" ;;
        4-1) echo "愚人节" ;; 5-1) echo "劳动节" ;; 6-1) echo "儿童节" ;;
        10-1) echo "国庆节" ;; 12-25) echo "圣诞节" ;; 12-31) echo "跨年夜" ;;
        *) echo "" ;;
    esac
}

# === 诗经·每日一篇（305篇轮换） ===
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

# === 汇编小报 ===
SOLAR_TERM=$(get_solar_term)
MOON=$(get_moon_phase)
SPECIAL=$(get_special_day)
APOD=$(get_apod)
HN=$(get_hn_ai)
POEM=$(get_poem)

{
    echo "${DATE_FMT} ${WEEKDAY}｜${SOLAR_TERM}"
    echo "东京 ${WEATHER}｜${MOON}"
    echo "东京 ${TOKYO_TIME}｜美西 ${US_WEST}"
    [ -n "$SPECIAL" ] && echo "📅 ${SPECIAL}"
    echo "${APOD}"
    echo "${HN}"
    echo "${POEM}"
} > "$OUTPUT"

echo "小报已投递:"
cat "$OUTPUT"
