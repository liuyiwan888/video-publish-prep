#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 video-publish-prep 打成可分发包（自动脱敏）。

用法：
    python scripts/package.py                      # 输出到 ./dist/
    python scripts/package.py --out D:/share       # 指定输出目录

做的事：
1. 复制 SKILL.md / README.md / install.* / config.example.json / references / scripts
2. 排除 __pycache__、.video-publish、*.pyc
3. **绝不打包 config.json**（里面有真实 API Key）
4. 扫描所有文本文件，确认没有 sk- 开头的真实密钥泄漏，有则报错中止
5. 打成 zip
"""
import argparse
import re
import shutil
import sys
import zipfile
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
NAME = SKILL_DIR.name

INCLUDE_FILES = ["SKILL.md", "README.md", "config.example.json",
                 "install.bat", "install.sh", ".gitignore"]
INCLUDE_DIRS = ["references", "scripts"]
EXCLUDE_NAMES = {"__pycache__", ".video-publish", ".git", ".DS_Store"}
EXCLUDE_SUFFIX = {".pyc", ".pyo"}

# 真实密钥特征：sk- 后跟 20 位以上 base64 字符
KEY_RE = re.compile(r"sk-[A-Za-z0-9]{20,}")


def die(msg: str, code: int = 1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def scan_leaks(root: Path) -> list:
    """扫描待打包文件里的真实密钥（config.example.json 允许占位符）。"""
    leaks = []
    allow_placeholder = {"YOUR_API_KEY_HERE", "sk-你的", "sk-xxxx"}
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix in EXCLUDE_SUFFIX:
            continue
        if p.name == "package.py":
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for m in KEY_RE.findall(text):
            if m not in allow_placeholder:
                leaks.append((p.relative_to(root), m[:12] + "..."))
    return leaks


def main():
    ap = argparse.ArgumentParser(description="打包 video-publish-prep 为可分发 zip")
    ap.add_argument("--out", default=None, help="输出目录（默认 skill 同级 dist/）")
    ap.add_argument("--no-zip", action="store_true", help="只生成目录，不打 zip")
    args = ap.parse_args()

    out_root = Path(args.out).expanduser().resolve() if args.out else SKILL_DIR.parent / "dist"
    staging = out_root / NAME
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    print(f"[pkg] 源目录 : {SKILL_DIR}")
    print(f"[pkg] 输出目录: {staging}")

    # 1. 文件
    for f in INCLUDE_FILES:
        src = SKILL_DIR / f
        if src.exists():
            shutil.copy2(src, staging / f)
            print(f"  + {f}")
        else:
            print(f"  - {f} (缺失，跳过)")

    # 2. 目录
    for d in INCLUDE_DIRS:
        src_dir = SKILL_DIR / d
        if not src_dir.exists():
            print(f"  - {d}/ (缺失，跳过)")
            continue
        (staging / d).mkdir(exist_ok=True)
        for p in sorted(src_dir.rglob("*")):
            if any(part in EXCLUDE_NAMES for part in p.parts):
                continue
            if p.is_dir():
                continue
            if p.suffix in EXCLUDE_SUFFIX or p.name == "package.py":
                continue
            rel = p.relative_to(src_dir)
            dst = staging / d / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)
        print(f"  + {d}/")

    # 3. 密钥泄漏扫描
    print("[pkg] 扫描密钥泄漏 ...")
    leaks = scan_leaks(staging)
    if leaks:
        for rel, sample in leaks:
            print(f"   ! {rel} 疑似含真实密钥: {sample}", file=sys.stderr)
        die("发现疑似真实密钥，已中止打包。请脱敏后重试。")

    # 4. 确认 config.json 没被打包
    if (staging / "config.json").exists():
        die("config.json（含 API Key）不应被打包，请检查排除规则。")
    print("[pkg] 校验通过：无密钥泄漏，config.json 已排除")

    # 5. 打 zip
    if args.no_zip:
        print(f"\n[pkg] 完成（未打 zip）：{staging}")
        return

    zip_path = out_root / f"{NAME}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for p in sorted(staging.rglob("*")):
            if p.is_file():
                zf.write(p, f"{NAME}/{p.relative_to(staging)}")

    size_kb = zip_path.stat().st_size // 1024
    print(f"\n[pkg] 打包完成：{zip_path}  ({size_kb} KB)")
    print(f"[pkg] 收件人用法：解压 → 双击 install.bat（Win）或 bash install.sh（Mac/Linux）")


if __name__ == "__main__":
    main()
