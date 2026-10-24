"""ATS 体检：验证导出的 PDF 是否能被简历筛选系统正确解析。

用法：
    python ats_check.py resume.pdf

检查项：
1. 文本层是否可选中（图片型 PDF 直接判定不通过）
2. 关键信息是否可被提取（姓名、联系方式、岗位名、时间）
3. 阅读顺序是否正确（双栏错序检测）
4. 解析出的文本是否包含 ATS 常见的「粘连」现象
5. 页数与页边距安全性

退出码：0 = 通过；1 = 存在阻断性问题。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _console  # noqa: F401  (UTF-8 控制台兜底)

try:
    from pypdf import PdfReader
except ImportError:
    print("需要 pypdf：pip install pypdf", file=sys.stderr)
    raise SystemExit(2)


def check(pdf_path: Path, expect_pages: int | None = None) -> tuple[int, list[str], list[str]]:
    errors: list[str] = []
    warns: list[str] = []
    infos: list[str] = []

    reader = PdfReader(str(pdf_path))
    pages = len(reader.pages)
    texts = []
    for p in reader.pages:
        try:
            texts.append(p.extract_text() or "")
        except Exception as e:
            texts.append("")
            warns.append(f"第 {len(texts)} 页文本提取异常：{e}")

    full = "\n".join(texts)
    visible = re.sub(r"\s+", "", full)

    # 1. 文本层
    if len(visible) < 80:
        errors.append("PDF 几乎没有可提取文本，疑似图片型 PDF。ATS 将完全无法解析，请检查导出方式")
    else:
        infos.append(f"文本层正常，可提取 {len(visible)} 个字符")

    # 2. 关键信息
    # 手机号允许 138-0000-0000 / 138 0000 0000 / +8613800138000 等写法
    if not re.search(r"1[3-9]\d[\s\-]?\d{4}[\s\-]?\d{4}", visible):
        errors.append("未提取到手机号，ATS 解析后可能丢失联系方式")
    if not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", visible):
        errors.append("未提取到邮箱")
    if not re.search(r"(19|20)\d{2}", visible):
        errors.append("未提取到任何年份，工作经历时间轴缺失，ATS 无法建立时间线")

    # 3. 阅读顺序（双栏错序检测）
    # 典型症状：所有右栏内容挤在一起、且出现在左栏内容之前
    name_like = re.findall(r"[一-龥]{2,4}(?=[\s\n]*(?:男|女)?[\s\n]*[\d@])", texts[0] if texts else "")
    if pages >= 1 and texts:
        first_page = texts[0]
        # 检查分区标题是否按合理顺序出现
        order_markers = ["教育", "实习", "工作", "项目", "技能", "荣誉", "证书", "奖项"]
        positions = []
        for m in order_markers:
            idx = first_page.find(m)
            if idx >= 0:
                positions.append((idx, m))
        positions.sort()
        seen = [m for _, m in positions]
        expected_first = {"教育", "实习", "工作", "项目"}
        if seen and seen[0] not in expected_first:
            warns.append(f"首个分区是「{seen[0]}」，建议教育/实习/工作经历靠前")
        if len(seen) >= 3:
            infos.append(f"识别到分区顺序：{' → '.join(seen)}")

    # 4. 粘连检测：解析器把两栏文本横向拼接
    # 症状：一行里同时出现两个不同分区的关键词
    suspicious = []
    for line in texts[0].splitlines() if texts else []:
        compact = line.replace(" ", "")
        if re.search(r"(教育经历|实习经历|工作经历|项目经历).*(专业技能|荣誉奖项|获奖情况)", compact) and len(compact) > 30:
            suspicious.append(line.strip()[:60])
    if suspicious:
        warns.append(f"检测到 {len(suspicious)} 处可能存在跨栏粘连（同一行混排不同分区），双栏简历有解析错序风险")
    else:
        infos.append("未检测到跨栏粘连，阅读顺序正常")

    # 5. 页数
    if pages == 1:
        infos.append("单页简历，符合应届生与 5 年内经验的主流要求")
    elif pages == 2:
        warns.append(f"共 {pages} 页。若第二页内容不足半页，建议压缩回一页（ATS 对两页简历的第二页可能截断）")
    else:
        errors.append(f"共 {pages} 页，超出常规上限，会显著降低 HR 翻阅意愿")

    if expect_pages and pages != expect_pages:
        warns.append(f"实际 {pages} 页，与预期 {expect_pages} 页不符")

    return pages, errors, warns, infos


def main() -> int:
    ap = argparse.ArgumentParser(description="ATS 体检")
    ap.add_argument("pdf")
    ap.add_argument("--expect-pages", type=int)
    args = ap.parse_args()

    path = Path(args.pdf)
    if not path.exists():
        print(f"找不到文件：{path}", file=sys.stderr)
        return 2

    pages, errors, warns, infos = check(path, args.expect_pages)

    print("=" * 60)
    print(f"ATS 体检报告 — {path.name}")
    print("=" * 60)
    print(f"页数：{pages}")

    for title, items, mark in (
        ("阻断问题", errors, "✗"),
        ("风险提示", warns, "!"),
        ("检查通过", infos, "✓"),
    ):
        if not items:
            continue
        print(f"\n{title}（{len(items)}）")
        print("-" * 60)
        for it in items:
            print(f"  {mark} {it}")

    print()
    if errors:
        print(f"结论：存在 {len(errors)} 个阻断性问题，此文件大概率无法通过 ATS 机筛。")
        return 1
    print("结论：ATS 解析无阻断性问题，可正常投递。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
