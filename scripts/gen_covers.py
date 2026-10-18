"""
video-publish-prep / gen_covers.py
按 content.json.cover 出 4 比例封面（杂志/极简风）：
  - 颜色：调 Agnes AI 出 1 张 256x256 缩略色卡 → PIL 提取 3-4 主色
  - 背景：PIL 自绘大色块渐变（按比例选方向） + 可选 accent 暖色点缀
  - 文字：PIL 烧中文（避免模型对中文标题的随机增删）
  - 颜色 fallback：tone → 预设调色板

设计理念：
  - 杂志感 = 大色块 + 亚光 + 留白 + 极简
  - AI 只负责"取色"（灵感），不参与构图（避免 30-50% 概率的 panel/circuit 翻车）
  - PIL 自绘保证 4 张永远稳定、视觉可控、秒出

输出：
  <session>/covers/v<n>/backgrounds/<ratio>.png            纯背景
  <session>/covers/v<n>/cover-<ratio>.png                  终稿（本地阅读）
  <session>/covers/v<n>/cover-<ratio>-<sessionId>-v<n>.png **上传专用唯一名**
  <session>/covers/v<n>/color_card.png                     AI 出的色卡（仅参考）
  <session>/covers/v<n>/manifest.json                      这一版的元数据

  ⚠️ 上传到蚁小二等"按文件名生成存储 key"的渠道，**必须用带 sessionId 的唯一名那份**，
     否则不同视频的封面会共用同一个 key、后传覆盖先传（封面张冠李戴）。

用法：
  python gen_covers.py --session <session_dir>
  python gen_covers.py --session <session_dir> --only 9:16
  python gen_covers.py --session <session_dir> --new-version
  python gen_covers.py --session <session_dir> --no-ai-color  # 跳过 AI，纯 tone 默认色
"""

import argparse
import base64
import io
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# PIL 由系统 Python 自带（Pillow 11+）
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps, ImageStat

SKILL_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = SKILL_DIR / "config.json"
CONFIG_EXAMPLE_PATH = SKILL_DIR / "config.example.json"

# 占位 key（模板里的默认值），遇到就当作未配置
PLACEHOLDER_KEYS = ("YOUR_API_KEY_HERE", "sk-你的", "sk-xxx", "")

RATIO_TAG = {
    "16:9": "16x9",
    "4:3":  "4x3",
    "3:4":  "3x4",
    "9:16": "9x16",
}

# tone → 默认调色板（AI 出图失败时用；4 色 = 3 主色 + 1 暖色 accent）
# 设计原则：3 主色按 浅→中→深 或 深→中→浅 排序，accent 跟主调形成色相对比
TONE_PALETTES = {
    "energetic": {
        "main": [(255, 230, 195), (255, 130, 90), (180, 50, 60)],   # 奶→珊瑚→深红
        "accent": (255, 90, 50),
    },
    "warm": {
        "main": [(255, 230, 210), (255, 170, 145), (175, 70, 90)],  # 奶→玫瑰金→酒红
        "accent": (220, 100, 80),
    },
    "professional": {
        "main": [(220, 235, 245), (90, 130, 175), (20, 50, 95)],    # 浅蓝→海军→深蓝
        "accent": (220, 160, 90),  # 暖金点缀
    },
    "calm": {
        "main": [(240, 248, 252), (180, 215, 230), (100, 150, 175)],  # 雾白→浅蓝→灰蓝
        "accent": (180, 200, 150),  # 草绿点缀
    },
    "dark": {
        "main": [(60, 60, 75), (30, 30, 40), (10, 10, 20)],          # 灰→深炭→黑
        "accent": (200, 90, 60),  # 暖红点缀
    },
    "natural": {
        "main": [(235, 225, 200), (160, 175, 130), (75, 100, 80)],   # 奶→草绿→深绿
        "accent": (220, 160, 80),  # 麦金
    },
    "wine": {
        "main": [(152, 26, 44), (16, 10, 16), (104, 14, 32)],      # 酒红→墨黑→深酒红（红黑交替）
        "accent": (186, 32, 50),  # 亮酒红点缀
    },
    "luxury": {
        "main": [(245, 230, 200), (170, 80, 100), (60, 25, 50)],    # 金→酒红→深紫
        "accent": (200, 160, 70),  # 哑光金
    },
    "tech": {
        "main": [(220, 230, 240), (100, 140, 175), (30, 50, 85)],   # 浅灰蓝→蓝→深蓝
        "accent": (90, 200, 200),  # 青色点缀
    },
    "default": {
        "main": [(225, 225, 230), (140, 150, 170), (40, 55, 80)],
        "accent": (210, 130, 80),
    },
}


