# 贡献指南

感谢你考虑为 resume-crafter 做贡献。

## 开发环境

```bash
git clone https://github.com/<your-name>/resume-crafter.git
cd resume-crafter
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

提交前请务必跑通：

```bash
python scripts/doctor.py        # 环境自检
python scripts/selftest.py      # 端到端回归测试（必须全部通过）
```

## 代码约定

- **注释与文档字符串用中文**，与现有代码风格保持一致。
- **纯文本优先**：任何新增的视觉元素都不得产生额外文本层，否则会破坏 ATS 解析。
- **样式与内容分离**：样式改动只动 `assets/templates/`，内容改动只动数据模型。
- **绝不硬编码本机路径**：使用 `Path.home()` / `Path(__file__).parent` 等相对定位方式。
- **跨平台**：新脚本需同时兼容 Windows / macOS / Linux。路径拼接用 `pathlib`，不要手拼字符串。

## 新增排版风格

1. 在 `assets/templates/` 新建 `style-<名字>.css`，只写与 `base.css` 的差异部分。
2. 在 `scripts/render_resume.py` 的 `STYLES` 字典中注册，并填写 `ats` 布尔值与描述。
3. 在 `scripts/doctor.py` 的 `REQUIRED_TEMPLATES` 中登记文件名。
4. 在 `scripts/selftest.py` 的风格渲染测试中登记。
5. 在 `README.md` 的风格表格中补一行。
6. 运行 `python scripts/selftest.py` 确认无回归。

> 双栏风格（`sidebar` / `soft` / `creative`）必须标注 `ats: false`，且 Skill 会强制额外产出一份单栏版作为投递兜底。

## 外观体系的两条分层铁律

外观由 **版式 × 底板 × 配色 × 密度** 四个正交维度组合而成。
新增样式时必须遵守下面两条，否则某一维度会静默失效。

### 铁律一：排版节奏分「基值」与「系数」两层

```
风格 CSS   →  基值   --lh-base / --gap-section-base / --gap-entry-base / --pad-y-base / --fs-body-base
密度档      →  系数   --lh-scale / --gap-section-scale / ...
最终值      →  body 上用 calc(基值 × 系数) 派生
```

**为什么**：`body.tpl-elite` 与 `body.dens-normal` 的 CSS 特异性完全相同（都是 0,1,1），
后注入者胜。若风格直接写死 `--lh`，就会把密度档覆盖掉，
「密度自动分档」形同虚设 —— 而且不报错，只是排版悄悄不对。

**还有一处易错**：派生变量必须声明在 `body` 上，不能写在 `:root`。
因为 CSS 自定义属性的 `var()` 在「声明它的元素」上求值，
写在 `:root` 时 body 上的 `--lh-base` 覆盖根本读不到。

`doctor.py` 会自动检查这两点。

### 铁律二：主色分「色块用」与「文字用」两套

```
--accent        色块、描边、分隔条    对纸面对比度 ≥ 3:1
--accent-text   分区标题、标签、正文强调 对纸面对比度 ≥ 4.5:1
```

**为什么**：主色是为色块设计的，不一定能直接当文字色。
靛蓝 `#1F3A5F` 在深墨底板 `#12141A` 上对比度只有 1.6:1，
直接当分区标题色等于看不见。

`theme.py` 会自动做这件事：深色底板上把主色提亮到 ≥3:1（混入底板自己的 ink 色以保住色相），
再单独算一个 ≥4.5:1 的文字色。浅色底板完全不动主色 —— 改动会破坏已确认的观感。

**新增深色底板时不要手工写死派生色**：深色底板的派生色混合比会自动放大 2 倍
（黑纸上 10% 的 tint 几乎不可见，不放大胶囊描边会整个消失）。
手工写死就绕过了这套机制。

## 新增底板或配色

在 `scripts/theme.py` 的 `SURFACES` / `PALETTES` 字典中追加即可，派生色阶与对比度校准全自动完成。
新增后运行 `python scripts/selftest.py` —— 35 种底板 × 配色组合都会被断言。

## 新增证件照规格

在 `scripts/photo.py` 的 `PHOTO_SIZES` 中补充，注明对应的像素比例来源。

## 提交信息

用中文或英文均可，格式参考 Conventional Commits：

```
feat(elite): 新增精英几何排版风格
fix(photo): 修复一寸照片在双栏风格下尺寸错乱
docs(readme): 补充批量定制用法
```

## 报告 Bug

请在 Issue 中提供：

- 操作系统与 Python 版本
- 使用的风格与命令
- 复现步骤
- 完整报错输出

## 许可

提交即表示你同意你的贡献以 [MIT 许可证](LICENSE) 发布。
