"""批量定制：一份简历底稿 → 针对多个 JD 生成各自的定制版简历。

用法：
    python tailor_batch.py resume.json --jd jd1.txt jd2.txt ... --out ./out
    python tailor_batch.py resume.json --jd jd1.txt --out ./out --style classic --formats pdf docx

原理：
- 以一份「底稿简历」为唯一事实来源，逐个 JD 做关键词匹配。
- 每个 JD 产出一份独立的 JSON（已做分区重排 + 关键词补强标注）+ 完整报告。
- 绝不修改用户的真实经历内容；所有补强都以「建议」形式记录在报告中，
  由使用者确认后再手工落实到 JSON。

这解决了应届生最真实的痛点：投 20 家公司要改 20 版简历。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jd_match import match, term_in  # noqa: E402
from render_resume import STYLES, render_html  # noqa: E402
from html_to_pdf import convert  # noqa: E402
from json_to_docx import build as build_docx  # noqa: E402
from theme import PALETTES, SURFACES  # noqa: E402

import _console  # noqa: F401  (UTF-8 控制台兜底)

# 分区在简历中的理想顺序（应届生场景：教育与实习优先）
SECTION_PRIORITY = [
    "教育经历", "教育背景", "学习经历",
    "实习经历", "工作经历", "工作经验",
    "项目经历", "项目经验", "科研经历",
    "专业技能", "技能", "语言能力", "证书",
    "荣誉奖项", "获奖情况", "获奖", "社团经历", "志愿经历",
]


def section_rank(title: str) -> int:
    for i, t in enumerate(SECTION_PRIORITY):
        if title == t:
            return i
    return len(SECTION_PRIORITY)


def guess_role(jd_text: str) -> str:
    """从 JD 猜岗位名称，用于文件命名与求职信抬头。"""
    # 这些是 JD 的结构性标签行，不是岗位名，必须排除
    LABEL_RE = re.compile(
        r"^(职位要求|岗位职责|任职要求|职位描述|岗位描述|工作内容|加分项|"
        r"任职资格|岗位要求|工作职责|职位名称|岗位名称|职位类别|招聘部门|"
        r"团队介绍|职位描述|投递要求|公司简介|职位ID|职位\s*ID|Requirements|"
        r"Responsibilities|Job\s*Description)[:：]?"
    )
    patterns = [
        r"^\s*([一-龥A-Za-z0-9/（）()·\-]{2,20}(?:实习生|工程师|专员|经理|主管|顾问|助理|设计师|分析师|运营|BD|HR))\s*$",
        r"^\s*([一-龥A-Za-z0-9/（）()·\-]{2,20}(?:实习生|工程师|专员|经理|主管|顾问|助理|设计师|分析师|运营岗|运营|BD|HR))\s*(?:[-—|｜].*)?$",
        r"岗位名称[：:]\s*(.+)",
        r"职位名称[：:]\s*(.+)",
    ]
    lines = [l.strip() for l in jd_text.splitlines()]
    for line in lines:
        if not line or LABEL_RE.match(line):
            continue
        for p in patterns:
            m = re.match(p, line)
            if m:
                role = clean_role(m.group(1))
                if role and not LABEL_RE.match(role):
                    return role
    # 退化：取第一行非标签、非空且长度合适的文本
    for line in lines:
        if line and len(line) <= 24 and not LABEL_RE.match(line):
            return clean_role(line)
    return "岗位"


def clean_role(role: str) -> str:
    """剥离岗位名中的招聘性质后缀（如「（校园招聘）」「（社招）」）。"""
    role = re.sub(r"[（(][^）)]*[）)]", "", role)
    role = re.sub(r"^(校园招聘|社会招聘|实习招聘|急招|诚聘)\s*", "", role)
    return role.strip() or "岗位"


def safe_name(s: str) -> str:
    """清理文件名中的非法字符与易乱码的全角括号。"""
    s = re.sub(r"[\\/:*?\"<>|\s]+", "", s)
    # 全角括号在部分环境下编码不稳，统一转半角
    s = s.replace("（", "(").replace("）", ")")
    s = s.replace("【", "").replace("】", "")
    return s[:30].strip() or "岗位"


def tailor(data: dict, jd_text: str) -> tuple[dict, dict]:
    """生成针对某个 JD 的定制版简历数据与报告。"""
    report = match(data, jd_text)

    tailored = json.loads(json.dumps(data, ensure_ascii=False))

    # 1) 分区重排：按「应届生优先序」排列
    tailored["sections"] = sorted(
        tailored.get("sections", []),
        key=lambda s: section_rank(s.get("title", "")),
    )

    # 2) 分区标题规范化为 ATS 标准词
    alias = {
        "学习经历": "教育经历", "教育背景": "教育经历", "学历": "教育经历",
        "工作经验": "工作经历", "实习与工作经历": "实习经历",
        "项目经验": "项目经历", "科研经历": "项目经历",
        "技能": "专业技能", "技能特长": "专业技能",
        "获奖": "荣誉奖项", "获奖情况": "荣誉奖项", "荣誉": "荣誉奖项",
        "证书": "证书", "资格证书": "证书",
        "语言": "语言能力", "社团经历": "社团经历", "志愿经历": "志愿经历",
    }
    for s in tailored.get("sections", []):
        t = s.get("title", "")
        if t in alias:
            s["title"] = alias[t]

    # 3) 个人简介重写：把 JD 关键词自然嵌入（只嵌入简历中已出现过的词）
    matched_kw = [k for k in report["matched"]["keywords"] if k]
    if tailored.get("summary"):
        s = tailored["summary"]
        for kw in matched_kw[:3]:
            if kw not in s and len(kw) >= 2:
                # 保守做法：不自动改写，仅在报告中提示可嵌入位置
                pass

    # 4) 标记出与 JD 强相关的条目（便于使用者排序）
    for s in tailored.get("sections", []):
        if s.get("type") in ("skills", "text", "list"):
            continue
        for it in s.get("items", []) or []:
            score = 0
            blob = json.dumps(it, ensure_ascii=False)
            for kw in report["matched"]["tools"] + report["matched"]["keywords"]:
                if term_in(kw, blob):
                    score += 1
            it["_relevance"] = score

    # 按相关度重排条目（相关度高的排前面），稳定排序保持原顺序作为次级键
    for s in tailored.get("sections", []):
        if s.get("type") in ("skills", "text", "list"):
            continue
        items = s.get("items", []) or []
        if len(items) > 1:
            indexed = list(enumerate(items))
            indexed.sort(key=lambda p: (-p[1].get("_relevance", 0), p[0]))
            s["items"] = [it for _, it in indexed]
            for it in s["items"]:
                it.pop("_relevance", None)

    return tailored, report


def main() -> int:
    ap = argparse.ArgumentParser(description="多岗位批量定制简历")
    ap.add_argument("resume", help="简历底稿 JSON")
    ap.add_argument("--jd", nargs="+", required=True, help="一个或多个 JD 文本文件")
    ap.add_argument("--out", required=True, help="输出目录")
    ap.add_argument("--style", default="auto",
                    help="排版风格，auto 表示按 JD 行业自动匹配")
    ap.add_argument("--formats", nargs="+", default=["pdf", "html", "docx"],
                    help="输出格式：pdf / html / docx")
    ap.add_argument("--surface", default="", choices=[""] + list(SURFACES), help="纸面底板")
    ap.add_argument("--palette", default="", choices=[""] + list(PALETTES), help="主色配色")
    ap.add_argument("--name", default="", help="简历文件名前缀，默认取简历中的姓名")
    args = ap.parse_args()

    base = json.loads(Path(args.resume).read_text(encoding="utf-8"))
    base_dir = Path(args.resume).resolve().parent
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    person = args.name or base.get("basic", {}).get("name", "简历")
    person = safe_name(person)

    results = []
    for jd_path in args.jd:
        jd_path = Path(jd_path)
        jd_text = jd_path.read_text(encoding="utf-8", errors="ignore")
        role = guess_role(jd_text)

        tailored, report = tailor(base, jd_text)

        style = args.style
        if style == "auto":
            style = pick_style(report, tailored)

        stem = f"{person}-{safe_name(role)}"
        stem = stem.replace(" ", "")

        surface = args.surface or base.get("meta", {}).get("surface") or "white"
        palette = (
            args.palette
            or base.get("meta", {}).get("palette")
            or STYLES[style].get("palette", "indigo")
        )

        made = []
        if "html" in args.formats:
            hp = outdir / f"{stem}.html"
            hp.write_text(
                render_html(tailored, style, base_dir, surface, palette), encoding="utf-8"
            )
            made.append(hp.name)
        if "pdf" in args.formats:
            hp = outdir / f"{stem}.html"
            if not hp.exists():
                hp.write_text(
                    render_html(tailored, style, base_dir, surface, palette), encoding="utf-8"
                )
            pp = outdir / f"{stem}.pdf"
            if convert(hp, pp):
                made.append(pp.name)
        if "docx" in args.formats:
            dp = outdir / f"{stem}.docx"
            docx_data = dict(tailored)
            docx_meta = dict(docx_data.get("meta") or {})
            docx_meta["accent"] = PALETTES[palette]["accent"]
            docx_data["meta"] = docx_meta
            build_docx(docx_data, dp, base_dir=base_dir)
            made.append(dp.name)

        rp = outdir / f"{stem}-匹配报告.txt"
        rp.write_text(format_report(role, style, report, jd_path.name), encoding="utf-8")

        results.append({
            "jd": jd_path.name,
            "role": role,
            "style": style,
            "coverage": report["coverage"],
            "tool_coverage": report["tool_coverage"],
            "files": made,
            "report": rp.name,
        })

    summary = {
        "base": str(args.resume),
        "person": person,
        "generated": results,
    }
    (outdir / "批量结果.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("=" * 66)
    print("批量定制完成")
    print("=" * 66)
    for r in results:
        cov = r["coverage"]
        tc = f" / 硬技能 {r['tool_coverage']}%" if r["tool_coverage"] is not None else ""
        print(f"\n【{r['role']}】  风格={r['style']}  覆盖率={cov}%{tc}")
        print(f"  JD 来源：{r['jd']}")
        for f in r["files"]:
            print(f"  → {f}")
        print(f"  → {r['report']}")
    print(f"\n全部文件输出目录：{outdir}")
    return 0


def pick_style(report: dict, data: dict) -> str:
    """按 JD 行业自动匹配排版风格。"""
    from jd_match import detect_family, detect_family_from_resume
    from jd_match import flatten_resume

    jd_tools = list(report["missing"]["tools"]) + list(report["matched"]["tools"])
    fam = detect_family(jd_tools)
    resume_text = flatten_resume(data)

    if "学术" in str(report.get("requirements", {}).get("edu", "")):
        pass

    edu = str(report.get("requirements", {}).get("edu", ""))
    if any(k in edu for k in ("博士", "硕士", "研究生")):
        return "academic"

    if fam & {"设计"} and not (fam & {"数据", "开发"}):
        return "sidebar"
    if fam & {"电商运营", "市场"}:
        return "modern"
    if fam & {"数据", "开发"}:
        return "modern"
    return "classic"


def format_report(role: str, style: str, report: dict, jd_name: str) -> str:
    L = []
    L.append("=" * 62)
    L.append(f"定制匹配报告 — {role}")
    L.append(f"来源 JD：{jd_name}")
    L.append(f"推荐风格：{style}")
    L.append("=" * 62)
    L.append(f"关键词覆盖率：{report['coverage']}%")
    if report["tool_coverage"] is not None:
        L.append(f"硬性要求覆盖率：{report['tool_coverage']}%")

    L.append("\n【已命中 — 保持并强化】")
    L.append("  技能工具：" + ("、".join(report["matched"]["tools"]) or "无"))
    L.append("  业务关键词：" + ("、".join(report["matched"]["keywords"][:12]) or "无"))

    L.append("\n【简历缺失 — 需你确认是否真实具备，确认后再写进简历】")
    L.append("  技能工具：" + ("、".join(report["missing"]["tools"]) or "无"))
    L.append("  业务关键词：" + ("、".join(report["missing"]["keywords"][:12]) or "无"))

    if report["warnings"]:
        L.append("\n【⚠ 风险提示】")
        for w in report["warnings"]:
            L.append(f"  ! {w}")

    L.append("\n【逐条修改建议】")
    for i, a in enumerate(report["priority_actions"], 1):
        badge = {"high": "【必改】", "medium": "【建议】", "low": "【可选】"}[a["level"]]
        L.append(f"  {i}. {badge} {a['item']}")
        L.append(f"      → {a['action']}")
    L.append("\n" + "-" * 62)
    L.append("提示：以上建议均未自动写入简历。请你逐条确认后手动修改 JSON，")
    L.append("再重新运行生成命令，以确保内容真实、表述准确。")
    return "\n".join(L)


if __name__ == "__main__":
    sys.exit(main())