def load_config(require_key: bool = False) -> dict:
    """读取配置。首次使用（config.json 不存在）时从模板自举，避免直接崩溃。

    require_key=False（默认）：不强制要 key。因为默认出封面走 PIL 本地生成，
    只在 `--ai-color`（AI 取色）时才真正调用 Agnes API。
    """
    if not CONFIG_PATH.exists():
        if CONFIG_EXAMPLE_PATH.exists():
            cfg = json.loads(CONFIG_EXAMPLE_PATH.read_text(encoding="utf-8"))
            CONFIG_PATH.write_text(
                json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[init] 已生成配置文件：{CONFIG_PATH}", file=sys.stderr)
        else:
            print(f"ERROR: 找不到 {CONFIG_PATH}，也没有 config.example.json 模板。",
                  file=sys.stderr)
            sys.exit(2)

    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    # 环境变量优先（方便 CI / 多账号切换 / 不落盘 key）
    env_key = (os.environ.get("AGNES_API_KEY") or "").strip()
    if env_key:
        cfg["api_key"] = env_key

    key = (cfg.get("api_key") or "").strip()
    key_missing = (key in PLACEHOLDER_KEYS
                   or any(key.startswith(p) for p in PLACEHOLDER_KEYS if p))

    if key_missing and require_key:
        print("ERROR: 本次要调用 Agnes API，但还没配置 API Key。二选一：", file=sys.stderr)
        print("  方式1（推荐，不落盘）：set AGNES_API_KEY=sk-xxxx", file=sys.stderr)
        print("        PowerShell: $env:AGNES_API_KEY=\"sk-xxxx\"", file=sys.stderr)
        print(f"  方式2：把 key 填进 {CONFIG_PATH} 的 api_key 字段", file=sys.stderr)
        print("  Key 获取：https://www.agnes-ai.com/ （控制台 → API Keys）", file=sys.stderr)
        sys.exit(2)
    return cfg


def load_session(session_dir: Path) -> dict:
    sj = session_dir / "session.json"
    cj = session_dir / "content.json"
    if not sj.exists():
        print(f"ERROR: 找不到 {sj}，请先跑 prepare.py。", file=sys.stderr); sys.exit(2)
    if not cj.exists():
        print(f"ERROR: 找不到 {cj}，请先写 content.json。", file=sys.stderr); sys.exit(2)
    return {
        "session": json.loads(sj.read_text(encoding="utf-8")),
        "content": json.loads(cj.read_text(encoding="utf-8")),
    }


def next_version(covers_root: Path) -> str:
    existing = sorted(p.name for p in covers_root.iterdir() if p.is_dir() and p.name.startswith("v"))
    n = len(existing) + 1
    return f"v{n}"


def file_to_data_uri(p: Path) -> str:
    mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"


# ---------- 调色板逻辑 ----------

def build_color_prompt(content: dict) -> str:
    """出 256x256 缩略图专门用于取色。"""
    bg = content.get("cover", {}).get("background", {})
    tone = (bg.get("tone") or content.get("cover", {}).get("tone") or "default").lower()
    user_palette = (bg.get("palette") or "").strip()
    tone_palette = TONE_PALETTES.get(tone, TONE_PALETTES["default"])
    default_main = " to ".join(", ".join(str(c) for c in color) for color in tone_palette["main"])
    palette = user_palette or default_main

    return (
        f"abstract color palette, {palette}. "
        f"smooth color blocks, soft gradient, matte paper texture, no objects, no patterns, "
        f"no people, no text, no letters, no logos. "
        f"no light rays, no particles, no cyber, no frame, no border, no panel. "
        f"high quality."
    )


def agnes_generate(cfg: dict, prompt: str, size: list[int],
                   ref_data_uris: list[str] | None = None) -> bytes:
    model = cfg["models"]["image_i2i"] if ref_data_uris else cfg["models"]["image_t2i"]
    body = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": f"{size[0]}x{size[1]}",
    }
    if ref_data_uris:
        body["tags"] = ["img2img"]
        body["image"] = ref_data_uris
    req = urllib.request.Request(
        cfg["api_base"] + "/images/generations",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": "Bearer " + cfg["api_key"],
            "Content-Type": "application/json",
        },
    )
    try:
        r = urllib.request.urlopen(req, timeout=cfg.get("request_timeout_sec", 120))
        d = json.loads(r.read().decode())
        url = d["data"][0].get("url")
        if not url:
            raise RuntimeError(f"Agnes 返回无 url：{json.dumps(d)[:300]}")
        return urllib.request.urlopen(url, timeout=cfg.get("request_timeout_sec", 120)).read()
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode(errors="ignore")[:500]
        raise RuntimeError(f"Agnes HTTP {e.code}: {body_txt}") from e


