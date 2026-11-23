"""
从「可爱向导吉祥物与梦幻箭头贴纸集.png」无损提取各独立透明贴纸切片。

采用像素连通域分析将每个主贴纸及其附属星光/强调射线单独掩码剥离，
即使相邻贴纸外接矩形存在交叉，也不会带入任何相邻贴纸的像素。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_SHEET = PROJECT_ROOT / "素材" / "可爱向导吉祥物与梦幻箭头贴纸集.png"
OUTPUT_DIR = PROJECT_ROOT / "frontend" / "src" / "assets" / "onboarding"


@dataclass(frozen=True)
class StickerSpec:
    """定义贴纸输出文件名及其主体像素锚点坐标（原图坐标系）。"""

    filename: str
    anchor_x: int
    anchor_y: int
    # 可选附带额外连通域锚点（如分离的强调射线或虚线段）
    extra_anchors: tuple[tuple[int, int], ...] = ()


STICKER_SPECS: tuple[StickerSpec, ...] = (
    StickerSpec("mascot-point-right.png", 280, 240),
    StickerSpec("mascot-point-down.png", 730, 240),
    StickerSpec("mascot-welcome.png", 1170, 240, extra_anchors=((1370, 180),)),
    StickerSpec("arrow-curve-right.png", 250, 570),
    StickerSpec("arrow-curve-left.png", 710, 570),
    StickerSpec("arrow-swirl-up-right.png", 1190, 570),
    StickerSpec("arrow-down-bold.png", 170, 775),
    StickerSpec("arrow-up-bold.png", 450, 775),
    StickerSpec("arrow-spiral-right.png", 800, 760),
    StickerSpec("arrow-loop-right.png", 1200, 765),
    StickerSpec("cursor-click.png", 150, 975),
    StickerSpec("arrow-straight-right.png", 420, 985),
    StickerSpec("arrow-dashed-right.png", 790, 985, extra_anchors=((635, 985),)),
    StickerSpec("arrow-comic-right.png", 1200, 985, extra_anchors=((1045, 920),)),
)


def extract_components(
    alpha_img: Image.Image, alpha_threshold: int = 10
) -> tuple[list[int], dict[int, tuple[int, int, int, int, int]]]:
    """
    对整张贴纸集进行 8 邻域连通域标记。
    返回 (labels_flat, stats_by_label)，其中 stats 为 (area, x0, y0, x1, y1)。
    """
    w, h = alpha_img.size
    px = alpha_img.load()
    if px is None:
        raise RuntimeError("Failed to read alpha channel")

    labels = [0] * (w * h)
    stats: dict[int, tuple[int, int, int, int, int]] = {}
    current_label = 0

    for y in range(h):
        row_off = y * w
        for x in range(w):
            idx = row_off + x
            if labels[idx] != 0 or px[x, y] <= alpha_threshold:
                continue

            current_label += 1
            labels[idx] = current_label
            queue = deque([(x, y)])
            min_x = max_x = x
            min_y = max_y = y
            area = 0

            while queue:
                cx, cy = queue.popleft()
                area += 1
                if cx < min_x:
                    min_x = cx
                if cx > max_x:
                    max_x = cx
                if cy < min_y:
                    min_y = cy
                if cy > max_y:
                    max_y = cy

                for ny in (cy - 1, cy, cy + 1):
                    if 0 <= ny < h:
                        noff = ny * w
                        for nx in (cx - 1, cx, cx + 1):
                            if 0 <= nx < w:
                                nidx = noff + nx
                                if labels[nidx] == 0 and px[nx, ny] > alpha_threshold:
                                    labels[nidx] = current_label
                                    queue.append((nx, ny))

            stats[current_label] = (area, min_x, min_y, max_x, max_y)

    return labels, stats


def find_component_near(
    labels: list[int],
    stats: dict[int, tuple[int, int, int, int, int]],
    w: int,
    h: int,
    ax: int,
    ay: int,
    radius: int = 60,
) -> int:
    """在指定锚点附近查找面积最大的有效贴纸连通域标签。"""
    best_label = 0
    best_area = 0
    for dy in range(-radius, radius + 1, 2):
        py = ay + dy
        if not (0 <= py < h):
            continue
        for dx in range(-radius, radius + 1, 2):
            px = ax + dx
            if not (0 <= px < w):
                continue
            lbl = labels[py * w + px]
            if lbl != 0:
                area = stats[lbl][0]
                if area > best_area:
                    best_area = area
                    best_label = lbl
    if best_label == 0:
        raise RuntimeError(f"No sticker component found near ({ax}, {ay})")
    return best_label


def slice_stickers() -> None:
    """将全部向导吉祥物与梦幻箭头切为独立高清透明 PNG。"""
    if not SOURCE_SHEET.is_file():
        raise FileNotFoundError(f"Sticker sheet not found: {SOURCE_SHEET}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with Image.open(SOURCE_SHEET) as raw_img:
        rgba = raw_img.convert("RGBA")

    w, h = rgba.size
    alpha = rgba.getchannel("A")
    labels, stats = extract_components(alpha)
    src_px = rgba.load()
    if src_px is None:
        raise RuntimeError("Failed to read RGBA buffer")

    padding = 6

    for spec in STICKER_SPECS:
        target_labels: set[int] = {
            find_component_near(labels, stats, w, h, spec.anchor_x, spec.anchor_y)
        }
        for ex, ey in spec.extra_anchors:
            target_labels.add(find_component_near(labels, stats, w, h, ex, ey))

        # 合并包络矩形，并额外吸纳落在此包络内的微小同组抗锯齿点（如虚线顶边缘）
        x0 = min(stats[lbl][1] for lbl in target_labels)
        y0 = min(stats[lbl][2] for lbl in target_labels)
        x1 = max(stats[lbl][3] for lbl in target_labels)
        y1 = max(stats[lbl][4] for lbl in target_labels)

        for lbl, (area, lx0, ly0, lx1, ly1) in stats.items():
            if area < 150 and lx0 >= x0 and lx1 <= x1 and ly0 >= y0 - 4 and ly1 <= y1 + 4:
                target_labels.add(lbl)

        crop_w = (x1 - x0 + 1) + padding * 2
        crop_h = (y1 - y0 + 1) + padding * 2
        out_img = Image.new("RGBA", (crop_w, crop_h), (0, 0, 0, 0))
        out_px = out_img.load()
        if out_px is None:
            raise RuntimeError("Failed to allocate output sticker buffer")

        for py in range(y0, y1 + 1):
            row_off = py * w
            for px_x in range(x0, x1 + 1):
                if labels[row_off + px_x] in target_labels:
                    out_px[px_x - x0 + padding, py - y0 + padding] = src_px[px_x, py]

        out_path = OUTPUT_DIR / spec.filename
        out_img.save(out_path, format="PNG", optimize=True)
        print(f"Saved {spec.filename}: {out_img.size}")


if __name__ == "__main__":
    slice_stickers()
