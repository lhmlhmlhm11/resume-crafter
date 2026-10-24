"""简历质检：在渲染前检查信息缺口、量化程度与 ATS 友好度。

用法：
    python lint_resume.py resume.json [--style classic]

输出分为三级：
  ERROR  会让简历明显掉分的硬伤（缺姓名、联系方式、经历时间等）
  WARN   明显影响竞争力的问题（无量化、动词空洞、分区顺序不当等）
  INFO   优化建议（措辞、篇幅、细节）

退出码：0 = 无 ERROR；1 = 存在 ERROR。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _console  # noqa: F401  (UTF-8 控制台兜底)

# 空洞动词：出现在 bullet 开头且不带量化结果的，视为无信息量
WEAK_VERBS = {
    "负责", "参与", "协助", "帮助", "配合", "跟进", "了解", "学习", "熟悉",
    "熟练", "精通", "掌握", "完成", "处理", "进行", "从事", "接触", "试用",
    "负责了", "参加了", "做了", "干活", "协助了", "配合了",
}

# 有信息量的动词，优先使用
STRONG_VERBS = {
    "搭建", "拆解", "上线", "复盘", "谈下", "迁移", "压缩", "搭建了", "主导",
    "设计", "开发", "运营", "策划", "优化", "提升", "降低", "拉动", "转化",
    "管理", "协调", "落地", "推广", "分析", "预测", "自动化", "沉淀",
}

# 量化结果：数字 + 量词/单位。
# 单位表要覆盖中文里常见的量词，否则「回收268份问卷」「产出28页报告」
# 这类明显带数字的 bullet 会被误报「缺少量化结果」，
# 逼着用户去硬凑数字 —— 比漏报更有害。
QUANT_RE = re.compile(
    r"\d+(\.\d+)?\s*(%|％|万|亿|人|元|块|天|周|月|年|季|次|倍|单|台|款|个|条|篇|家"
    r"|份|页|张|批|项|节|章|课|门|杯|本|支|件|套|组|类|种|重|斤|吨|米|分钟|小时"
    r"|轮|遍|场|店|摊|sku|K|k|㎡|m2)",
    re.IGNORECASE,
)
# 兜底：数字后接中文量词（未在上表中的），也算量化
QUANT_LOOSE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([一-龥])")
# 时间表达：年份 / 日期 / 日期区间 / "N 年经验"。
# 这些数字不是业绩量化，不能让 bullet 通过质检。
# 例：「2025.03 - 2025.08」「2028.06（预计）」「2028 年毕业」「3 年经验」。
TIME_ONLY_RE = re.compile(
    r"\d{4}\s*[-–—~至到]\s*\d{1,2}\s*[-–—~至到]?\s*\d{0,2}"  # 2025-2026 / 2025.03-2025.08
    r"|\d{4}\s*[./]\s*\d{1,2}(\s*[./]\s*\d{1,2})?"              # 2025.03 / 2025/3/1
    r"|\d{4}\s*年\s*\d{0,2}\s*月?\s*\d{0,2}\s*日?"                # 2025年3月 / 2029年
    r"|\d+\s*年\s*(以内|以上|以下|左右|经验|实习|工作|学习)?",     # 3年经验 / 2年以上
    re.IGNORECASE,
)
NUMBER_RE = re.compile(r"\d")

# ATS 解析器不认识的装饰性字符
RISKY_CHARS = re.compile(r"[★☆◆◇■□▪▫➤➤→⇒»«‣⁃]")

STANDARD_SECTIONS = {
    "基本信息", "个人简介", "自我评价", "个人总结", "职业目标", "求职意向",
    "教育经历", "教育背景", "学习经历", "学历", "教育与培训",
    "实习经历", "工作经历", "工作经验", "项目经历", "项目经验", "科研经历",
    "专业技能", "技能", "技能特长", "证书", "资格证书", "获奖", "荣誉",
    "获奖情况", "语言能力", "语言", "兴趣爱好", "自我评价",
    "奖项", "荣誉奖项", "在校经历", "社团经历", "学生工作", "志愿经历",
}


def has_quant(text: str) -> bool:
    """判断一句话里有没有「业绩量化」。

    顺序很重要：先把时间表达剥掉，再看剩下的数字。
    否则「2025.03 - 2025.08」会被当成量化而漏报，
    「2028 年毕业」会被当成量化而误判。
    """
    cleaned = TIME_ONLY_RE.sub(" ", text)

    if QUANT_RE.search(cleaned):
        return True

    # 兜底：数字后接中文量词也算（例如「268份」「28页」「6个」）
    for m in QUANT_LOOSE_RE.finditer(cleaned):
        num, unit = m.group(1), m.group(2)
        # 剩下的四位数年份（剥不干净的）仍不算量化
        if len(num) >= 4 and re.match(r"^(19|20)\d{2}", num):
            continue
        # 「3 年」「2 个月」这类时间单位不算量化
        if unit in "年月份":
            continue
        return True
    return False


# 本就适合无数字表述的行，不强制要求量化
NON_QUANT_PREFIXES = (
    "核心课程", "课程", "主修", "辅修", "相关课程", "证书", "语言", "兴趣",
    "获奖", "荣誉", "称号", "资质", "掌握", "熟悉", "了解",
)

# 行尾是结果性荣誉/状态时，数字不是必需的。
# 例：「撰写商业计划书并主导现场答辩，获省级奖项」——奖项本身就是结果，
# 再逼着补「XX 页」「XX 分」反而不自然。
RESULT_TAIL_RE = re.compile(
    r"(获|荣获|取得|获得|当选|入选|评为|命名为|通过|完成|达成|落地|上线|发布)"
    r"[^，。；]{0,10}"
    r"(奖|奖项|荣誉|称号|资格|证书|资质|认证|第一|冠军|亚军|季军|优秀|达标|结项|验收)",
    re.IGNORECASE,
)


def is_non_quantifiable(text: str) -> bool:
    t = text.strip()
    if any(t.startswith(p) or p in t[:8] for p in NON_QUANT_PREFIXES):
        return True
    # 行尾落在结果性荣誉上 → 视为已自带结论
    tail = t[-18:]
    return bool(RESULT_TAIL_RE.search(tail))


def lint(data: dict, style: str, base_dir: Path | None = None) -> tuple[list[tuple[str, str]], list[tuple[str, str]], list[tuple[str, str]]]:
    errors: list[tuple[str, str]] = []
    warns: list[tuple[str, str]] = []
    infos: list[tuple[str, str]] = []

    basic = data.get("basic", {})
    sections = data.get("sections", [])

    # ---- 基础信息 ----
    if not basic.get("name", "").strip():
        errors.append(("basic.name", "缺少姓名，简历首行必须出现真实姓名"))
    if not basic.get("title", "").strip():
        warns.append(("basic.title", "缺少求职意向/身份标签（如「电子商务专业 · 2027 届本科」）"))

    contact = basic.get("contact") or []
    contact_text = " ".join(str(c.get("text", "")) for c in contact)
    if not contact_text.strip():
        errors.append(("basic.contact", "缺少联系方式，至少要有手机号与邮箱"))
    else:
        if not re.search(r"1[3-9]\d{9}", contact_text.replace(" ", "").replace("-", "")):
            errors.append(("basic.contact", "联系方式中未识别到手机号"))
        if not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", contact_text):
            errors.append(("basic.contact", "联系方式中未识别到邮箱"))

    # ---- 分区检查 ----
    if not sections:
        errors.append(("sections", "简历没有任何内容分区"))

    titles = [s.get("title", "") for s in sections]
    for t in titles:
        if t and t not in STANDARD_SECTIONS:
            warns.append(("section.title", f"分区名「{t}」不属于 ATS 标准词汇，可能导致解析器无法归类；建议改为「教育经历」「实习经历」「项目经历」「专业技能」等"))

    # 分区顺序：分两种情形判断，避免给出与投递场景不符的建议
    # - 应届生有实习/项目经历：实习 → 项目 → 教育 → 技能 → 奖项（作品与实践优先）
    # - 无实习的在校生：教育 → 实习 → 项目 → 技能 → 奖项（学历优先）
    order = ["教育经历", "实习经历", "工作经历", "项目经历", "专业技能", "荣誉奖项"]
    recognized = [t for t in titles if t in STANDARD_SECTIONS]
    has_practice = any(t in ("实习经历", "工作经历", "项目经历") for t in recognized)
    if has_practice:
        order = ["实习经历", "工作经历", "项目经历", "教育经历", "专业技能", "荣誉奖项"]
    if recognized and recognized != sorted(recognized, key=lambda x: order.index(x) if x in order else 99):
        if has_practice:
            infos.append(("section.order",
                "分区顺序建议为：个人简介 → 实习经历 → 项目经历 → 教育经历 → 专业技能 → 荣誉奖项"
                "（有实习/项目时实践经历优先，学历放后面）"))
        else:
            infos.append(("section.order",
                "分区顺序建议为：基本信息 → 个人简介 → 教育经历 → 实习/项目经历 → 专业技能 → 荣誉奖项"))

    # ---- 条目检查 ----
    bullet_total = 0
    for s in sections:
        stype = s.get("type", "entries")
        sid = s.get("title", s.get("id", "section"))
        if stype in ("skills", "text"):
            continue
        items = s.get("items") or []
        if not items:
            warns.append((f"section.{sid}", f"分区「{sid}」为空，建议删除或补充内容"))
            continue

        # list 型分区（奖项、证书、语言等）按「文本条目」校验，不套用经历条目规则
        if stype == "list":
            for idx, it in enumerate(items):
                label = f"{sid}#{idx + 1}"
                text = it if isinstance(it, str) else (it.get("text") or "")
                if not text.strip():
                    errors.append((label, f"「{sid}」中有一条内容为空"))
                elif len(text) > 50:
                    infos.append((label, "条目偏长，建议控制在 40 字内"))
            continue

        for idx, it in enumerate(items):
            label = f"{sid}#{idx + 1}"
            if not it.get("org") and not it.get("role"):
                errors.append((label, f"「{sid}」中有一条既无组织名也无职位"))
            if not it.get("start"):
                warns.append((label, f"「{sid}」中有一条缺少起始时间"))
            bullets = it.get("bullets") or []
            if not bullets and stype not in ("list",):
                warns.append((label, f"「{sid}」中有一条没有任何描述性内容"))
            bullet_total += len(bullets)

            for b in bullets:
                if len(b) > 90:
                    infos.append((label, f"bullet 过长（{len(b)} 字），单条控制在 60 字内、每条不超过 2 行"))
                if RISKY_CHARS.search(b):
                    infos.append((label, "包含装饰性符号（★◆■等），部分 ATS 会丢失该字符，建议用文字替代"))
                first = b.strip().split("，")[0].split("、")[0]
                if first in WEAK_VERBS:
                    warns.append((label, f"以「{first}」开头信息量偏低，建议换成「{next(iter(STRONG_VERBS))}」类动作动词并补上结果"))
                if not has_quant(b) and len(b) > 12 and not is_non_quantifiable(b):
                    warns.append((label, f"「{b[:24]}…」缺少量化结果，建议补数字（比例/金额/人数/周期）"))
                if re.search(r"[。；;]{2,}", b):
                    infos.append((label, "存在重复句号/分号"))

    # ---- 篇幅 ----
    if bullet_total > 0 and bullet_total < 3:
        warns.append(("global.bullets", f"全篇仅 {bullet_total} 条描述，内容偏少，招聘方会觉得经历单薄"))
    if bullet_total > 28:
        infos.append(("global.bullets", f"共 {bullet_total} 条描述，一页简历建议 12—20 条，多余内容考虑删减或拆到第二页"))

    # ---- 风格提示 ----
    if style in ("sidebar", "creative", "soft"):
        warns.append(("style", f"当前风格「{style}」为双栏布局，部分 ATS 解析器会跨栏错读；建议同时输出一份 classic 单栏版用于线上投递"))
    if style == "neon":
        warns.append(("style", "当前风格「neon」使用整幅渐变色带与反白文字，打印耗墨且部分 ATS 截图预览会失真；线上投递建议另备 classic 浅色版"))
    if style == "geo":
        warns.append(("style", "当前风格「geo」的分区为圆角卡片，若跨页会把卡片切成两半；请确认 PDF 为单页或分区不跨页"))

    # ---- 头像 ----
    photo = (basic.get("photo") or "").strip()
    photo_shape = basic.get("photo_shape", "rect")
    if photo:
        if photo.startswith(("http://", "https://")):
            infos.append(("basic.photo", "头像使用远程链接：PDF 渲染与 Word 插入时可能加载失败，建议改用本地图片文件"))
        elif photo.startswith("data:"):
            infos.append(("basic.photo", "头像为内嵌 base64，文件体积会明显增大，功能正常"))
        else:
            p = Path(photo).expanduser()
            if not p.is_absolute() and base_dir is not None:
                p = (Path(base_dir) / p).resolve()
            if not p.exists():
                errors.append(("basic.photo", f"头像文件不存在：{photo}（相对路径以简历 JSON 所在目录为基准）"))
        if photo_shape == "circle":
            infos.append(("basic.photo", "圆形头像在部分国企/事业单位的制式简历中不被接受，建议改用矩形（rect）"))
    else:
        infos.append(("basic.photo", "未设置一寸照片：应届生网申、事业单位、公务员等场景常要求附证件照，如需放置可设置 basic.photo"))

    # ---- 摘要 ----
    summary = (data.get("summary") or "").strip()
    if not summary:
        infos.append(("global.summary", "缺少个人简介/自我评价，一段 60—100 字的定位概述能显著提升第一印象"))
    elif len(summary) > 180:
        infos.append(("global.summary", f"个人简介 {len(summary)} 字偏长，建议压缩到 60—120 字"))

    # ---- 弱词统计 ----
    all_text = json.dumps(data, ensure_ascii=False)
    weak_hits = [w for w in WEAK_VERBS if w in all_text]
    if len(weak_hits) >= 3:
        infos.append(("global.weak", f"简历中出现较多弱化词（{'、'.join(sorted(set(weak_hits))[:5])} 等），『精通/熟练/了解』在筛选中会被默认打折"))

    return errors, warns, infos


def main() -> int:
    ap = argparse.ArgumentParser(description="简历质检")
    ap.add_argument("data")
    ap.add_argument("--style", default="classic")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    args = ap.parse_args()

    data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    errors, warns, infos = lint(data, args.style, Path(args.data).resolve().parent)

    if args.json:
        print(json.dumps(
            {"errors": errors, "warnings": warns, "infos": infos},
            ensure_ascii=False, indent=2,
        ))
        return 1 if errors else 0

    print("=" * 62)
    print("简历质检报告")
    print("=" * 62)
    for tag, items, color in (
        ("ERROR 必须修复", errors, "✗"),
        ("WARN  影响竞争力", warns, "!"),
        ("INFO  优化建议", infos, "·"),
    ):
        if not items:
            continue
        print(f"\n{tag}（{len(items)}）")
        print("-" * 62)
        for loc, msg in items:
            print(f"  {color} [{loc}] {msg}")
    print()
    if errors:
        print(f"结论：存在 {len(errors)} 个必须修复的问题，不建议直接投递。")
        return 1
    print(f"结论：无硬伤。另有 {len(warns)} 处建议修复、{len(infos)} 条优化建议。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