def extract_palette(img: Image.Image, n: int = 3) -> list[tuple[int, int, int]]:
    """从图像提取 n 个主色（按亮度排序：深→浅）。"""
    small = img.convert("RGB").resize((64, 64))
    quant = small.quantize(colors=n, method=Image.Quantize.MEDIANCUT)
    palette = quant.getpalette()
    colors = []
    for i in range(n):
        colors.append(tuple(palette[i*3:i*3+3]))
    # 按亮度（RGB 之和）排序：最暗在前
    colors.sort(key=lambda c: sum(c))
    return colors


def pick_accent(main: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    """从 3 主色中挑出 accent：色相差异最大的那一个，按更暖/更亮方向偏。"""
    # 简化：取亮度居中的那个，HSV 饱和度最高的作为 accent
    def sat(c):
        mx, mn = max(c), min(c)
        return (mx - mn) / max(mx, 1)
    if len(main) >= 2:
        # 取主色中饱和度最高的
        return max(main, key=sat)
    return main[0]


def get_palette(cfg: dict, content: dict, use_ai: bool = True) -> tuple[dict, str]:
    """获取调色板。返回 ({"main": [c0,c1,c2], "accent": c3}, source)。
    source ∈ {"ai", "fallback"}。
    """
    bg = content.get("cover", {}).get("background", {})
    tone = (bg.get("tone") or content.get("cover", {}).get("tone") or "default").lower()
    user_palette_str = (bg.get("palette") or "").strip()
    fallback = TONE_PALETTES.get(tone, TONE_PALETTES["default"])

    if not use_ai:
        return fallback, "fallback"

    try:
        prompt = build_color_prompt(content)
        png = agnes_generate(cfg, prompt, [256, 256], None)
        color_card = Image.open(io.BytesIO(png))
        main = extract_palette(color_card, n=3)
        if main and len(main) == 3:
            accent = pick_accent(main)
            return {"main": main, "accent": accent}, "ai"
    except Exception as e:
        print(f"[covers] AI 取色失败 ({e})，使用 tone 默认色", file=sys.stderr)

    return fallback, "fallback"


# ---------- PIL 渐变背景 ----------

def make_2color_gradient(size: tuple[int, int], c0: tuple[int, int, int],
                          c1: tuple[int, int, int], horizontal: bool = True) -> Image.Image:
    """PIL 线性 2 色渐变（手画灰度行 → colorize → resize）。"""
    W, H = size
    if horizontal:
        pixels = [int(255 * x / max(W - 1, 1)) for x in range(W)]
        gray = Image.new("L", (W, 1))
        gray.putdata(pixels)
    else:
        pixels = [int(255 * y / max(H - 1, 1)) for y in range(H)]
        gray = Image.new("L", (1, H))
        gray.putdata(pixels)
    colored = ImageOps.colorize(gray, black=c0, white=c1)
    return colored.resize(size, Image.BILINEAR)


def make_3color_gradient(size: tuple[int, int], c0, c1, c2,
                         direction: str = "horizontal") -> Image.Image:
    """3 色渐变（左 c0 → 中 c1 → 右 c2）。
    direction: horizontal / vertical / diagonal
    """
    W, H = size
    if direction == "horizontal":
        half = W // 2
        left = make_2color_gradient((half, H), c0, c1, horizontal=True)
        right = make_2color_gradient((W - half, H), c1, c2, horizontal=True)
        out = Image.new("RGB", (W, H))
        out.paste(left, (0, 0))
        out.paste(right, (half, 0))
        return out
    elif direction == "vertical":
        half = H // 2
        top = make_2color_gradient((W, half), c0, c1, horizontal=False)
        bot = make_2color_gradient((W, H - half), c1, c2, horizontal=False)
        out = Image.new("RGB", (W, H))
        out.paste(top, (0, 0))
        out.paste(bot, (0, half))
        return out
    else:  # diagonal
        # 横向 3 色 + 垂直 3 色平均
        h = make_3color_gradient(size, c0, c1, c2, "horizontal")
        v = make_3color_gradient(size, c0, c1, c2, "vertical")
        h_arr = h.convert("RGB")
        v_arr = v.convert("RGB")
        blended = Image.blend(h_arr, v_arr, 0.5)
        return blended


def add_accent_blob(bg: Image.Image, color: tuple[int, int, int],
                    pos: tuple[float, float] = (0.78, 0.22),
                    size_frac: tuple[float, float] = (0.55, 0.55),
                    max_alpha: int = 110) -> Image.Image:
    """在 bg 上加一个柔和的 accent 色块（径向渐变椭圆）。
    pos: (x_frac, y_frac) 中心位置（0-1）
    size_frac: (w_frac, h_frac) 占 bg 比例
    max_alpha: 中心最大不透明度
    """
    W, H = bg.size
    rgba = bg.convert("RGBA")
    cx, cy = int(W * pos[0]), int(H * pos[1])
    rx, ry = int(W * size_frac[0] / 2), int(H * size_frac[1] / 2)

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    # 多层椭圆模拟径向渐变
    steps = [(max_alpha, 1.0), (int(max_alpha * 0.65), 0.75), (int(max_alpha * 0.35), 0.5),
             (int(max_alpha * 0.15), 0.28), (int(max_alpha * 0.05), 0.12)]
    for a, shrink in steps:
        d.ellipse(
            [cx - int(rx * shrink), cy - int(ry * shrink),
             cx + int(rx * shrink), cy + int(ry * shrink)],
            fill=(*color, a),
        )
    layer = layer.filter(ImageFilter.GaussianBlur(radius=int(min(W, H) * 0.08)))
    rgba.alpha_composite(layer)
    return rgba.convert("RGB")


def make_gradient_bg(size: tuple[int, int], palette: dict, ratio: str, tone: str = "") -> Image.Image:
    """按 ratio 选方向，画 3 主色渐变 + accent 暖色点缀。

    渐变方向：所有比例统一用 diagonal（对角），保证视觉风格一致；
    accent blob 弱化放边角，不抢中央文字区。
    """
    main = palette["main"]
    accent = palette["accent"]

    # 4 个比例统一用对角渐变（左上→右下），视觉风格统一
    # 例外：wine 配色用三段实色带（上酒红/中墨黑/下深酒红），呈现"红黑交替"的层次感
    if tone == "wine":
        W, H = size
        bg = Image.new("RGB", (W, H), main[1])
        h_top = int(H * 0.34)
        h_bot = int(H * 0.34)
        bg.paste(Image.new("RGB", (W, h_top), main[0]), (0, 0))
        bg.paste(Image.new("RGB", (W, h_bot), main[2]), (0, H - h_bot))
        # 接缝处做一道柔和过渡（每条边 18px），避免实色带太硬
        band = 18
        for band_y, blend_to in [(h_top - band, main[0]), (H - h_bot, main[2])]:
            top0 = max(band_y - band, 0)
            bot0 = band_y
            for off in range(band):
                t = off / band
                r = int((1 - t) * blend_to[0] + t * main[1][0])
                g = int((1 - t) * blend_to[1] + t * main[1][1])
                b = int((1 - t) * blend_to[2] + t * main[1][2])
                y = top0 + off
                for x in range(W):
                    bg.putpixel((x, y), (r, g, b))
        # accent 点缀放右下角弱化，避免抢中央
        bg = add_accent_blob(bg, accent, pos=(0.88, 0.92), size_frac=(0.35, 0.30), max_alpha=70)
        return bg

    # accent 放右上角小区域，不抢中央
    # 先画浅色对角渐变底（main[0] → main[1]，保持整体偏亮，中央文字区可读）
    W, H = size
    small = Image.new("RGB", (64, 64))
    _px = small.load()
    for _y in range(64):
        for _x in range(64):
            _t = (_x + _y) / 126.0  # 0..1 对角
            _c = tuple(int((1 - _t) * main[0][i] + _t * main[1][i]) for i in range(3))
            _px[_x, _y] = _c
    bg = small.resize((W, H), Image.BILINEAR)
    if ratio in ("16:9", "3:4"):
        bg = add_accent_blob(bg, accent, pos=(0.88, 0.12), size_frac=(0.50, 0.65), max_alpha=95)
    elif ratio == "4:3":
        bg = add_accent_blob(bg, accent, pos=(0.85, 0.18), size_frac=(0.55, 0.55), max_alpha=100)
    else:  # 9:16
        bg = add_accent_blob(bg, accent, pos=(0.90, 0.10), size_frac=(0.50, 0.50), max_alpha=90)

    return bg


# ---------- 字体 & 文字烧录 ----------

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyhbd.ttc",   # 微软雅黑 Bold
    r"C:\Windows\Fonts\msyh.ttc",     # 微软雅黑
    r"C:\Windows\Fonts\simhei.ttf",   # 黑体
    r"C:\Windows\Fonts\simsun.ttc",   # 宋体
    "/System/Library/Fonts/PingFang.ttc",     # macOS
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",  # Linux
]


