"""JD 匹配器：把岗位描述与简历做结构化比对，输出定制化修改建议。

用法：
    python jd_match.py resume.json jd.txt [--out report.json]

方法：
1. 从 JD 中抽取「硬性要求」（学历/年限/技能工具/证书/职责关键词）与「软性要求」。
2. 抽取简历中的全部文本。
3. 逐条比对，输出四类结果：
   - matched   已命中，可强化措辞
   - missing   简历缺失且简历中确实有素材 → 建议补写（需用户确认真实性）
   - uncovered JD 要求但无从判断 → 需用户决策是否可满足
   - irrelevant 简历有但与 JD 无关的段落 → 建议弱化或删除
4. 给出关键词覆盖率与优先级排序，供排版与内容调整使用。

输出是「建议」而非自动改写 —— 绝不编造用户没有的经历。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _console  # noqa: F401  (UTF-8 控制台兜底)

# ---- 常见岗位关键词词库（用于识别 JD 里的硬技能）----
TOOL_KEYWORDS = [
    # 数据 / 分析
    "Excel", "SQL", "Python", "R", "SPSS", "Stata", "Tableau", "Power BI",
    "BI", "Hadoop", "Spark", "Hive", "Pandas", "NumPy", "数据可视化", "数据建模",
    "埋点", "A/B测试", "AB测试", "用户画像", "数据仓库", "ETL", "指标体系",
    # 电商 / 运营
    "淘宝", "天猫", "京东", "拼多多", "抖音", "快手", "小红书", "微信小程序",
    "私域", "公域", "选品", "定价", "详情页", "主图", "直通车", "万相台",
    "千牛", "生意参谋", "DSR", "GMV", "ROI", "UV", "转化率", "客单价", "复购率",
    "大促", "活动策划", "店铺装修", "类目", "竞品分析", "供应链", "库存周转",
    "推广", "投放", "ROI优化", "内容营销", "SEO", "SEM", "信息流",
    # 设计 / 产品
    "Photoshop", "PS", "Illustrator", "AI", "Figma", "Sketch", "Axure",
    "墨刀", "C4D", "AE", "Premiere", "剪映", "UI", "UX", "交互", "原型",
    "视觉", "排版", "文案", "品牌", "视觉设计", "产品设计", "需求文档",
    # 开发 / 技术
    "Java", "Python", "C++", "Go", "前端", "后端", "小程序开发", "APP开发",
    "数据库", "接口", "Git", "Linux", "Docker", "K8s", "测试", "运维",
    # 通用职能
    "项目管理", "数据分析", "市场研究", "用户研究", "客服", "销售", "商务",
    "BD", "运营管理", "活动运营", "内容运营", "用户运营", "私域运营", "社群",
    "财务", "会计", "审计", "法务", "HR", "人力", "行政", "供应链管理",
    "跨境", "电商运营", "国际贸易", "报关", "物流", "仓储", "生产管理",
    # 新媒体 / 内容工具
    "秀米", "135编辑器", "i排版", "壹伴", "Canva", "创客贴", "图怪兽",
    "石墨文档", "飞书", "Notion", "有道云笔记", "H5", "海报",
    "公众号后台", "视频号", "快手", "B站", "知乎", "微博", "头条号",
]

# 过于泛化的词：几乎任何 JD 都会出现，不能当作具体技能要求
VAGUE_TOOLS = {"视觉", "品牌", "测试", "推广", "投放", "商务", "运营", "管理"}

CERT_KEYWORDS = [
    "CET-6", "CET6", "英语六级", "英语四级", "CET-4", "雅思", "托福", "专八", "专四",
    "CPA", "初级会计", "中级会计", "注册会计师", "教师资格证", "导游证", "法律职业资格",
    "计算机二级", "计算机三级", "一级建造师", "PMP", "CFA", "ACCA", "CPA",
    "软考", "普通话二级甲等", "驾驶证",
]

EDU_KEYWORDS = {
    "博士": 5, "硕士": 4, "研究生": 4, "本科": 3, "学士": 3, "大专": 2, "专科": 2,
    "高中": 1, "硕士及以上": 5, "本科及以上": 3, "统招本科": 3,
}

YEAR_RE = re.compile(r"(\d+)\s*[-~到至]?\s*(\d+)?\s*年")
EXP_PATTERNS = [
    (re.compile(r"(\d+)\s*[-~到至]\s*(\d+)\s*年"), lambda m: int(m.group(2)) - int(m.group(1))),
    (re.compile(r"(\d+)\s*年以上"), lambda m: int(m.group(1))),
    (re.compile(r"经验\s*(\d+)\s*年"), lambda m: int(m.group(1))),
]

STOP_ZH = set(
    "的 了 和 与 及 等 一 我们 公司 岗位 职责 要求 工作 相关 能力 优先 具备 "
    "以上 以及 并且 熟悉 熟练 良好 具备 有 一定 能够 负责 完成 参与 协助 使用 "
    "各种 各种 各类 进行 提供 支持 配合 团队 良好 加分 优先考虑 者优先".split()
)

# 中文业务语义词库：只从真实词汇中匹配，避免滑窗切出「销活」「园招」这类跨词碎片
CN_KEYWORDS = [
    # 运营职能
    "电商运营", "店铺运营", "商品运营", "活动运营", "内容运营", "用户运营",
    "私域运营", "社群运营", "社群", "私域", "公域", "直播运营", "会员运营",
    "市场推广", "品牌推广", "渠道运营", "全渠道", "新零售", "跨境电商",
    # 电商专业动作
    "选品", "定价", "详情页", "主图", "直通车", "万相台", "千牛", "生意参谋",
    "竞品分析", "竞品监控", "店铺装修", "大促", "促销", "满减", "优惠券",
    "库存周转", "滞销", "类目", "客单价", "复购率", "转化率", "加购率",
    "流量", "曝光", "点击率", "uv", "pv", "gmv", "roi", "dsr", "sku",
    "站内搜索", "搜索排名", "评价管理", "客服", "售后", "工单",
    # 数据分析
    "数据复盘", "复盘", "数据分析", "数据看板", "数据监控", "指标体系",
    "漏斗分析", "转化漏斗", "ab测试", "a/b测试", "用户画像", "用户调研",
    "市场研究", "行业分析", "商业分析", "报表", "可视化", "数据埋点",
    # 设计产品
    "视觉设计", "ui设计", "ux设计", "交互设计", "产品设计", "原型设计",
    "需求分析", "需求文档", "竞品调研", "品牌设计", "排版", "文案",
    # 项目与软技能
    "项目管理", "团队协作", "沟通能力", "逻辑思维", "抗压", "执行力",
    "主动性", "学习能力", "责任心", "细心", "数据敏感度", "商业敏感度",
    "统筹", "协调", "落地", "复盘迭代",
    # 组织形式
    "校园招聘", "社会招聘", "秋招", "春招", "管培生", "实习生",
    "兼职", "志愿服务", "学生工作", "社团",
    # 通用
    "实习经历", "工作经验", "项目经验", "自我评价", "职业规划",
    "数字营销", "整合营销", "内容策划", "活动策划", "商务拓展",
    "客户服务", "仓储物流", "采购", "供应商", "生产管理", "质量管理",
    # 新媒体 / 内容运营
    "新媒体运营", "新媒体", "内容运营", "社群运营", "私域运营", "用户运营",
    "内容策划", "选题策划", "图文排版", "文案写作", "短视频", "直播",
    "自媒体", "公众号", "小红书", "抖音", "微博", "视频号", "知乎",
    "品牌传播", "品牌公关", "媒体公关", "舆情", "KOL", "种草", "投放",
    "粉丝运营", "私域流量", "阅读量", "涨粉", "互动率", "完播率",
    "推文", "软文", "信息流", "SEO", "SEM", "广告投放", "物料",
    "活动策划", "活动执行", "活动复盘", "节日营销", "联名",
    "编辑", "采编", "采访", "撰稿", "校对", "排版", "策划",
    # 通用职能 / 人力
    "人力资源", "招聘", "面试", "绩效", "薪酬", "员工关系", "培训体系",
    "行政", "前台", "财务", "会计", "审计", "法务", "法务合规",
    "数据分析师", "商业分析", "用户研究", "行业研究", "咨询",
    "供应链", "仓储", "物流", "采购管理", "生产计划", "品质管理",
    "市场营销", "品牌建设", "渠道拓展", "客户成功", "售后服务",
    "跨部门协作", "团队建设", "目标管理", "复盘分析", "方案撰写",
]

# 常见 JD 分类标签：出现在 JD 里不代表是能力要求，匹配时应排除
JD_LABEL_WORDS = {
    "技能工具类", "证书类", "内容运营类", "专业工具", "工具类",
    "软技能", "硬技能", "能力要求", "任职资格", "岗位要求",
}

# 跨词碎片黑名单：滑窗切词可能产生的伪词（如「校招关联」「定效修改建议」）
# 这些不是真实词汇，即使出现在 JD 中也不应作为关键词
FRAGMENT_BLACKLIST = {
    "校招关联", "定效修改", "修改建议", "建议类", "类工具", "工具类",
    "招关联", "定效", "效修改", "关联类", "经历类", "能力类",
}

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#.\-]{1,20}|[\u4e00-\u9fa5]{2,8}")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


# 短词工具名（AI / PS / BI / UV / AE…）必须按词边界匹配，
# 否则会命中 "email"、"emailAddress" 之类的无关文本。
SHORT_ASCII = {"ai", "ps", "bi", "uv", "pv", "ae", "sql", "seo", "sem", "hr", "bd", "r"}


def term_in(term: str, text: str) -> bool:
    """判断术语是否出现在文本中。ASCII 短词要求词边界，中文词直接子串匹配。"""
    t = term.strip()
    if not t:
        return False
    if re.match(r"^[A-Za-z][A-Za-z0-9+#.\-]*$", t):
        pattern = r"(?<![A-Za-z0-9])" + re.escape(t) + r"(?![A-Za-z0-9])"
        return bool(re.search(pattern, text, re.IGNORECASE))
    return t.lower() in text.lower()


def flatten_resume(data: dict) -> str:
    """把简历 JSON 摊平成纯文本，便于关键词匹配。"""
    parts: list[str] = []
    basic = data.get("basic", {})
    parts.append(str(basic.get("name", "")))
    parts.append(str(basic.get("title", "")))
    for c in basic.get("contact", []) or []:
        parts.append(str(c.get("text", "")))
    if data.get("summary"):
        parts.append(str(data["summary"]))
    for s in data.get("sections", []) or []:
        parts.append(str(s.get("title", "")))
        for g in s.get("groups", []) or []:
            parts.append(str(g.get("label", "")))
            parts.extend(str(i) for i in g.get("items", []) or [])
        if s.get("text"):
            parts.append(str(s["text"]))
        for it in s.get("items", []) or []:
            if isinstance(it, str):
                parts.append(it)
                continue
            for k in ("org", "role", "location", "start", "end", "note", "text", "date"):
                if it.get(k):
                    parts.append(str(it[k]))
            parts.extend(str(b) for b in it.get("bullets", []) or [])
    return "\n".join(parts)


def extract_jd_requirements(jd: str) -> dict:
    """从 JD 文本中抽取结构化要求。"""
    req = {
        "edu": [],
        "edu_level": 0,
        "years": [],
        "tools": [],
        "certs": [],
        "keywords": [],
        "responsibilities": [],
        "must_have": [],
        "nice_to_have": [],
        "raw_lines": [],
    }

    lines = [l.strip() for l in jd.splitlines() if l.strip()]
    req["raw_lines"] = lines

    lower = jd.lower()
    for kw in TOOL_KEYWORDS:
        # 泛词（如「视觉」「品牌」）不能当作具体技能要求
        if kw in VAGUE_TOOLS:
            continue
        if term_in(kw, jd):
            req["tools"].append(kw)
    for kw in CERT_KEYWORDS:
        if term_in(kw, jd):
            req["certs"].append(kw)

    for name, level in EDU_KEYWORDS.items():
        if name in jd:
            req["edu"].append(name)
            req["edu_level"] = max(req["edu_level"], level)

    for pat, fn in EXP_PATTERNS:
        for m in pat.finditer(jd):
            try:
                v = fn(m)
                if 0 < v <= 30:
                    req["years"].append(v)
            except Exception:
                pass

    # 区分「任职要求」与「加分项」区块
    in_nice = False
    section_lines: list[tuple[str, str]] = []  # (区块类型, 文本)

    # 这些词出现在行内时只作为「区块标记」，该行本身是标题而非内容
    SECTION_MARKERS = (
        "岗位职责", "工作职责", "职位描述", "工作内容", "任职要求",
        "岗位要求", "任职资格", "我们希望你", "加分项", "优先考虑",
        "职位要求", "职位名称", "岗位名称", "团队介绍", "公司简介",
    )
    # 纯标签行（冒号后无内容）不是职责/要求内容
    def _is_label_only(line: str) -> bool:
        head = re.split(r"[：:]", line, maxsplit=1)
        if len(head) == 2 and head[1].strip():
            return False
        return any(m in line for m in SECTION_MARKERS)

    for line in lines:
        low = line.lower()
        if any(k in line for k in ("加分", "优先", "nice to have", "bonus", "更佳")):
            in_nice = True
        # 区块标记：切换状态，并把标记后的实际内容记入对应区块
        if any(k in line for k in ("岗位职责", "工作职责", "职位描述", "工作内容", "职责")):
            in_nice = False
            # 冒号后若跟有内容，取该内容作为职责；否则该行只是标题
            parts = re.split(r"[：:]", line, maxsplit=1)
            inline = parts[1].strip() if len(parts) == 2 else ""
            if inline and len(inline) >= 8 and not _is_label_only(inline):
                req["responsibilities"].append(inline)
                section_lines.append(("responsibility", inline))
            else:
                section_lines.append(("responsibility_marker", line))
            continue
        if any(k in line for k in ("任职要求", "岗位要求", "任职资格", "我们希望你")):
            in_nice = False
            parts = re.split(r"[：:]", line, maxsplit=1)
            inline = parts[1].strip() if len(parts) == 2 else ""
            if inline and len(inline) >= 8:
                req["must_have"].append(inline)
                section_lines.append(("requirement", inline))
            else:
                section_lines.append(("requirement_marker", line))
            continue
        if any(k in line for k in ("加分项", "优先考虑", "具备以下条件者优先")):
            in_nice = True
        if _is_label_only(line):
            continue
        if in_nice:
            req["nice_to_have"].append(line)
            section_lines.append(("nice", line))
        elif req["must_have"]:
            req["must_have"].append(line)
            section_lines.append(("requirement", line))

    req["section_lines"] = section_lines

    # 中文业务关键词：优先用受控词库匹配；词库未覆盖时回退到「高频 n-gram + 碎片过滤」
    found_cn = [kw for kw in CN_KEYWORDS if kw in jd]
    found_cn = [kw for kw in found_cn if kw not in JD_LABEL_WORDS]

    # 受控词库未覆盖到的部分，用 n-gram 兜底，但必须过滤掉跨词碎片
    if len(found_cn) < 5:
        fallback = _extract_ngrams(jd)
        for kw in fallback:
            if kw not in found_cn:
                found_cn.append(kw)

    # 去重并保持词库顺序（长词优先，避免「社群运营」与「社群」重复计入）
    req["keywords"] = _dedupe_keywords(found_cn)

    return req


def _dedupe_keywords(words: list[str]) -> list[str]:
    """去掉重复词与被更长词包含的短词。"""
    out: list[str] = []
    for w in sorted(set(words), key=lambda x: (-len(x), x)):
        if any(w in v and w != v for v in out):
            continue
        out.append(w)
    return out


def _extract_ngrams(jd: str) -> list[str]:
    """从 JD 中提取中文 n-gram 关键词，并过滤掉跨词边界的碎片。

    碎片判定规则：
    1. 命中黑名单（已知的历史误切词）
    2. 以停用字开头或结尾（如「的运营」「运营的」）
    3. 是另一个更长候选词的真子串（说明它只是长词的一部分）
    """
    from collections import Counter

    # 高频停用字：不能出现在关键词首尾
    EDGE_STOP = set("的了和与及等在有把被对为以之其此该并就都也很更再又只把将从向到对为对于关于我们公司岗位")
    # 常见双字功能词，不单独成词
    INNER_STOP = {"我们", "公司", "岗位", "职责", "要求", "优先", "具备", "熟悉",
                  "熟练", "良好", "以及", "并且", "相关", "能力", "工作", "负责",
                  "完成", "参与", "协助", "使用", "进行", "提供", "支持", "配合"}

    counter: Counter = Counter()
    for tok in re.findall(r"[\u4e00-\u9fa5]{2,10}", jd):
        for n in (2, 3, 4):
            for i in range(len(tok) - n + 1):
                gram = tok[i:i + n]
                if gram in INNER_STOP or gram in FRAGMENT_BLACKLIST:
                    continue
                if gram[0] in EDGE_STOP or gram[-1] in EDGE_STOP:
                    continue
                counter[gram] += 1

    if not counter:
        return []

    # 只取出现 2 次以上的候选（高频词更可能是真实术语）
    cands = [w for w, c in counter.items() if c >= 2]
    if not cands:
        return []

    # 若某候选是另一候选的真子串，则它多半是被切碎的片段，丢弃
    result = []
    for w in sorted(cands, key=len, reverse=True):
        if any(w != v and w in v for v in cands):
            continue
        result.append(w)

    return result[:12]


def match(data: dict, jd_text: str) -> dict:
    req = extract_jd_requirements(jd_text)
    resume_text = flatten_resume(data)
    resume_lower = resume_text.lower()

    matched_tools = [t for t in req["tools"] if term_in(t, resume_text)]
    missing_tools = [t for t in req["tools"] if not term_in(t, resume_text)]

    matched_certs = [c for c in req["certs"] if term_in(c, resume_text)]
    missing_certs = [c for c in req["certs"] if not term_in(c, resume_text)]

    matched_kw = [k for k in req["keywords"] if k in resume_text]
    missing_kw = [k for k in req["keywords"] if k not in resume_text]

    # 关键词出现在 JD 的哪个区块，决定其优先级
    def where_appears(term: str) -> set[str]:
        locs = set()
        t = term.lower()
        for kind, line in req.get("section_lines", []):
            if t in line.lower():
                locs.add(kind)
        return locs

    # 覆盖率计算：把「工具 + 证书 + 关键词」合并为一份去重的要求清单。
    # 若不合并，同一个词（如「数据分析」既是工具又是关键词）会被重复计入分母，
    # 导致覆盖率被严重低估。
    def _dedupe_demand(items: list[str]) -> list[str]:
        out: list[str] = []
        for w in sorted(set(items), key=lambda x: (-len(x), x)):
            if any(w in v and w != v for v in out):
                continue
            out.append(w)
        return out

    demand_all = _dedupe_demand(req["tools"] + req["certs"] + req["keywords"])
    matched_all = [w for w in demand_all if term_in(w, resume_text)]
    coverage = round(len(matched_all) / len(demand_all) * 100, 1) if demand_all else 0.0

    # 硬性要求覆盖率：只统计出现在「任职要求 / 岗位职责」区块的词
    hard_demand = _dedupe_demand(
        [t for t in demand_all
         if where_appears(t) & {"requirement", "responsibility"}]
    )
    hard_matched = [t for t in hard_demand if term_in(t, resume_text)]
    tool_coverage = (
        round(len(hard_matched) / len(hard_demand) * 100, 1) if hard_demand else None
    )

    # 简历中与 JD 完全无关的内容（如 JD 要 Java 开发，简历全是设计）
    irrelevant_hints = []
    if req["tools"]:
        jd_family = detect_family(req["tools"])
        r_family = detect_family_from_resume(resume_text)
        if jd_family and r_family and not (jd_family & r_family):
            irrelevant_hints.append(
                f"JD 核心技术栈为「{'/'.join(sorted(jd_family))}」，简历内容偏向「{'/'.join(sorted(r_family))}」，"
                "两者错位，建议按 JD 重新组织经历叙述"
            )

    def level_for(term: str) -> str:
        locs = where_appears(term)
        if "requirement" in locs:
            return "high"
        if "responsibility" in locs:
            return "high"
        if "nice" in locs:
            return "low"
        return "medium"

    # 优先级排序
    priority = []
    for t in missing_tools:
        lv = level_for(t)
        priority.append({"type": "skill", "item": t, "level": lv,
                         "action": f"若你实际掌握 {t}，在「专业技能」中显式列出，并在相关经历中用具体案例佐证；若无真实经验则不要写"})
    for c in missing_certs:
        lv = level_for(c)
        priority.append({"type": "cert", "item": c, "level": lv,
                         "action": f"JD 要求 {c}，简历未体现。若持有请补充到荣誉/证书分区；若未持有需评估是否影响投递"})
    if req["edu_level"]:
        level_name = {5: "博士", 4: "硕士", 3: "本科", 2: "大专", 1: "高中"}.get(req["edu_level"], "")
        edu_text = resume_text
        if level_name and level_name not in edu_text:
            priority.append({"type": "edu", "item": f"学历要求 {level_name}", "level": "high",
                             "action": "JD 学历要求高于简历体现，需确认是否为硬性门槛；否则重点强化项目与实习的分量"})
    if req["years"]:
        need = max(req["years"])
        priority.append({"type": "exp", "item": f"{need} 年经验", "level": "medium",
                         "action": f"JD 提及 {need} 年经验。应届生可突出实习密度、项目复杂度与可量化结果，用「项目规模」替代「工作年限」"})

    for k in missing_kw:
        # 与已列出的技能建议去重（同一词不再重复建议）
        if k in missing_tools or k in missing_certs:
            continue
        # JD 的分类标签（如「技能工具类」）不是能力要求，跳过
        if k in JD_LABEL_WORDS or k in FRAGMENT_BLACKLIST:
            continue
        lv = level_for(k)
        if lv == "low":
            action = f"「{k}」属于 JD 加分项，非必需。若确有相关经历可自然提及，缺失通常不影响投递"
        else:
            action = f"JD 中出现「{k}」，若与你的经历相关，可在 bullet 中自然嵌入该词（仅限真实经历）"
        priority.append({"type": "keyword", "item": k, "level": lv, "action": action})

    order = {"high": 0, "medium": 1, "low": 2}
    priority.sort(key=lambda x: order.get(x["level"], 3))

    return {
        "coverage": coverage,
        "tool_coverage": tool_coverage,
        "matched": {
            "tools": matched_tools,
            "certs": matched_certs,
            "keywords": matched_kw,
        },
        "missing": {
            "tools": missing_tools,
            "certs": missing_certs,
            "keywords": missing_kw,
        },
        "requirements": {
            "edu": req["edu"],
            "years": req["years"],
            "must_have": req["must_have"],
            "nice_to_have": req["nice_to_have"],
            "responsibilities": req["responsibilities"],
        },
        "priority_actions": priority,
        "warnings": irrelevant_hints,
    }


FAMILIES = {
    "开发": {"Java", "Python", "C++", "Go", "前端", "后端", "Linux", "Docker", "K8s", "Git", "数据库", "接口", "测试", "运维", "小程序开发", "APP开发"},
    "数据": {"SQL", "Python", "R", "SPSS", "Stata", "Tableau", "Power BI", "BI", "Hadoop", "Spark", "Hive", "数据可视化", "数据建模", "埋点", "A/B测试", "AB测试", "用户画像", "数据仓库", "ETL", "指标体系", "Pandas", "NumPy", "Excel"},
    "电商运营": {"淘宝", "天猫", "京东", "拼多多", "抖音", "快手", "小红书", "选品", "定价", "详情页", "主图", "直通车", "千牛", "生意参谋", "DSR", "GMV", "ROI", "转化率", "客单价", "复购率", "大促", "活动策划", "店铺装修", "类目", "竞品分析", "供应链", "库存周转", "投放", "信息流", "电商运营", "私域", "公域"},
    "设计": {"Photoshop", "PS", "Illustrator", "AI", "Figma", "Sketch", "Axure", "墨刀", "C4D", "AE", "Premiere", "剪映", "UI", "UX", "交互", "原型", "视觉", "排版", "品牌", "视觉设计", "产品设计"},
    "产品": {"Axure", "Figma", "Sketch", "原型", "交互", "产品设计", "需求文档", "项目管理", "用户研究"},
    "市场": {"内容营销", "SEO", "SEM", "信息流", "推广", "投放", "文案", "品牌", "市场研究", "活动策划"},
    "职能": {"项目管理", "数据分析", "客服", "销售", "商务", "BD", "财务", "会计", "审计", "法务", "HR", "人力", "行政", "跨境", "国际贸易", "报关", "物流", "仓储", "生产管理", "活动运营", "内容运营", "用户运营", "私域运营", "社群", "运营管理"},
}


def detect_family(tools: list[str]) -> set[str]:
    fam = set()
    for t in tools:
        for name, keys in FAMILIES.items():
            if t in keys:
                fam.add(name)
    return fam


def detect_family_from_resume(text: str) -> set[str]:
    fam = set()
    for name, keys in FAMILIES.items():
        hits = sum(1 for k in keys if k.lower() in text.lower())
        if hits >= 2:
            fam.add(name)
    return fam


def main() -> int:
    ap = argparse.ArgumentParser(description="JD 匹配分析")
    ap.add_argument("resume")
    ap.add_argument("jd")
    ap.add_argument("--out", help="把完整结果写入 JSON")
    args = ap.parse_args()

    data = json.loads(Path(args.resume).read_text(encoding="utf-8"))
    jd_text = read_text(Path(args.jd))
    result = match(data, jd_text)

    print("=" * 64)
    print("JD 匹配分析")
    print("=" * 64)
    print(f"关键词覆盖率：{result['coverage']}%"
          + (f"   硬技能覆盖率：{result['tool_coverage']}%" if result["tool_coverage"] is not None else ""))

    print("\n【已命中】")
    print(f"  技能工具：{'、'.join(result['matched']['tools']) or '无'}")
    print(f"  证书语言：{'、'.join(result['matched']['certs']) or '无'}")
    print(f"  关键词  ：{'、'.join(result['matched']['keywords'][:15]) or '无'}")

    print("\n【简历缺失（需用户确认是否真实具备）】")
    print(f"  技能工具：{'、'.join(result['missing']['tools']) or '无'}")
    print(f"  证书语言：{'、'.join(result['missing']['certs']) or '无'}")
    print(f"  关键词  ：{'、'.join(result['missing']['keywords'][:15]) or '无'}")

    if result["warnings"]:
        print("\n【⚠ 风险提示】")
        for w in result["warnings"]:
            print(f"  ! {w}")

    print("\n【定制化修改建议（按优先级）】")
    if not result["priority_actions"]:
        print("  简历与 JD 匹配度良好，无需大幅调整。")
    shown = 0
    for i, a in enumerate(result["priority_actions"], 1):
        if a["level"] == "low" and shown >= 12:
            continue
        badge = {"high": "【必改】", "medium": "【建议】", "low": "【可选】"}[a["level"]]
        print(f"  {i}. {badge} {a['item']}")
        print(f"      → {a['action']}")
        shown += 1
    low_count = sum(1 for a in result["priority_actions"] if a["level"] == "low")
    if low_count > 12:
        print(f"  …… 另有 {low_count - 12} 条「可选」级建议（多为加分项关键词），详见 JSON 输出")

    if args.out:
        Path(args.out).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # 只回显文件名，不回显本机绝对路径：
        # 报告会随仓库一起公开，绝对路径会泄露用户名与本机目录结构。
        print(f"\n完整结果已写入：{Path(args.out).name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
