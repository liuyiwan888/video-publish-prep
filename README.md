# video-publish-prep

一段文案（或视频/字幕）→ 一键生成 **4 种比例的发布封面** + **四平台可复制文案**。

封面走 **本地 PIL 渐变自绘 + 中文字烧录**，1 秒/张、零随机翻车、不依赖联网。
可选接 Agnes AI 做"取色"，但**不配 Key 也能正常出图**。

产出比例：`16:9`（B站）· `4:3`（B站/视频号）· `3:4`（小红书/抖音）· `9:16`（抖音/视频号）

---

## 30 秒上手

```bash
# 只给文案，直接出 4 张封面
python scripts/quick.py --headline "副业变现" --subheadline "从 0 到 1 的完整路径" --tone energetic
```

跑完在 `.video-publish/sessions/<时间戳>/covers/v1/` 下拿到 4 张 PNG。**不需要 API Key。**

---

## 安装

### 方式 A：装成 WorkBuddy / Codex / Claude 技能（推荐）

目录结构符合通用 Agent Skill 规范（`SKILL.md` + frontmatter），三类工具都认。

**Windows**：双击 `install.bat`
**macOS / Linux**：

```bash
bash install.sh
```

脚本会把整个目录复制到 `~/.workbuddy/skills/video-publish-prep/`，重开客户端即生效。

装好后直接对话即可：「用这段文案出 4 张封面」「给这个视频做发布物料」。

### 方式 B：手动复制

```bash
# WorkBuddy
cp -r video-publish-prep ~/.workbuddy/skills/
# Codex
cp -r video-publish-prep ~/.codex/skills/
# Claude Code
cp -r video-publish-prep ~/.claude/skills/
```

### 方式 C：不当技能用，纯命令行

脚本是独立 Python CLI，不装成技能也能直接跑，见下方「用法」。

---

## 环境要求

| 依赖 | 是否必需 | 说明 |
|---|---|---|
| Python 3.9+ | ✅ 必需 | 脚本用标准库 + Pillow |
| Pillow | ✅ 必需 | `pip install Pillow` |
| ffmpeg / ffprobe | 仅完整模式 | 只有处理**视频文件**时才需要；纯文案出封面不用 |
| Agnes API Key | ❌ 可选 | 仅 `--ai-color` 取色时用到 |

首次运行会自动从 `config.example.json` 生成 `config.json`。

### 配置 Key（可选）

要用 AI 取色时二选一：

```bash
# 方式1：环境变量（推荐，不落盘）
export AGNES_API_KEY="sk-xxxx"          # macOS/Linux
setx AGNES_API_KEY "sk-xxxx"            # Windows CMD

# 方式2：写进 config.json 的 api_key 字段
```

Key 获取：<https://www.agnes-ai.com/> → 控制台 → API Keys

---

## 用法

### 快速模式：给文案就出封面

```bash
python scripts/quick.py \
  --headline "副业变现" \
  --subheadline "从 0 到 1 的完整路径" \
  --tone energetic \
  --title "普通人副业变现的 5 条真实路径" \
  --desc "正文文案……" \
  --topics "副业,搞钱,自媒体" \
  --finalize \
  --out "D:/your/project"
```

| 参数 | 说明 | 必填 |
|---|---|---|
| `--headline` | 封面主标题（大字） | 与 `--title` 至少一个 |
| `--subheadline` | 封面副标题 | 否 |
| `--tone` | 配色风格，见下表（默认 `tech`） | 否 |
| `--title` | 发布标题 | 否（用 headline 兜底） |
| `--desc` / `--desc-file` | 正文文案或文件路径 | `--finalize` 时必备 |
| `--topics` | 话题，逗号分隔 | 否 |
| `--ratios` | 要出的比例，默认全 4 个，如 `--ratios 9:16` | 否 |
| `--finalize` | 顺便出四平台发布清单 `publish-kit.md` | 否 |
| `--ai-color` | 用 AI 出色卡提主色（需要 Key） | 否 |
| `--font` | 指定中文字体路径 | 否 |
| `--out` | 输出根目录 | 否（默认当前目录） |