def load_font(size: int) -> ImageFont.FreeTypeFont:
    """按 环境变量 > 系统常见中文字体 > 默认字体 的顺序找。

    跨平台提示：Linux 常缺中文字体，可用 VPP_FONT_PATH 指定，例如
        export VPP_FONT_PATH=/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc
    """
    candidates = list(FONT_CANDIDATES)
    env_font = (os.environ.get("VPP_FONT_PATH") or "").strip()
    if env_font:
        candidates.insert(0, env_font)

    for f in candidates:
        if os.path.exists(f):
            try:
                return ImageFont.truetype(f, size=size)
            except Exception:
                continue

    # 兜底：系统默认字体（可能不含中文，会渲染成方块，给一次警告）
    if not getattr(load_font, "_warned", False):
        print("WARN: 没找到中文字体，标题可能显示为方块。", file=sys.stderr)
        print("      Windows 装微软雅黑即可；Linux 可执行："
              "sudo apt install fonts-wqy-zenhei", file=sys.stderr)
        print("      或设环境变量 VPP_FONT_PATH 指向任一 .ttf/.ttc 中文字体。", file=sys.stderr)
        load_font._warned = True
    return ImageFont.load_default()


def fit_font(draw: ImageDraw.ImageDraw, text: str, max_w: int, max_h: int,
             start: int) -> ImageFont.FreeTypeFont:
    for sz in range(start, 12, -2):
        font = load_font(sz)
        bbox = draw.textbbox((0, 0), text, font=font)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if w <= max_w and h <= max_h:
            return font
    return load_font(16)


