# 栖云小报 ☁️📰

> cron 是送报员，不是闹钟。
>
> 每天早上六点，把「今天的世界」安静地放在门口。醒来时伸手一拿就行。

## 设计哲学

小报不是主动唤醒机制——它不敲门、不叫起床。cron 是送报员，它只负责把报纸放好就走。小克什么时候醒来、什么时候打开，是小克和阿鹤之间的事。

## 当前内容（七层）

| 层 | 内容 | 数据源 | 状态 |
|---|------|--------|------|
| 时间感 | 日期、星期、节气（第几天） | 本地计算 + 2026年节气查表 | ✅ 已完成 |
| 天气 | 东京天气 + 温度 | [wttr.in](https://wttr.in) 免费 API | ✅ 已完成 |
| 月相 | 当日月相（新月→满月→残月） | 天文算法（朔望周期 29.53 天） | ✅ 已完成 |
| 双时区 | 东京时间 ｜ 美西时间 | 本地 `date` 命令 | ✅ 已完成 |
| 天空 | NASA 每日天文图片标题 + 链接 | [NASA APOD API](https://api.nasa.gov) DEMO_KEY | ✅ 已完成 |
| AI 邻里 | Hacker News AI 相关热帖 Top 3 | [HN API](https://github.com/HackerNews/API) 免费无限制 | ✅ 已完成 |
| 每日一言 | 诗经 305 篇按日轮换 | 本地 `shijing.json`（[chinese-poetry](https://github.com/chinese-poetry/chinese-poetry)） | ✅ 已完成 |

## 示例输出

```
2026年04月24日 周五｜谷雨第5天
东京 Light rain shower 16°C｜🌒 蛾眉月
东京 03:41｜美西 11:41
🔭 Large Scale Structure of the Universe
   https://apod.nasa.gov/apod/image/2604/noirlab2610c_1024.jpg
📰 AI邻里 (Hacker News)
  · GPT-5.5 (344↑)
  · An update on recent Claude Code quality reports (190↑)
📖 蟋蟀在堂，岁聿其莫。——《国风·唐风·蟋蟀》
```

## 部署

```bash
# 拉代码
git clone https://github.com/qiyun-kxc/morning-paper.git
cd morning-paper

# 下载诗经数据（305篇，~200KB，两千年不更新）
curl -sL "https://raw.githubusercontent.com/chinese-poetry/chinese-poetry/master/%E8%AF%97%E7%BB%8F/shijing.json" -o shijing.json

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
- 无需任何 API key（NASA APOD 使用 DEMO_KEY，HN API 完全公开）
- 诗经数据本地存储，不依赖任何外部服务

## 后续规划

- [ ] **阿鹤那边的天气**：美西具体城市天气，双城天气对比
- [ ] **arXiv 论文动态**：cs.AI / cs.CL 每日新增论文标题（知野建议的第三层）
- [ ] **特殊日期扩充**：更多纪念日、农历节日
- [ ] **第四层「我们的时间」**：与记忆库重构联动——距离栖云建立第 N 天、欠账簿提醒、纪念日倒计时
- [ ] **小报存档**：每日归档历史小报，以后能翻「去年今天的世界长什么样」
- [ ] **节气表跨年**：当前硬编码 2026 年节气，后续改为天文算法动态计算
- [ ] **NASA APOD 正式 key**：DEMO_KEY 有限流，申请免费 key 提升稳定性
- [ ] **ZenQuotes 英文每日一言**：诗经 + 英文名言双语并列（备选方案，暂不急）

## 致谢

- 知野（GPT-5.4）推荐了 HN API / arXiv / Currents 等信息源方案
- 诗经数据来自 [chinese-poetry](https://github.com/chinese-poetry/chinese-poetry)
- 月相算法基于朔望周期计算，锚点新月 2024-01-11 11:57 UTC
- NASA APOD 由 NASA 开放平台提供
