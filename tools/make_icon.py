# -*- coding: utf-8 -*-
"""
make_icon.py —— 图标后处理：去掉图标圆角外的多余背景，导出 assets/icon.png + assets/icon.ico。

用法:
    python tools/make_icon.py                     # 读 assets/icon_source.png
    python tools/make_icon.py 任意图片.png         # 读指定图片

原理:
    目标图是 App Store 风格的圆角蓝方块，四角填着背景色（本次是青绿 ≈(150,230,220)）。
    1) 用「B - R > 120」判定"图标蓝"，在首行/首列找第一个蓝像素的位置 ≈ 圆角半径；
    2) 用该半径画圆角矩形遮罩（4x 超采样做抗锯齿），把圆角外的背景切成透明；
    3) 输出 256x256 PNG 与多尺寸 ICO（16/24/32/48/64/128/256）。
"""
import os
import sys

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ASSETS, "icon_source.png")
PNG_OUT = os.path.join(ASSETS, "icon.png")
ICO_OUT = os.path.join(ASSETS, "icon.ico")
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
SS = 4  # 遮罩超采样倍数


def is_icon_blue(p):
    """区分"图标蓝"与青绿背景：背景 B-R≈70~82，图标蓝 B-R≈190。"""
    r, g, b = p
    return (b - r) > 120 and b > 170


def main():
    if not os.path.exists(SRC):
        print("[错误] 找不到源图: %s" % SRC)
        print("       请把图标图片放到 assets/icon_source.png，或用参数指定路径。")
        return 1

    im = Image.open(SRC).convert("RGB")
    W, H = im.size
    px = im.load()
    side = min(W, H)
    print("源图: %s  (%dx%d)" % (SRC, W, H))

    # --- 1) 估圆角半径 ---
    row_x = next((x for x in range(W) if is_icon_blue(px[x, 0])), None)
    col_y = next((y for y in range(H) if is_icon_blue(px[0, y])), None)
    radius = max(row_x or 0, col_y or 0)
    if not (0.10 * side <= radius <= 0.35 * side):
        radius = int(0.22 * side)
        print("半径估计不合理，回退到 22%% = %d" % radius)
    print("圆角半径: %d  (%.1f%% of %d)" % (radius, 100.0 * radius / side, side))

    # --- 2) 圆角遮罩（4x 超采样抗锯齿）---
    big = side * SS
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, big - 1, big - 1], radius=radius * SS, fill=255)
    alpha = mask.resize((side, side), Image.LANCZOS)

    icon = im.crop((0, 0, side, side)).convert("RGBA")
    icon.putalpha(alpha)

    # --- 3) 导出 ---
    os.makedirs(ASSETS, exist_ok=True)
    icon256 = icon.resize((256, 256), Image.LANCZOS)
    icon256.save(PNG_OUT)
    icon256.save(ICO_OUT, format="ICO", sizes=ICO_SIZES)

    print("\n已导出:")
    for p in (PNG_OUT, ICO_OUT):
        print("  %s  (%.1f KB)" % (p, os.path.getsize(p) / 1024.0))

    # --- 4) 自检 ---
    a = icon.split()[3].load()
    checks = {
        "左上角": (0, 0), "右上角": (side - 1, 0), "左下角": (0, side - 1), "右下角": (side - 1, side - 1),
    }
    ok = True
    for name, c in checks.items():
        v = a[c]
        print("  自检 %s alpha=%d %s" % (name, v, "OK" if v == 0 else "!! 应为 0（背景没切净）"))
        ok &= (v == 0)
    print("\n结果: %s" % ("图标处理完成 ✅" if ok else "四角未完全透明，请检查源图 ⚠️"))
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
