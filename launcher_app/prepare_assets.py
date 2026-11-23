"""
构建期素材准备脚本：
1. 从官方确认的参考图 preview/reference_launcher.png 无损裁剪标题栏并无痕清理
   羊皮纸内部烘焙文字与底部按钮，完整保留角色立绘、双回形针、邮戳、右下卷角与金色短线；
2. 将 logo/app_icon.png 转换为多分辨率 app_icon.ico；
3. 复制运行期所需的 SVG/PNG 图标与轻量化动态装饰素材至 launcher_app/assets/。

注意：本脚本仅在开发/打包阶段运行；启动器运行期不依赖 Pillow。
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFilter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
)
logger = logging.getLogger("PrepareAssets")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_ASSETS_DIR = PROJECT_ROOT / "素材" / "MailHub_Launcher_Assets"
TARGET_ASSETS_DIR = PROJECT_ROOT / "launcher_app" / "assets"

# 标题栏高度（1672x941 原图中 y=0..42 为静态窗口标题栏）
TITLE_BAR_CROP_Y = 42

# 拷贝到运行期的图标清单
ICON_FILES = [
    "icon_console.png",
    "icon_info.png",
    "icon_settings.png",
    "icon_folder.png",
    "icon_link.png",
    "icon_sync.png",
    "icon_check.png",
    "icon_warning.png",
    "icon_mail.png",
    "icon_play.png",
    "icon_refresh.png",
    "icon_minimize.svg",
    "icon_maximize.svg",
    "icon_close.svg",
]

# 拷贝到运行期的轻量动效装饰清单
DECOR_FILES = [
    "sakura_petal.png",
    "sparkle.png",
]


def _is_clean_paper_pixel(rgb: tuple[int, int, int]) -> bool:
    """判断像素是否为干净暖羊皮纸色，避免边界采到回形针、邮戳或折角阴影。"""
    r, g, b = rgb
    return r >= 247 and g >= 240 and b >= 228


def _sample_clean_line(
    coords: list[tuple[int, int]],
    pixels: object,
    predicate: Callable[[tuple[int, int, int]], bool],
    fallback: tuple[int, int, int] = (254, 249, 243),
) -> list[tuple[int, int, int]]:
    """沿采样线读取像素，并将非纯背景像素替换为邻近干净背景像素。"""
    raw = [pixels[x, y] for x, y in coords]  # type: ignore[index]
    clean_indices = [i for i, rgb in enumerate(raw) if predicate(rgb)]
    if not clean_indices:
        return [fallback] * len(raw)

    result: list[tuple[int, int, int]] = []
    pos = 0
    for i, rgb in enumerate(raw):
        if predicate(rgb):
            result.append(rgb)
            continue
        while pos + 1 < len(clean_indices) and abs(clean_indices[pos + 1] - i) <= abs(clean_indices[pos] - i):
            pos += 1
        result.append(raw[clean_indices[pos]])
    return result


def _bilinear_fill_rect(
    image: Image.Image,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    sample_margin: int = 3,
    feather: int = 4,
    clean_only: bool = True,
) -> None:
    """
    利用矩形区域外围干净像素进行四边双线性插值填充，并做边缘羽化柔化，
    使羊皮纸底色自然过渡且不带入邻近回形针或阴影颜色。
    """
    width, height = image.size
    pixels = image.load()
    if pixels is None:
        raise RuntimeError("Failed to access image pixel buffer")

    sx0 = max(0, x0 - sample_margin)
    sx1 = min(width - 1, x1 + sample_margin)
    sy0 = max(0, y0 - sample_margin)
    sy1 = min(height - 1, y1 + sample_margin)

    predicate = _is_clean_paper_pixel if clean_only else (lambda _rgb: True)
    top_line = _sample_clean_line([(x, sy0) for x in range(x0, x1 + 1)], pixels, predicate)
    bot_line = _sample_clean_line([(x, sy1) for x in range(x0, x1 + 1)], pixels, predicate)
    left_line = _sample_clean_line([(sx0, y) for y in range(y0, y1 + 1)], pixels, predicate)
    right_line = _sample_clean_line([(sx1, y) for y in range(y0, y1 + 1)], pixels, predicate)

    w = x1 - x0 + 1
    h = y1 - y0 + 1
    patch = Image.new("RGB", (w, h))
    patch_px = patch.load()
    if patch_px is None:
        raise RuntimeError("Failed to create patch buffer")

    span_x = max(1, w - 1)
    span_y = max(1, h - 1)

    for iy in range(h):
        v = iy / span_y
        left_px = left_line[iy]
        right_px = right_line[iy]
        for ix in range(w):
            u = ix / span_x
            top_px = top_line[ix]
            bot_px = bot_line[ix]

            h_col = (
                left_px[0] * (1.0 - u) + right_px[0] * u,
                left_px[1] * (1.0 - u) + right_px[1] * u,
                left_px[2] * (1.0 - u) + right_px[2] * u,
            )
            v_col = (
                top_px[0] * (1.0 - v) + bot_px[0] * v,
                top_px[1] * (1.0 - v) + bot_px[1] * v,
                top_px[2] * (1.0 - v) + bot_px[2] * v,
            )
            dx = min(u, 1.0 - u)
            dy = min(v, 1.0 - v)
            wx = 1.0 / (dx + 0.08)
            wy = 1.0 / (dy + 0.08)
            w_sum = wx + wy
            r = int(round((h_col[0] * wx + v_col[0] * wy) / w_sum))
            g = int(round((h_col[1] * wx + v_col[1] * wy) / w_sum))
            b = int(round((h_col[2] * wx + v_col[2] * wy) / w_sum))
            patch_px[ix, iy] = (r, g, b)

    patch = patch.filter(ImageFilter.GaussianBlur(radius=1.5))

    mask = Image.new("L", (w, h), 255)
    if feather > 0:
        draw = ImageDraw.Draw(mask)
        for i in range(feather):
            alpha = int(255 * (i + 1) / (feather + 1))
            draw.rectangle([i, i, w - 1 - i, h - 1 - i], outline=alpha)

    image.paste(patch, (x0, y0), mask)


def _clean_rounded_pill(
    image: Image.Image,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    radius: int,
) -> None:
    """
    清理圆角胶囊区域（用于移除底部粉色按钮及其柔和外阴影），
    采用胶囊上下干净浅粉背景垂直线性插值修复，严格保留两侧金色短线。
    """
    pixels = image.load()
    if pixels is None:
        raise RuntimeError("Failed to access image pixel buffer")

    w = x1 - x0 + 1
    h = y1 - y0 + 1
    patch = Image.new("RGB", (w, h))
    patch_px = patch.load()
    if patch_px is None:
        raise RuntimeError("Failed to create pill patch buffer")

    sy_top = max(0, y0 - 5)
    sy_bot = min(image.height - 1, y1 + 5)

    for ix in range(w):
        x = x0 + ix
        top_rgb = pixels[x, sy_top]
        bot_rgb = pixels[x, sy_bot]
        for iy in range(h):
            t = iy / max(1, h - 1)
            r = int(round(top_rgb[0] * (1.0 - t) + bot_rgb[0] * t))
            g = int(round(top_rgb[1] * (1.0 - t) + bot_rgb[1] * t))
            b = int(round(top_rgb[2] * (1.0 - t) + bot_rgb[2] * t))
            patch_px[ix, iy] = (r, g, b)

    patch = patch.filter(ImageFilter.GaussianBlur(radius=2.2))

    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=2.5))

    image.paste(patch, (x0, y0), mask)


def build_clean_backdrop(src_path: Path, dst_path: Path) -> None:
    """生成无静态文字与按钮的纯净启动器主体背景图。"""
    if not src_path.exists():
        raise FileNotFoundError(f"Reference launcher image not found: {src_path}")

    with Image.open(src_path) as raw_img:
        rgb_img = raw_img.convert("RGB")

    # 1. 保留主体区 y=42..941（裁掉系统标题栏）
    cropped = rgb_img.crop((0, TITLE_BAR_CROP_Y, rgb_img.width, rgb_img.height))
    dy = -TITLE_BAR_CROP_Y

    # 2. 一次性完整清理羊皮纸内部文字、头栏、虚线与绿胶囊（y=312..626, x=506..1048）
    #    上方止于回形针底端下，右侧止于邮戳左侧，下方止于折角上方干净纸面
    _bilinear_fill_rect(
        cropped,
        x0=506,
        y0=312 + dy,
        x1=1048,
        y1=626 + dy,
        sample_margin=3,
        feather=4,
        clean_only=True,
    )

    # 3. 清理邮戳下方与卷角上方之间的右侧延伸日志（包含第 4 行的 "✓ OK"）
    _bilinear_fill_rect(
        cropped,
        x0=1042,
        y0=384 + dy,
        x1=1136,
        y1=548 + dy,
        sample_margin=3,
        feather=4,
        clean_only=True,
    )

    # 4. 清理第 7 行靠右下角的尾巴文字（避开 x>=1092, y>=558 的卷角和信封）
    _bilinear_fill_rect(
        cropped,
        x0=1042,
        y0=542 + dy,
        x1=1086,
        y1=582 + dy,
        sample_margin=3,
        feather=4,
        clean_only=True,
    )

    # 5. 清理底部粉色按钮及阴影（严格避让 x<=573 与 x>=1098 的金色短线）
    _clean_rounded_pill(
        cropped,
        x0=578,
        y0=695 + dy,
        x1=1092,
        y1=810 + dy,
        radius=54,
    )

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    cropped.save(dst_path, format="PNG", optimize=True)
    logger.info("Generated clean backdrop: %s (%dx%d)", dst_path, cropped.width, cropped.height)


def build_app_icon(src_png: Path, dst_ico: Path, dst_png: Path) -> None:
    """将素材目录 app_icon.png 转换为多分辨率 Windows .ico 与运行期 PNG。"""
    if not src_png.exists():
        raise FileNotFoundError(f"App icon not found: {src_png}")

    dst_ico.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src_png) as icon_img:
        rgba = icon_img.convert("RGBA")
        base_256 = rgba.resize((256, 256), Image.Resampling.LANCZOS)
        sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
        base_256.save(dst_ico, format="ICO", sizes=sizes)

    shutil.copy2(src_png, dst_png)
    logger.info("Generated multi-resolution icon: %s", dst_ico)


def copy_runtime_assets() -> None:
    """复制运行期所需的图标与装饰图至 launcher_app/assets。"""
    icons_src = SOURCE_ASSETS_DIR / "icons"
    icons_dst = TARGET_ASSETS_DIR / "icons"
    icons_dst.mkdir(parents=True, exist_ok=True)

    for filename in ICON_FILES:
        src_file = icons_src / filename
        if not src_file.exists():
            raise FileNotFoundError(f"Missing icon asset: {src_file}")
        shutil.copy2(src_file, icons_dst / filename)

    decor_src = SOURCE_ASSETS_DIR / "decor"
    decor_dst = TARGET_ASSETS_DIR / "decor"
    decor_dst.mkdir(parents=True, exist_ok=True)

    for filename in DECOR_FILES:
        src_file = decor_src / filename
        if not src_file.exists():
            raise FileNotFoundError(f"Missing decor asset: {src_file}")
        shutil.copy2(src_file, decor_dst / filename)

    logger.info("Copied %d icons and %d decor assets.", len(ICON_FILES), len(DECOR_FILES))


def main() -> int:
    """执行素材转换与同步。"""
    build_clean_backdrop(
        src_path=SOURCE_ASSETS_DIR / "preview" / "reference_launcher.png",
        dst_path=TARGET_ASSETS_DIR / "backdrop_clean.png",
    )
    build_app_icon(
        src_png=SOURCE_ASSETS_DIR / "logo" / "app_icon.png",
        dst_ico=TARGET_ASSETS_DIR / "app_icon.ico",
        dst_png=TARGET_ASSETS_DIR / "app_icon.png",
    )
    copy_runtime_assets()
    logger.info("All launcher assets prepared successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
