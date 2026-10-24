"""主题引擎：底板（纸面）× 配色（主色）→ 一整套协调的 CSS 变量。

设计目标
--------
1. **底板**决定「纸是什么颜色、文字什么颜色」：纯白 / 米白 / 雾灰 / 苔绿 / 深墨。
2. **配色**只决定「主色是什么」：靛蓝 / 青碧 / 赭红 / 紫罗兰 / 琥珀 / 石墨 / 绛红。
3. 两者任意组合都自动派生出配套的浅底、描边、胶囊色 —— 不需要人工配对。
4. **深色底板必须整套反色**：文字、分割线、面板、胶囊全部翻转，否则读不了。

所有派生色都在这里用 Python 算好再注入 CSS：
- 不依赖 color-mix()（老版本 Chromium 不支持）
- 不依赖浏览器渲染差异，PDF 与 Word 完全一致

用法：
    from theme import resolve_theme, SURFACES, PALETTES
    theme = resolve_theme(surface="ink", palette="indigo")
    css = theme.to_css()
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# 颜色工具
# --------------------------------------------------------------------------


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        raise ValueError(f"非法颜色值：{value}")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def mix(color_a: str, color_b: str, ratio: float) -> str:
    """把 color_a 按 ratio 混入 color_b。

    ratio=0 → 全是 color_b；ratio=1 → 全是 color_a。
    """
    a = _hex_to_rgb(color_a)
    b = _hex_to_rgb(color_b)
    blended = tuple(round(a[i] * ratio + b[i] * (1 - ratio)) for i in range(3))
    return _rgb_to_hex(blended)


# --------------------------------------------------------------------------
# 对比度（WCAG 2.1 相对亮度公式）
# --------------------------------------------------------------------------

# sRGB → 线性化阈值
_SRGB_THRESHOLD = 0.03928


def _channel_luminance(v: int) -> float:
    c = v / 255.0
    if c <= _SRGB_THRESHOLD:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(color: str) -> float:
    r, g, b = _hex_to_rgb(color)
    return (
        0.2126 * _channel_luminance(r)
        + 0.7152 * _channel_luminance(g)
        + 0.0722 * _channel_luminance(b)
    )


def contrast_ratio(fg: str, bg: str) -> float:
    """前景色与背景色的对比度。1.0 = 完全同色，21 = 黑白。"""
    l1 = relative_luminance(fg)
    l2 = relative_luminance(bg)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


def readable_on(color: str, bg: str, min_ratio: float = 4.5) -> str:
    """把 color 调整到在 bg 上可读（对比度 ≥ min_ratio）。

    - bg 是深色 → 把 color 往白色方向提亮
    - bg 是浅色 → 把 color 往黑色方向压暗

    为什么要这一步：主色是为「色块/描边」设计的，不一定适合当文字色。
    靛蓝 #1F3A5F 在深墨底板 #12141A 上对比度只有 1.6:1，
    直接拿来当分区标题色就等于看不见。
    """
    if contrast_ratio(color, bg) >= min_ratio:
        return color

    target = "#FFFFFF" if relative_luminance(bg) < 0.5 else "#000000"
    # mix(a, b, ratio) 里 ratio 是「保留多少 a」，所以要从 1.0 往 0 递减，
    # 越递减越接近 target。步长取 0.02 —— 步子大了会明显改变原色观感。
    best = target
    ratio = 1.0
    while ratio > 0.02:
        candidate = mix(color, target, ratio)
        best = candidate
        if contrast_ratio(candidate, bg) >= min_ratio:
            return candidate
        ratio -= 0.02
    return best


def lift_for_dark(color: str, paper: str, ink: str, min_ratio: float = 3.0) -> str:
    """深色底板上把主色提亮到「色块可见」的程度。

    深墨底板上，靛蓝 #1F3A5F 与纸面 #12141A 对比度只有 1.6:1，
    用它画 1mm 宽的分隔色条几乎等于没画。
    提亮时混入的是底板自己的 ink 色（而不是纯白），保住色相不跑偏。
    """
    if contrast_ratio(color, paper) >= min_ratio:
        return color
    best = color
    ratio = 1.0
    while ratio > 0.02:
        candidate = mix(color, ink, ratio)
        best = candidate
        if contrast_ratio(candidate, paper) >= min_ratio:
            return candidate
        ratio -= 0.02
    return best


def pick_on_color(bg: str) -> str:
    """在 bg 上放文字，选对比度更高的黑或白。"""
    return "#FFFFFF" if contrast_ratio("#FFFFFF", bg) >= contrast_ratio("#000000", bg) else "#12141A"


# --------------------------------------------------------------------------
# 底板（纸面）
# --------------------------------------------------------------------------

SURFACES: dict[str, dict] = {
    "white": {
        "label": "纯白",
        "desc": "标准 A4 白纸，ATS 与打印最稳，通用首选。",
        "paper": "#FFFFFF",
        "ink": "#1A1A1A",
        "ink_soft": "#404040",
        "ink_mute": "#6E6E6E",
        "rule": "#D6DCE3",
        "panel": "#F4F6F9",
        "dark": False,
    },
    "ivory": {
        "label": "米白",
        "desc": "带一点暖调的纸面，比纯白更柔和，适合打印与文艺/内容岗。",
        "paper": "#FBF8F2",
        "ink": "#221E18",
        "ink_soft": "#4A443A",
        "ink_mute": "#7A7263",
        "rule": "#E2DACB",
        "panel": "#F4EFE5",
        "dark": False,
    },
    "mist": {
        "label": "雾灰",
        "desc": "冷调浅灰蓝纸面，衬托深蓝主色，科技感强。",
        "paper": "#F4F6F9",
        "ink": "#16191C",
        "ink_soft": "#3C4248",
        "ink_mute": "#6C737B",
        "rule": "#DCE2E9",
        "panel": "#EAEEF3",
        "dark": False,
    },
    "sage": {
        "label": "苔绿",
        "desc": "低饱和绿灰纸面，环保/教育/公益行业观感好。",
        "paper": "#F1F5EF",
        "ink": "#1A211A",
        "ink_soft": "#3E4A3C",
        "ink_mute": "#6E7A6B",
        "rule": "#D7E0D3",
        "panel": "#E8EFE5",
        "dark": False,
    },
    "ink": {
        "label": "深墨",
        "desc": "深色底板，文字与分割线整套反色。适合作品集与设计岗，"
                "但打印耗墨、部分 ATS 截图预览会失真，线上投递需另备浅色版。",
        "paper": "#12141A",
        "ink": "#ECEEF2",
        "ink_soft": "#B9BFC9",
        "ink_mute": "#868D99",
        "rule": "#2A2F3A",
        "panel": "#1B1F27",
        "dark": True,
    },
}

# --------------------------------------------------------------------------
# 配色（主色）
# --------------------------------------------------------------------------

PALETTES: dict[str, dict] = {
    "indigo": {
        "label": "靛蓝",
        "desc": "沉稳专业，金融/国企/外企通用。",
        "accent": "#1F3A5F",
        "accent2": "#4A6FA5",
    },
    "teal": {
        "label": "青碧",
        "desc": "清透现代，互联网/产品/运营岗主流。",
        "accent": "#0F6E8C",
        "accent2": "#3FA7C4",
    },
    "clay": {
        "label": "赭红",
        "desc": "温暖有质感，内容/品牌/文化岗。",
        "accent": "#B04A2F",
        "accent2": "#D98060",
    },
    "plum": {
        "label": "紫罗兰",
        "desc": "创意出彩，设计/创意/互联网产品岗。",
        "accent": "#5B3E8E",
        "accent2": "#9179C4",
    },
    "amber": {
        "label": "琥珀",
        "desc": "明快亲和，运营/活动/销售岗。",
        "accent": "#A86A12",
        "accent2": "#D99A3E",
    },
    "graphite": {
        "label": "石墨",
        "desc": "近乎无彩，极简克制，学术与高端咨询风。",
        "accent": "#33373D",
        "accent2": "#6E737B",
    },
    "crimson": {
        "label": "绛红",
        "desc": "醒目有冲击力，赛事/创业/市场岗。",
        "accent": "#A32236",
        "accent2": "#D0576B",
    },
}


# --------------------------------------------------------------------------
# 主题对象
# --------------------------------------------------------------------------


class Theme:
    """一套可直接注入 CSS 的颜色变量。"""

    def __init__(self, surface: str, palette: str, accent_override: str | None = None):
        if surface not in SURFACES:
            raise KeyError(f"未知底板：{surface}，可选：{', '.join(SURFACES)}")
        if palette not in PALETTES:
            raise KeyError(f"未知配色：{palette}，可选：{', '.join(PALETTES)}")

        self.surface = surface
        self.palette = palette
        s = SURFACES[surface]
        p = PALETTES[palette]

        self.paper = s["paper"]
        self.ink = s["ink"]
        self.ink_soft = s["ink_soft"]
        self.ink_mute = s["ink_mute"]
        self.rule = s["rule"]
        self.panel = s["panel"]
        self.dark = s["dark"]

        self.accent = (accent_override or p["accent"]).strip().lstrip("#")
        self.accent = "#" + self.accent.upper()
        self.accent2 = p["accent2"]

        # 深色底板上，原主色往往与纸面对比不足：
        # 靛蓝 #1F3A5F 在深墨 #12141A 上只有 1.6:1，
        # 拿来画色块等于没画、拿来写字等于看不清。
        # 这里先把主色提亮到「色块可见」的程度（≥3:1），
        # 再单独算一个「文字可读」（≥4.5:1）的版本。
        # 浅色底板完全不受影响 —— 原主色对比度本来就够。
        if self.dark:
            self.accent = lift_for_dark(self.accent, self.paper, self.ink, min_ratio=3.0)
            self.accent2 = lift_for_dark(self.accent2, self.paper, self.ink, min_ratio=3.0)

        # 文字专用色：主色按「在纸上可读」的规则调整过。
        # 色块/描边用 accent，文字用 accent-text —— 两者分开才不会出现
        # 「深墨底板上分区标题看不见」这种问题。
        self.accent_text = readable_on(self.accent, self.paper, min_ratio=4.5)
        self.accent2_text = readable_on(self.accent2, self.paper, min_ratio=3.0)

        # 派生色：主色向纸面靠拢。深色底板时纸面本身是深色，
        # 于是浅底自动变深底，规则天然成立。
        #
        # 但 sRGB 线性混合在深色纸面上有两个问题：
        #   1. 感知更弱 —— 白纸上 10% 主色的 tint 明显可见，黑纸上几乎看不出层次
        #   2. 色相被吃掉 —— 主色混向近黑的纸面后会褪成灰色，
        #      「蓝灰色块」变成「灰块」，观感与浅底板完全不同
        #
        # 所以深色底板做两件事：
        #   1. 放大混合比（保住色相）
        #   2. 给「承担结构」的派生色设可见下限（对比度阈值），
        #      低于下限就继续加大混合比 —— 保证它在深底上真的看得见。
        # 浅色底板完全不受影响：原始混合比与已确认的观感一致。
        if self.dark:
            def tint(ratio: float, min_ratio: float = 0.0) -> str:
                r = ratio
                best = mix(self.accent, self.paper, r)
                # 逐步加大主色占比，直到色块在纸面上达到可见下限
                while r < 0.92:
                    if contrast_ratio(best, self.paper) >= min_ratio:
                        break
                    r += 0.03
                    best = mix(self.accent, self.paper, r)
                return best

            # accent_soft：斜切色块尾段与摘要竖线 —— 要看得见，也要保留色相
            self.accent_soft = tint(0.18, min_ratio=1.35)
            # accent_line：描边与分隔线 —— 结构线，必须清楚
            self.accent_line = tint(0.40, min_ratio=1.60)
            # 分区标题底带：可以含蓄，但不能消失
            self.sec_h_bg = tint(0.14, min_ratio=1.18)
            # 技能胶囊底：含蓄底色
            self.chip_bg = tint(0.12, min_ratio=1.12)
            # 技能胶囊描边：结构边
            self.chip_border = tint(0.30, min_ratio=1.40)
            # 圆角卡片底（geo 风格）：几何块底
            self.card_bg = tint(0.16, min_ratio=1.16)
        else:
            self.accent_soft = mix(self.accent, self.paper, 0.10)
            self.accent_line = mix(self.accent, self.paper, 0.34)
            self.sec_h_bg = mix(self.accent, self.paper, 0.07)
            self.chip_bg = mix(self.accent, self.paper, 0.06)
            self.chip_border = mix(self.accent, self.paper, 0.17)
            # 卡片底：比纯纸面略深一点的浅色块，用于「几何圆角」这类分区卡片
            self.card_bg = mix(self.accent, self.paper, 0.045)
        # 反白文字：色块上的文字用。
        # 深色底板上主色被提亮后，白字可能不够清楚 —— 按对比度自动选黑或白。
        self.on_accent = pick_on_color(self.accent) if self.dark else "#FFFFFF"

    def to_css(self) -> str:
        """输出 CSS 变量声明块。"""
        rows = [
            ("--paper-bg", self.paper),
            ("--ink", self.ink),
            ("--ink-soft", self.ink_soft),
            ("--ink-mute", self.ink_mute),
            ("--rule", self.rule),
            ("--panel", self.panel),
            ("--accent", self.accent),
            ("--accent-text", self.accent_text),
            ("--accent-2", self.accent2),
            ("--accent-2-text", self.accent2_text),
            ("--accent-soft", self.accent_soft),
            ("--accent-line", self.accent_line),
            ("--sec-h-bg", self.sec_h_bg),
            ("--chip-bg", self.chip_bg),
            ("--chip-border", self.chip_border),
            ("--card-bg", self.card_bg),
            ("--on-accent", self.on_accent),
        ]
        body = "\n".join(f"  {name}: {value};" for name, value in rows)
        return f"/* 底板 {self.surface} × 配色 {self.palette} */\nbody {{\n{body}\n}}"


def resolve_theme(
    surface: str = "white",
    palette: str = "indigo",
    accent: str | None = None,
) -> Theme:
    """解析底板 + 配色 → Theme。用户显式指定的 accent 优先于配色默认值。"""
    return Theme(surface, palette, accent_override=accent or None)


# --------------------------------------------------------------------------
# 密度档：按内容体量自动选择排版密度
# --------------------------------------------------------------------------

# 密度档不再直接写最终值，只写「系数」。
# 风格 CSS 决定基值（--*-base），密度档决定系数（--*-scale），
# 两者分层正交，任何注入顺序都不会互相覆盖。
#
# 系数由实测定标：把同一份内容渲染到 A4 后测量正文底边位置，
# 反推各档在「典型应届生简历」下的实际容量。
DENSITY_TIERS = [
    # (档位名, 行距系数, 分区间距系数, 条目间距系数, 页边距系数, 字号系数)
    ("airy",    1.05, 1.20, 1.15, 1.08, 1.000),
    ("normal",  1.00, 1.00, 1.00, 1.00, 1.000),
    ("compact", 0.93, 0.68, 0.72, 0.86, 0.972),
    ("dense",   0.87, 0.54, 0.58, 0.76, 0.952),
    ("tight",   0.80, 0.30, 0.30, 0.62, 0.952),
]

# 各档在 A4 上的「估算行容量」——由实测定标（渲染到 A4 后测正文底边 + PDF 页数）。
# 实测对照（elite 模板）：
#   短案例 est 34.6 → airy  84.5% 单页 / normal 80.4% / compact 72.4%
#   长案例 est 53.2 → dense 98.0% 溢出2页 / tight 93.7% 单页
# 容量表的含义是「该档能舒适容纳多少估算行」，据此自宽松向紧凑试档。
DENSITY_CAPACITY = {
    "airy":    40.0,
    "normal":  46.0,
    "compact": 49.0,
    "dense":   51.5,
    "tight":   70.0,
}


def _estimate_lines(data: dict) -> float:
    """估算内容会占多少行。用于挑选排版密度档。

    经验系数来自实际渲染比对：
    - 一条 bullet 通常占 1 行（超过 48 字会折成 2 行，此处按平均折算）
    - 一个条目标题占 1 行 + 与上一条的间隔
    - 技能胶囊每 4 个占 1 行
    """
    import math

    total = 0.0

    summary = (data.get("summary") or "").strip()
    if summary:
        total += math.ceil(len(summary) / 46)

    for section in data.get("sections", []):
        stype = section.get("type", "entries")
        total += 1.9  # 分区标题 + 分区间距

        if stype == "skills":
            for group in section.get("groups") or []:
                total += 1.4
                total += len(group.get("items") or []) * 0.42
        elif stype == "list":
            for it in section.get("items") or []:
                text = it if isinstance(it, str) else (it.get("text") or "")
                total += 0.8 + (len(text) // 60) * 0.5
        elif stype == "text":
            total += math.ceil(len(section.get("text") or "") / 46)
        else:
            for item in section.get("items") or []:
                total += 2.6  # 条目标题 + 间隔
                for b in item.get("bullets") or []:
                    total += 1.0 + (len(b) // 48) * 0.5

    return total


def pick_density(data: dict) -> str:
    """根据内容体量挑选排版密度档。

    策略：从最宽松档开始，选第一个「装得下」且留有余量的档。
    装不下就往紧一档走。

    容量表 DENSITY_CAPACITY 由实测定标（渲染到 A4 后测正文底边位置）：
    - 短案例（3 条经历 / 9 bullet / 8 胶囊）→ 估算 34.6 行 → airy，填充率 84.5%，单页
    - 长案例（6 条目 / 16 bullet / 15 胶囊）→ 估算 53.2 行 → 需 compact 以上，否则溢出到第 2 页

    注意：不能一味选最宽松档 —— 内容少时 airy 会让页面下半截大片留白；
    也不能一味选最紧档 —— 会挤成一团。容量表就是这两者之间的平衡点。
    """
    est = _estimate_lines(data)

    # 留 4% 余量：正文底边不要贴到页面下缘
    for name, *_ in DENSITY_TIERS:
        if est <= DENSITY_CAPACITY[name] * 0.96:
            return name

    # 都装不下：用最紧的档，并提示用户精简内容
    return DENSITY_TIERS[-1][0]