### 完整模式：有视频/字幕时

```bash
# 1. 抽转写 + 关键帧
python scripts/prepare.py --input "video.mp4"     # 或 subtitle.srt
# 2. 按 references/content-contract.md 写 content.json
# 3. 出封面
python scripts/gen_covers.py --session ".video-publish/sessions/<id>"
# 4. 出四平台发布清单
python scripts/finalize.py --session ".video-publish/sessions/<id>"
```

### 8 种配色风格（tone）

| tone | 配色 | 适合 |
|---|---|---|
| `tech`（默认） | 浅灰蓝 → 蓝 → 深蓝 + 青 | AI、效率、编程 |
| `energetic` | 奶白 → 珊瑚 → 深红 | 干货、副业、励志 |
| `warm` | 奶白 → 玫瑰金 → 酒红 | 生活、情感 |
| `professional` | 浅蓝 → 海军蓝 + 暖金 | 商业、咨询、报告 |
| `calm` | 雾白 → 浅蓝 + 草绿 | 心理、冥想、健康 |
| `natural` | 奶白 → 草绿 + 麦金 | 户外、农产品 |
| `luxury` | 金 → 酒红 + 哑光金 | 高端、品牌、设计 |
| `dark` | 灰 → 深炭 + 暖红 | 电影、悬疑、夜间话题 |

---

## 版面规则

封面**只保留画面中央的主标题 + 副标题**，左下/右下/四角不加分类标签、水印、角标、日期、署名等任何附加文字。

由 `config.json → cover.show_category = false` 控制。确需破例时改成 `true`，或运行加 `--show-category`。

---

## 常见问题

**Q：中文字显示成方块？**
系统缺中文字体。任选其一：

```bash
# 指定字体
python scripts/quick.py --headline "标题" --font "C:/Windows/Fonts/msyhbd.ttc"
# 或设环境变量
export VPP_FONT_PATH="/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
```

Linux 安装字体：`sudo apt install fonts-wqy-zenhei`；macOS 自带 PingFang，一般无需处理。

**Q：提示缺 ffmpeg？**
只有处理视频文件才需要。Windows 用 `winget install ffmpeg`，macOS `brew install ffmpeg`，Linux `sudo apt install ffmpeg`。只做文案封面可忽略。

**Q：没配 Key 能出图吗？**
能。默认纯本地 PIL 生成，不联网。Key 只在 `--ai-color` 时用。

**Q：封面版本怎么管理？**
`covers/v1/`、`v2/`… 各自完整封存不覆盖。重做单个比例：`gen_covers.py --session <dir> --only 9:16`；整体重出：`--new-version`。

---

## 目录结构

```
video-publish-prep/
├── SKILL.md                  # 技能入口（Agent 读这个）
├── README.md                 # 本文件
├── config.example.json       # 配置模板（无密钥，可分享）
├── install.bat / install.sh  # 一键安装
├── references/
│   ├── content-contract.md   # content.json 字段与校验
│   ├── cover-workflow.md     # 封面分层 + 安全区 + 比例规范
│   └── platforms.md          # 四平台字段与人工发布清单规则
└── scripts/
    ├── quick.py              # 文案 → 封面，一条命令入口
    ├── prepare.py            # 视频/字幕 → 会话 + 转写 + 关键帧
    ├── gen_covers.py         # 渐变背景 + PIL 烧中文（4 比例）
    └── finalize.py           # 校验 + 四平台文案 + publish-kit.md
```

## 关于发布

本工具**只负责发布前的物料准备**，不会自动登录、不会绕过验证码、不会替你点发布按钮。
`publish-kit.md` 里四平台文案都是现成代码块，复制粘贴即可。

## 许可

上游思路参考 [sunshineLixun/video-publish-skill](https://github.com/sunshineLixun/video-publish-skill)（MIT）。
本版本为 WorkBuddy 适配改写版，可自由使用与修改。
