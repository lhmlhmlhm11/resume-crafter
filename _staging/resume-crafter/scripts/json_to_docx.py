"""简历 JSON → DOCX（Word 可编辑版）。

用法：
    python json_to_docx.py resume.json --out 简历.docx

设计要点：
- 用 Word 原生样式与表格布局，方便 HR/用户在 Word 里继续微调。
- 正文全部为可编辑文本，标题层级使用 Heading 样式，ATS 可解析。
- 左右布局用无边框表格实现（Word 里最稳的双栏写法）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor, Cm

import photo as photo_mod

import _console  # noqa: F401  (UTF-8 控制台兜底)

ACCENT = "1F3A5F"
INK = "1A1A1A"
MUTE = "6E6E6E"

CN_FONT = "Microsoft YaHei"
EN_FONT = "Calibri"


def set_font(run, size=10.5, bold=False, color=INK, font=None):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = RGBColor.from_string(str(color).lstrip("#").upper())
    run.font.name = font or EN_FONT
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:ascii"), font or EN_FONT)
    rfonts.set(qn("w:hAnsi"), font or EN_FONT)
    rfonts.set(qn("w:eastAsia"), CN_FONT)


def set_para_border(p, color=ACCENT, size=8, position="bottom", space=1):
    pPr = p._p.get_or_add_pPr()
    borders = pPr.find(qn("w:pBdr"))
    if borders is None:
        borders = OxmlElement("w:pBdr")
        pPr.append(borders)
    el = OxmlElement(f"w:{position}")
    el.set(qn("w:val"), "single")
    el.set(qn("w:sz"), str(size))
    el.set(qn("w:space"), str(space))
    el.set(qn("w:color"), color)
    borders.append(el)


def add_run(p, text, **kw):
    r = p.add_run(text)
    set_font(r, **kw)
    return r


def tight(p, before=0, after=0, line=None):
    pf = p.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    if line:
        pf.line_spacing = line
    return p


def add_section_head(doc, title, accent=ACCENT):
    p = doc.add_paragraph()
    tight(p, before=10, after=3)
    add_run(p, title, size=12, bold=True, color=accent)
    set_para_border(p, color="D6DCE3", size=6, position="bottom", space=2)
    return p


def add_entry(doc, item, accent=ACCENT):
    org = item.get("org", "")
    role = item.get("role", "")
    start, end = item.get("start", ""), item.get("end", "")
    date = " — ".join(x for x in (start, end) if x)
    if start and not end:
        date = f"{start} 至今"

    p = doc.add_paragraph()
    tight(p, before=4, after=0, line=1.15)
    pf = p.paragraph_format
    pf.tab_stops.add_tab_stop(Cm(17.6), WD_TAB_ALIGNMENT.RIGHT)
    main = role if role else org
    if role and org:
        main = f"{role}  |  {org}"
    add_run(p, main, size=10.5, bold=True, color=INK)
    if date:
        add_run(p, f"\t{date}", size=9.5, color=MUTE)

    if item.get("note"):
        sp = doc.add_paragraph()
        tight(sp, before=0, after=0)
        add_run(sp, item["note"], size=9.5, color=MUTE)

    for b in item.get("bullets") or []:
        bp = doc.add_paragraph(style="List Bullet")
        tight(bp, before=1, after=0, line=1.35)
        bp.paragraph_format.left_indent = Cm(0.6)
        add_run(bp, b, size=10.5, color=INK)


def add_photo(doc, data: dict, base_dir: Path | None) -> bool:
    """在 Word 页眉区插入一寸证件照（无照片或非本地文件则返回 False）。"""
    basic = data.get("basic", {})
    meta = data.get("meta", {})
    src = basic.get("photo") or meta.get("photo") or ""
    if not src:
        return False

    info = photo_mod.read_photo(src, base_dir)
    if not info or info["kind"] != "data_uri":
        return False

    size = basic.get("photo_size", "1in")
    info = photo_mod.configure(info, size, basic.get("photo_shape", "rect"))
    w_mm, h_mm = info["w_mm"], info["h_mm"]

    # 用两栏表格把「姓名信息」与「照片」并排 —— Word 中最稳的双栏写法
    table = doc.add_table(rows=1, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _set_table_borders(table, none=True)
    _set_col_width(table, 0, 15.6)
    _set_col_width(table, 1, 3.6)

    left = table.cell(0, 0)
    right = table.cell(0, 1)

    # 照片插入到右侧单元格
    rp = right.paragraphs[0]
    rp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    try:
        run = rp.add_run()
        run.add_picture(
            _write_temp_image(info["value"]),
            width=Cm(w_mm / 10),
            height=Cm(h_mm / 10),
        )
    except Exception:
        return False

    # 左侧：姓名 / 身份 / 联系方式
    lp = left.paragraphs[0]
    tight(lp, before=0, after=2)
    add_run(lp, basic.get("name", ""), size=20, bold=True, color=INK)
    if basic.get("title"):
        tp = left.add_paragraph()
        tight(tp, before=0, after=2)
        add_run(tp, basic["title"], size=10.5, color=ACCENT)
    contact = [c.get("text", "") for c in basic.get("contact", []) if c.get("text")]
    if contact:
        cp = left.add_paragraph()
        tight(cp, before=0, after=0)
        add_run(cp, "  ·  ".join(contact), size=9.5, color="404040")
    return True


def _write_temp_image(data_uri: str) -> str:
    """把 base64 data URI 落成临时图片文件，供 Word 插入。"""
    import base64
    import tempfile

    payload = data_uri.split(",", 1)[1] if "," in data_uri else data_uri
    ext = "jpg" if data_uri.startswith("data:image/jpeg") else "png"
    fd, path = tempfile.mkstemp(suffix=f".{ext}")
    with os.fdopen(fd, "wb") as f:
        f.write(base64.b64decode(payload))
    return path


def _set_table_borders(table, none=False):
    tblPr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "none" if none else "single")
        el.set(qn("w:sz"), "0" if none else "4")
        el.set(qn("w:color"), "auto")
        borders.append(el)
    tblPr.append(borders)


def _set_col_width(table, idx, width_cm):
    for cell in table.columns[idx].cells:
        cell.width = Cm(width_cm)


def add_skills(doc, section, accent=ACCENT):
    for g in section.get("groups") or []:
        p = doc.add_paragraph()
        tight(p, before=2, after=0, line=1.35)
        if g.get("label"):
            add_run(p, f"{g['label']}：", size=10.5, bold=True, color=INK)
        add_run(p, "、".join(g.get("items") or []), size=10.5, color="404040")


def add_list(doc, section, accent=ACCENT):
    for it in section.get("items") or []:
        if isinstance(it, str):
            text, date = it, ""
        else:
            text, date = it.get("text", ""), it.get("date", "")
        p = doc.add_paragraph(style="List Bullet")
        tight(p, before=1, after=0, line=1.35)
        p.paragraph_format.left_indent = Cm(0.6)
        add_run(p, text, size=10.5, color=INK)
        if date:
            pf = p.paragraph_format
            pf.tab_stops.add_tab_stop(Cm(17.6), WD_TAB_ALIGNMENT.RIGHT)
            add_run(p, f"\t{date}", size=9.5, color=MUTE)


def build(data: dict, out: Path, accent=ACCENT, base_dir: Path | None = None) -> Path:
    doc = Document()
    sec = doc.sections[0]
    sec.page_width = Cm(21.0)
    sec.page_height = Cm(29.7)
    sec.top_margin = Cm(1.4)
    sec.bottom_margin = Cm(1.4)
    sec.left_margin = Cm(1.6)
    sec.right_margin = Cm(1.6)

    style = doc.styles["Normal"]
    style.font.size = Pt(10.5)
    style.font.name = EN_FONT
    style.element.rPr.rFonts.set(qn("w:eastAsia"), CN_FONT)

    basic = data.get("basic", {})
    meta = data.get("meta", {})
    # 主色：显式 accent > JSON 里的 palette > 默认靛蓝
    accent = meta.get("accent") or ""
    if not accent:
        try:
            from theme import PALETTES
            accent = PALETTES.get(meta.get("palette") or "indigo", {}).get("accent", ACCENT)
        except Exception:
            accent = ACCENT
    accent = str(accent).lstrip("#").upper()

    # 页眉：有照片走「左信息 + 右照片」表格；无照片走居中文本
    has_photo = add_photo(doc, data, base_dir)

    if not has_photo:
        p = doc.add_paragraph()
        tight(p, before=0, after=2)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        add_run(p, basic.get("name", ""), size=20, bold=True, color=INK)

        if basic.get("title"):
            p = doc.add_paragraph()
            tight(p, before=0, after=2)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            add_run(p, basic["title"], size=10.5, color=accent)

        contact = [c.get("text", "") for c in basic.get("contact", []) if c.get("text")]
        if contact:
            p = doc.add_paragraph()
            tight(p, before=0, after=6)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            add_run(p, "  ·  ".join(contact), size=9.5, color="404040")

    if data.get("summary"):
        p = doc.add_paragraph()
        tight(p, before=2, after=2, line=1.4)
        add_run(p, data["summary"], size=10.5, color="404040")

    for section in data.get("sections", []):
        stype = section.get("type", "entries")
        add_section_head(doc, section.get("title", ""), accent)
        if stype == "skills":
            add_skills(doc, section, accent)
        elif stype == "list":
            add_list(doc, section, accent)
        elif stype == "text":
            p = doc.add_paragraph()
            tight(p, before=0, after=0)
            add_run(p, section.get("text", ""), size=10.5, color="404040")
        else:
            for item in section.get("items") or []:
                add_entry(doc, item, accent)

    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="简历 JSON 转 DOCX")
    ap.add_argument("data")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    out = build(data, Path(args.out), base_dir=Path(args.data).resolve().parent)
    print(f"已生成 DOCX: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