def text_with_shadow(img: Image.Image, xy, text, font, fill=(255, 255, 255, 255),
                     shadow=(0, 0, 0, 110), offset=(0, 5), radius=8):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x, y = xy
    d.text((x + offset[0], y + offset[1]), text, font=font, fill=shadow)
    layer = layer.filter(ImageFilter.GaussianBlur(radius=radius))
    d2 = ImageDraw.Draw(layer)
    d2.text((x, y), text, font=font, fill=fill)
    img.alpha_composite(layer)


def avg_brightness(img: Image.Image, box=None) -> float:
    """文字区平均亮度（0-255）。用 ImageStat 走 C 实现，比逐像素快很多。"""
    crop = img.crop(box).convert("L") if box is not None else img.convert("L")
    return float(ImageStat.Stat(crop).mean[0])


def make_radial_mask(size: tuple[int, int]) -> Image.Image:
    """径向渐变蒙版：中央 100% → 边缘 0%（高斯模糊软边）。"""
    W, H = size
    cx, cy = W // 2, H // 2
    rx, ry = max(int(W * 0.70), 200), max(int(H * 0.60), 200)
    mask = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(mask)
    for i, a in enumerate((255, 200, 140, 80, 35, 12)):
        shrink = 1 - i * 0.20
        md.ellipse(
            [cx - int(rx * shrink), cy - int(ry * shrink),
             cx + int(rx * shrink), cy + int(ry * shrink)],
            fill=a,
        )
    return mask.filter(ImageFilter.GaussianBlur(radius=int(min(W, H) * 0.12)))


