"""端到端全流程回归测试：验证技能在真实使用路径下无断裂。

用法：python scripts/selftest.py
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from _env import ensure_deps  # noqa: E402

import _console  # noqa: F401  (UTF-8 控制台兜底)

PY = str(ensure_deps())


def run(script: str, *args: str) -> subprocess.CompletedProcess:
    cmd = [PY, str(ROOT / "scripts" / script), *args]
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="rc_selftest_"))
    sample = ROOT / "assets" / "sample-resume.json"
    jd = ROOT / "assets" / "sample-jd.txt"
    jd2 = ROOT / "assets" / "sample-jd-2.txt"

    results = []

    def check(name: str, cond: bool, detail: str = ""):
        results.append((name, cond, detail))
        print(f"  {'✓' if cond else '✗'} {name}" + (f"  — {detail}" if detail and not cond else ""))

    print("=" * 60)
    print("端到端回归测试")
    print("=" * 60)

    # 1. 质检
    print("\n[1] 内容质检")
    r = run("lint_resume.py", str(sample), "--style", "classic")
    check("质检可运行", r.returncode == 0, r.stderr[-200:])
    check("示例数据无 ERROR", "必须修复" not in r.stdout or "0 个必须修复" in r.stdout)

    # 2. 九种风格渲染
    print("\n[2] 九种风格渲染")
    for style in ("classic", "modern", "sidebar", "academic", "creative",
                  "elite", "neon", "soft", "geo"):
        h = tmp / f"{style}.html"
        r = run("render_resume.py", str(sample), "--style", style, "--out", str(h))
        check(f"{style} HTML 渲染", r.returncode == 0 and h.exists() and h.stat().st_size > 3000, r.stderr[-200:])

    # 2b. 头像位
    print("\n[2b] 一寸头像位")
    html_text = (tmp / "classic.html").read_text(encoding="utf-8") if (tmp / "classic.html").exists() else ""
    check("照片已内嵌为 base64", "data:image/png;base64" in html_text)
    check("渲染出照片容器", 'class="photo' in html_text)
    check("图片 alt 文本可读", "一寸照片" in html_text)
    # 无照片时应输出占位框
    nophoto = tmp / "nophoto.json"
    data = json.loads(sample.read_text(encoding="utf-8"))
    data.get("basic", {}).pop("photo", None)
    nophoto.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    h2 = tmp / "nophoto.html"
    r = run("render_resume.py", str(nophoto), "--style", "classic", "--out", str(h2))
    t2 = h2.read_text(encoding="utf-8") if h2.exists() else ""
    check("无照片时输出占位框", "photo-empty" in t2)
    check("占位框标注尺寸", "25×35mm" in t2)

    # 3. PDF 生成
    print("\n[3] PDF 生成")
    sys.path.insert(0, str(ROOT / "scripts"))
    from html_to_pdf import find_browser

    if not find_browser():
        # 无浏览器内核的环境（如部分 CI runner）跳过 PDF 相关断言
        print("  ! 未找到 Chromium 内核浏览器，跳过 PDF / ATS 测试")
        print("    （HTML 与 DOCX 渲染仍已在上方验证）")
    else:
        for style in ("classic", "sidebar"):
            p = tmp / f"{style}.pdf"
            r = run("html_to_pdf.py", str(tmp / f"{style}.html"), str(p))
            check(f"{style} PDF 生成", r.returncode == 0 and p.exists() and p.stat().st_size > 5000, r.stderr[-200:])

    # 4. DOCX 生成
    print("\n[4] DOCX 生成")
    d = tmp / "out.docx"
    r = run("json_to_docx.py", str(sample), "--out", str(d))
    check("DOCX 生成", r.returncode == 0 and d.exists() and d.stat().st_size > 10000, r.stderr[-200:])

    # 5. ATS 体检
    print("\n[5] ATS 体检")
    if find_browser():
        r = run("ats_check.py", str(tmp / "classic.pdf"))
        check("ATS 体检可运行", r.returncode == 0, r.stdout[-300:])
        check("classic 无阻断问题", "阻断问题" not in r.stdout or "存在 0 个阻断" in r.stdout or "结论：ATS 解析无阻断" in r.stdout)
    else:
        print("  ! 无浏览器内核，跳过 ATS 体检测试")

    # 6. JD 匹配
    print("\n[6] JD 匹配")
    r = run("jd_match.py", str(sample), str(jd), "--out", str(tmp / "jd.json"))
    check("JD 匹配可运行", r.returncode == 0, r.stderr[-200:])
    check("检出关键词", "Excel" in r.stdout)
    check("区分必改与可选", "【可选】" in r.stdout)
    # 关键词质量：必须全部来自受控词库，杜绝跨词边界的伪词
    if (tmp / "jd.json").exists():
        from jd_match import CN_KEYWORDS, TOOL_KEYWORDS
        allowed = set(CN_KEYWORDS) | set(TOOL_KEYWORDS)
        jd_data = json.loads((tmp / "jd.json").read_text(encoding="utf-8"))
        all_kw = jd_data["matched"]["keywords"] + jd_data["missing"]["keywords"]
        junk = [k for k in all_kw if k not in allowed]
        check("关键词均来自受控词库", not junk, f"发现非词库词：{junk}")

    # 7. 批量定制
    print("\n[7] 批量定制")
    r = run("tailor_batch.py", str(sample), "--jd", str(jd), str(jd2), "--out", str(tmp / "batch"))
    check("批量定制可运行", r.returncode == 0, r.stderr[-300:])
    bdir = tmp / "batch"
    if bdir.exists():
        htmls = list(bdir.glob("*.html"))
        check("生成两份 HTML", len(htmls) == 2, f"实际 {len(htmls)}")
        if find_browser():
            pdfs = list(bdir.glob("*.pdf"))
            check("生成两份 PDF", len(pdfs) == 2, f"实际 {len(pdfs)}")
        check("生成两份匹配报告", len(list(bdir.glob("*匹配报告.txt"))) == 2)
        check("岗位名已清洗", not any("（" in p.name for p in bdir.iterdir()))

    # 8. 求职信
    print("\n[8] 求职信与面试准备")
    cl = tmp / "cl.md"
    r = run("cover_letter.py", str(sample), str(jd), "--out", str(cl), "--interview")
    check("求职信生成", r.returncode == 0 and cl.exists(), r.stderr[-200:])
    if cl.exists():
        txt = cl.read_text(encoding="utf-8")
        check("含求职信正文", "敬启者" in txt)
        check("含面试准备清单", "面试准备" in txt)

    # 9. 一键构建
    print("\n[9] 一键构建")
    r = run("build_all.py", str(sample), "--out", str(tmp / "all"), "--style", "auto", "--name", "测试")
    check("一键构建可运行", r.returncode == 0, r.stderr[-300:])
    adir = tmp / "all"
    check("产出 HTML", (adir / "测试.html").exists())
    check("产出 DOCX", (adir / "测试.docx").exists())
    if find_browser():
        check("产出 PDF", (adir / "测试.pdf").exists())

    # 9.5 一页适配
    print("\n[9.5] 一页适配")
    fitdir = tmp / "fit"
    r = run("fit_one_page.py", str(sample), "--style", "elite",
            "--out-dir", str(fitdir), "--name", "适配测试")
    check("一页适配可运行", r.returncode == 0, r.stderr[-300:])
    fpdf = fitdir / "适配测试.pdf"
    if fpdf.exists() and find_browser():
        try:
            import pypdf
            n = len(pypdf.PdfReader(str(fpdf)).pages)
            check("适配后为单页", n == 1, f"实际 {n} 页")
        except Exception as e:
            check("适配后为单页", False, str(e)[:120])
    check("适配产出 HTML", (fitdir / "适配测试.html").exists())

    # 10. 结构完整性
    print("\n[10] 结构完整性")
    for name in ("SKILL.md", "agents/openai.yaml", "README.md", "LICENSE",
                 "requirements.txt"):
        check(f"存在 {name}", (ROOT / name).exists())
    # 官方示例文件必须已清理
    leftovers = [
        p for p in ROOT.rglob("*")
        if p.is_file() and p.name in ("example.py", "api_reference.md", "example_asset.txt")
    ]
    check("无官方示例残留", not leftovers, f"残留：{[p.name for p in leftovers]}")

    # 11. 主题体系：底板 × 配色组合矩阵
    print("\n[11] 主题矩阵（底板 × 配色）")
    sys.path.insert(0, str(ROOT / "scripts"))
    from theme import PALETTES, SURFACES, DENSITY_TIERS, pick_density  # noqa: E402

    bad_combo = []
    for surf in SURFACES:
        for pal in PALETTES:
            h = tmp / f"t-{surf}-{pal}.html"
            r = run("render_resume.py", str(sample), "--style", "elite",
                    "--surface", surf, "--palette", pal, "--out", str(h))
            if r.returncode != 0 or not h.exists():
                bad_combo.append(f"{surf}×{pal}")
                continue
            t = h.read_text(encoding="utf-8")
            # 主题变量必须真的被注入。
            # 注意：深色底板的主色会被提亮（否则色块画出来等于没画），
            # 所以这里检查「变量存在且是合法十六进制」，
            # 而不是「等于调色板原值」—— 后者只在浅色底板上成立。
            m_accent = re.search(r"--accent:\s*(#[0-9A-F]{6})", t)
            m_text = re.search(r"--accent-text:\s*(#[0-9A-F]{6})", t)
            if "--paper-bg:" not in t or not m_accent or not m_text:
                bad_combo.append(f"{surf}×{pal}(变量未注入)")
    check(f"{len(SURFACES)}×{len(PALETTES)} 组合全部渲染",
          not bad_combo, f"失败：{bad_combo[:6]}")

    # 11b. 深色底板必须整套反色，否则文字读不出来
    print("\n[11b] 深色底板反色")
    h = tmp / "dark.html"
    run("render_resume.py", str(sample), "--style", "elite",
        "--surface", "ink", "--out", str(h))
    dark_text = h.read_text(encoding="utf-8") if h.exists() else ""
    s = SURFACES["ink"]
    def lum(hexv):
        return sum(int(hexv[i:i + 2], 16) for i in (1, 3, 5))
    check("深色底板文字亮于纸面", lum(s["ink"]) > lum(s["paper"]),
          f"ink={s['ink']} paper={s['paper']}")
    check("深色底板分割线可见", lum(s["rule"]) > lum(s["paper"]),
          f"rule={s['rule']}")
    check("深色底板已注入主题", "--paper-bg: #12141A" in dark_text)

    # 11b-2. 主色在所有底板 × 配色组合上都必须够用
    print("\n[11b-2] 主色对比度")
    from theme import contrast_ratio, resolve_theme  # noqa: E402
    low_block, low_text = [], []
    for surf in SURFACES:
        for pal in PALETTES:
            th = resolve_theme(surf, pal)
            if contrast_ratio(th.accent, th.paper) < 3.0:
                low_block.append(f"{surf}×{pal} 色块")
            if contrast_ratio(th.accent_text, th.paper) < 4.5:
                low_text.append(f"{surf}×{pal} 文字")
    check("色块主色对比度 ≥ 3:1", not low_block, f"不足：{low_block[:6]}")
    check("文字主色对比度 ≥ 4.5:1", not low_text, f"不足：{low_text[:6]}")
    # 浅色底板的主色不应被改动（改动会破坏已确认的观感）
    changed = [f"{s}×{p}" for s, sf in SURFACES.items() if not sf["dark"]
               for p, pv in PALETTES.items()
               if resolve_theme(s, p).accent != pv["accent"].upper()]
    check("浅色底板主色保持原值", not changed, f"被改动：{changed[:6]}")

    # 11b-3. 深底派生色不能「隐形」
    # 深色纸上 sRGB 混合的感知比白纸弱，10% 的 tint 在黑纸上几乎看不到，
    # 而且会褪成灰色（色相被纸面吃掉）。
    # theme.py 已按「结构色 vs 底色」分档设下限，这里按同一标准断言。
    print("\n[11b-3] 深底派生色可辨识性")
    # (属性, 最低对比度) —— 结构线要求高，含蓄底色要求低
    DERIVED_MIN = {
        "accent_soft": 1.35,     # 斜切色块尾段 / 摘要竖线：要看得见
        "accent_line": 1.60,     # 描边 / 分隔线：结构线，必须清楚
        "chip_border": 1.40,     # 胶囊描边：结构边
        "sec_h_bg": 1.15,        # 分区标题底带：可以含蓄，但不能消失
    }
    weak = []
    for surf, sf in SURFACES.items():
        if not sf["dark"]:
            continue
        for pal in PALETTES:
            th = resolve_theme(surf, pal)
            for attr, floor in DERIVED_MIN.items():
                ratio = contrast_ratio(getattr(th, attr), th.paper)
                if ratio < floor:
                    weak.append(f"{surf}×{pal} {attr}={ratio:.2f}<{floor}")
    check("深底派生色对比度达标", not weak, f"过弱：{weak[:6]}")

    # 11c. 密度档必须真的生效（不被风格 CSS 覆盖）
    print("\n[11c] 密度分档生效性")
    dens_ok = True
    dens_detail = ""
    for tier, *_ in DENSITY_TIERS:
        h = tmp / f"d-{tier}.html"
        run("render_resume.py", str(sample), "--style", "elite",
            "--density", tier, "--out", str(h))
        if not h.exists():
            dens_ok = False
            dens_detail = f"{tier} 未生成"
            break
        t = h.read_text(encoding="utf-8")
        if f"dens-{tier}" not in t:
            dens_ok = False
            dens_detail = f"{tier} 未写入 body class"
            break
        # 关键断言：风格 CSS 不得直接写死 --lh 等最终值，
        # 否则同优先级的 dens-* 会被覆盖，密度分档形同虚设
        style_css = re.search(r"body\.tpl-elite\s*\{([^}]*)\}", t)
        if style_css:
            body = style_css.group(1)
            for m in re.finditer(r"--(lh|gap-section|gap-entry|pad-y)\s*:\s*([^;}]+)", body):
                if "var(" not in m.group(2):
                    dens_ok = False
                    dens_detail = f"风格 CSS 写死了 --{m.group(1)}"
    check("5 档密度全部写入且未被风格覆盖", dens_ok, dens_detail)

    # 11d. 自动选档：内容多的走紧档，内容少的走松档
    print("\n[11d] 自动选档策略")
    data_s = json.loads(sample.read_text(encoding="utf-8"))
    rich = json.loads(json.dumps(data_s))
    rich["sections"] = (rich["sections"] * 3)[:9]
    for s in rich["sections"]:
        if s.get("items"):
            for it in s["items"]:
                it["bullets"] = (it.get("bullets") or ["占位"]) * 3
    d_sparse = pick_density(data_s)
    d_rich = pick_density(rich)
    order = [t[0] for t in DENSITY_TIERS]
    check("稀疏内容选更宽松档",
          order.index(d_sparse) <= order.index(d_rich),
          f"稀疏={d_sparse} 密集={d_rich}")
    check("密集内容不选最松档", d_rich in ("compact", "dense", "tight"),
          f"密集={d_rich}")

    # 11e. 技能区结构：分组标签独占一行，胶囊整行铺开
    print("\n[11e] 技能区排版")
    h = tmp / "skills.html"
    run("render_resume.py", str(sample), "--style", "elite", "--out", str(h))
    sk = h.read_text(encoding="utf-8") if h.exists() else ""
    check("技能组为块级（标签独占一行）", ".skills .g" in sk and "display: contents" not in sk,
          "若用 display:contents 网格布局，胶囊列会被标签挤窄")
    check("分组标签独占一行", "display: block" in sk)

    # 11f. 量化识别：中文量词要认，年份/日期不能当成业绩数字
    print("\n[11f] 量化结果识别")
    from lint_resume import has_quant, is_non_quantifiable
    quant_yes = [
        "设计问卷回收312份有效样本，拆解目标人群价格敏感度",
        "产出19页调研报告，核心结论被后续项目直接引用",
        "用 Excel 透视表对比4个竞品的定价与卖点",
        "活动期单日最高订单37单，GMV 约2400元",
        "带5人团队做项目负责人，负责商业模式设计",
        "转化率提升20%，GMV 增长 1.5 万",
    ]
    quant_no = [
        "撰写商业计划书并主导现场答辩，获省级奖项",
        "输出目标用户画像与竞品对标分析，落地选品定价方案",
        "2025.03 - 2025.08",
        "2028 年毕业",
    ]
    bad_yes = [t for t in quant_yes if not has_quant(t)]
    check("中文量词被识别为量化", not bad_yes, f"漏判：{bad_yes}")
    bad_no = [t for t in quant_no if has_quant(t)]
    check("年份与日期不算业绩量化", not bad_no, f"误判：{bad_no}")
    check("结果性荣誉不强制量化",
          is_non_quantifiable("撰写商业计划书并主导现场答辩，获省级奖项"),
          "奖项本身即结果，不该再逼用户补数字")

    # 11g. 外观参数的真实生效链路
    # 文档承诺 meta.style 与 placement 生效，这里断言它们真的生效，
    # 防止「文档写了但代码没读」这类静默失配。
    print("\n[11g] 外观参数生效链路")
    from render_resume import render_html

    d0 = json.loads(sample.read_text(encoding="utf-8"))
    meta_style = (d0.get("meta") or {}).get("style") or ""
    h_meta = render_html(d0, "__invalid__", base_dir=ROOT / "assets")
    got = re.search(r'<body class="tpl-(\w+)', h_meta)
    check("meta.style 生效",
          bool(got) and got.group(1) == meta_style,
          f"meta.style={meta_style!r} 实际 tpl-{got.group(1) if got else '?'}")

    d_bad = json.loads(json.dumps(d0))
    d_bad["meta"]["style"] = "ats-classic"   # 早期遗留的无效键
    try:
        h_bad = render_html(d_bad, "__invalid__", base_dir=ROOT / "assets")
        ok_bad = bool(re.search(r'<body class="tpl-\w+', h_bad))
    except Exception as e:
        ok_bad = False
    check("无效 meta.style 不崩溃（回落到默认）", ok_bad)

    # placement：双栏风格下强制分区归属
    d_pl = json.loads(json.dumps(d0))
    edu_sec = next((s for s in d_pl.get("sections", [])
                    if s.get("type") == "education"), None)
    if edu_sec is None:
        check("placement=side 生效", False, "示例数据缺少 education 分区")
    else:
        edu_sec["placement"] = "side"
        edu_key = edu_sec.get("org") or edu_sec.get("title") or edu_sec.get("id") or ""
        h_pl = render_html(d_pl, "sidebar", base_dir=ROOT / "assets")
        body = h_pl[h_pl.index("<body"):]
        s_at = body.index('<div class="side">')
        m_at = body.index('<div class="main">', s_at)
        side_txt, main_txt = body[s_at:m_at], body[m_at:]
        check("placement=side 生效",
              bool(edu_key) and edu_key in side_txt and edu_key not in main_txt,
              f"{edu_key!r} 应出现在侧栏")

        h_single = render_html(d_pl, "elite", base_dir=ROOT / "assets")
        check("单栏风格忽略 placement（不重复渲染）",
              h_single.count(edu_key) == 1, f"出现 {h_single.count(edu_key)} 次")
    check("普通描述仍会被提示补数字",
          not is_non_quantifiable("输出目标用户画像与竞品对标分析，落地选品定价方案"))

    print("\n" + "=" * 60)
    passed = sum(1 for _, c, _ in results if c)
    print(f"通过 {passed}/{len(results)}")
    if passed != len(results):
        print("\n失败项：")
        for n, c, d in results:
            if not c:
                print(f"  ✗ {n}: {d}")
    print("=" * 60)

    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
