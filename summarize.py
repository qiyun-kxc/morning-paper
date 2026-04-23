#!/usr/bin/env python3
"""
栖云小报 — Gemini 摘要工具
从 stdin 读取文本，输出一句中文概括。
用法: echo "长文本" | python3 summarize.py "用一句中文概括这段天文描述"
"""
import sys, json, urllib.request, os

def summarize(text, instruction):
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key or not text.strip():
        return ""

    prompt = f"{instruction}\n\n{text}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": 200,
            "temperature": 0.3
        }
    }

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite-preview:generateContent?key={api_key}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
            result = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            # 只取第一行，确保是一句话
            return result.split("\n")[0].strip()
    except Exception as e:
        print(f"[summarize error: {e}]", file=sys.stderr)
        return ""

if __name__ == "__main__":
    instruction = sys.argv[1] if len(sys.argv) > 1 else "用一句简洁的中文概括以下内容，直接输出概括，不要加前缀"
    text = sys.stdin.read()
    result = summarize(text, instruction)
    if result:
        print(result)