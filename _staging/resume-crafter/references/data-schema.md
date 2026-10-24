# 数据格式定义

简历 JSON 是本技能的**唯一事实来源**。HTML / PDF / DOCX 三种产物都由它渲染，因此改 JSON 再重新构建即可同步更新所有格式。

---

## 顶层结构

```json
{
  "meta":   { ... },   // 元信息：版式、底板、配色、密度
  "basic":  { ... },   // 基本信息：姓名、身份标签、联系方式
  "summary": "……",    // 个人简介（纯文本，可选）
  "sections": [ ... ]  // 内容分区列表
}
```

---

## meta

外观由四个正交维度决定：`style`（版式）× `surface`（底板）× `palette`（配色）+ `density`（密度）。

| 字段 | 类型 | 说明 |
|---|---|---|
| `style` | string | 版式：`classic` / `modern` / `sidebar` / `academic` / `creative` / `elite` / `neon` / `soft` / `geo` |
| `surface` | string | 底板：`white` / `ivory` / `mist` / `sage` / `ink`，默认 `white` |
| `palette` | string | 配色：`indigo` / `teal` / `clay` / `plum` / `amber` / `graphite` / `crimson`，默认取版式的默认配色 |
| `density` | string | 密度：`airy` / `normal` / `compact` / `dense` / `tight`，**省略则按内容体量自动选档** |
| `accent` | string | 手工指定主色，如 `#1F3A5F`。**仅在未指定 `surface` / `palette` 时生效** |
| `target_role` | string | 目标岗位，仅作记录，不影响渲染 |
| `lang` | string | 预留 |

### 优先级规则

```
命令行 --style/--surface/--palette/--density  >  JSON meta  >  风格默认值
```

`meta.style` 为**无效键**时（例如早期遗留的 `"ats-classic"`）不会让构建失败，
而是回落到「按内容/JD 自动推断」，再兜底到 `classic`。

**关于 `accent`**：只要 `surface` 或 `palette` 被显式指定（命令行参数或 JSON meta），
`accent` 就不再生效 —— 这样一份数据可以直接复用多套外观，
而不会被 JSON 里遗留的旧 `accent` 全部渲染成同一个颜色。

需要固定主色时，两种做法：
- 用 `meta.palette`（推荐，能派生整套协调色阶）
- 删掉 `meta.surface` / `meta.palette`，只留 `meta.accent`

---

## basic

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | string | **必填**，姓名 |
| `title` | string | 身份标签，如「电子商务专业 · 2027 届本科」「电商运营实习生」 |
| `contact` | array | 联系方式对象数组 |

### contact 元素

```json
{ "type": "phone", "text": "138-0000-0000" }
```

`type` 可取：`phone` / `email` / `location` / `link` / `wechat` / `other`。
`text` 是实际显示的文本（**必须是可解析的完整值**，如 `138-0000-0000`、`zhangsan@example.com`，不要写「电话如下」）。
多个联系方式之间自动用 `·` 分隔。

---

## summary

字符串，60—120 字最佳。写清「我是谁 + 做过什么 + 会什么」，避免空话。

---

## sections

数组。每个元素：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string | 是 | 分区标识，用于锚点与程序引用 |
| `title` | string | 是 | 分区显示名。**必须用 ATS 标准词** |
| `type` | string | 是 | `experience` / `project` / `education` / `skills` / `list` / `text` |
| `items` | array | 视类型 | 条目数组（`text` 类型除外） |
| `groups` | array | 仅 `skills` | 技能分组 |
| `text` | string | 仅 `text` | 纯文本内容 |

### type = experience / project / education

```json
{
  "id": "experience",
  "title": "实习经历",
  "type": "experience",
  "items": [
    {
      "org": "苏州某某电子商务有限公司",
      "role": "电商运营实习生",
      "location": "苏州",
      "start": "2025.07",
      "end": "2025.09",
      "bullets": [
        "接管天猫店铺日常运营，通过重排选品结构与详情页 A/B 测试，将单品转化率由 1.8% 提升至 2.6%"
      ],
      "note": "可选项，显示在标题下方的灰色小字"
    }
  ]
}
```

| 字段 | 说明 |
|---|---|
| `org` | 组织名（公司/学校/项目名） |
| `role` | 职位名或学位名 |
| `location` | 地点 |
| `start` / `end` | 起止时间。`end` 留空自动显示「至今」 |
| `bullets` | 描述数组 |
| `note` | 附加说明（灰色小字） |
| `title_first` | `true` 时显示为「职位 \| 组织」（默认）；`false` 时显示为「组织 \| 职位」（教育类常用） |

**显示逻辑**：`start` 与 `end` 之间用 ` — ` 连接；只有 `start` 时自动补「至今」。

### type = skills

```json
{
  "id": "skills",
  "title": "专业技能",
  "type": "skills",
  "groups": [
    { "label": "数据与工具", "items": ["Excel（数据透视表、函数建模）", "SPSS", "Axure", "SQL 基础"] },
    { "label": "运营能力", "items": ["选品与市场分析", "店铺后台与千牛", "活动策划与文案"] }
  ]
}
```

`label` 为空则只显示条目。条目用「、」连接，同组自动换行。

### type = list

用于奖项、证书、语言能力等。

```json
{
  "id": "awards",
  "title": "荣誉奖项",
  "type": "list",
  "items": [
    { "text": "校级一等奖学金（2024—2025 学年）", "date": "2025" },
    { "text": "全国大学生电子商务三创赛校赛一等奖" }
  ]
}
```

也可直接写字符串数组：`["校级一等奖学金", "三创赛校赛一等奖"]`。

### type = text

```json
{ "id": "self_eval", "title": "自我评价", "type": "text", "text": "内容……" }
```

---

## 分区在双栏风格中的归属

`sidebar` / `creative` / `soft` 风格会自动分配：

- **侧栏**（`skills` `certificates` `languages` `interests` `contact_extra`）
- **主栏**（`experience` `project` `education` `awards` `publications` 及其他）

如需强制指定，在分区加 `"placement": "side"` 或 `"placement": "main"`：

```json
{ "id": "education", "title": "教育经历", "type": "education", "placement": "side", "items": [ ... ] }
```

`placement` 只在双栏风格下有意义，单栏风格会忽略它（内容仍正常渲染，不会重复）。

---

## 校验

构建前可运行质检：

```bash
python scripts/lint_resume.py resume.json --style classic
```

会检查：姓名与联系方式完整性、分区名是否符合 ATS 标准、分区顺序、bullet 是否缺量化、弱化动词、篇幅、装饰性字符。
