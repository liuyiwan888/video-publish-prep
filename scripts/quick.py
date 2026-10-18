"""
video-publish-prep / quick.py
「给文案 → 出封面」一条命令入口。不需要视频、不需要字幕、不需要手写 content.json。

典型场景：用户只有一段文案/标题，想直接要 4 张封面（可附带发布清单）。

用法：
  # 最小：只要封面（默认 tech 风格，4 比例）
  python quick.py --headline "ChatGPT 输出翻倍" --subheadline "3 个提示词技巧"

  # 完整：带分类 + 风格 + 发布标题/正文 + 话题，并顺便出 publish-kit.md
  python quick.py \
    --headline "副业变现" \
    --subheadline "从 0 到 1 的完整路径" \
    --category "搞钱思路" \
    --tone energetic \
    --title "普通人副业变现的 5 条真实路径" \
    --desc "正文文案……" \
    --topics "副业,搞钱,自媒体" \
    --finalize \
    --out "D:/workbuddy/github/my-covers"

  # 只要某几个比例
  python quick.py --headline "标题" --ratios 9:16,3:4

  # 从文件读正文（避免命令行转义地狱）
  python quick.py --headline "标题" --desc-file ./desc.txt

tone 可选（决定配色，不填默认 tech）：
  tech  深蓝+青      energetic 珊瑚+深红    warm   玫瑰金+酒红
  professional 海军蓝+暖金  calm  雾白+草绿   natural 草绿+麦金
  luxury 酒红+哑光金   dark  深炭+暖红   wine 酒红×墨黑（红黑交替）

输出：
  <out>/.video-publish/sessions/<id>/covers/v1/cover-<ratio>.png
  <out>/.video-publish/sessions/<id>/publish-kit.md   （--finalize 时）

最后一行会打印 SESSION_DIR=... 方便上层 agent 直接拿路径。
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TONES = ["tech", "energetic", "warm", "professional",
         "calm", "natural", "luxury", "dark", "wine"]
ALL_RATIOS = ["16:9", "4:3", "3:4", "9:16"]


def die(msg, code=1):
    print(f"[quick] ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def short_id():
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    h = str(int(time.time_ns()))[-6:]
    return f"{ts}-{h}"


def build_content(args) -> dict:
    headline = (args.headline or "").strip()
    title = (args.title or "").strip()
    if not headline and not title:
        die("至少要给 --headline（封面主标题）或 --title（发布标题）。")

    # 封面主标题：没单独给就用发布标题
    if not headline:
        headline = title
    # 发布标题：没单独给就用封面主标题
    if not title:
        title = headline

    desc = (args.desc or "").strip()
    if args.desc_file:
        p = Path(args.desc_file).expanduser().resolve()
        if not p.exists():
            die(f"--desc-file 不存在：{p}")
        file_desc = p.read_text(encoding="utf-8").strip()
        desc = (desc + "\n\n" + file_desc).strip() if desc else file_desc
    # 兜底：不给正文时，用发布标题当正文，保证 finalize 能通过校验
    if not desc:
        desc = (args.title or args.headline or "").strip()

    topics = [t.strip() for t in (args.topics or "").split(",") if t.strip()]
    if args.topic:
        topics.extend(t.strip() for t in args.topic if t.strip())
    # 去重保序
    seen, topics_uq = set(), []
    for t in topics:
        if t not in seen:
            seen.add(t)
            topics_uq.append(t)

    sub = (args.subheadline or "").strip()
    cat = (args.category or "").strip()

    # summary：优先用户给，否则从 desc 取首段，再兜底用 title
    summary = (args.summary or "").strip()
    if not summary:
        first_para = desc.split("\n")[0].strip() if desc else ""
        summary = first_para or title

    return {
        "summary": summary,
        "title": title,
        "description": desc,
        "cover": {
            "headline": headline,
            "subheadline": sub,
            "category": cat,
            "keywords": topics_uq,
            "tone": args.tone,
            "emphasis": [e.strip() for e in (args.emphasis or "").split(",") if e.strip()],
            "background": {"tone": args.tone},
            "reference_images": [],
        },
    }


def main():
    ap = argparse.ArgumentParser(
        description="video-publish-prep / quick：从文案直接出封面",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--headline", help="封面主标题（大字，必填其一）")
    ap.add_argument("--subheadline", default="", help="封面副标题（较小字，可空）")
    ap.add_argument("--category", default="",
                    help="分类标签。默认不在封面渲染（config.json → cover.show_category=false）")
    ap.add_argument("--tone", default="tech", choices=TONES, help="配色风格，默认 tech")
    ap.add_argument("--title", help="发布标题（不给则用 headline）")
    ap.add_argument("--desc", help="正文/简介文案")
    ap.add_argument("--desc-file", help="从文件读正文（推荐长文案用）")
    ap.add_argument("--summary", help="摘要（不给则自动取正文首段或标题）")
    ap.add_argument("--topics", help="话题，逗号分隔：副业,搞钱,自媒体")
    ap.add_argument("--topic", action="append", help="单个话题，可重复传")
    ap.add_argument("--emphasis", default="", help="希望强调的词，逗号分隔（当前仅记录）")
    ap.add_argument("--out", default=".", help="输出根目录，默认当前目录")
    ap.add_argument("--ratios", default=",".join(ALL_RATIOS),
                    help=f"要出的比例，逗号分隔。默认 {','.join(ALL_RATIOS)}")
    ap.add_argument("--finalize", action="store_true",
                    help="顺便生成 publish-kit.md（四平台文案与清单）")
    ap.add_argument("--ai-color", action="store_true",
                    help="用 AI 出色卡提主色（需 Agnes API Key，默认关闭）")
    ap.add_argument("--no-ai-color", action="store_true",
                    help="跳过 AI 取色，纯用 tone 预设色板（更快更稳，默认本就如此）")
    ap.add_argument("--font", help="指定中文字体文件路径（.ttf/.ttc），覆盖自动探测")
    args = ap.parse_args()

    ratios = [r.strip() for r in args.ratios.split(",") if r.strip()]
    for r in ratios:
        if r not in ALL_RATIOS:
            die(f"不支持的比例：{r}（可选 {ALL_RATIOS}）")

    out_root = Path(args.out).expanduser().resolve()
    sessions = out_root / ".video-publish" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    sid = short_id()
    sdir = sessions / sid
    (sdir / "frames").mkdir(parents=True)
    (sdir / "covers").mkdir()
    print(f"[quick] session = {sdir}")

    content = build_content(args)
    (sdir / "content.json").write_text(
        json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    # transcript 留空（纯文案模式没有视频），但保留文件让 finalize 不报错
    (sdir / "transcript.txt").write_text(content.get("description", ""), encoding="utf-8")
    (sdir / "session.json").write_text(json.dumps({
        "id": sid,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "kind": "text",
        "input": None,
        "video": None,
        "note": "由 quick.py 从文案直接创建（无视频/字幕输入）",
        "transcript_chars": len(content.get("description", "")),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[quick] content.json 已写入（tone={args.tone}, 主标题=「{content['cover']['headline']}」）")

    # 出封面
    py = sys.executable
    gc = SCRIPT_DIR / "gen_covers.py"
    for r in ratios:
        cmd = [py, str(gc), "--session", str(sdir), "--only", r]
        if args.ai_color:
            cmd.append("--ai-color")
        elif args.no_ai_color:
            cmd.append("--no-ai-color")
        if args.font:
            cmd += ["--font", args.font]
        res = subprocess.run(cmd, capture_output=True, text=True)
        out = (res.stdout or "") + (res.stderr or "")
        for line in out.strip().splitlines():
            if line.strip():
                print(f"  {line.strip()}")

    # 发布清单
    if args.finalize:
        fz = SCRIPT_DIR / "finalize.py"
        res = subprocess.run([py, str(fz), "--session", str(sdir)],
                             capture_output=True, text=True)
        out = (res.stdout or "") + (res.stderr or "")
        for line in out.strip().splitlines():
            if line.strip():
                print(f"  {line.strip()}")

    print(f"\n[quick] 完成 → {sdir / 'covers' / 'v1'}")
    print(f"SESSION_DIR={sdir}")


if __name__ == "__main__":
    main()
