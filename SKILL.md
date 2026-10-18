---
name: video-publish-prep
description: "两条入口，按用户给的素材自动选：①【快速模式】用户只给一段文案/标题时，提炼主标题+副标题+tone，一条命令出 4 比例封面（16:9/4:3/3:4/9:16），可选连四平台（小红书/抖音/Bilibili/微信视频号）发布文案一起出，秒级完成，无需视频；②【完整模式】用户给视频/字幕文件时，抽转写→写 content.json→出封面→出 publish-kit.md 发布清单。封面=Agnes 取色+PIL 自绘杂志感渐变+PIL 烧中文字（1-2秒/张，零翻车）。铁律：封面只保留中央主标题+副标题，四角（左下/右下）一律不加分类标签/角标/水印等任何附加文字（config show_category=false 默认关闭）。最终发布按钮永远人工。触发词：生成封面、出封面、视频封面、发布素材、发布物料、四平台文案。"
---

# video-publish-prep

从一段视频或字幕，自动产出可发布到**小红书 / 抖音 / Bilibili / 微信视频号**的成稿物料。**最终发布按钮始终由人工点击**——本 skill 只负责把发布前的体力活干完。

## 适配自

上游参考：[sunshineLixun/video-publish-skill](https://github.com/sunshineLixun/video-publish-skill)。原版只跑在 Codex、依赖 Codex ImageGen 和 Ego Lite。本版本做了三处 WorkBuddy 适配：

1. **封面生成换为 Agnes AI**（`apihub.agnes-ai.com/v1`，OpenAI 兼容），用户已提供 API Key 落在 `config.json`。
2. **中文字独立烧录**：用 Agnes 出干净背景，再用 PIL 烧中文标题/副标题（消除 AI 模型对中文的随机增删）。
3. **跨平台文案与发布清单**自动出 `.md`，人工粘贴到各平台草稿框。

> ## 版面铁律（用户明确要求，务必遵守）
>
> 封面**只保留画面中央的主标题 + 副标题**。
> **左下角 / 右下角 / 任何角落一律不加**分类标签、角标、水印、页码、署名、日期等附加文字。
> 由 `config.json → cover.show_category = false` 控制（默认关闭）。
> 未经用户明确许可，**不要**把该开关打开，也不要用其它方式往角落加字。

> ## 发布前预检（强制，先审后写）
>
> 封面主标题 / 副标题、以及 `content.json` 里的标题与简介**属于要发布的内容**：
> 在写进 `content.json` 之前，先过 `yuwen-publish-precheck`（用 `Skill` 加载；
> 主流程：内容身份 → `scripts/scan.py` 词面预检 → 逐条判定 → 保意修复 → 报告）。
> 有「必改」先改、复检通过再出封面。（用户 2026-09-14 拍板：所有要发布的内容先审后发。）

## 工作流（按顺序）

1. **抽取转写**：`scripts/prepare.py` —— 输入视频（mp4/mov/mkv/webm）或字幕（srt/vtt）→ 产出 `.video-publish/sessions/<id>/{session.json, transcript.txt, frames/}`。视频内嵌字幕用 ffmpeg 抽；无字幕则需要 faster-whisper（可选）。
2. **写 `content.json`**：参考 [references/content-contract.md](references/content-contract.md)，把摘要/标题/简介/封面文案写齐。
3. **生成封面**：`scripts/gen_covers.py` —— Agnes 出 4 比例背景 + PIL 烧中文。支持 `--only 9:16` 单比例重做。输出在 `covers/v1/`。
4. **生成发布物料**：`scripts/finalize.py` —— 校验 `content.json`、自动产出四平台文案变体与 `publish-kit.md`（人工发布清单，含可复制代码块）。
5. **人工确认 + 人工发布**：把 `publish-kit.md` 里的文案复制到四个平台草稿框，封面图上传到对应字段，按平台规改标签/话题，**人按发布按钮**。

## 触发条件

用户发来视频或字幕文件 + 任一以下措辞，即触发：

- "准备发布到抖音/小红书/B站/视频号"
- "做四平台发布物料"
- "出 4 个比例封面 + 发布文案"
- "$video-publish-prep" / "$prepare-video-publish"

## 输入约定

两类必传：

1. **素材**：视频或字幕文件的**绝对路径**（mp4 / mov / mkv / webm / srt / vtt）。
2. **基础信息**（如已具备可放对话里）：核心受众、平台、是否原创、是否要话题标签等。

没有可补问一项：缺素材就让用户发文件；缺主题就一句主题即可。不要为风格、字体、配色、模板再发问（自主决策）。

## 关键设计原则

- **不绕过登录/验证码/风控，不自动点发布**。和原版一致。
- **不静默装系统软件**：ffmpeg 已在本机，缺 faster-whisper 时提示用户手动装。
- **本地数据本地化**：会话默认 `项目根/.video-publish/`，不进任何云端。
- **API Key 落在 `config.json`**（用户级 skill 目录，不入版本控制）；env `AGNES_API_KEY` 可覆盖。
- **封面版本不可变**：`covers/v1/`、`covers/v2/` 各自完整封存；单比例重做只覆盖当前版本对应的那张，其它比例继承上一版本。
- **封面必须用唯一名上传（血泪教训）**：`covers/v<n>/` 会同时产出 `cover-<ratio>.png`（本地阅读）和 `cover-<ratio>-<slug>-<sessionId>-v<n>.png`（**唯一名，上传专用**；sessionId 形如 `20260918-170108-675700`，**自带 8 位日期**）。**上传到蚁小二等"按文件名生成存储 key"的渠道时，一律用带 slug+sessionId 的那份**。原因：蚁小二对**图片**素材的 key = `yfb/<team>/<原文件名>`（**保留原文件名、不做哈希**，已实测两次上传同名文件返回同一 key），固定名 `cover-9x16.png` 会让不同视频的封面共用同一 key、**后传覆盖先传**，发布后作品封面张冠李戴（表现为"封面不是这个视频的封面"，且**每发一篇就复现一次**）。
  - **2026-09-18 命名规则**：成片与封面文件名都必须带「项目 slug + 8 位日期」。compose.sh 默认产出 `<slug>-<YYYYMMDD>-成片.mp4`，gen_covers.py 默认产出 `cover-<ratio>-<slug>-<sessionId>-v<n>.png`，两者自动满足，**别手动改名去掉日期/slug**。
  - 对照（2026-09-16 实测纠正）：**视频**素材 yxer **同样保留原文件名**（key = `yfb/t-<team>/<原文件名>.mp4`），**并不会**重命名成 `file_<hash>.mp4`。所以视频也要保证文件名按工程唯一且带日期（`<slug>-<YYYYMMDD>-成片.mp4` 天然满足）；**切勿**把两条不同视频都命名成 `final.mp4` / `成片.mp4`，否则会像封面一样互相覆盖。
  - 发之前必须跑一次校验，退出码非 0 就不要发：
    ```bash
    python scripts/check_publish_assets.py --dir <工程目录>
    # 或指定文件：python scripts/check_publish_assets.py a.json b.json
    ```
    它强制「一个 video key ↔ 一个 cover key」，并拦截裸名封面（`cover-9x16.png` 这种）。

## 平台文案规则（自动派生）

详见 [references/platforms.md](references/platforms.md)。脚本会按各平台字数/字段约束自动从 `content.json` 派生并产出可复制代码块。

| 平台 | 标题上限 | 简介上限 | 封面比例（推荐） | 必填话题/标签 |
|---|---|---|---|---|
| 小红书 | 20 字 | 1000 字 | 3:4 | 话题实体 |
| 抖音 | 30 字 | 1000 字 | 3:4（可加 4:3） | 话题实体 |
| Bilibili | 80 字 | 2000 字 | 4:3 | 标签（≤10） |
| 微信视频号 | 14 字（短） | 1000 字 | 3:4（可加 4:3） | 话题 |

## 文件结构

```
~/.workbuddy/skills/video-publish-prep/
├── SKILL.md                  # 本文件（Agent 读这个）
├── README.md                 # 给收件人看的安装/使用说明
├── config.example.json       # 脱敏配置模板（首次运行自动复制为 config.json）
├── install.bat / install.sh  # 一键安装到 ~/.workbuddy/skills/
├── .gitignore                # 阻止 config.json 误传
├── references/
│   ├── content-contract.md   # content.json 字段与校验
│   ├── cover-workflow.md     # 封面分层 + 安全区 + 比例规范
│   └── platforms.md          # 四平台字段与人工发布清单规则
└── scripts/
    ├── quick.py              # 文案 -> 封面 的一条命令入口
    ├── prepare.py            # 视频/字幕 -> 会话 + 转写 + 关键帧
    ├── gen_covers.py         # 渐变背景 + PIL 烧中文（4 比例）
    ├── finalize.py           # 校验 content.json + 四平台文案 + publish-kit.md
    └── package.py            # 打可分发包（自动脱敏密钥、生成 zip）
```

## 已知限制

- 中文标题烧录依赖系统中文字体（Win: 微软雅黑 / macOS: PingFang / Linux: 文泉驿）。Linux 缺字体时可 `export VPP_FONT_PATH=...` 或传 `--font` 指定。
- 视频无字幕时不会自动调 whisper（避免静默装包），只生成待办提示。
- 4 比例封面 1.0-1.2 秒/张（纯 PIL 像素运算，杂志感渐变 + accent blob，**无 AI 翻车概率**）。
- 不做 Ego Lite 那一步的"自动暂存到平台草稿框"（那是 Codex 专属）。
- 暂不支持抖音原创声明的可验证门（与原版一致，待平台适配）。

## 分发给别人用

打 zip（自动脱敏密钥、排除缓存/会话产物）：

```bash
python scripts/package.py --out D:/share
# 产出：D:/share/video-publish-prep.zip（~36 KB）
```

收件人三步：解压 → 双击 `install.bat`（Win）/ `bash install.sh`（Mac/Linux）→ 重启客户端。**默认零配置可出图**；要用 AI 取色才需要 Agnes Key。

## 快速开始

两条路，按需选：

### A. 快速模式（只给文案就出封面，无需视频/字幕）

适合：用户只有标题/正文、要快速出 4 比例封面分发。**一条命令**完成"建会话 + 写 content.json + 出封面（可选 publish-kit.md）"。

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

参数速记（完整列表见 `python quick.py --help`）：

| 参数 | 说明 | 必填 |
|---|---|---|
| `--headline` | 封面主标题（大字） | 与 `--title` 至少一个 |
| `--subheadline` | 封面副标题 | 否 |
| `--category` | 分类标签（**默认不渲染**，config 关闭；仅作元数据存 content.json） | 否 |
| `--tone` | 配色风格：`tech`（默认）/ `energetic` / `warm` / `professional` / `calm` / `natural` / `luxury` / `dark` / `wine`（酒红×墨黑，红黑交替） | 否 |
| `--title` | 发布标题 | 否（用 headline 兜底） |
| `--desc` / `--desc-file` | 正文文案或文件路径 | `--finalize` 时必备 |
| `--topics` | 话题，逗号分隔 | 否 |
| `--ratios` | 要出的比例（默认全 4 个） | 否 |
| `--finalize` | 顺便出 `publish-kit.md` | 否 |
| `--out` | 输出根目录 | 否（默认当前目录） |

### B. 完整流程（有视频/字幕时用）

```bash
# 1. 准备会话
python scripts/prepare.py --input "D:/path/to/video.mp4"
# 或用字幕
python scripts/prepare.py --input "D:/path/to/subtitle.srt"

# 2. 在 .video-publish/sessions/<id>/ 写 content.json（参考 references/content-contract.md）

# 3. 生成封面（必须先有 content.json）
python scripts/gen_covers.py --session ".video-publish/sessions/<id>"

# 4. 生成发布物料
python scripts/finalize.py --session ".video-publish/sessions/<id>"
```

之后 `present_files` 把封面图与 `publish-kit.md` 一起交回给用户。
