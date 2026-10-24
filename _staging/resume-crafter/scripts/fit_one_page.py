#!/usr/bin/env python3
"""一页适配器：渲染后若超过一页，自动收紧排版参数直到塞进一页。

设计原则：优先调整「视觉密度」类参数（行距、间距、内边距），
只有在这些都到底了仍超页时，才提示需要用户精简内容。
不修改任何简历文字内容。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _console  # noqa: F401

from render_resume import render_html, STYLES  # noqa: E402
from html_to_pdf import find_browser  # noqa: E402
from theme import PALETTES, SURFACES  # noqa: E402

HERE = Path(__file__).resolve().parent
TEMPLATE_DIR = HERE.parent / "assets" / "templates"


def page_count(pdf: Path) -> int:
    try:
        import pypdf
    except ImportError:
        return -1
    try:
        return len(pypdf.PdfReader(str(pdf)).pages)
    except Exception:
        return -1


def convert(html: Path, pdf: Path) -> bool:
    browser = find_browser()
    if not browser:
        return False
    url = "file:///" + str(html).replace("\\", "/")
    cmd = [
        str(browser), "--headless=new", "--disable-gpu", "--no-sandbox",
        f"--print-to-pdf={pdf}", "--print-to-pdf-no-header",
        "--no-pdf-header-footer", url,
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=90)
    except Exception:
        return False
    return pdf.exists() and pdf.stat().st_size > 1000


# 密度档位：从宽松到紧凑。每一档同时调整多个参数，
# 保证视觉比例协调，不会出现「行距紧了但间距没紧」的割裂感。
# 与 base.css 的 dens-* 档位一一对应（这里做的是最后一轮微调）。
# 用「系数」而非绝对值：风格 CSS 提供的基值会被自动继承，
# 这样 fit_one_page 与 render_html 的排版语言保持一致。
DENSITY_TIERS = [
    # 每一档同时调整行距、间距、页边距与正文字号等视觉密度参数，
    # 保证比例协调，不会出现「行距紧了但间距没紧」的割裂感。
    # 正文字号下限 10pt（ATS 与可读性红线），内容一律不删。
    {"name": "标准", "density": "normal", "lh": 1.00, "gap_section": 1.00, "gap_entry": 1.00,
     "pad_y": 1.00, "summary_mb": 1.8, "sec_h_mb": 2.0, "fs_body": 10.5},
    {"name": "紧凑", "density": "compact", "lh": 0.93, "gap_section": 0.68, "gap_entry": 0.72,
     "pad_y": 0.86, "summary_mb": 1.5, "sec_h_mb": 1.8, "fs_body": 10.2},
    {"name": "高密", "density": "dense", "lh": 0.87, "gap_section": 0.54, "gap_entry": 0.58,
     "pad_y": 0.76, "summary_mb": 1.2, "sec_h_mb": 1.5, "fs_body": 10.0},
    {"name": "偏紧", "density": "dense", "lh": 0.84, "gap_section": 0.45, "gap_entry": 0.50,
     "pad_y": 0.72, "summary_mb": 1.0, "sec_h_mb": 1.4, "fs_body": 10.0},
    {"name": "极限", "density": "tight", "lh": 0.82, "gap_section": 0.40, "gap_entry": 0.42,
     "pad_y": 0.68, "summary_mb": 0.9, "sec_h_mb": 1.3, "fs_body": 10.0},
    # 微调档：用于临界溢出（只差 1—2 行）的情况，做最后 0.5mm 级别的微调
    {"name": "微调", "density": "tight", "lh": 0.80, "gap_section": 0.36, "gap_entry": 0.38,
     "pad_y": 0.64, "summary_mb": 0.8, "sec_h_mb": 1.2, "fs_body": 10.0},
]


def build_html(
    data: dict,
    style: str,
    tier: dict,
    out: Path,
    surface: str | None = None,
    palette: str | None = None,
) -> None:
    """按密度档位注入 CSS 覆盖后输出 HTML。"""
    lh, gap_s, gap_e, pad_y, sum_mb, sec_mb, fs_body = (
        tier["lh"], tier["gap_section"], tier["gap_entry"],
        tier["pad_y"], tier["summary_mb"], tier["sec_h_mb"], tier["fs_body"],
    )
    # 覆盖密度系数（--*-scale），基值仍由风格 CSS 提供。
    # 注意：--fs-title / --fs-meta 在 base.css 里是由 --fs-body-scale 派生的，
    # 这里不能直接写绝对值，否则会绕开密度体系。
    override = f"""
/* ---- 一页适配：密度档 {tier['name']} ---- */
body.tpl-{style} {{
  --lh-scale: {lh};
  --gap-section-scale: {gap_s};
  --gap-entry-scale: {gap_e};
  --pad-y-scale: {pad_y};
  --fs-body-scale: {round(fs_body / 10.5, 4)};
}}
.summary-block {{ margin-bottom: {sum_mb}mm; }}
.sec-h {{ margin-bottom: {sec_mb}mm; }}
"""

    html = render_html(data, style, None, surface, palette, tier["density"])
    # 把覆盖样式插到最后一个 </style> 之前
    idx = html.rfind("</style>")
    if idx != -1:
        html = html[:idx] + override + html[idx:]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="自动适配到一页")
    ap.add_argument("data")
    ap.add_argument("--style", default="classic", choices=list(STYLES))
    ap.add_argument("--surface", default="", choices=[""] + list(SURFACES), help="纸面底板")
    ap.add_argument("--palette", default="", choices=[""] + list(PALETTES), help="主色配色")
    ap.add_argument("--out-dir", required=True, help="输出目录")
    ap.add_argument("--name", default=None, help="文件主名")
    args = ap.parse_args()

    import json
    data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    base_dir = Path(args.data).resolve().parent
    outdir = Path(args.out_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    stem = args.name or data.get("basic", {}).get("name", "简历")
    stem = "".join(ch for ch in stem if ch not in '\\/:*?"<>| ').strip() or "简历"

    # 底板/配色：命令行 > JSON meta > 风格默认。
    # 传 None 表示「未显式指定」，由 render_html 决定是否采用 meta.accent。
    meta = data.get("meta", {})
    surface = args.surface or meta.get("surface")
    palette = args.palette or meta.get("palette")

    html_path = outdir / f"{stem}.html"
    pdf_path = outdir / f"{stem}.pdf"

    chosen = None
    for tier in DENSITY_TIERS:
        build_html(data, args.style, tier, html_path, surface, palette)
        if not convert(html_path, pdf_path):
            print("PDF 转换失败：请确认已安装 Edge / Chrome", file=sys.stderr)
            return 2
        n = page_count(pdf_path)
        if n <= 1:
            chosen = tier
            print(f"已适配为单页（密度档：{tier['name']}）")
            break
        print(f"  密度档「{tier['name']}」→ {n} 页，继续收紧…")

    if chosen is None:
        chosen = DENSITY_TIERS[-1]
        print(f"[提示] 已用最紧密度档，仍为 {page_count(pdf_path)} 页。")
        print("       保留全部内容需要 2 页；如需严格 1 页，请在 JSON 中精简 1—2 条 bullet。")

    # 输出最终版（用选中的档位重新生成，确保 HTML 与 PDF 一致）
    build_html(data, args.style, chosen, html_path, surface, palette)
    convert(html_path, pdf_path)

    print(f"HTML: {html_path}")
    print(f"PDF : {pdf_path}  ({page_count(pdf_path)} 页)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
