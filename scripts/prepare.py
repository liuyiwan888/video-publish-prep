"""
video-publish-prep / prepare.py
把视频或字幕变成一个可继续的"会话"：
  .video-publish/sessions/<id>/
    session.json       元数据（路径、时长、分辨率、字幕来源）
    transcript.txt     完整转写
    frames/            关键帧 PNG（按 1/8 1/4 1/2 3/4 时点抽，可作封面参考图）

支持：
  --input  <video.mp4 | subtitle.srt | subtitle.vtt>
  --subtitle  <subtitle.srt>   # 视频有外挂字幕时优先用
  --video  <video.mp4>         # 字幕文件单独提供时给一个视频，仅记路径
  --root  <dir>                # 会话根目录，默认当前目录下的 .video-publish

依赖：
  - ffmpeg + ffprobe（PATH 里）
  - 有外挂字幕或视频内嵌字幕时无需 whisper
  - 视频无字幕时会跳过 transcript 并打印待办；用户后续装 faster-whisper 再补
"""

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
SUB_EXTS = {".srt", ".vtt"}


def die(msg, code=1):
    print(f"[prepare] ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def need(cmd, hint=""):
    if shutil.which(cmd) is None:
        die(f"找不到 {cmd}（PATH 里）。{hint}")


def short_id():
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    h = hashlib.sha1(str(time.time_ns()).encode()).hexdigest()[:6]
    return f"{ts}-{h}"


def ffprobe_meta(path: Path) -> dict:
    try:
        out = subprocess.check_output(
            [
                "ffprobe", "-v", "error",
                "-print_format", "json",
                "-show_format", "-show_streams", str(path),
            ],
            stderr=subprocess.STDOUT,
            timeout=60,
        )
    except subprocess.CalledProcessError as e:
        die(f"ffprobe 失败：{e.output.decode(errors='ignore')[:300]}")
    return json.loads(out)


def parse_srt(text: str) -> str:
    """把 srt/vtt 解析成纯文本。"""
    lines = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue
        if re.match(r"^\d+$", s):
            continue
        if "-->" in s:
            continue
        if s.upper() == "WEBVTT":
            continue
        if s.lower().startswith("kind:") or s.lower().startswith("language:"):
            continue
        lines.append(s)
    return "\n".join(lines)


def read_srt_or_vtt(path: Path) -> str:
    return parse_srt(path.read_text(encoding="utf-8-sig", errors="ignore"))


def extract_embedded_subtitle(video: Path, out_dir: Path) -> Path | None:
    """用 ffmpeg 抽第一条字幕轨到 srt。返回 srt 路径或 None。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    srt = out_dir / "embedded.srt"
    # 先列字幕轨
    meta = ffprobe_meta(video)
    streams = meta.get("streams", [])
    sub_idxs = [i for i, s in enumerate(streams) if s.get("codec_type") == "subtitle"]
    if not sub_idxs:
        return None
    # 优先 srt/text mov_text；其次任何
    for i in sub_idxs:
        codec = streams[i].get("codec_name", "")
        if codec in ("subrip", "srt", "mov_text"):
            cmd = ["ffmpeg", "-y", "-i", str(video), "-map", f"0:{i}", str(srt)]
            r = subprocess.run(cmd, capture_output=True, timeout=180)
            if srt.exists() and srt.stat().st_size > 10:
                return srt
    return None


def extract_keyframes(video: Path, out_dir: Path, n: int = 6) -> list[Path]:
    """均匀抽 n 帧。返回 png 路径列表。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = ffprobe_meta(video)
    duration = float(meta.get("format", {}).get("duration", 0) or 0)
    if duration <= 0:
        # 单帧
        paths = _snap_single(video, out_dir)
        return paths
    paths = []
    for i in range(n):
        t = duration * (i + 1) / (n + 1)
        p = out_dir / f"keyframe_{i+1:02d}_t{int(t*1000):07d}ms.png"
        cmd = [
            "ffmpeg", "-y", "-ss", f"{t:.3f}", "-i", str(video),
            "-frames:v", "1", "-q:v", "2", str(p),
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=60)
        if p.exists() and p.stat().st_size > 0:
            paths.append(p)
    return paths


def _snap_single(video: Path, out_dir: Path) -> list[Path]:
    p = out_dir / "keyframe_01.png"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(p)],
        capture_output=True, timeout=60,
    )
    return [p] if p.exists() and p.stat().st_size > 0 else []


def setup_session(input_path: Path, root: Path) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    sessions = root / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    sid = short_id()
    sdir = sessions / sid
    sdir.mkdir()
    (sdir / "frames").mkdir()
    (sdir / "covers").mkdir()
    return {"id": sid, "dir": sdir}


def find_chinese_srt_for(video: Path) -> Path | None:
    """同目录找同名 .srt/.vtt 字幕，优先中文（带 .zh / .cn / .chs 之类）。"""
    stem = video.stem
    parent = video.parent
    candidates = []
    for ext in SUB_EXTS:
        for p in parent.glob(f"{stem}*{ext}"):
            candidates.append(p)
    if not candidates:
        return None
    # 优先 zh/cn/chs
    for p in candidates:
        n = p.stem.lower()
        if any(tag in n for tag in ("zh", "cn", "chs", "中文", "简体")):
            return p
    return candidates[0]


