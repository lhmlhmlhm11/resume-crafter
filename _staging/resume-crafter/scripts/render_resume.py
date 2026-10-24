"""resume-crafter 核心渲染器：把结构化简历数据渲染成 A4 HTML。

用法：
    python render_resume.py <data.json> --style classic --out resume.html

设计要点：
- 数据驱动：所有内容来自 JSON，样式由 CSS 变量控制，HTML 与 PDF/DOCX 共用同一份数据。
- 纯文本优先：所有信息都是可选中的真实文本，不使用图标字体、图片或表格排版，保证 ATS 可解析。
- 样式与内容分离：改样式不动数据，改数据不动样式。
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import photo as photo_mod  # noqa: E402
from theme import PALETTES, SURFACES, pick_density, resolve_theme  # noqa: E402

import _console  # noqa: F401  (UTF-8 控制台兜底)

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "assets" / "templates"

STYLES = {
    "classic": {
        "label": "经典单栏（ATS 首选）",
        "css": "style-classic.css",
        "ats": True,
        "palette": "indigo",
        "desc": "单栏自上而下、居中页眉、左侧色条分区标题。适配 90% 场景，投递大厂/外企首选。",
    },
    "modern": {
        "label": "现代单栏",
        "css": "style-modern.css",
        "ats": True,
        "palette": "teal",
        "desc": "左对齐页眉、圆角短色条。适合互联网、产品、运营岗，兼顾 ATS 与现代感。",
    },
    "sidebar": {
        "label": "双栏侧边栏",
        "css": "style-sidebar.css",
        "ats": False,
        "palette": "graphite",
        "desc": "左侧面板放技能与联系方式，右侧主栏放经历。适合设计师、产品经理，仅用于直接给人看的场景。",
    },
    "academic": {
        "label": "学术严谨",
        "css": "style-academic.css",
        "ats": True,
        "palette": "graphite",
        "desc": "衬线字体、黑白克制、居中对称分隔线。适合教师、科研、读博申请与外企学术 CV。",
    },
    "creative": {
        "label": "创意顶栏侧栏",
        "css": "style-creative.css",
        "ats": False,
        "palette": "clay",
        "desc": "顶部整幅色带 + 左侧浅底面板。视觉冲击力强，适合设计、品牌、内容创作岗。",
    },
    "elite": {
        "label": "精英几何（几何色块）",
        "css": "style-elite.css",
        "ats": True,
        "palette": "indigo",
        "desc": "斜切几何色块 + 一寸照片 + 浅底分区带。视觉层次强的单栏方案，适合需要展示个人形象的岗位。",
    },
    "neon": {
        "label": "霓虹卡片（深色渐变）",
        "css": "style-neon.css",
        "ats": True,
        "palette": "plum",
        "desc": "顶部整幅渐变色带 + 反白姓名 + 发光照片 + 色块标签式分区标题。参考付费模板「极客」的视觉语言。",
    },
    "soft": {
        "label": "柔光双栏（大圆角）",
        "css": "style-soft.css",
        "ats": False,
        "palette": "teal",
        "desc": "顶部圆角几何块 + 左右双卡片布局。参考付费模板「醒春」，轻盈不厚重。",
    },
    "geo": {
        "label": "几何圆角（分区卡片）",
        "css": "style-geo.css",
        "ats": True,
        "palette": "amber",
        "desc": "每个分区做成大圆角浅色卡片，标题为实心彩色胶囊。参考付费模板「浅熏」，留白充足。",
    },
}

# 侧边栏风格中归入侧栏的分区类型
SIDEBAR_TYPES = {"skills", "certificates", "languages", "interests", "contact_extra"}
# 侧边栏风格中归入主栏的分区类型
MAIN_TYPES = {"experience", "project", "education", "awards", "publications"}
# 采用双栏版式的风格
TWO_COLUMN_STYLES = {"sidebar", "creative", "soft"}

CONTACT_ICON = {
    "phone": "☎",
    "email": "@",
    "location": "⌖",
    "link": "🔗",
    "wechat": "◈",
    "other": "·",
}


def esc(text) -> str:
    return html.escape(str(text if text is not None else ""))


def render_contact(items, sep="&nbsp;·&nbsp;") -> str:
    """把联系方式渲染成一行纯文本。不用图标字体，避免 ATS 丢失信息。"""
    parts = []
    for item in items or []:
        text = (item.get("text") or "").strip()
        if not text:
            continue
        parts.append(f'<span class="ct">{esc(text)}</span>')
    return f'<span class="sep">{sep}</span>'.join(parts)


def render_item(item, style) -> str:
    """渲染单条经历/项目/教育条目。"""
    org = esc(item.get("org", ""))
    role = esc(item.get("role", ""))
    loc = esc(item.get("location", ""))
    start = esc(item.get("start", ""))
    end = esc(item.get("end", ""))
    bullets = item.get("bullets") or []

    date = " — ".join(x for x in (start, end) if x)
    if start and not end:
        date = f"{start} 至今"

    # 标题：经历类以「职位」在前，组织在后；教育类以「学校」在前
    if item.get("title_first", True):
        main = role
        if org:
            main += f' <span class="org">{esc(org)}</span>' if role else esc(org)
    else:
        main = org
        if role:
            main += f' <span class="org">{esc(role)}</span>' if org else esc(role)

    sub_bits = []
    if loc and not role and not org:
        sub_bits.append(loc)
    if item.get("note"):
        sub_bits.append(esc(item["note"]))
    sub = ""
    if sub_bits:
        sub = f'<div class="entry-sub">{"<span class=dot>·</span>".join(sub_bits)}</div>'

    bullet_html = ""
    if bullets:
        lis = "".join(f"<li>{esc(b)}</li>" for b in bullets if b)
        if lis:
            bullet_html = f'<ul class="b">{lis}</ul>'

    date_html = f'<div class="date">{esc(date)}</div>' if date else ""
    return (
        f'<div class="entry">'
        f'<div class="entry-h"><div class="main">{main}</div>'
        f'<div class="spacer"></div>{date_html}</div>{sub}{bullet_html}</div>'
    )


def render_skills(section, style) -> str:
    """技能区：胶囊标签 + 分组标签，内容全是真实文本（ATS 可解析）。"""
    groups = section.get("groups") or []
    blocks = []
    for g in groups:
        label = esc(g.get("label", ""))
        items = [i for i in (g.get("items") or []) if i]
        if not items:
            continue
        chips = "".join(f'<span class="chip">{esc(i)}</span>' for i in items)
        lab = f'<span class="gl">{label}</span>' if label else ""
        blocks.append(f'<div class="g">{lab}<div class="chips">{chips}</div></div>')
    # 技能条目多时启用紧凑模式，压缩胶囊垂直占位以挤进一页
    total = sum(len(g.get("items") or []) for g in groups)
    compact = " compact" if total > 9 else ""
    return '<div class="skills' + compact + '">' + "".join(blocks) + "</div>"


def render_photo(data: dict, style: str, base_dir: Path | None) -> str:
    """渲染一寸头像位。

    - 有照片：内嵌 base64，无头渲染与单文件分享都不丢图
    - 无照片：输出带虚线占位的空位框，提示尺寸，方便用户替换
    """
    basic = data.get("basic", {})
    meta = data.get("meta", {})
    src = basic.get("photo") or meta.get("photo") or ""
    size = basic.get("photo_size", "1in")
    shape = basic.get("photo_shape", "rect")

    info = photo_mod.read_photo(src, base_dir) if src else None
    if info:
        info = photo_mod.configure(info, size, shape)
        w_mm, h_mm = info["w_mm"], info["h_mm"]
        shape = info["shape"]
        img = f'<img src="{info["value"]}" alt="{esc(basic.get("name", ""))} 一寸照片">'
        return (
            f'<div class="photo photo-{shape}" '
            f'style="--pw:{w_mm}mm;--ph:{h_mm}mm">{img}</div>'
        )

    # 占位框：明确标注标准尺寸，降低用户裁剪成本
    w_mm, h_mm = photo_mod.PHOTO_SIZES.get(size, photo_mod.PHOTO_SIZES["1in"])
    if shape in photo_mod.PHOTO_SHAPES and photo_mod.PHOTO_SHAPES[shape][1]:
        w_mm = h_mm = max(w_mm, h_mm)
    return (
        f'<div class="photo photo-empty photo-{shape}" '
        f'style="--pw:{w_mm}mm;--ph:{h_mm}mm">'
        f'<div class="photo-tip"><span class="pt-ico"></span>'
        f'<span class="pt-txt">一寸照片<br>{int(w_mm)}×{int(h_mm)}mm</span></div>'
        f"</div>"
    )


def render_list(section, style) -> str:
    items = section.get("items") or []
    rows = []
    for it in items:
        if isinstance(it, str):
            rows.append(f"<li><span>{esc(it)}</span></li>")
        else:
            text = esc(it.get("text", ""))
            d = esc(it.get("date", ""))
            date_html = f'<span class="spacer"></span><span class="d">{d}</span>' if d else ""
            rows.append(f"<li><span>{text}</span>{date_html}</li>")
    if not rows:
        return ""
    return f'<ul class="p">{"".join(rows)}</ul>'


def render_section(section, style) -> str:
    stype = section.get("type", "entries")
    title = esc(section.get("title", ""))
    sid = esc(section.get("id", ""))

    if stype == "skills":
        body = render_skills(section, style)
    elif stype == "list":
        body = render_list(section, style)
    elif stype == "text":
        body = f'<div class="summary">{esc(section.get("text", ""))}</div>'
    else:
        items = section.get("items") or []
        body = "".join(render_item(i, style) for i in items)

    if not body.strip():
        return ""

    return (
        f'<section class="sec" id="{sid}">'
        f'<div class="sec-h"><span class="bar"></span>'
        f'<span class="t">{title}</span><span class="rule"></span></div>'
        f"{body}</section>"
    )


def render_html(
    data: dict,
    style: str,
    base_dir: Path | None = None,
    surface: str | None = None,
    palette: str | None = None,
    density: str | None = None,
) -> str:
    # 风格优先级：显式传入 > JSON meta.style > classic
    # meta.style 里的无效键（例如早期遗留的 "ats-classic"）会被忽略并回落，
    # 而不是让整个构建直接崩掉。
    if style not in STYLES:
        meta_style = (data.get("meta") or {}).get("style") or ""
        style = meta_style if meta_style in STYLES else "classic"

    meta = data.get("meta", {})
    basic = data.get("basic", {})
    sections = data.get("sections", [])

    # ---- 主题：底板 × 配色 ----
    # 优先级：命令行显式指定 > JSON meta > 风格默认。
    #
    # 关于 meta.accent：它是「手工指定的主色」，会覆盖配色默认值。
    # 但只要外部显式指定了配色（命令行或 JSON meta.palette），
    # 就应当以该配色为准 —— 否则「一条数据复用多套配色」会因为
    # JSON 里遗留的旧 accent 而全部渲染成同一个颜色。
    explicit_theme = (
        palette is not None
        or surface is not None
        or meta.get("palette") is not None
        or meta.get("surface") is not None
    )
    surface = surface or meta.get("surface") or "white"
    palette = palette or meta.get("palette") or STYLES[style].get("palette", "indigo")
    accent = meta.get("accent") or ""
    theme = resolve_theme(surface, palette, None if explicit_theme else (accent or None))

    # ---- 密度：按内容体量自动选档，也可手动锁定 ----
    density = density or meta.get("density") or pick_density(data)

    contact_html = render_contact(basic.get("contact", []))
    title_html = f'<div class="title">{esc(basic.get("title", ""))}</div>' if basic.get("title") else ""
    summary = data.get("summary", "")
    summary_html = f'<div class="summary">{esc(summary)}</div>' if summary else ""

    is_side = style in TWO_COLUMN_STYLES
    side_sections, main_sections = [], []
    if is_side:
        for s in sections:
            stype = s.get("type", "entries")
            # placement 允许强制指定归属（"side" / "main"），
            # 缺省按分区类型自动分配。
            placement = (s.get("placement") or "").strip().lower()
            if placement == "side":
                side_sections.append(s)
            elif placement == "main":
                main_sections.append(s)
            elif stype in SIDEBAR_TYPES:
                side_sections.append(s)
            else:
                main_sections.append(s)
    else:
        main_sections = sections

    def blocks(items):
        out = []
        for i, s in enumerate(items):
            html_block = render_section(s, style)
            if not html_block:
                continue
            if i == 0:
                html_block = html_block.replace('class="sec"', 'class="sec first"', 1)
            out.append(html_block)
        return "\n".join(out)

    main_html = blocks(main_sections)
    side_html = blocks(side_sections) if is_side else ""

    # ---- 头像 ----
    # 双栏风格：照片放进左侧面板顶部（贴近姓名，视觉聚合）
    # 单栏风格：照片放在页眉右侧
    photo_html = render_photo(data, style, base_dir)
    has_photo = bool(photo_html)
    body_class = f"tpl-{style} dens-{density}" + (" has-photo" if has_photo else "")

    base_css = (TEMPLATE_DIR / "base.css").read_text(encoding="utf-8")
    style_css = (TEMPLATE_DIR / STYLES[style]["css"]).read_text(encoding="utf-8")

    if is_side:
        # 页眉：姓名与联系方式通栏，照片移入侧栏
        head_inner = (
            f'<div class="hd-main">'
            f'<div class="name">{esc(basic.get("name", ""))}</div>'
            f"{title_html}"
            f'<div class="contact">{contact_html}</div>'
            f"</div>"
        )
        side_photo = (
            f'<div class="side-photo">{photo_html}</div>' if has_photo else ""
        )
        body_layout = (
            '<div class="sheet">'
            f'<div class="hd">{head_inner}<div class="rule"></div></div>'
            f'<div class="side">{side_photo}{side_html}</div>'
            f'<div class="main">{summary_html}{main_html}</div>'
            "</div>"
        )
    else:
        head_inner = (
            f'<div class="hd-main">'
            f'<div class="name">{esc(basic.get("name", ""))}</div>'
            f"{title_html}"
            f'<div class="contact">{contact_html}</div>'
            f"</div>"
            f"{photo_html}"
        )
        body_layout = (
            f'<div class="hd">{head_inner}<div class="rule thin"></div></div>'
            f'<div class="summary-block">{summary_html}</div>'
            f"{main_html}"
        )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{esc(basic.get("name", "简历"))} - 简历</title>
<style>
{base_css}
{style_css}
{theme.to_css()}
</style>
</head>
<body class="{body_class}">
{body_layout}
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="渲染简历 HTML")
    ap.add_argument("data", nargs="?", help="简历 JSON 数据文件")
    ap.add_argument("--style", default="classic", choices=list(STYLES), help="排版风格")
    ap.add_argument("--surface", choices=list(SURFACES), help="纸面底板（默认 white）")
    ap.add_argument("--palette", choices=list(PALETTES), help="主色配色（默认 indigo）")
    ap.add_argument("--density", choices=["airy", "normal", "compact", "dense", "tight"],
                    help="排版密度，默认按内容体量自动选择")
    ap.add_argument("--out", help="输出 HTML 路径")
    ap.add_argument("--list-styles", action="store_true", help="列出所有风格并退出")
    ap.add_argument("--list-themes", action="store_true", help="列出所有底板与配色并退出")
    args = ap.parse_args()

    if args.list_styles:
        print("排版风格（版式）")
        print("=" * 66)
        for key, meta in STYLES.items():
            ats = "ATS友好" if meta["ats"] else "⚠ 非ATS优先"
            print(f"  {key:10s} [{ats:12s}] {meta['label']}\n              {meta['desc']}")
        print()
        print("提示：风格只决定版式；纸面底板用 --surface，主色用 --palette。")
        return 0

    if args.list_themes:
        print("纸面底板（--surface）")
        print("=" * 66)
        for key, meta in SURFACES.items():
            print(f"  {key:10s} {meta['label']}\n              {meta['desc']}")
        print()
        print("主色配色（--palette）")
        print("=" * 66)
        for key, meta in PALETTES.items():
            print(f"  {key:10s} {meta['label']}  {meta['accent']}\n              {meta['desc']}")
        return 0

    if not args.data or not args.out:
        ap.error("需要提供 data 与 --out 参数（--list-styles / --list-themes 可单独使用）")

    data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # 照片相对路径以「简历 JSON 所在目录」为基准解析
    base_dir = Path(args.data).resolve().parent
    out.write_text(
        render_html(data, args.style, base_dir, args.surface, args.palette, args.density),
        encoding="utf-8",
    )
    print(f"已生成 HTML: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
