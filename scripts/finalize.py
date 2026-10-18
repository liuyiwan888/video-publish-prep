"""
video-publish-prep / finalize.py
把 content.json 校验 + 派生成四平台文案 + 输出 publish-kit.md
不调用 LLM（确定性派生），用户可在 publish-kit.md 基础上人工微调。

输出：
  <session>/publish-kit.md         人工发布清单（含可复制代码块）
  <session>/content.validated.json 校验通过后的 content.json（带派生字段）
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

# 平台规则
PLATFORM_RULES = {
    "rednote": {  # 小红书
        "title_max": 20,
        "body_max": 1000,
        "primary_cover": "3x4",
        "short_title_required": False,
        "topic_style": "entity",   # 真实话题实体（搜索后点选）
    },
    "douyin": {   # 抖音
        "title_max": 55,
        "body_max": 1000,
        "primary_cover": "3x4",
        "extra_cover": "4x3",
        "short_title_required": False,
        "topic_style": "entity",
    },
    "bilibili": {  # B 站
        "title_max": 80,
        "body_max": 2000,
        "primary_cover": "4x3",
        "short_title_required": False,
        "topic_style": "tag",
    },
    "wechat_channels": {  # 视频号
        "title_max": 1000,  # 描述
        "short_title_max": 14,
        "body_max": 1000,
        "primary_cover": "3x4",
        "extra_cover": "4x3",
        "short_title_required": True,
        "topic_style": "hashtag",
    },
}

PLATFORM_LABEL = {
    "rednote": "小红书",
    "douyin": "抖音",
    "bilibili": "Bilibili",
    "wechat_channels": "微信视频号",
}


def validate(content: dict) -> list[str]:
    """返回错误列表。空列表 = 通过。"""
    errs = []
    summary = content.get("summary", "")
    if not summary or len(summary) < 10:
        errs.append("summary 缺失或太短（≥ 10 字）")
    if not content.get("title"):
        errs.append("title 缺失")
    elif len(content["title"]) > 100:
        errs.append(f"title 超 100 字（{len(content['title'])}）")
    if not content.get("description"):
        errs.append("description 缺失")
    cover = content.get("cover", {})
    if not cover.get("headline"):
        errs.append("cover.headline 缺失")
    else:
        h = cover["headline"]
        if len(h) > 18:
            errs.append(f"cover.headline {len(h)} 字（≤ 18 汉字更稳）")
    if cover.get("subheadline") and len(cover["subheadline"]) > 24:
        errs.append(f"cover.subheadline {len(cover['subheadline'])} 字（≤ 24）")
    kws = cover.get("keywords", [])
    if not (3 <= len(kws) <= 5):
        errs.append(f"cover.keywords {len(kws)} 个（需 3-5）")
    emp = cover.get("emphasis", [])
    if len(emp) > 3:
        errs.append(f"cover.emphasis {len(emp)} 个（≤ 3）")
    return errs


def trim_to(s: str, n: int, suffix: str = "…") -> str:
    s = s.strip()
    if len(s) <= n:
        return s
    return s[: n - 1] + suffix


def platform_copy(content: dict, pid: str) -> dict:
    rule = PLATFORM_RULES[pid]
    title_full = content["title"].strip()
    desc = content["description"].strip()
    summary = content["summary"].strip()
    kws = content.get("cover", {}).get("keywords", [])

    if pid == "rednote":
        # 标题：截到 20 字 + 情绪 emoji
        emo = ["✨", "🔥", "💡", "📌", "🚀", "🪄"]
        plat_title = trim_to(title_full, 18) + " " + emo[hash(title_full) % len(emo)]
        if len(plat_title) > rule["title_max"]:
            plat_title = plat_title[: rule["title_max"]]
        # 正文：description + 引导段
        guide = "\n\n📌 收藏夹点这 / 💬 评论区聊聊你的情况"
        plat_body = trim_to(desc, rule["body_max"] - len(guide)) + guide
        topics = kws[:5]  # 真实话题
        short_title = None
    elif pid == "douyin":
        # 抖音标题：前半句钩子 + 分隔 + 后半句
        hook = trim_to(summary, 18)
        tail = trim_to(title_full, rule["title_max"] - len(hook) - 3)
        plat_title = f"{hook} | {tail}"
        if len(plat_title) > rule["title_max"]:
            plat_title = plat_title[: rule["title_max"]]
        plat_body = trim_to(desc, rule["body_max"] - 25) + "\n\n评论区告诉我你的情况 👇"
        topics = kws[:5]
        short_title = None
    elif pid == "bilibili":
        # B 站：title + 描述，描述末尾加关注引导
        plat_title = trim_to(title_full, rule["title_max"])
        plat_body = trim_to(desc, rule["body_max"] - 30) + "\n\n觉得有用点个关注，更多 AI 实战下期见～"
        topics = kws[:10]
        short_title = None
    else:  # wechat_channels
        # 视频号：短标题独立 + 描述带 # 话题
        short_title = trim_to(content["cover"].get("headline", title_full), rule["short_title_max"])
        tags_line = " " + " ".join(f"#{kw}" for kw in kws[:5])
        plat_title = trim_to(desc, rule["body_max"] - len(tags_line) - 5) + tags_line
        plat_body = None
        topics = kws[:5]

    return {
        "title": plat_title,
        "body": plat_body,
        "short_title": short_title,
        "topics": topics,
        "primary_cover_ratio": rule["primary_cover"],
        "extra_cover_ratio": rule.get("extra_cover"),
    }


def cover_path(version: str, ratio: str) -> str:
    return f"covers/{version}/cover-{ratio}.png"


def render_publish_kit(content: dict, session: dict, pc: dict) -> str:
    sid = session["id"]
    video = session.get("video") or "（未提供视频）"
    # 默认最新版本
    covers_root = Path(session.get("_session_dir", ".")) / "covers"
    v = "v1"
    if covers_root.exists():
        vs = sorted([p.name for p in covers_root.iterdir() if p.is_dir() and p.name.startswith("v")])
        if vs:
            v = vs[-1]
    version = v

    lines = []
    lines.append(f"# 发布清单 — {content['title']}")
    lines.append("")
    lines.append(f"> 生成时间：{datetime.now().isoformat(timespec='seconds')}  |  会话：{sid}")
    lines.append("")
    lines.append("## 全局素材")
    lines.append(f"- 视频：`{video}`")
    lines.append(f"- 通用封面（4 比例，最新版本 **{version}**）：")
    for r in ("16x9", "4x3", "3x4", "9x16"):
        lines.append(f"  - `{cover_path(version, r)}`")
    lines.append(f"- 转写稿：`transcript.txt`（{session.get('transcript_chars', 0)} 字）")
    lines.append("")

    platform_order = ["rednote", "douyin", "bilibili", "wechat_channels"]
    for pid in platform_order:
        label = PLATFORM_LABEL[pid]
        p = pc[pid]
        lines.append(f"---")
        lines.append(f"## {label}")
        lines.append("")
        if p["short_title"] is not None:
            lines.append(f"### 短标题（独立字段，{PLATFORM_RULES[pid]['short_title_max']} 字以内）")
            lines.append("```text")
            lines.append(p["short_title"])
            lines.append("```")
            lines.append("")
            lines.append(f"### 描述（带 # 话题）")
            lines.append("```text")
            lines.append(p["title"])
            lines.append("```")
        else:
            lines.append(f"### 标题（{PLATFORM_RULES[pid]['title_max']} 字以内）")
            lines.append("```text")
            lines.append(p["title"])
            lines.append("```")
            if p["body"]:
                lines.append("")
                lines.append(f"### 正文（{PLATFORM_RULES[pid]['body_max']} 字以内）")
                lines.append("```text")
                lines.append(p["body"])
                lines.append("```")
        if p["topics"]:
            topic_kind = PLATFORM_RULES[pid]["topic_style"]
            if topic_kind == "entity":
                lines.append("")
                lines.append("### 话题（**搜索后点选**，不要手打 # 标签）")
            elif topic_kind == "hashtag":
                lines.append("")
                lines.append("### 话题（**用 # 真实话题**）")
            else:  # tag
                lines.append("")
                lines.append("### 标签（系统推荐里点选最相关的 5-8 个）")
            for t in p["topics"]:
                lines.append(f"- {t}")
        lines.append("")
        lines.append(f"### 封面图")
        primary = cover_path(version, p["primary_cover_ratio"])
        lines.append(f"- 必传：`{primary}`")
        if p["extra_cover_ratio"]:
            lines.append(f"- 备选：`{cover_path(version, p['extra_cover_ratio'])}`")
        lines.append("")

    lines.append("---")
    lines.append("## 人工发布清单")
    lines.append("- [ ] 视频上传完成")
    lines.append("- [ ] 标题 / 短标题 填好")
    lines.append("- [ ] 正文 / 描述 填好")
    lines.append("- [ ] 话题点选（小红书 / 抖音）/ # 标签填好（B 站 / 视频号）")
    lines.append("- [ ] 封面图上传")
    lines.append("- [ ] 原创声明按本视频实际情况勾选")
    lines.append("- [ ] 预览没问题，按发布")
    lines.append("")
    lines.append("> 本清单由 video-publish-prep 自动生成。最终发布按钮由你点。")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="video-publish-prep / finalize")
    ap.add_argument("--session", required=True, help="会话目录")
    args = ap.parse_args()

    session_dir = Path(args.session).expanduser().resolve()
    cj = session_dir / "content.json"
    sj = session_dir / "session.json"
    if not cj.exists():
        print(f"ERROR: 找不到 {cj}", file=sys.stderr); sys.exit(2)
    if not sj.exists():
        print(f"ERROR: 找不到 {sj}", file=sys.stderr); sys.exit(2)

    content = json.loads(cj.read_text(encoding="utf-8"))
    session = json.loads(sj.read_text(encoding="utf-8"))
    session["_session_dir"] = str(session_dir)

    errs = validate(content)
    if errs:
        print("[finalize] 校验失败：", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        print("\n修完 content.json 再跑一次。", file=sys.stderr)
        sys.exit(1)
    print("[finalize] 校验通过 ✓")

    # 派生存稿
    pc = {pid: platform_copy(content, pid) for pid in PLATFORM_RULES}
    # 校验平台字数
    for pid, p in pc.items():
        rule = PLATFORM_RULES[pid]
        if len(p["title"]) > rule["title_max"]:
            print(f"  WARN: {pid}.title 超 {rule['title_max']} 字（{len(p['title'])}）", file=sys.stderr)
        if p["body"] and len(p["body"]) > rule["body_max"]:
            print(f"  WARN: {pid}.body 超 {rule['body_max']} 字（{len(p['body'])}）", file=sys.stderr)

    # 落盘 content.validated.json
    out_content = dict(content)
    out_content["_platforms"] = pc
    (session_dir / "content.validated.json").write_text(
        json.dumps(out_content, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    # 落盘 publish-kit.md
    md = render_publish_kit(content, session, pc)
    md_path = session_dir / "publish-kit.md"
    md_path.write_text(md, encoding="utf-8")
    print(f"[finalize] 写入 {md_path}")
    print(f"          写入 {session_dir / 'content.validated.json'}")

    print("\n=== 下一步 ===")
    print("1. 用 present_files 把 publish-kit.md 和 4 张封面图交给用户")
    print("2. 用户按平台清单复制粘贴 + 人工按发布按钮")


if __name__ == "__main__":
    main()