def main():
    ap = argparse.ArgumentParser(description="video-publish-prep / prepare")
    ap.add_argument("--input", required=True, help="视频或字幕文件的绝对路径")
    ap.add_argument("--subtitle", help="可选：外挂字幕路径（视频 + 字幕时用）")
    ap.add_argument("--video", help="可选：仅给字幕时记录的视频路径")
    ap.add_argument("--root", default=".video-publish", help="会话根目录（默认 .video-publish）")
    ap.add_argument("--keyframes", type=int, default=6, help="关键帧抽帧数")
    args = ap.parse_args()

    need("ffprobe", hint="请先安装 ffmpeg 并加到 PATH。")
    need("ffmpeg", hint="请先安装 ffmpeg 并加到 PATH。")

    inp = Path(args.input).expanduser().resolve()
    if not inp.exists():
        die(f"输入文件不存在：{inp}")

    root = Path(args.root).expanduser().resolve()
    sess = setup_session(inp, root)
    sdir: Path = sess["dir"]
    print(f"[prepare] session = {sdir}")

    is_video = inp.suffix.lower() in VIDEO_EXTS
    is_sub = inp.suffix.lower() in SUB_EXTS

    session = {
        "id": sess["id"],
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "input": str(inp),
        "kind": "video" if is_video else "subtitle",
        "video": None,
        "subtitle_used": None,
        "duration_sec": None,
        "resolution": None,
        "fps": None,
        "frames": [],
        "transcript_source": None,
        "transcript_chars": 0,
    }

    # 决定视频与字幕
    video_path: Path | None = None
    sub_path: Path | None = None

    if is_video:
        video_path = inp
        session["video"] = str(inp)
        # 优先用 --subtitle；否则找同目录；否则抽内嵌
        if args.subtitle:
            sub_path = Path(args.subtitle).expanduser().resolve()
            if not sub_path.exists():
                die(f"--subtitle 指定但文件不存在：{sub_path}")
        else:
            sub_path = find_chinese_srt_for(inp)
        if sub_path is None:
            sub_path = extract_embedded_subtitle(inp, sdir)
    elif is_sub:
        sub_path = inp
        if args.video:
            video_path = Path(args.video).expanduser().resolve()
            if not video_path.exists():
                die(f"--video 指定但文件不存在：{video_path}")
    else:
        die(f"不支持的输入类型：{inp.suffix}（仅 {sorted(VIDEO_EXTS | SUB_EXTS)}）")

    if video_path:
        meta = ffprobe_meta(video_path)
        v_stream = next((s for s in meta.get("streams", []) if s.get("codec_type") == "video"), {})
        session["duration_sec"] = float(meta.get("format", {}).get("duration", 0) or 0) or None
        session["resolution"] = f"{v_stream.get('width')}x{v_stream.get('height')}" if v_stream else None
        session["fps"] = v_stream.get("r_frame_rate")

        # 抽关键帧
        frames = extract_keyframes(video_path, sdir / "frames", args.keyframes)
        session["frames"] = [str(p.relative_to(sdir)) for p in frames]
        print(f"[prepare] 抽帧 {len(frames)} 张到 frames/")

    # transcript
    transcript_text = ""
    if sub_path and sub_path.exists():
        transcript_text = read_srt_or_vtt(sub_path)
        session["transcript_source"] = f"subtitle:{sub_path}"
        (sdir / "transcript.txt").write_text(transcript_text, encoding="utf-8")
        session["transcript_chars"] = len(transcript_text)
        print(f"[prepare] transcript.txt 已写入，{session['transcript_chars']} 字")
    elif video_path:
        print("[prepare] 视频无外挂/内嵌字幕。转写待办：")
        print("          1) pip install faster-whisper")
        print("          2) 用 faster-whisper 转写后将结果保存到 transcript.txt")
        print("             或运行: python -c 'import faster_whisper; ...'")
        (sdir / "transcript.txt").write_text("", encoding="utf-8")

    # session.json
    (sdir / "session.json").write_text(
        json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    # 控制台输出下一步
    print("\n=== 下一步 ===")
    print(f"1. 在会话目录写 content.json，参考 references/content-contract.md：")
    print(f"   {sdir / 'content.json'}")
    if not sub_path and video_path:
        print(f"2. （视频无字幕）先补 transcript.txt 再写 content.json")
        print(f"3. python scripts/gen_covers.py --session \"{sdir}\"")
        print(f"4. python scripts/finalize.py  --session \"{sdir}\"")
    else:
        print(f"2. python scripts/gen_covers.py --session \"{sdir}\"")
        print(f"3. python scripts/finalize.py  --session \"{sdir}\"")

    # 给本进程之外消费的 stdout 结果（方便 WorkBuddy agent 直接拿到路径）
    print(f"\nSESSION_DIR={sdir}")


if __name__ == "__main__":
    main()
