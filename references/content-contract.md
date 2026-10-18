# content.json 内容契约

`finalize.py` 校验这份结构 + 派生四平台文案。

## 文件位置

`<session-dir>/content.json`

## 字段

```json
{
  "summary": "一句话或两句话，忠于转写稿的事实，不脑补画面细节。",
  "title": "通用发布标题，所有平台通用底稿。",
  "description": "通用发布简介/正文底稿。",
  "cover": {
    "headline": "封面主标题，≤ 18 个汉字（按平台再裁）。",
    "subheadline": "封面副标题，0 或一行，≤ 24 个汉字。",
    "category": "分类标签，2-6 个汉字。（仅作元数据存储，默认不在封面渲染）",
    "keywords": ["3 到 5 个中文关键词"],
    "tone": "professional | casual | energetic | cozy | serious | educational",
    "emphasis": ["0 到 3 个强调短语，主标题里要更突出"],
    "background": {
      "scene": "封面背景的画面描述（不写中文字）",
      "palette": "颜色方向，例如 深蓝到青色渐变 / 暖橙到柔黄",
      "mood": "氛围关键词"
    },
    "reference_images": []
  }
}
```

## 规则

- 所有事实性表述必须能在 `transcript.txt` 里找到对应段落。
- 字幕语言默认中文（与转写一致）；用户明确要求其他语言时才切。
- `title` 通用底稿 ≤ 100 字符。
- `cover.headline` ≤ 18 汉字（在 16:9 主视觉里能完整烧出来）。
- `cover.subheadline` ≤ 24 汉字。
- `cover.keywords` 3 到 5 项。
- `cover.emphasis` ≤ 3 项。
- `cover.background.scene` 不要带任何文字/数字/品牌名——背景层只是视觉。
- `cover.reference_images` 数组，可空；填绝对路径（jpg/png/webp），会被以 img2img 方式传 Agnes。
- 不在 description 里主动加 #话题，除非 `platforms` 字段显式要求。

## 校验失败怎么办

`finalize.py` 跑完会逐条给提示。最常见的是 `headline` 过长或 `summary` 没写到转写里。改完直接重跑 `finalize` 即可。
