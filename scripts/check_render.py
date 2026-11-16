# -*- coding: utf-8 -*-
"""对渲染截图做基本体检：尺寸、颜色丰富度、分带内容密度、主色出现次数。"""
from collections import Counter
from pathlib import Path

from PIL import Image

img = Image.open(Path("reports/ui.png")).convert("RGB")
w, h = img.size
print("size:", w, h)

colors = Counter(img.getdata())
print("distinct colors:", len(colors))
print("top colors:", colors.most_common(8))

# 每个横向条带里非背景像素的比例，用来判断内容是否分布到整页
bg = (244, 246, 250)
bands = 18
for i in range(bands):
    top, bottom = h * i // bands, h * (i + 1) // bands
    crop = img.crop((0, top, w, bottom))
    total = crop.size[0] * crop.size[1]
    non_bg = sum(1 for px in crop.getdata() if abs(px[0] - bg[0]) + abs(px[1] - bg[1]) + abs(px[2] - bg[2]) > 12)
    print(f"band {i:>2} y={top:>5}-{bottom:<5} content={non_bg / total * 100:5.1f}%")

# 关键色出现次数：主色蓝、绿、琥珀、红
targets = {"accent": (79, 107, 255), "green": (22, 160, 107), "amber": (217, 138, 0), "red": (224, 74, 79)}
for name, rgb in targets.items():
    count = sum(1 for px in img.getdata() if abs(px[0] - rgb[0]) < 18 and abs(px[1] - rgb[1]) < 18 and abs(px[2] - rgb[2]) < 18)
    print(f"{name}: {count} px")