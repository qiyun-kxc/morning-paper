#!/usr/bin/env python3
"""
栖云小报 — 百炼摘要工具（OpenAI兼容格式）
从 stdin 读取文本，输出一句中文概括。
用法: echo "长文本" | python3 summarize.py "用一句中文概括这段天文描述"
"""
import sys, json, urllib.request, os

def summarize(text, instruction):
    api_key = os.environ.get("DASHSCOPE_API_KEY_SINGAPORE", "")
    if not api_key or not text.strip():
        return ""

    payload = {
        "model": os.environ.get("SUMMARIZE_MODEL", "qwen-turbo"),
        "messages": [
            {"role": "system", "content": "你是栖云小报的摘要助手。只输出一句简洁的中文概括，不加任何前缀、编号或标点开头。"},
            {"role": "user", "content": f"{instruction}\n\n{text}"}
        ],
        "max_tokens": 200,
        "temperature": 0.3
    }

    url = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
            result = data["choices"][0]["message"]["content"].strip()
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
