"""技能自检：验证 scripts / assets / references 完整性。

用法：python scripts/doctor.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import _console  # noqa: F401  (UTF-8 控制台兜底)

ROOT = Path(__file__).resolve().parent.parent
TPL = ROOT / "assets" / "templates"

REQUIRED_SCRIPTS = [
    "render_resume.py", "html_to_pdf.py", "json_to_docx.py",
    "lint_resume.py", "jd_match.py", "ats_check.py",
    "tailor_batch.py", "cover_letter.py", "build_all.py", "_env.py",
    "fit_one_page.py",
    "photo.py", "make_sample_photo.py",
]
REQUIRED_TEMPLATES = ["base.css", "style-classic.css", "style-modern.css",
                      "style-sidebar.css", "style-academic.css", "style-creative.css",
                      "style-elite.css", "style-neon.css", "style-soft.css",
                      "style-geo.css"]
REQUIRED_REFS = ["design-system.md", "data-schema.md", "writing-guide.md"]
REQUIRED_ROOT_FILES = ["README.md", "LICENSE", "requirements.txt", "CONTRIBUTING.md",
                        "agents/openai.yaml"]


def main() -> int:
    ok = True
    print("=" * 56)
    print("resume-crafter 技能自检")
    print("=" * 56)

    print("\n[文件完整性]")
    for name in REQUIRED_SCRIPTS:
        p = ROOT / "scripts" / name
        mark = "✓" if p.exists() else "✗"
        if not p.exists():
            ok = False
        print(f"  {mark} scripts/{name}")
    for name in REQUIRED_TEMPLATES:
        p = TPL / name
        mark = "✓" if p.exists() else "✗"
        if not p.exists():
            ok = False
        print(f"  {mark} assets/templates/{name}")
    for name in REQUIRED_REFS:
        p = ROOT / "references" / name
        mark = "✓" if p.exists() else "✗"
        if not p.exists():
            ok = False
        print(f"  {mark} references/{name}")

    print("\n[仓库文件]")
    for name in REQUIRED_ROOT_FILES:
        p = ROOT / name
        mark = "✓" if p.exists() else "✗"
        if not p.exists():
            ok = False
        print(f"  {mark} {name}")

    print("\n[SKILL.md]")
    skill_md = ROOT / "SKILL.md"
    if skill_md.exists():
        text = skill_md.read_text(encoding="utf-8")
        has_front = text.startswith("---") and "name:" in text and "description:" in text
        has_agent = "agent_created: true" in text
        print(f"  {'✓' if has_front else '✗'} YAML frontmatter")
        print(f"  {'✓' if has_agent else '✗'} agent_created 标记")
        if not (has_front and has_agent):
            ok = False
    else:
        print("  ✗ SKILL.md 缺失")
        ok = False

    print("\n[依赖]")
    try:
        from _env import ensure_deps
        py = ensure_deps()
        for mod in ("pypdf", "docx"):
            r = subprocess.run([str(py), "-c", f"import {mod}"], capture_output=True)
            print(f"  {'✓' if r.returncode == 0 else '✗'} {mod}")
            if r.returncode != 0:
                ok = False
    except Exception as e:
        print(f"  ! 依赖检查失败：{e}")

    print("\n[浏览器内核]")
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        from html_to_pdf import find_browser
        b = find_browser()
        if b:
            print(f"  ✓ {b}")
        else:
            # 无浏览器只影响 PDF 生成，HTML / DOCX 仍可用 —— 降级为警告
            print("  ! 未找到 Chromium 内核浏览器，PDF 无法自动生成（HTML / DOCX 不受影响）")
            print("    可手动用浏览器打开 HTML 后「打印 → 另存为 PDF」，或安装 Edge / Chrome")
    except Exception as e:
        print(f"  ! 检查失败：{e}")

    print("\n[示例数据]")
    sample = ROOT / "assets" / "sample-resume.json"
    if sample.exists():
        try:
            data = json.loads(sample.read_text(encoding="utf-8"))
            print(f"  ✓ sample-resume.json 可解析（{len(data.get('sections', []))} 个分区）")
        except Exception as e:
            print(f"  ✗ 解析失败：{e}")
            ok = False

    print("\n[主题体系一致性]")
    # 排版节奏必须拆成「基值（--*-base）」与「系数（--*-scale）」两层。
    # 若风格 CSS 直接写 --lh / --gap-section 等最终值，
    # 会与同优先级的密度档互相覆盖，导致密度自动分档形同虚设。
    base_css = TPL / "base.css"
    if base_css.exists():
        css = base_css.read_text(encoding="utf-8")
        # 派生变量必须声明在 body 上：写在 :root 时 body 的覆盖不会被 var() 读到。
        # 注意不能用 "body\s*\{" 搜索 —— "html, body {" 会先命中且跨不过 }。
        body_blocks = re.findall(r"(?:^|[},])\s*body\s*\{([^}]*)\}", css, re.M)
        root_blocks = re.findall(r":root\s*\{([^}]*)\}", css, re.M)
        derived_keys = ("--lh:", "--gap-section:", "--gap-entry:", "--pad-y:")
        # 必须在 body 上能找到，且不能在 :root 上被声明（否则 body 的覆盖不生效）
        body_derived = all(any(k in b for b in body_blocks) for k in derived_keys)
        root_conflict = [k for k in derived_keys
                         if any(k in b for b in root_blocks)]
        print(f"  {'✓' if body_derived and not root_conflict else '✗'} 派生变量声明在 body 层")
        if not body_derived:
            print("    提示：派生变量若只在 :root，body 上的 --*-base / --*-scale 覆盖不会生效")
            ok = False
        if root_conflict:
            print(f"    冲突：这些派生变量同时写在 :root → {root_conflict}")
            ok = False

        # 各风格 CSS 不应直接写最终排版值
        bad = []
        for p in sorted(TPL.glob("style-*.css")):
            t = p.read_text(encoding="utf-8")
            for m in re.finditer(r"--(lh|gap-section|gap-entry|pad-y)\s*:\s*([^;}]+)", t):
                if "var(" not in m.group(2):
                    bad.append(f"{p.name}: --{m.group(1)}: {m.group(2).strip()}")
        print(f"  {'✓' if not bad else '✗'} 风格 CSS 只写基值（--*-base）")
        for b in bad:
            print(f"    {b}")
        if bad:
            print("    提示：应写成 --lh-base / --gap-section-base 等基值，密度系数由 dens-* 档提供")
            ok = False

        # 密度档必须使用系数而非最终值
        dens = re.findall(r"body\.dens-\w+\s*\{([^}]*)\}", css)
        hardcoded = []
        for block in dens:
            for m in re.finditer(r"--(lh|gap-section|gap-entry|pad-y)\s*:\s*([^;}]+)", block):
                if "var(" not in m.group(2) and "scale" not in m.group(0):
                    hardcoded.append(m.group(0).strip())
        print(f"  {'✓' if not hardcoded else '✗'} 密度档只写系数（--*-scale）")
        for h in hardcoded:
            print(f"    {h}")
        if hardcoded:
            ok = False

        # 密度档数量与 Python 端定义必须一致
        try:
            sys.path.insert(0, str(ROOT / "scripts"))
            from theme import DENSITY_TIERS
            py_tiers = {t[0] for t in DENSITY_TIERS}
            css_tiers = set(re.findall(r"body\.dens-(\w+)\s*\{", css))
            same = py_tiers == css_tiers
            print(f"  {'✓' if same else '✗'} 密度档 Python / CSS 一致（{len(py_tiers)} 档）")
            if not same:
                print(f"    仅 Python 有：{sorted(py_tiers - css_tiers)}；仅 CSS 有：{sorted(css_tiers - py_tiers)}")
                ok = False
        except Exception as e:
            print(f"  ! 密度档比对失败：{e}")

    print("\n[底板与配色]")
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from theme import PALETTES, SURFACES
        print(f"  ✓ {len(SURFACES)} 种底板：{'、'.join(SURFACES)}")
        print(f"  ✓ {len(PALETTES)} 种配色：{'、'.join(PALETTES)}")
        # 深色底板必须整套反色
        dark = [k for k, v in SURFACES.items() if v["dark"]]
        for k in dark:
            s = SURFACES[k]
            ok_dark = (
                sum(int(s["ink"][i:i + 2], 16) for i in (1, 3, 5)) >
                sum(int(s["paper"][i:i + 2], 16) for i in (1, 3, 5))
            )
            print(f"  {'✓' if ok_dark else '✗'} 深色底板「{k}」文字亮于纸面")
            if not ok_dark:
                ok = False

        # 主色对比度：色块 ≥3:1、文字 ≥4.5:1
        from theme import contrast_ratio, resolve_theme
        low = []
        for surf in SURFACES:
            for pal in PALETTES:
                th = resolve_theme(surf, pal)
                cb = contrast_ratio(th.accent, th.paper)
                ct = contrast_ratio(th.accent_text, th.paper)
                if cb < 3.0 or ct < 4.5:
                    low.append(f"{surf}×{pal}(色块{cb:.1f}/文字{ct:.1f})")
        print(f"  {'✓' if not low else '✗'} 主色对比度达标（色块≥3:1、文字≥4.5:1）")
        for x in low:
            print(f"    {x}")
        if low:
            ok = False

        # 深色底板的派生色可见下限
        # 黑纸上 sRGB 混合既更弱、又会吃掉色相（蓝灰褪成灰），
        # 派生色低于下限就等于「画了但看不见」。
        DERIVED_MIN = {
            "accent_soft": 1.35,   # 斜切色块尾段 / 摘要竖线
            "accent_line": 1.60,   # 结构线
            "chip_border": 1.40,   # 胶囊描边
            "sec_h_bg": 1.15,      # 分区标题底带
        }
        weak = []
        for surf, sf in SURFACES.items():
            if not sf["dark"]:
                continue
            for pal in PALETTES:
                th = resolve_theme(surf, pal)
                for attr, floor in DERIVED_MIN.items():
                    r = contrast_ratio(getattr(th, attr), th.paper)
                    if r < floor:
                        weak.append(f"{surf}×{pal} {attr}={r:.2f}<{floor}")
        print(f"  {'✓' if not weak else '✗'} 深底派生色达到可见下限")
        for x in weak:
            print(f"    {x}")
        if weak:
            ok = False
    except Exception as e:
        print(f"  ! 检查失败：{e}")

    print("\n" + "=" * 56)
    print("自检通过，技能可用。" if ok else "自检发现问题，请修复上方 ✗ 项。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
