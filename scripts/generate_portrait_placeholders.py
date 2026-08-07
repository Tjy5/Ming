"""生成元末主题占位头像（自绘，非商业素材）。

用途：阶段C 素材清单——为 frontend/public/portraits/ 生成 8 张
512x512 PNG 占位头像（徐达/常遇春/李善长/刘基/宋濂/朱升/汤和/胡大海）。
文件名严格匹配 frontend/src/utils/portraits.ts 的 MINISTER_PORTRAIT_FILENAMES。

风格：水墨暗底 + 朱砂印章式圆框 + 楷体姓名，供后续人工/AI 绘制正式头像前的占位。
运行：python scripts/generate_portrait_placeholders.py

依赖：需先安装 Pillow（`pip install pillow`）。本机 Windows 环境下假设
C:\\Windows\\Fonts\\STKAITI.TTF（楷体）存在；非 Windows 系统需修改
_load_font 中的字体路径（如改为 Linux 的 /usr/share/fonts/... 楷体/黑体），
否则脚本会因找不到字体而失败。
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT_DIR = Path(__file__).resolve().parent.parent / "frontend" / "public" / "portraits"
SIZE = 512

# (姓名, 文件名)
PORTRAITS = [
    ("徐达", "xu_da.png"),
    ("常遇春", "chang_yuchun.png"),
    ("李善长", "li_shanchang.png"),
    ("刘基", "liu_ji.png"),
    ("宋濂", "song_lian.png"),
    ("朱升", "zhu_sheng.png"),
    ("汤和", "tang_he.png"),
    ("胡大海", "hu_dahai.png"),
]

# 元末主题色板：墨色暗底 + 朱砂印章 + 宣纸字色
INK_TOP = (46, 34, 24)      # 深褐
INK_BOTTOM = (18, 13, 9)    # 近黑
CINNABAR = (143, 45, 29)    # 朱砂
CINNABAR_LIGHT = (186, 76, 50)
PAPER = (216, 201, 163)     # 宣纸色
ACCENTS = [(178, 84, 42), (158, 122, 62), (120, 92, 54)]  # 底色晕染变化


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in (
        r"C:\Windows\Fonts\STKAITI.TTF",   # 楷体
        r"C:\Windows\Fonts\simhei.ttf",    # 黑体兜底
        r"C:\Windows\Fonts\msyh.ttc",      # 雅黑兜底
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    raise OSError("no Chinese font available")


def _draw_gradient(size: int, accent: tuple[int, int, int]) -> Image.Image:
    """竖直水墨渐变 + 中央暖色晕。"""
    img = Image.new("RGB", (size, size), INK_TOP)
    px = img.load()
    for y in range(size):
        t = y / (size - 1)
        r = int(INK_TOP[0] * (1 - t) + INK_BOTTOM[0] * t)
        g = int(INK_TOP[1] * (1 - t) + INK_BOTTOM[1] * t)
        b = int(INK_TOP[2] * (1 - t) + INK_BOTTOM[2] * t)
        for x in range(size):
            px[x, y] = (r, g, b)
    # 中央暖色晕
    glow = Image.new("L", (size, size), 0)
    gd = ImageDraw.Draw(glow)
    gd.ellipse((size * 0.16, size * 0.16, size * 0.84, size * 0.84), fill=120)
    glow = glow.filter(ImageFilter.GaussianBlur(60))
    overlay = Image.new("RGB", (size, size), accent)
    img = Image.composite(overlay, img, glow)
    return img


def _draw_frame(img: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """朱砂双环圆框（印章感）。"""
    margin = size = SIZE
    outer = (margin * 0.08, margin * 0.08, size * 0.92, size * 0.92)
    inner = (margin * 0.13, margin * 0.13, size * 0.87, size * 0.87)
    draw.ellipse(outer, outline=CINNABAR_LIGHT, width=8)
    draw.ellipse(inner, outline=CINNABAR, width=3)


def _draw_name(draw: ImageDraw.ImageDraw, name: str) -> None:
    """楷体姓名居中。"""
    font = _load_font(96 if len(name) <= 2 else 72)
    bbox = draw.textbbox((0, 0), name, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (SIZE - w) // 2 - bbox[0]
    y = (SIZE - h) // 2 - bbox[1]
    # 轻微阴影增强可读性
    draw.text((x + 2, y + 3), name, font=font, fill=(0, 0, 0, 140))
    draw.text((x, y), name, font=font, fill=PAPER)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for index, (name, filename) in enumerate(PORTRAITS):
        img = _draw_gradient(SIZE, ACCENTS[index % len(ACCENTS)])
        draw = ImageDraw.Draw(img)
        _draw_frame(img, draw)
        _draw_name(draw, name)
        path = OUT_DIR / filename
        img.save(path, "PNG")
        print(f"generated {path} ({name})")


if __name__ == "__main__":
    main()
