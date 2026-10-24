"""HTML → PDF：调用本机 Chromium 内核（Edge / Chrome / Brave）无头打印为 A4 PDF。

用法：
    python html_to_pdf.py resume.html resume.pdf

要点：
- 优先使用系统已安装的浏览器内核，无需下载额外依赖。
- 强制 --print-to-pdf-no-header，避免浏览器默认页眉页脚污染简历。
- 输出为「文本型 PDF」（真实可选中的文字），ATS 可解析；不是图片型 PDF。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _console  # noqa: F401  (UTF-8 控制台兜底)

BROWSER_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/microsoft-edge",
]


def find_browser() -> str | None:
    for p in BROWSER_CANDIDATES:
        if Path(p).exists():
            return p
    for name in ("msedge", "chrome", "brave", "google-chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    return None


def convert(html_path: Path, pdf_path: Path, timeout: int = 90) -> bool:
    browser = find_browser()
    if not browser:
        print(
            "[resume-crafter] 未找到可用的 Chromium 内核浏览器（Edge/Chrome/Brave）。\n"
            "  请手动用浏览器打开 HTML 后「打印 → 另存为 PDF」，或安装 Edge/Chrome。",
            file=sys.stderr,
        )
        return False

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    url = html_path.resolve().as_uri()

    with tempfile.TemporaryDirectory(prefix="resume_pdf_") as profile:
        cmd = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            f"--user-data-dir={profile}",
            "--no-pdf-header-footer",
            "--print-to-pdf-no-header",
            "--virtual-time-budget=8000",
            f"--print-to-pdf={pdf_path.resolve()}",
            url,
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, timeout=timeout, check=False
            )
        except subprocess.TimeoutExpired:
            print("[resume-crafter] 浏览器渲染超时", file=sys.stderr)
            return False

    if not pdf_path.exists() or pdf_path.stat().st_size < 1000:
        err = (proc.stderr or b"").decode("utf-8", "ignore")[:500]
        print(f"[resume-crafter] PDF 生成失败：{err}", file=sys.stderr)
        return False
    return True


def main() -> int:
    if len(sys.argv) < 3:
        print("用法：python html_to_pdf.py <input.html> <output.pdf>", file=sys.stderr)
        return 2
    html_path = Path(sys.argv[1]).resolve()
    pdf_path = Path(sys.argv[2]).resolve()
    if not html_path.exists():
        print(f"找不到输入文件：{html_path}", file=sys.stderr)
        return 2
    if convert(html_path, pdf_path):
        print(f"已生成 PDF: {pdf_path}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
