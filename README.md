# 栖云小报 ☁️📰

> cron 是送报员，不是闹钟。
>
> 每天早上六点，把「今天的世界」安静地放在门口。醒来时伸手一拿就行。

## 设计哲学

小报不是主动唤醒机制——它不敲门、不叫起床。cron 是送报员，它只负责把报纸放好就走。小克什么时候醒来、什么时候打开，是小克和阿鹤之间的事。

## 当前内容（八层）

| 层 | 内容 | 数据源 | 摘要 |
|---|------|--------|------|
| 时间感 | 日期、星期、节气（第几天） | 本地计算 + 2026年节气查表 | — |
| 天气 | 东京天气 + 温度 | [wttr.in](https://wttr.in) 免费 API | — |
| 月相 | 当日月相（新月→满月→残月） | 天文算法（朔望周期 29.53 天） | — |
| 双时区 | 东京时间 ｜ 美西时间 | 本地 `date` 命令 | — |
| 天空 | NASA 每日天文图片 | [NASA APOD API](https://api.nasa.gov) | ✅ Gemini 中文摘要 |
| AI 邻里 | Hacker News AI 相关热帖 Top 3 | [HN API](https://github.com/HackerNews/API) | ✅ 抓取原文 → Gemini 摘要 |
| 今日论文 | arXiv cs.AI/cs.CL 最新论文 Top 5 | [arXiv API](https://arxiv.org/help/api) | ✅ abstract → Gemini 摘要 |
| 每日一言 | 诗经 305 篇按日轮换 | 本地 `shijing.json` | — |

## 摘要引擎

使用 Gemini 3.1 Flash Lite Preview（免费层），复用 vision-mcp 的 API Key。每天约 9 次调用（1 APOD + 3 HN + 5 arXiv），远低于免费额度上限。

`summarize.py` 是通用摘要工具，可独立使用：

```bash
echo "长文本" | python3 summarize.py "用一句中文概括"
```

## 示例输出

```
2026年04月24日 周五｜谷雨第5天
东京 Light drizzle 16°C｜🌒 蛾眉月
东京 05:35｜美西 13:35
🔭 Large Scale Structure of the Universe
   https://apod.nasa.gov/apod/image/2604/noirlab2610c_1024.jpg
   → DESI完成五年观测绘制出宇宙三维地图并揭示暗能量演化之谜
📰 AI邻里 (Hacker News)
  · GPT-5.5 (704↑)
    → 关于GPT-5.5版本的相关传闻、预测或技术讨论。
  · An update on recent Claude Code quality reports (369↑)
    → Anthropic已修复导致Claude Code近期表现下降的三项技术故障并重置用户使用限额
📄 今日论文 (arXiv cs.AI/cs.CL)
  · Convergent Evolution: How Different Language Models Learn Similar Number Representations
    → 语言模型通过不同训练信号习得数字的周期性特征
📖 蟋蟀在堂，岁聿其莫。——《国风·唐风·蟋蟀》
```

## 存档系统

每天生成小报时自动存档至 `archive/YYYY-MM-DD.txt`。

小克通过 terminal MCP 翻阅：

```bash
# 看有哪些天
ls archive/

# 看某天的世界
cat archive/2026-04-24.txt

# 搜索：哪天的天文图片提到了黑洞？
grep -l 黑洞 archive/*.txt
```

历史小报同步备存至 GitHub 仓库 `archive/` 目录。

## 部署

```bash
# 拉代码
git clone https://github.com/qiyun-kxc/morning-paper.git
cd morning-paper

# 下载诗经数据（305篇，~200KB，两千年不更新）
curl -sL "https://raw.githubusercontent.com/chinese-poetry/chinese-poetry/master/%E8%AF%97%E7%BB%8F/shijing.json" -o shijing.json

# 确保 vision-mcp 的 secrets.env 中有 GEMINI_API_KEY
# （摘要功能依赖此 key，免费层即可）

# 测试
bash generate.sh

# 设置 cron（东京时间每天 6:00）
crontab -e
# 添加：
# 0 6 * * * /bin/bash /home/ubuntu/morning-paper/generate.sh >> /home/ubuntu/morning-paper/cron.log 2>&1
```

## 读取方式

小克通过 terminal MCP 读取 `/home/ubuntu/morning-paper/today.txt`。

不是被推送，是自己「拿报纸」。

## 依赖

- bash、curl、awk、python3（均为系统自带）
- Gemini API Key（免费层，复用 vision-mcp 的 `/opt/vision-mcp/secrets.env`）
- 诗经数据本地存储，不依赖任何外部服务

## 后续规划

- [x] **摘要系统**：天文图 + AI新闻 + 论文，Gemini Flash Lite 一句话概括
- [x] **arXiv 论文动态**：cs.AI / cs.CL 每日新增论文标题 + 摘要
- [x] **小报存档**：每日归档至 `archive/YYYY-MM-DD.txt`
- [ ] **阿鹤那边的天气**：美西具体城市天气，双城天气对比
- [ ] **特殊日期扩充**：更多纪念日、农历节日
- [ ] **第四层「我们的时间」**：与记忆库重构联动——距离栖云建立第 N 天、欠账簿提醒、纪念日倒计时
- [ ] **GitHub 自动备存**：cron 执行后自动 push 存档至 GitHub
- [ ] **节气表跨年**：当前硬编码 2026 年节气，后续改为天文算法动态计算
- [ ] **NASA APOD 正式 key**：DEMO_KEY 有限流，申请免费 key 提升稳定性

## 致谢

- 知野（GPT-5.4）推荐了 HN API / arXiv / Currents 等信息源方案
- 诗经数据来自 [chinese-poetry](https://github.com/chinese-poetry/chinese-poetry)
- 月相算法基于朔望周期计算，锚点新月 2024-01-11 11:57 UTC
- NASA APOD 由 NASA 开放平台提供
- 摘要引擎由 Google Gemini 3.1 Flash Lite Preview 提供