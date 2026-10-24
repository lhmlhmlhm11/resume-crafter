"""求职信生成 + 面试问题预测。

用法：
    python cover_letter.py resume.json jd.txt --out 求职信.md --interview

输出：
- 求职信正文（可直接复制投递，或导出为 DOCX/PDF）
- 面试官高概率提问清单 + 回答要点提示
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jd_match import match, flatten_resume  # noqa: E402
from jd_match import extract_jd_requirements  # noqa: E402

import _console  # noqa: F401  (UTF-8 控制台兜底)

# 面试高频问题模板：按问题类型给出回答框架
QUESTION_BANK = {
    "自我介绍": {
        "q": "请做一个 1—2 分钟的自我介绍",
        "frame": "现在身份 + 与岗位的 2 个最强证据 + 求职动机。用「经历—成果—为什么是你」三段式，不要复述简历。",
    },
    "为什么选我们": {
        "q": "为什么选择我们公司/这个岗位？",
        "frame": "先说对该公司业务/产品的具体了解（越具体越可信），再说你做过的事如何直接对应这个岗位的痛点。忌空喊「贵公司前景好」。",
    },
    "最大优势": {
        "q": "你最大的优势是什么？",
        "frame": "只讲 1 个，用具体案例证明，结尾落到这个岗位的需求上。不要罗列 5 条。",
    },
    "最大短板": {
        "q": "你最大的缺点/不足是什么？",
        "frame": "选一个真实但不致命的短板，说明你已采取的具体改进动作，以及现在的进展。忌把优点伪装成缺点。",
    },
    "职业规划": {
        "q": "你未来 3 年的职业规划是什么？",
        "frame": "1 年扎实做熟本岗 → 2 年独立负责模块 → 3 年在相关方向沉淀。与该公司的实际发展路径对齐。",
    },
    "抗压": {
        "q": "讲一次压力最大的经历，你是怎么处理的？",
        "frame": "STAR：背景压力点 → 你的具体动作（拆解优先级/求助/取舍）→ 结果数据 → 沉淀出的方法。",
    },
    "团队协作": {
        "q": "和同事/上级意见不一致时你怎么处理？",
        "frame": "讲一个具体冲突。重点讲你如何用数据或事实说服对方，以及最终如何达成一致。忌讲「我一般听领导的」。",
    },
    "失败经历": {
        "q": "讲一次失败或没做成的事",
        "frame": "STAR + 复盘：承认结果 → 归因（客观不甩锅）→ 具体改进 → 后续用类似场景证明改进有效。",
    },
    "加班/出差": {
        "q": "能接受加班或出差吗？",
        "frame": "态度明确表态，同时用具体经历证明你的抗压与交付能力，避免模糊回答「都可以」。",
    },
    "薪资": {
        "q": "你的期望薪资是多少？",
        "frame": "先问清薪资结构（底薪/绩效/提成/补贴）。给一个基于市场水平的区间，应届生可说「更看重成长空间，愿意向公司标准靠拢」。",
    },
    "到岗时间": {
        "q": "什么时候可以到岗？能实习多久？",
        "frame": "应届生必答项。给出确切日期与可实习时长，并强调稳定性（学业安排已理顺）。",
    },
}


def build_cover_letter(data: dict, jd_text: str, role: str, company: str = "") -> str:
    basic = data.get("basic", {})
    report = match(data, jd_text)
    req = extract_jd_requirements(jd_text)
    resume_text = flatten_resume(data)

    matched_tools = report["matched"]["tools"][:5]
    matched_kw = report["matched"]["keywords"][:5]

    # 从简历里找最强的量化成果
    best = []
    for s in data.get("sections", []):
        for it in s.get("items", []) or []:
            for b in it.get("bullets", []) or []:
                # 排除「学业表现」这类非成果项与含占位符的条目
                if "学业表现" in b or "核心课程" in b:
                    continue
                if re.search(r"\d", b) and "待填" not in b:
                    best.append(b)
    best = sorted(best, key=len)[:3]
    # 若全部条目都是占位符，则退而选取不含占位符的完整 bullet
    if not best:
        for s in data.get("sections", []):
            for it in s.get("items", []) or []:
                for b in it.get("bullets", []) or []:
                    if "学业表现" in b or "核心课程" in b or "待填" in b:
                        continue
                    best.append(b)
            if len(best) >= 3:
                break
        best = best[:3]

    strengths = []
    if matched_tools:
        strengths.append("、".join(matched_tools[:4]))
    if matched_kw:
        strengths.append("、".join(matched_kw[:4]))

    # 公司称呼：默认「贵公司」，指定后用具体名称更显诚意
    org = company or "贵公司"
    # 岗位职责：取第一条并按句号截断，避免截断在半句
    resp = ""
    for r in req.get("responsibilities", []) or []:
        r = r.strip()
        if len(r) >= 8:
            resp = (r[:56] + "……") if len(r) > 56 else r
            break

    L = []
    L.append(f"# 求职信 —— {role}")
    L.append("")
    L.append(f"**应聘岗位：** {role}")
    L.append(f"**姓名：** {basic.get('name', '')}")
    contact = " / ".join(
        c.get("text", "") for c in basic.get("contact", []) if c.get("text")
    )
    if contact:
        L.append(f"**联系方式：** {contact}")
    L.append("")
    L.append("---")
    L.append("")
    L.append("敬启者：")
    L.append("")
    L.append(
        f"您好，我是{basic.get('name', '')}，{basic.get('title', '一名应届毕业生')}。"
        f"我在{org}发布的「{role}」岗位信息中了解到，"
        + (f"该岗位的核心职责是{resp}，" if resp else "")
        + f"这与我的经历方向高度契合，因此投递此岗位。"
    )
    L.append("")
    if best:
        L.append("在校期间，我主导并落地了以下工作：")
        for b in best:
            L.append(f"- {b}")
        L.append("")
    if strengths:
        L.append(
            f"这些经历让我系统掌握了{strengths[0]}"
            + (f"，并在{strengths[1]}等方面形成了可迁移的方法论。" if len(strengths) > 1 else "。")
        )
        L.append("")
    if data.get("summary"):
        L.append(f"总的来说，{data['summary']}")
        L.append("")
    L.append(
        f"我理解{role}的核心挑战在于{req.get('responsibilities', ['快速上手并稳定产出'])[0][:50] if req.get('responsibilities') else '快速上手并稳定产出'}，"
        f"这也是我希望在{org}深入学习与积累的方向。我已做好到岗准备，愿意从基础工作做起，"
        f"用可验证的结果证明价值。"
    )
    L.append("")
    L.append(f"随信附上我的简历，期待有机会与您进一步交流。感谢您抽出时间阅读此信。")
    L.append("")
    L.append("此致")
    L.append("敬礼")
    L.append("")
    L.append(f"{basic.get('name', '')}")
    L.append(f"{contact}")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 投递前自查")
    L.append("")
    L.append("- [ ] 公司名称、岗位名称已替换为准确信息")
    L.append(f"- [ ] 简历中所有【待填 / 【姓名】等占位符已替换为真实信息")
    L.append("- [ ] 引用的成果数据与简历一致")
    L.append("- [ ] 末尾联系方式准确")
    L.append(f"- [ ] 已加入 1—2 处对{org}具体业务/产品的了解（体现做过功课）")
    return "\n".join(L)


def build_interview(data: dict, jd_text: str, role: str) -> str:
    report = match(data, jd_text)
    L = []
    L.append(f"# 面试准备 —— {role}")
    L.append("")
    L.append("## 一、基于 JD 的定制问题")
    L.append("")
    L.append("这些是本岗位最可能问到的问题，请结合自身经历准备。")
    L.append("")

    # JD 中缺失但要求的能力 → 大概率被追问
    missing_hard = [
        a["item"] for a in report["priority_actions"]
        if a["level"] == "high" and a["type"] in ("skill", "cert")
    ]
    if missing_hard:
        L.append("### ⚠ 需要提前准备的说辞")
        L.append("")
        L.append("JD 明确要求但简历未体现以下内容，面试官大概率追问。**不要临场编造**，")
        L.append("正确做法是承认接触程度 + 说明学习路径与可迁移能力。")
        L.append("")
        for m in missing_hard:
            L.append(f"- **{m}** —— 准备：真实接触程度（课程/自学/项目/实习）+ 具体做过什么 + 如何快速补齐")
        L.append("")

    L.append("### 岗位业务相关")
    L.append("")
    for kw in report["matched"]["keywords"][:6]:
        L.append(f"- 你在「{kw}」方面的经验具体是什么？举一个你独立完成或主导的例子。")
    L.append("")

    L.append("### 简历薄弱点")
    L.append("")
    L.append("以下问题会直接指向简历上的薄弱环节，务必提前想好答案。")
    L.append("")
    weak = [a["item"] for a in report["priority_actions"] if a["level"] == "high"]
    if weak:
        for w in weak:
            L.append(f"- 关于「{w}」，你实际到什么程度？")
    else:
        L.append("- 简历经历较少时，面试官会追问：这段实习中你个人独立负责的部分是什么？和团队的分工？")
    L.append("")

    L.append("## 二、通用高频问题")
    L.append("")
    for name, item in QUESTION_BANK.items():
        L.append(f"### {item['q']}")
        L.append(f"**回答框架：** {item['frame']}")
        L.append("")

    L.append("## 三、面试前 30 分钟检查清单")
    L.append("")
    L.append("- [ ] 简历打印 3 份纸质版（万一现场要简历）")
    L.append("- [ ] 能用 90 秒讲完自我介绍")
    L.append("- [ ] 每段实习都能说清：背景 / 我做了什么 / 结果 / 收获")
    L.append("- [ ] 简历上的每个数字都记得来龙去脉")
    L.append("- [ ] 准备好 2 个反问问题（如「团队目前主要在做什么方向」「新人前三个月如何上手」）")
    L.append("- [ ] 提前测试线上会议设备与网络")
    L.append("")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="求职信与面试准备")
    ap.add_argument("resume")
    ap.add_argument("jd")
    ap.add_argument("--out", help="输出 Markdown 路径")
    ap.add_argument("--role", default="", help="岗位名称，默认从 JD 推断")
    ap.add_argument("--company", default="", help="公司名称，默认用「贵公司」")
    ap.add_argument("--interview", action="store_true", help="同时生成面试准备清单")
    args = ap.parse_args()

    data = json.loads(Path(args.resume).read_text(encoding="utf-8"))
    jd_text = Path(args.jd).read_text(encoding="utf-8", errors="ignore")

    role = args.role
    if not role:
        from tailor_batch import guess_role
        role = guess_role(jd_text)

    content = build_cover_letter(data, jd_text, role, args.company)
    if args.interview:
        content += "\n\n" + build_interview(data, jd_text, role)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8")
        print(f"已生成：{out}")
    else:
        print(content)
    return 0


if __name__ == "__main__":
    sys.exit(main())
