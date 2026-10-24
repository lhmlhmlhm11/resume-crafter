"""一寸头像（证件照）处理模块。

职责：
1. 从简历 JSON 的 basic.photo 解析头像来源（本地路径 / data URI / 远程 URL）
2. 本地图片转成 base64 data URI 内嵌进 HTML —— 保证 HTML 被单独分享、或交给
   无头浏览器渲染 PDF 时图片不会丢失（相对路径在部分渲染环境下会失效）
3. 提供标准证件照尺寸换算（一寸 25×35mm 等）

设计约束：
- 头像不产生文本层，不影响 ATS 解析，可安全使用
- 不做任何图像处理（不裁剪、不压缩），完整保留用户原图
"""

from __future__ import annotations

import base64
from pathlib import Path

# 标准证件照尺寸（毫米）：宽 × 高
PHOTO_SIZES = {
    "1in": (25.0, 35.0),       # 一寸，最通用
    "small1in": (22.0, 32.0),  # 小一寸
    "2in": (35.0, 49.0),       # 二寸
    "square": (30.0, 30.0),    # 方形
    "boss": (25.0, 31.25),     # 200×250px 比例（Boss 直聘头像推荐规格）
}

# 头像形状 → (圆角样式, 是否强制正方形)
# circle 用正方形容器，保证裁出的是正圆而不是椭圆
PHOTO_SHAPES = {
    "rect": ("1.2mm", False),      # 标准证件照矩形（默认）
    "rounded": ("3mm", False),     # 大圆角矩形
    "circle": ("50%", True),       # 正圆头像
}


def detect_mime(path: Path) -> str:
    """按文件头判断图片类型，不依赖扩展名。"""
    try:
        head = path.read_bytes()[:16]
    except OSError:
        return "image/png"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"GIF8"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith(b"BM"):
        return "image/bmp"
    return "image/png"


def read_photo(src: str, base_dir: Path | None = None) -> dict | None:
    """解析头像来源，返回可直接用于渲染的结构。

    返回 dict：
        kind   "data_uri" | "url"
        value  data URI 字符串，或 http(s) 地址
        w_mm   显示宽度（毫米）
        h_mm   显示高度（毫米）
        shape  "rect" | "round"
    解析失败返回 None（调用方应退化为占位框）。
    """
    if not src:
        return None
    src = str(src).strip()
    if not src:
        return None

    if src.startswith("data:"):
        return {"kind": "data_uri", "value": src, "w_mm": 25.0, "h_mm": 35.0, "shape": "rect"}

    if src.startswith(("http://", "https://")):
        return {"kind": "url", "value": src, "w_mm": 25.0, "h_mm": 35.0, "shape": "rect"}

    p = Path(src).expanduser()
    if not p.is_absolute() and base_dir is not None:
        p = (Path(base_dir) / p).resolve()
    if not p.exists() or not p.is_file():
        return None

    try:
        payload = base64.b64encode(p.read_bytes()).decode("ascii")
    except OSError:
        return None

    mime = detect_mime(p)
    return {
        "kind": "data_uri",
        "value": f"data:{mime};base64,{payload}",
        "w_mm": 25.0,
        "h_mm": 35.0,
        "shape": "rect",
    }


def configure(photo: dict, size: str = "1in", shape: str = "rect") -> dict:
    """按用户指定的证件照规格与形状调整显示参数。"""
    w, h = PHOTO_SIZES.get(size, PHOTO_SIZES["1in"])
    photo = dict(photo)
    if shape not in PHOTO_SHAPES:
        shape = "rect"
    _, force_square = PHOTO_SHAPES[shape]
    if force_square:
        w = h = max(w, h)
    photo["w_mm"] = w
    photo["h_mm"] = h
    photo["shape"] = shape
    return photo
