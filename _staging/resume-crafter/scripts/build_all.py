"""一键构建：从简历 JSON 出发，一次性产出 HTML / PDF / DOCX 并完成质检。

用法：
    python build_all.py resume.json --out ./out --style classic --name 张三
    python build_all.py resume.json --out ./out --style auto --jd jd.txt

流程：
    JSON → 质检 → HTML → PDF → DOCX → ATS 体检 → 汇总报告
任何一步失败都会明确报告，不会静默跳过。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from render_resume import STYLES, render_html  # noqa: E402
from html_to_pdf import convert  # noqa: E402
from json_to_docx import build as build_docx  # noqa: E402
from lint_resume import lint  # noqa: E402
from ats_check import check as ats_check  # noqa: E402
from theme import PALETTES, SURFACES  # noqa: E402

import _console  # noqa: F401  (UTF-8 控制台兜底)


def pick_style(data: dict, jd_text: str | None) -> str:
    """无 JD 时按简历内容判断行业，有 JD 时按 JD 判断。"""
    from jd_match import detect_family, detect_family_from_resume, flatten_resume

    text = flatten_resume(data)
    if jd_text:
        from jd_match import extract_jd_requirements
        req = extract_jd_requirements(jd_text)
        fam = detect_family(req["tools"])
        edu = " ".join(req.get("edu", []))
        if any(k in edu for k in ("博士", "硕士")):
            return "academic"
        if fam & {"设计"} and not (fam & {"数据", "开发"}):
            return "sidebar"
        if fam & {"电商运营", "市场", "数据", "开发"}:
            return "modern"
        return "classic"

    fam = detect_family_from_resume(text)
    if fam & {"设计"} and not (fam & {"数据", "开发"}):
        return "sidebar"
    if fam & {"电商运营", "市场"}:
        return "modern"
    return "classic"


def main() -> int:
    ap = argparse.ArgumentParser(description="一键构建简历")
    ap.add_argument("resume", help="简历 JSON")
    ap.add_argument("--out", required=True, help="输出目录")
    ap.add_argument("--style", default="auto", choices=["auto"] + list(STYLES))
    ap.add_argument("--surface", default="", choices=[""] + list(SURFACES), help="纸面底板")
    ap.add_argument("--palette", default="", choices=[""] + list(PALETTES), help="主色配色")
    ap.add_argument("--density", default="", choices=["", "airy", "normal", "compact", "dense", "tight"],
                    help="排版密度，默认按内容体量自动选择")
    ap.add_argument("--name", default="", help="文件名（不含扩展名）")
    ap.add_argument("--jd", help="可选：JD 文本，用于风格推荐与匹配度评估")
    ap.add_argument("--formats", nargs="+", default=["pdf", "docx", "html"])
    args = ap.parse_args()

    data = json.loads(Path(args.resume).read_text(encoding="utf-8"))
    resume_path = Path(args.resume).resolve()
    base_dir = resume_path.parent
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    jd_text = Path(args.jd).read_text(encoding="utf-8", errors="ignore") if args.jd else None

    # 风格优先级：命令行 > JSON meta.style > 按内容/JD 自动推断 > classic
    meta = data.get("meta", {})
    meta_style = meta.get("style") or ""
    if args.style != "auto":
        style = args.style
    elif meta_style in STYLES:
        style = meta_style
    else:
        # meta.style 是无效键（早期遗留写法）时按内容推断，而不是直接崩掉
        style = pick_style(data, jd_text)

    stem = args.name or data.get("basic", {}).get("name", "简历")
    stem = "".join(ch for ch in stem if ch not in '\\/:*?"<>| ').strip() or "简历"

    # 底板/配色/密度：命令行 > JSON meta > 风格默认
    # 注意：命令行显式指定了 --surface/--palette 时，
    # JSON 里遗留的 meta.accent 不应再覆盖它（一条数据要能复用多套外观）。
    surface = args.surface or meta.get("surface") or "white"
    palette = args.palette or meta.get("palette") or STYLES[style].get("palette", "indigo")
    density = args.density or meta.get("density") or ""
    # 传给 render_html 的 surface/palette 传 None 表示「未显式指定」，
    # 由 render_html 决定是否采用 meta.accent
    surface_arg = args.surface or meta.get("surface")
    palette_arg = args.palette or meta.get("palette")

    print("=" * 66)
    print(f"简历构建 — {stem}")
    print("=" * 66)
    print(f"排版风格：{style}（{STYLES[style]['label']}）")
    print(f"纸面底板：{surface}　主色配色：{palette}"
          + (f"　密度：{density}" if density else "　密度：自动"))
    if data.get("basic", {}).get("photo"):
        print("头像位：已启用一寸照片位")

    # 1. 质检
    errors, warns, infos = lint(data, style, base_dir)
    print(f"\n[1/4] 内容质检：{len(errors)} 个必须修复 / {len(warns)} 处建议 / {len(infos)} 条优化建议")
    for loc, msg in errors:
        print(f"      ✗ [{loc}] {msg}")

    # 2. HTML
    html_path = outdir / f"{stem}.html"
    html_path.write_text(
        render_html(data, style, base_dir, surface_arg, palette_arg, density or None),
        encoding="utf-8",
    )
    print(f"[2/4] HTML 已生成：{html_path.name}")

    # 3. PDF
    pdf_path = outdir / f"{stem}.pdf"
    pdf_ok = False
    if "pdf" in args.formats:
        pdf_ok = convert(html_path, pdf_path)
        print(f"[3/4] PDF {'已生成' if pdf_ok else '生成失败'}：{pdf_path.name}")

    # 4. DOCX
    if "docx" in args.formats:
        docx_path = outdir / f"{stem}.docx"
        build_docx(data, docx_path, base_dir=base_dir)
        print(f"[4/4] DOCX 已生成：{docx_path.name}")

    # 5. ATS 体检
    if pdf_ok:
        pages, a_err, a_warn, a_info = ats_check(pdf_path)
        print(f"\n[ATS 体检] {pages} 页 — 阻断 {len(a_err)} / 风险 {len(a_warn)}")
        for e in a_err:
            print(f"      ✗ {e}")
        for w in a_warn:
            print(f"      ! {w}")

    # 6. 汇总
    print("\n" + "=" * 66)
    print("产出清单")
    print("=" * 66)
    for f in sorted(outdir.iterdir()):
        if f.is_file():
            print(f"  {f.name}  ({f.stat().st_size // 1024} KB)")
    print(f"\n目录：{outdir.resolve()}")

    if errors:
        print("\n⚠ 存在必须修复的内容问题，请先按提示修改 JSON 再投递。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
