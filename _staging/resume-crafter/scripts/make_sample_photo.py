"""生成示例证件照（用于演示与自动化测试）。

绘制一张标准证件照风格的示意图：蓝底 + 灰色人形剪影 + 白边，
不涉及真实人物，可安全随仓库分发。

用法：python make_sample_photo.py [输出路径]
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _console  # noqa: F401  (UTF-8 控制台兜底)

W, H = 413, 579  # 200×250 比例放大 2 倍多，对应 25×35mm


def make_photo(out: Path) -> Path:
    img = Image.new("RGB", (W, H), (222, 233, 244))
    d = ImageDraw.Draw(img)

    # 证件照蓝底渐层（用横向条带模拟）
    top = (58, 96, 140)
    bottom = (108, 145, 184)
    for y in range(H):
        t = y / (H - 1)
        d.line(
            [(0, y), (W, y)],
            fill=(
                int(top[0] + (bottom[0] - top[0]) * t),
                int(top[1] + (bottom[1] - top[1]) * t),
                int(top[2] + (bottom[2] - top[2]) * t),
            ),
        )

    # 人形剪影：头 + 肩
    skin = (226, 213, 200)
    suit = (62, 66, 74)
    cx = W // 2
    head_r = int(W * 0.19)
    head_cy = int(H * 0.34)
    d.ellipse([cx - head_r, head_cy - head_r, cx + head_r, head_cy + head_r], fill=skin)

    # 肩部
    shoulder_top = head_cy + int(head_r * 1.45)
    d.ellipse(
        [cx - int(W * 0.42), shoulder_top, cx + int(W * 0.42), H + int(H * 0.30)],
        fill=suit,
    )
    # 领口
    d.polygon(
        [
            (cx - int(W * 0.11), shoulder_top - int(H * 0.005)),
            (cx + int(W * 0.11), shoulder_top - int(H * 0.005)),
            (cx, shoulder_top + int(H * 0.10)),
        ],
        fill=(245, 246, 248),
    )

    # 白边
    pad = int(W * 0.035)
    for i in range(pad):
        alpha = 255 - int(200 * (1 - i / pad))
        d.rectangle([i, i, W - 1 - i, H - 1 - i], outline=(255, 255, 255), width=1)

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, format="PNG", optimize=True)
    return out


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "assets" / "sample-photo.png"
    p = make_photo(target)
    print(f"已生成示例证件照：{p}")
