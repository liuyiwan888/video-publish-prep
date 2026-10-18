#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_publish_assets.py —— 发布前校验 payload 的「视频 key ↔ 封面 key」对应关系。

背景（血泪教训）：
  蚁小二对**图片**素材的存储 key = `yfb/<team>/<原文件名>`（保留原文件名，不做哈希）。
  封面若统一叫 `cover-9x16.png`，则**所有视频的封面共用同一个 key**，
  后上传的会覆盖先上传的 → 已发布作品的封面张冠李戴（封面不是这个视频的封面），
  且**每发一篇就复现一次**。

  核心不变量：**不同视频的 key 绝不能共用同一个封面 key。**

用法：
  python check_publish_assets.py payload_a.json payload_b.json ...
  python check_publish_assets.py --dir D:/path/to/project
  python check_publish_assets.py --dir D:/path/to/project --json

规则：
  [FAIL] 封面 key 的文件名是裸名 cover-<ratio>.png（不含 session 标识）——必然与其他视频冲突
  [FAIL] 成片 key 文件名不带「slug + 8 位日期」（应为 <slug>-<YYYYMMDD>-成片.mp4）
  [FAIL] 封面 key 文件名不带「slug + 8 位日期」（应为 cover-<ratio>-<slug>-<YYYYMMDD>-...png）
  [FAIL] 两个不同的 video.key 使用了同一个 coverKey
  [FAIL] 同一 payload 内 cover.key 与 coverKey 不一致
  [WARN] coverKey 文件名里找不到 session/版本形态的标识，同日同名重跑时无法确认唯一性

退出码：存在 FAIL → 1；只有 WARN 或全通过 → 0
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# 裸封面名：cover-9x16.png / cover-3:4.png / cover-3x4.png ...
RE_BARE_COVER = re.compile(r"^cover-(?:9:16|3:4|4:3|16:9|9x16|3x4|4x3|16x9)\.(?:png|jpg|jpeg)$", re.I)
# session 形态：20260909-112124-625600
RE_SESSION = re.compile(r"\d{8}-\d{6}-\d{3,}")


def has_slug_date(name: str) -> bool:
    """文件名是否含「<slug>-<YYYYMMDD>」形态（slug 非空）。

    封面先剥掉 `cover-<ratio>-` 前缀，再要求出现 `<任意非空>-20YYMMDD`。
    成片应为 <slug>-<YYYYMMDD>-成片.mp4；封面应为 cover-<ratio>-<slug>-<YYYYMMDD>-<session>-v<n>.png。
    """
    if not name:
        return False
    n = re.sub(r"^cover-[^-]+-", "", name, flags=re.I)  # 封面剥 cover-9x16-
    return bool(re.match(r"^.+?[-_]20\d{6}(?:[-_.]|$)", n))


def load_payload(p: Path):
    """返回 [(cover_key, video_key, cover_inner_key)] 或抛错。"""
    data = json.loads(p.read_text(encoding="utf-8"))
    forms = (((data.get("publishArgs") or {}).get("accountForms")) or [])
    out = []
    for i, f in enumerate(forms):
        cover_key = f.get("coverKey")
        cover_inner = ((f.get("cover") or {}).get("key"))
        video_key = ((f.get("video") or {}).get("key"))
        out.append((cover_key, video_key, cover_inner))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="发布前校验视频/封面 key 对应关系")
    ap.add_argument("payloads", nargs="*", help="payload json 文件")
    ap.add_argument("--dir", help="扫描该目录下所有 payload*.json")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    ap.add_argument("--allow-legacy", action="store_true",
                    help="把「缺 slug+日期」降级为 WARN（仅排障/补发老片时用，正式发布别加）")
    args = ap.parse_args()

    files: list[Path] = []
    for s in args.payloads:
        p = Path(s)
        if not p.exists():
            print(f"[ERR] 找不到文件：{p}", file=sys.stderr)
            return 2
        files.append(p)
    if args.dir:
        files += sorted(Path(args.dir).glob("payload*.json"))
    # 去重保序
    seen, uniq = set(), []
    for f in files:
        r = f.resolve()
        if r not in seen:
            seen.add(r)
            uniq.append(f)
    files = uniq

    if not files:
        print("[ERR] 没有输入。给若干 payload.json，或用 --dir 指定目录。", file=sys.stderr)
        return 2

    fails, warns, records = [], [], []
    video_to_covers: dict[str, set] = {}

    for f in files:
        try:
            entries = load_payload(f)
        except Exception as e:
            fails.append(f"{f.name}: 解析失败 {e}")
            continue
        if not entries:
            warns.append(f"{f.name}: 没有 accountForms，跳过")
            continue
        for cover_key, video_key, cover_inner in entries:
            name = (cover_key or "").split("/")[-1]
            vname = (video_key or "").split("/")[-1]
            records.append({
                "file": f.name, "coverKey": cover_key,
                "videoKey": video_key, "coverName": name,
            })
            if not cover_key:
                fails.append(f"{f.name}: coverKey 为空")
            elif RE_BARE_COVER.match(name):
                fails.append(
                    f"{f.name}: 封面 key 是裸名「{name}」——不同视频会共用同一 key、互相覆盖。"
                    f"必须改用带 slug+日期+session 的唯一名"
                    f"（cover-<ratio>-<slug>-<YYYYMMDD>-<sessionId>-v<n>.png）"
                )
            elif not has_slug_date(name):
                msg = (f"{f.name}: 封面名「{name}」不带「slug + 8 位日期」——"
                       f"应为 cover-<ratio>-<slug>-<YYYYMMDD>-<sessionId>-v<n>.png")
                (warns if args.allow_legacy else fails).append(msg)
            elif not RE_SESSION.search(name):
                warns.append(f"{f.name}: 封面名「{name}」里没有 session 标识，"
                             f"同 slug 同日期重跑时无法确认唯一性")
            # 成片命名同样必须带 slug + 日期（2026-09-18 规则）
            if vname and not has_slug_date(vname):
                msg = (f"{f.name}: 成片名「{vname}」不带「slug + 8 位日期」——"
                       f"应为 <slug>-<YYYYMMDD>-成片.mp4")
                (warns if args.allow_legacy else fails).append(msg)
            if cover_inner and cover_key and cover_inner != cover_key:
                warns.append(f"{f.name}: cover.key 与 coverKey 不一致（{cover_inner} vs {cover_key}）")
            if video_key:
                video_to_covers.setdefault(video_key, set()).add(cover_key)

    # 跨文件不变量：不同视频不得共用封面
    cover_to_videos: dict[str, set] = {}
    for vk, cks in video_to_covers.items():
        for ck in cks:
            cover_to_videos.setdefault(ck, set()).add(vk)
    for ck, vks in cover_to_videos.items():
        if len(vks) > 1:
            fails.append(f"封面 key「{ck}」被 {len(vks)} 个不同视频共用 → 后发覆盖先发")

    ok = not fails
    if args.json:
        print(json.dumps({"ok": ok, "fails": fails, "warns": warns,
                          "records": records}, ensure_ascii=False, indent=2))
    else:
        print(f"[check] 检查 {len(files)} 个 payload，{len(records)} 条 accountForm")
        for r in records:
            print(f"  - {r['file']}: cover={r['coverName']}  video={(r['videoKey'] or '').split('/')[-1]}")
        if warns:
            print("\n[WARN]")
            for w in warns:
                print("  ! " + w)
        if fails:
            print("\n[FAIL]")
            for x in fails:
                print("  x " + x)
        print("\n" + ("✅ 通过：视频与封面 key 一一对应" if ok else "❌ 不通过：封面 key 存在冲突风险，先修再发"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
