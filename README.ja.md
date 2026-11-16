# citereal-reference-check-dataset

[English](./README.md) | [简体中文](./README.zh-CN.md) | 日本語

`citereal-reference-check-dataset` は、実在する学術参考文献と破損・捏造された参考文献を対にしたオープンなベンチマークデータセットと、外部依存ゼロの Python 検証スクリプトを収録したリポジトリです。研究者、大学院生、学術誌編集者、査読者、および引用チェックワークフローを評価する開発者向けに設計されています。プレーンテキストや CSV 形式の参考文献リスト（国際会議論文、中国語論文、DOI のない文献を含む）をそのまま Crossref や OpenAlex と照合してスクリーニングできるほか、よくある 5 種類のハルシネーションやメタデータ破損パターンに対する引用検証ツールのベンチマークにも利用できます。CiteReal の公式サイトは [citereal.ai](https://citereal.ai) です。

---

## DOI のみを確認するスクリプトが不正な文献を見逃す理由

簡易的な検証スクリプトの多くは、`10.xxxx/...` の文字列だけを抽出して `doi.org` が HTTP 200 を返すかどうかを確認するにとどまります。しかし実務では、DOI のみのチェックでは次の 2 つの問題を見逃してしまいます。

1. **DOI を持たない正当な参考文献**：国際会議プロシーディングス（NeurIPS や NAACL など）、中国語の学術誌論文、書籍、技術標準、臨床コメンタリーなどは、DOI なしで参考文献リストに記載されることが珍しくありません。
2. **不一致・流用された DOI**：AI ライティング支援ツールは、捏造された文献や内容の食い違う引用に対して、無関係な実在論文の解決可能な DOI を付与することがよくあります。**タイトル、出版年、筆頭著者**を照合せずに DOI の疎通だけを確認すると、誤った引用を有効と判定してしまいます。

本リポジトリは、Python の標準ライブラリのみを用いてこの両方の問題に対処します。

---

## リポジトリ構成

```text
.
├── data/
│   ├── references.csv                  # 40 labeled references (20 valid + 20 error samples)
│   └── README.md                       # Column schema & error taxonomy documentation
├── tools/
│   └── check_references.py             # Pure Python stdlib CLI checker (Crossref + OpenAlex + difflib)
├── results/
│   └── run-2026-11-16.md               # Benchmark run report, confusion matrix & error analysis
├── docs/
│   ├── how-to-verify-references.en.md  # 5-step manual verification checklist & script limitations
│   └── how-to-verify-references.md     # 人工核查五步清单与脚本局限说明（中文）
├── README.md
├── README.zh-CN.md
└── LICENSE                             # MIT License (code)
```

---

## クイックスタート（サードパーティ依存なし）

`api.crossref.org` および `api.openalex.org` にインターネット接続できる **Python 3.9+** 環境が必要です。`pip install` や API キーは不要です。

### 1. プレーンテキストの参考文献リストを検証する

1 行につき 1 件の整形済み参考文献（APA、GB/T 7714、Vancouver、または IEEE 形式）を記述した `.txt` ファイルを用意し、以下を実行します。

```bash
python3 tools/check_references.py path/to/my_references.txt
```

必要に応じて、構造化された JSON または CSV レポートを出力できます。

```bash
python3 tools/check_references.py path/to/my_references.txt \
  --output-csv check_report.csv \
  --output-json check_report.json
```

### 2. 同梱のベンチマークデータセットで実行・評価する

```bash
python3 tools/check_references.py data/references.csv --evaluate
```

### CLI オプション

| フラグ | デフォルト | 説明 |
| --- | --- | --- |
| `--format {auto,csv,text}` | `auto` | 入力形式（`.csv` かその他の拡張子かで自動判定します）。 |
| `--interval SECONDS` | `1.05` | HTTP リクエスト間の待機時間（$\ge 1.0\text{s}$ が強制されます）。 |
| `--title-threshold FLOAT` | `0.85` | `verified` と判定するための `difflib` 正規化タイトル類似度の最小値です。 |
| `--year-tolerance INT` | `1` | `mismatch (year)` と報告するまでに許容する出版年の差です。 |
| `--output-csv PATH` | — | 各エントリの判定結果と一致レコードを CSV に保存します。 |
| `--output-json PATH` | — | 各エントリの判定結果と一致レコードを JSON に保存します。 |
| `--evaluate` | `false` | CSV に `label` 列がある場合、正解率と `error_type` 別の内訳を算出します。 |

---

## `tools/check_references.py` の仕組み

1. **フィールド抽出**：元の引用文字列を解析し、DOI、正規化タイトル、出版年、筆頭著者の姓（中国語名の場合はフルネーム）を抽出します。APA、GB/T 7714（`[J]`、`[C]`、`[M]`）、Vancouver、IEEE の各スタイルに対応しています。
2. **DOI ありの経路（Crossref）**：DOI が含まれる場合、`https://api.crossref.org/works/<DOI>` に問い合わせ、返されたレコードのタイトル（`difflib.SequenceMatcher`）、出版年、筆頭著者を引用情報と照合します。DOI が 404 を返した場合は OpenAlex のタイトル検索にフォールバックし、DOI の破損（`mismatch: doi`）と文献自体の不在（`not_found`）を区別します。
3. **DOI なしの経路（OpenAlex）**：DOI がない場合、`https://api.openalex.org/works?search=<title>` に問い合わせ、`difflib` のタイトル類似度で候補をランク付けしたうえで、タイトル類似度、出版年、筆頭著者の姓を検証します。
4. **出力される判定結果**：
   - `verified`：識別子またはタイトル検索で一致する文献が見つかり、`title`、`year`、`first_author` がすべて一致しました。
   - `mismatch`：対応するレコードまたは DOI の参照先は見つかりましたが、不一致となった具体的なフィールド（`doi`、`title`、`year`、`first_author`）が報告されます。
   - `not_found`：Crossref・OpenAlex のいずれからも類似度下限（`0.60`）を満たす候補が返されませんでした。
   - `network_error`：リトライ後も回復できなかった HTTP またはソケットエラーです。

すべてのリクエストで $\ge 1\text{s}$ の間隔を空け、`User-Agent: citereal-reference-check-dataset/0.1` を送信します。

---

## ベンチマークデータセットと実測結果

[`data/references.csv`](./data/references.csv)（仕様詳細は [`data/README.md`](./data/README.md) を参照）には、**APA（10 件）**、**GB/T 7714（10 件）**、**Vancouver（10 件）**、**IEEE（10 件）** の 4 スタイル、**英語（28 件）** と **中国語（12 件）**、**DOI なし（25 件）** と **DOI あり（15 件）** からなる計 **40 件** のエントリが収録されています。

- **`valid`（実在）文献 20 件（`error_type=none`）**：Crossref または OpenAlex の実際のレコードに対して検証済みの真正な文献です。
- **`invalid`（エラーサンプル）文献 20 件**（各カテゴリ 4 件ずつ）：
  - `fabricated`：論文、著者、掲載誌・会議のすべてが架空の文献。
  - `wrong_authors`：実在する論文のタイトル・出版年・掲載誌に誤った著者を組み合わせた文献。
  - `wrong_year_or_venue`：実在する著者とタイトルに虚偽の出版年または掲載誌を組み合わせた文献。
  - `wrong_doi`：DOI が無関係な別の実在論文に解決される文献。
  - `paraphrased_title`：実在する著者・出版年・掲載誌のまま、タイトルが類義語で言い換えられた文献。

[`results/run-2026-11-16.md`](./results/run-2026-11-16.md) に記録された全件ベンチマーク実行では、`tools/check_references.py` は **38 / 40（95.0%）** の二値分類正解率を達成しました（ネットワークエラー `0` 件）。

- **偽陰性（`R08`）**：実在する中国語 GB/T 7714 論文で、OpenAlex 上の中国語タイトルとは完全一致（`sim=1.00`）しましたが、OpenAlex 側の著者名が漢字（`高广帅`）ではなくピンイン（`Guangshuai Gao`）で登録されていたため、`mismatch (first_author)` となりました。
- **偽陽性（`R32`）**：Vaswani et al. (2017) *Attention Is All You Need* の著者・タイトル・年を維持したまま、NeurIPS の掲載先を架空の IEEE ジャーナル名に差し替えたエントリですが、スクリプトはジャーナル／会議名や巻号・ページ番号を比較しないため `verified` を通過しました。

---

## 手動確認チェックリストと既知の制限事項

自動スクリプトは高速な一次スクリーニング用のフィルタであり、一次資料の確認に代わるものではありません。詳細については [`docs/how-to-verify-references.en.md`](./docs/how-to-verify-references.en.md) をご覧ください。

- **5 ステップの手動確認チェックリスト**：識別子のクロスチェック、DOI のない中国語文献や書籍に対する複数データベース検索、撤回（Retraction）の確認、および主張レベルの本文確認を網羅しています。
- **スクリプトの既知の制限事項**：中国国内ジャーナルや書籍に対する OpenAlex / Crossref の収録漏れ、ピンイン表記と漢字表記の著者名不一致、`difflib` のタイトル類似度しきい値のトレードオフ、オンライン先行公開年と冊子体出版年の正当なずれなどを解説しています。

---

## 自動化したい場合

より多くの文献リストやアップロード原稿を Web 上で処理したい場合、[CiteReal Citation Checker](https://citereal.ai/tools/citation-checker) では参考文献リストの貼り付けや `.pdf`、`.docx`、`.txt` ファイルのアップロード（サインイン後、最大 15 MB）に対応しており、Crossref、OpenAlex、PubMed、arXiv、Semantic Scholar と照合して verified・partial・suspicious・not-found のステータスを報告し、撤回論文にフラグを付け、確認済みエントリを APA 7、MLA 9、Chicago 18、Harvard、または IEEE 形式でエクスポートできます。また、根拠となる実在文献を探したい主張や短い段落（最大 600 文字）がある場合は、[CiteReal Source Finder](https://citereal.ai/tools/source-finder) が OpenAlex と Semantic Scholar を検索し、撤回されていない論文を抄録の裏付け度順でランク付けします。アカウントなしでも 1 UTC 日あたり 3 回まで無料実行でき（1 回のチェックにつき最大 2,000 文字）、無料アカウントでは登録時に 50 クレジットと毎日 20 クレジットが付与されます（参考文献 1 件の検証につき 10 クレジット、Source Finder 1 回の実行につき 30 クレジット消費）。有料サブスクリプションは月額 $20 または年額 $120（月 800 クレジット）から利用可能です（なお、CNKI や Wanfang などの中国国内データベースには未対応であり、メタデータ検証は本文が主張を裏付けているかまでの確認は行いません）。

---

## ライセンス

- **コード**（`tools/`）：MIT License の下で公開されています — 詳細は [LICENSE](./LICENSE) を参照してください。
- **ドキュメント、データ、および画像**（`data/`、`docs/`、`results/`、`README.md`、`README.zh-CN.md`）：[Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/) の下で公開されています。
