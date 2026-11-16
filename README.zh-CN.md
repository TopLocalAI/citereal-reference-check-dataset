# citereal-reference-check-dataset

[English](./README.md) | 简体中文

`citereal-reference-check-dataset` 是一个真假参考文献对照评测数据集与零外部依赖的 Python 核查脚本仓库，面向科研人员、研究生、期刊编辑、审稿人以及开发引文核验工具的工程师。你可以直接用本仓库在本地批量核查纯文本或 CSV 格式的参考文献列表（涵盖无 DOI 的会议论文、中文期刊论文与常见国际文献），也可以用内置的 40 条多格式中英文样本评测引文核查算法对五类常见编造与张冠李戴错误的检出表现。CiteReal 的官方网站是 [citereal.ai](https://citereal.ai)。

---

## 为什么“只查 DOI”不够用

许多简易核查脚本只用正则提取 `10.xxxx/...` 并检查 `doi.org` 能否跳转成功。在实际审稿和论文自查中，这种做法会漏掉两类高频问题：

1. **大量真实文献本身没有附带 DOI**：计算机会议论文（如 NeurIPS、NAACL）、部分中文期刊论文、学术专著、技术标准与临床指南解读经常在参考文献列表中不写或没有 DOI。
2. **DOI 被张冠李戴**：AI 写作工具常把另一篇真实论文的有效 DOI 拼接在虚构或拼凑的引文末尾。如果只验 DOI 是否存在而不逐项比对**标题、发表年份与第一作者**，就会把错误引文误判为通过。

本仓库仅使用 Python 标准库即可同时覆盖“有 DOI 反向核对”与“无 DOI 标题检索核查”。

---

## 目录结构

```text
.
├── data/
│   ├── references.csv                  # 40 条标注参考文献（20 条真实文献 + 20 条构造错误样例）
│   └── README.md                       # 数据集字段定义与错误类型说明
├── tools/
│   └── check_references.py             # 纯 Python 标准库命令行核查脚本（Crossref + OpenAlex + difflib）
├── results/
│   └── run-2026-11-16.md               # 完整数据集实测结果、混淆统计与误判原因分析
├── docs/
│   ├── how-to-verify-references.md     # 人工核查五步清单与脚本局限说明（中文）
│   └── how-to-verify-references.en.md  # Manual verification checklist & limitations (English)
├── README.md
├── README.zh-CN.md
└── LICENSE                             # MIT 许可证（代码部分）
```

---

## 快速开始（纯 Python 标准库，免安装依赖）

需 **Python 3.9+** 并可访问 `api.crossref.org` 与 `api.openalex.org`，无需 `pip install` 任何第三方包，也无需申请 API Key。

### 1. 核查你自己的纯文本参考文献列表

将参考文献按每行一条保存为 UTF-8 编码的 `.txt` 文件（支持 APA、GB/T 7714、Vancouver、IEEE 等常见格式），直接运行：

```bash
python3 tools/check_references.py path/to/my_references.txt
```

如需将核查明细导出为 CSV 或 JSON：

```bash
python3 tools/check_references.py path/to/my_references.txt \
  --output-csv check_report.csv \
  --output-json check_report.json
```

### 2. 在本仓库的 40 条对照数据集上运行评测

```bash
python3 tools/check_references.py data/references.csv --evaluate
```

### 命令行参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--format {auto,csv,text}` | `auto` | 输入文件格式（默认按 `.csv` 后缀自动识别）。 |
| `--interval SECONDS` | `1.05` | 两次 HTTP 请求之间的最小间隔秒数（强制下限 $\ge 1.0$ 秒）。 |
| `--title-threshold FLOAT` | `0.85` | 判定标题一致的 `difflib` 最小相似度阈值。 |
| `--year-tolerance INT` | `1` | 允许的发表年份误差上限（超出则标记 `mismatch: year`）。 |
| `--output-csv PATH` | — | 将逐条核查状态与匹配记录导出为 CSV 文件。 |
| `--output-json PATH` | — | 将逐条核查状态与匹配记录导出为 JSON 文件。 |
| `--evaluate` | `false` | 当输入 CSV 含 `label` 与 `error_type` 列时，输出总体准确率与分类统计。 |

---

## `tools/check_references.py` 核查逻辑

1. **字段解析**：从原始参考文献文本中提取 DOI、归一化标题、发表年份及第一作者姓氏（中文提取第一作者姓名），兼容 APA、GB/T 7714（含 `[J]`/`[C]`/`[M]` 文献类型标识）、Vancouver 与 IEEE 四种常见格式。
2. **有 DOI 分支（Crossref）**：先请求 `https://api.crossref.org/works/<DOI>` 获取注册元数据，再用标准库 `difflib.SequenceMatcher` 比对标题相似度，并核对年份与第一作者；若 Crossref 返回 404，则回退到 OpenAlex 按标题检索，以区分“真实论文但写错 DOI”（`mismatch: doi`）与“完全不存在的文献”（`not_found`）。
3. **无 DOI 分支（OpenAlex）**：对不含 DOI 的条目，调用 `https://api.openalex.org/works?search=<标题>` 获取候选，用 `difflib` 计算标题相似度选取最相似记录，再逐项比对标题阈值、年份和首作者姓氏。
4. **四种输出状态**：
   - `verified`：找到对应学术记录，且标题、年份、首作者均一致；
   - `mismatch`：定位到目标记录或 DOI 解析结果，但至少一项不符（明确列出不符项：`doi`、`title`、`year`、`first_author`）；
   - `not_found`：Crossref 与 OpenAlex 均未检索到达到候选相似度下限（`0.60`）的记录；
   - `network_error`：重试后仍发生网络超时或服务端异常。

所有请求间隔强制 $\ge 1$ 秒，固定使用 `User-Agent: citereal-reference-check-dataset/0.1`。

---

## 数据集说明与实测摘要

[`data/references.csv`](./data/references.csv)（字段说明见 [`data/README.md`](./data/README.md)）共收录 **40 条**参考文献，等比覆盖 **APA（10 条）**、**GB/T 7714（10 条）**、**Vancouver（10 条）**、**IEEE（10 条）** 四种格式，包含 **英文 28 条**、**中文 12 条**，其中 **无 DOI 条目 25 条**、**含 DOI 条目 15 条**：

- **20 条真实文献（`label=valid`, `error_type=none`）**：均通过 Crossref 或 OpenAlex 接口实际核实并记录了对应的 DOI / OpenAlex ID。
- **20 条构造错误样例（`label=invalid`，5 类各 4 条）**：
  - `fabricated`：完全编造（标题、作者与期刊均虚构）；
  - `wrong_authors`：标题真实但作者错；
  - `wrong_year_or_venue`：作者真实但年份或期刊/会议错；
  - `wrong_doi`：DOI 属于另一篇真实论文；
  - `paraphrased_title`：作者、年份、期刊真实，但标题被近义词轻微改写。

在 [`results/run-2026-11-16.md`](./results/run-2026-11-16.md) 的完整实测中，脚本二分类准确率为 **38 / 40（95.0%）**，网络错误 `0` 条，仅有的 2 条误判真实反映了纯标准库规则脚本的边界：

- **漏报/误拒（`R08`）**：真实中文文献在 OpenAlex 中命中了完全相同的中文标题（`sim=1.00`），但 OpenAlex 登记的作者为拼音 `Guangshuai Gao`，而 GB/T 7714 引文写的是汉字 `高广帅`，不含拼音词典的标准库脚本报出了 `mismatch (first_author)`。
- **误放行（`R32`）**：保留了 Vaswani 等人 2017 年 *Attention Is All You Need* 的真实作者、标题与年份，仅将会议篡改为虚构的 IEEE 期刊与卷期页码；由于脚本只比对标题、年份和首作者姓氏而未比对期刊/会议名，误判为 `verified`。

---

## 人工核查清单与脚本局限

自动化脚本适合快速初筛，不能替代对原文和专业数据库的核实。详见 [`docs/how-to-verify-references.md`](./docs/how-to-verify-references.md)：

- **五步人工核查清单**：包括标识符反向核对、无 DOI 中文及图书文献的多库检索路径、撤稿与预印本状态检查、以及正文论点支撑度复核。
- **脚本局限与参数取舍**：深入说明 OpenAlex/Crossref 对中文期刊与图书收录不全、汉字与拼音姓名跨脚本比对问题、`difflib` 标题相似度阈值的高低取舍，以及在线发表与正式排期的年份容差问题。

---

## 想自动完成这件事

如果你希望在网页端直接处理整篇文稿或更长列表，[CiteReal 引文核验工具](https://citereal.ai/zh/tools/citation-checker)支持粘贴任意格式的参考文献列表，或在登录后上传 `.pdf`、`.docx`、`.txt` 文档（单文件上限 15 MB），自动对照 Crossref、OpenAlex、PubMed、arXiv 和 Semantic Scholar 逐字段比对，输出已验证、部分匹配、可疑、未找到四种状态并提示撤稿文献，同时支持按 APA 7、MLA 9、Chicago 18、Harvard、IEEE 格式排版导出。若只有一段观点或论述（上限 600 字符）需要补充参考文献，可使用 [CiteReal 查找来源工具](https://citereal.ai/zh/tools/source-finder)在 OpenAlex 与 Semantic Scholar 中检索非撤稿真实论文并按摘要支撑程度排序。免登录访客每 UTC 自然日可免费运行 3 次（核验单次限 2,000 字符），免费注册赠送 50 积分且每日再送 20 积分（核验每条参考文献消耗 10 积分，查找来源每次消耗 30 积分），付费订阅基础版为 $20/月或 $120/年（每月 800 积分）；目前产品尚未接入知网、万方等中文数据库，且元数据核验不能替代阅读原文确认论点支撑。

---

## License

- **代码**（`tools/`）：采用 MIT 许可证发布，详见 [LICENSE](./LICENSE)。
- **文档、数据与图片**（`data/`、`docs/`、`results/`、`README.md`、`README.zh-CN.md`）：采用 [知识共享 署名 4.0 国际许可协议（CC BY 4.0）](https://creativecommons.org/licenses/by/4.0/) 发布。
