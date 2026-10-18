# 封面工作流

## 两层结构

封面由**背景层**（Agnes 出图）+ **文字层**（PIL 烧中文字）合成。这样做是因为 Agnes 自己对中文标题会随机增删、错字、并加伪英文后缀，不稳定。把文字交给 PIL 就完全确定。

```
content.json.cover  ──┬──► Agnes /v1/images/generations  ──► 背景图（4 比例）
                     │
                     └──► PIL 烧录 headline/subheadline/category ──► 终稿（4 比例）
```

## 四比例与 Agnes size 映射

| 平台           | 比例    | Agnes size   | 推荐用途                            |
|----------------|---------|--------------|-------------------------------------|
| Bilibili 头图   | 16:9    | 1024x576     | 横版视频封面                        |
| 横版备选        | 4:3     | 1024x768     | 老式横版 / 通用备选                 |
| 小红书 3:4      | 3:4     | 768x1024     | 小红书主推 / 抖音主推 / 视频号主推   |
| 抖音/视频号 9:16 | 9:16    | 576x1024     | 抖音/视频号竖屏封面                 |

> 9:16 也可以换成 `1024x1792`（更接近真竖屏），但 Agnes 实测两种都支持，本 skill 默认 576x1024 节省出图时长；想更精细可用 `--9-16-large`。

## 提示词构造（Agnes 输入）

- 角色：平面设计 / 数字艺术 / 影视海报
- 视觉：颜色方向（`cover.background.palette`）+ 场景（`cover.background.scene`）+ 氛围（`cover.background.mood`）
- **显式禁止**：在背景 prompt 里写 "with text" / "with words" / 中文 / 任何可识别字符。背景里只放视觉元素。
- **鼓励**：cinematic lighting / minimalist / strong focal point / clean composition
- 模型：`agnes-image-2.1-flash`（高质量出图，~10 秒/张）
- 图生图：当 `cover.reference_images` 非空，模型改用 `agnes-image-2.0-flash` 并加 `tags:["img2img"], image:[data_uri]`

## 文字烧录（PIL 层）

- 字体：Windows 优先 `msyhbd.ttc`（微软雅黑 Bold）→ `simhei.ttf`（黑体）→ `msyh.ttc`（雅黑）。
- 颜色：主标题纯白 + 软阴影（offset 0,4 / radius 8 / alpha 80）；副标题 90% 白色。
- 安全区（防被平台 UI 遮挡）：
  - 16:9 / 4:3：文字集中在 8%-92% 的水平、18%-82% 的垂直范围内。
  - 3:4：标题 26%-48%，副标题 51%-64%，整体垂直居中。
  - 9:16：标题 32%-54%，副标题 57%-72%（避开抖音 1680-1920 文案条 / 视频号分享栏覆盖区）。
- **角落留空（强制）**：分类标签 / 角标 / 水印 / 署名 / 日期**一律不烧录**。
  开关为 `config.json → cover.show_category`，默认 `false`。
  四角空出来的区域留给平台 UI，画面只靠中央的主标题 + 副标题承载信息。
- 字号：根据 headline 长度自适应，但 16:9 主标题最高 64px、9:16 主标题最高 88px（按 1024 宽归一化）。

## 单比例重做

```bash
python scripts/gen_covers.py --session .video-publish/sessions/<id> --only 9:16
```

只重做 9:16 的背景 + 文字烧录；其他比例继承 v1 终稿。

## 整版重做

```bash
python scripts/gen_covers.py --session .video-publish/sessions/<id> --new-version
```

产生 v2 目录；v1 完整保留供回滚。