def compose_cover(bg: Image.Image, content: dict, ratio: str, cfg: dict = None) -> Image.Image:
    """把背景图和文字烧成终稿。返回 RGBA Image。

    版面原则（用户明确要求）：
    封面**只保留画面中央的主标题 + 副标题**，四角（左下 / 右下 / 任何角落）
    一律不绘制分类标签、水印、角标、页码、署名等附加文字。
    是否破例由 config.json 的 cover.show_category 控制（默认 false）。
    """
    img = bg.convert("RGBA")
    w, h = img.size
    cover = content["cover"]
    headline = (cover.get("headline") or "").strip()
    subheadline = (cover.get("subheadline") or "").strip()

    cover_cfg = (cfg or {}).get("cover", {})
    show_category = bool(cover_cfg.get("show_category", False))
    category = (cover.get("category") or "").strip() if show_category else ""

    # 安全区（中央文字带，四角留空）
    if ratio == "16:9":
        head_zone = (int(w * 0.08), int(h * 0.20), int(w * 0.92), int(h * 0.57))
        sub_zone  = (int(w * 0.08), int(h * 0.60), int(w * 0.92), int(h * 0.80))
        cat_xy    = (int(w * 0.06), int(h * 0.86))
        head_max  = int(h * 0.30)
        sub_max   = int(h * 0.13)
        cat_max   = int(h * 0.10)
    elif ratio == "4:3":
        head_zone = (int(w * 0.08), int(h * 0.18), int(w * 0.92), int(h * 0.57))
        sub_zone  = (int(w * 0.08), int(h * 0.60), int(w * 0.92), int(h * 0.82))
        cat_xy    = (int(w * 0.06), int(h * 0.86))
        head_max  = int(h * 0.30)
        sub_max   = int(h * 0.13)
        cat_max   = int(h * 0.10)
    elif ratio == "3:4":
        # 无角标后，文字块整体垂直居中（0.24 ~ 0.66）
        head_zone = (int(w * 0.08), int(h * 0.26), int(w * 0.92), int(h * 0.48))
        sub_zone  = (int(w * 0.10), int(h * 0.51), int(w * 0.90), int(h * 0.64))
        cat_xy    = (int(w * 0.08), int(h * 0.86))
        head_max  = int(h * 0.18)
        sub_max   = int(h * 0.09)
        cat_max   = int(h * 0.055)
    else:  # 9:16
        head_zone = (int(w * 0.10), int(h * 0.32), int(w * 0.90), int(h * 0.54))
        sub_zone  = (int(w * 0.10), int(h * 0.57), int(w * 0.90), int(h * 0.72))
        cat_xy    = (int(w * 0.10), int(h * 0.88))
        head_max  = int(h * 0.16)
        sub_max   = int(h * 0.085)
        cat_max   = int(h * 0.05)

    head_w = head_zone[2] - head_zone[0]
    head_h = head_zone[3] - head_zone[1]
    sub_w  = sub_zone[2]  - sub_zone[0]
    sub_h  = sub_zone[3]  - sub_zone[1]

    # 文字区中央"安全区"蒙版：让背景不抢字
    sample_box = (int(w * 0.4), int(h * 0.4), int(w * 0.6), int(h * 0.6))
    bg_brightness = avg_brightness(img, sample_box)
    is_dark_bg = bg_brightness < 145

    if is_dark_bg:
        # 全图轻压暗 + 中央更暗（径向渐变）
        base_dark = Image.new("RGBA", img.size, (0, 0, 0, 40))
        img.alpha_composite(base_dark)
        mask = make_radial_mask(img.size)
        black = Image.new("RGBA", img.size, (0, 0, 0, 0))
        black.putalpha(mask)
        img.alpha_composite(black)
        text_fill = (255, 255, 255, 255)
        sub_fill  = (255, 255, 255, 235)
    else:
        base = Image.new("RGBA", img.size, (255, 255, 255, 25))
        img.alpha_composite(base)
        mask = make_radial_mask(img.size)
        white = Image.new("RGBA", img.size, (255, 255, 255, 0))
        white.putalpha(mask)
        img.alpha_composite(white)
        text_fill = (20, 32, 60, 255)
        sub_fill  = (50, 60, 80, 245)

    draw = ImageDraw.Draw(img)

    # 标题
    if headline:
        font = fit_font(draw, headline, head_w - 16, head_h - 8, start=head_max)
        bbox = draw.textbbox((0, 0), headline, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = head_zone[0] + (head_w - tw) // 2
        y = head_zone[1] + (head_h - th) // 2 - bbox[1]
        if is_dark_bg:
            text_with_shadow(img, (x, y), headline, font,
                             fill=text_fill, shadow=(0, 0, 0, 150), offset=(0, 5), radius=10)
        else:
            text_with_shadow(img, (x, y), headline, font,
                             fill=text_fill, shadow=(255, 255, 255, 220), offset=(0, -2), radius=6)

    # 副标题
    if subheadline:
        font = fit_font(draw, subheadline, sub_w - 16, sub_h - 8, start=sub_max)
        bbox = draw.textbbox((0, 0), subheadline, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = sub_zone[0] + (sub_w - tw) // 2
        y = sub_zone[1] + (sub_h - th) // 2 - bbox[1]
        if is_dark_bg:
            text_with_shadow(img, (x, y), subheadline, font,
                             fill=sub_fill, shadow=(0, 0, 0, 130), offset=(0, 3), radius=6)
        else:
            text_with_shadow(img, (x, y), subheadline, font,
                             fill=sub_fill, shadow=(255, 255, 255, 220), offset=(0, -2), radius=4)

    # 分类标签（默认关闭：config.json → cover.show_category = false）
    if category:
        font = fit_font(draw, category, int(w * 0.4), int(cat_max * 1.4), start=cat_max)
        if is_dark_bg:
            text_with_shadow(img, cat_xy, category, font,
                             fill=(255, 255, 255, 235), shadow=(0, 0, 0, 120), offset=(0, 2), radius=4)
        else:
            text_with_shadow(img, cat_xy, category, font,
                             fill=(50, 60, 80, 230), shadow=(255, 255, 255, 220), offset=(0, -1), radius=3)

    return img


# ---------- 主流程 ----------

def main():
    ap = argparse.ArgumentParser(description="video-publish-prep / gen_covers")
    ap.add_argument("--session", required=True, help="会话目录（prepare.py 产出的）")
    ap.add_argument("--only", choices=list(RATIO_TAG.keys()),
                    help="只重做指定比例（其它比例继承上一版本终稿）")
    ap.add_argument("--new-version", action="store_true",
                    help="新建版本（v1 → v2）。未指定时默认继续上一版本")
    ap.add_argument("--ai-color", action="store_true",
                    help="用 AI 出 256x256 色卡提主色（默认用 cover.tone 调色板，秒出）")
    ap.add_argument("--no-ai-color", action="store_true",
                    help="显式关闭 AI 取色（与 --ai-color 互斥，默认本就是关闭）")
    ap.add_argument("--font", default=None,
                    help="指定中文字体文件路径（.ttf/.ttc），覆盖自动探测")
    args = ap.parse_args()

    if args.font:
        os.environ["VPP_FONT_PATH"] = args.font

    use_ai = bool(args.ai_color) and not args.no_ai_color

    # 只在真正要调 AI 时才强制要求 API Key（默认纯本地 PIL 生成，零配置可用）
    cfg = load_config(require_key=use_ai)
    session_dir = Path(args.session).expanduser().resolve()
    loaded = load_session(session_dir)
    session = loaded["session"]
    content = loaded["content"]
    tone = (content.get("cover") or {}).get("tone") or (content.get("background") or {}).get("tone") or ""
    covers_root = session_dir / "covers"
    covers_root.mkdir(exist_ok=True)

    # 决定版本
    if args.new_version or args.only is None:
        version = next_version(covers_root)
    else:
        existing = sorted([p for p in covers_root.iterdir() if p.is_dir() and p.name.startswith("v")],
                          key=lambda p: p.name)
        version = existing[-1].name if existing else "v1"

    vdir = covers_root / version
    bgs = vdir / "backgrounds"
    bgs.mkdir(parents=True, exist_ok=True)
    print(f"[covers] version = {version}")

    # 项目 slug + 日期（2026-09-18 规则：成片与封面文件名都必须带「slug + 8 位日期」）。
    # session 目录形态为 <project>/.video-publish/sessions/<YYYYMMDD-HHMMSS-xxxxxx>，
    # 因此 slug = 往上剥掉 sessions/.video-publish 后的目录名；日期取 sessionId 前 8 位。
    _p = session_dir.parent
    if _p.name == "sessions":
        _p = _p.parent
    if _p.name == ".video-publish":
        _p = _p.parent
    slug = _p.name
    _sid = session_dir.name
    date = _sid[:8] if _sid[:8].isdigit() else time.strftime("%Y%m%d")
    print(f"[covers] slug = {slug}  date = {date}")

    # 决定要做的比例
    ratios = [args.only] if args.only else list(RATIO_TAG.keys())

    # 调色板：默认走 tone fallback（稳定、秒出）；--ai-color 时才调 AI
    palette, source = get_palette(cfg, content, use_ai=use_ai)
    print(f"[covers] 调色板 source={source}, main={palette['main']}, accent={palette['accent']}")

    # 保存 AI 色卡（如果用了）
    if source == "ai":
        try:
            png = agnes_generate(cfg, build_color_prompt(content), [256, 256], None)
            (vdir / "color_card.png").write_bytes(png)
        except Exception:
            pass

    manifest = {
        "version": version,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "palette_source": source,
        "palette": palette,
        "ratios_done": [],
    }

    for ratio in ratios:
        w, h = cfg["sizes"][ratio]
        print(f"[covers] {ratio} ({w}x{h}) ...", end=" ", flush=True)
        t0 = time.time()
        try:
            bg = make_gradient_bg((w, h), palette, ratio, tone=tone)
            bg_path = bgs / f"{RATIO_TAG[ratio]}.png"
            bg.save(bg_path, "PNG", optimize=True)
            # 烧字
            final = compose_cover(bg, content, ratio, cfg)
            out = vdir / f"cover-{RATIO_TAG[ratio]}.png"
            final.convert("RGB").save(out, "PNG", optimize=True)
            # 唯一命名副本（slug + sessionId + 版本）：**上传蚁小二必须用这一份**。
            # 蚁小二对图片素材按文件名生成存储 key（yfb/<team>/<filename>），固定名
            # cover-9x16.png 会让不同视频的封面共用同一 key、后传覆盖先传，
            # 导致已发布作品封面张冠李戴。
            # sessionId 形如 YYYYMMDD-HHMMSS-xxxxxx，已含 8 位日期，
            # 因此本名同时满足「带 slug + 日期」且按视频唯一（2026-09-18 规则）。
            uniq = vdir / f"cover-{RATIO_TAG[ratio]}-{slug}-{session_dir.name}-{version}.png"
            final.convert("RGB").save(uniq, "PNG", optimize=True)
            print(f"OK  -> {out.relative_to(session_dir)}  ({time.time()-t0:.1f}s)")
            manifest["ratios_done"].append({"ratio": ratio,
                                            "background": str(bg_path.relative_to(session_dir)),
                                            "final": str(out.relative_to(session_dir)),
                                            "upload": str(uniq.relative_to(session_dir))})
        except Exception as e:
            print(f"FAIL: {e}")

    (vdir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[covers] 完成。本版 {len(manifest['ratios_done'])}/4 张。")
    print(f"        路径：{vdir}")


if __name__ == "__main__":
    main()
