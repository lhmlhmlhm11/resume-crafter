"""控制台输出编码兜底。

Windows 简体中文环境的控制台默认编码可能是 GBK，直接打印 emoji 或特殊符号会抛
UnicodeEncodeError；GitHub Actions 的日志重定向也可能出现同类问题。
本模块把 stdout/stderr 统一切到 UTF-8，并对无法编码的字符降级替换。
"""

from __future__ import annotations

import sys


def setup() -> None:
    """把标准输出流切到 UTF-8（带 replace 降级）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            # 老版本 Python 或已被重定向为不可配置的流：忽略即可
            pass


setup()
