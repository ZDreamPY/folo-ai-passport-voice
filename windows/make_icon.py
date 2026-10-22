#!/usr/bin/env python3
"""生成打包用 icon.ico(与托盘图标同款:暖橙小球+轮廓环眼+点阵笑)。"""

import os
from PIL import Image, ImageDraw


def make(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ink = (14, 22, 32, 255)
    s = size / 64.0
    d.ellipse([4 * s, 6 * s, 60 * s, 62 * s], fill=(255, 169, 77, 255))
    d.ellipse([13 * s, 19 * s, 27 * s, 37 * s], outline=ink,
              width=max(2, round(3 * s)))                       # 左眼环
    d.ellipse([37 * s, 19 * s, 51 * s, 37 * s], outline=ink,
              width=max(2, round(3 * s)))                       # 右眼环
    d.ellipse([17 * s, 25 * s, 23 * s, 31 * s], fill=ink)       # 瞳孔
    d.ellipse([41 * s, 25 * s, 47 * s, 31 * s], fill=ink)
    for x, y in ((22, 46), (28, 49), (36, 49), (42, 46)):       # 点阵笑
        r = 2 * s
        d.ellipse([x * s - r, y * s - r, x * s + r, y * s + r], fill=ink)
    return img


if __name__ == "__main__":
    base = os.path.dirname(os.path.abspath(__file__))
    imgs = [make(sz) for sz in (16, 24, 32, 48, 64, 128, 256)]
    imgs[-1].save(os.path.join(base, "icon.ico"),
                  sizes=[(i.width, i.height) for i in imgs])
    print("icon.ico written")
