# Official Source Ledger v0.1（取得元台帳。案）

- Task: Phase 2-C Official Data Source Availability Survey
- 作成: 2026-10-25（Claude）
- 状態: **設計案（OWNERレビュー待ち。正式採用されていない）**。本書と台帳は、実データの取得・製品実装・公開の承認ではない
- 基準コミット: `a4d8b39973ef33cba99aa55f92ede2f9c3cc6228`
- 改訂: 2026-10-25 Phase 2-C.3 — 根拠の日付と日時の区別（`observed_on`・`observed_at`・`time_precision`）と、手動の単発取得の結果（`availability.download_verification`）をSchemaに追加した（第3.1節・第4章）。記録: [Phase 2-C.3 取得試験](../../reviews/phase2/phase2c3-official-download-verification.md)
- 上位: [ADR-001](../decisions/2026-10-25-multiple-official-hazard-results.md)、[Design Principles](design-principles-v1.0.md)
- 台帳: [docs/data-sources/official-source-ledger.json](../data-sources/official-source-ledger.json)
- Schema案: [official-source-ledger.schema.json](schemas/official-source-ledger.schema.json)
- 調査報告: [Phase 2-C 公式データ取得可否調査](../../reviews/phase2/phase2c-official-source-availability-survey.md)

## 1. 目的

HereRiskの5つのAPI（標高・洪水・津波・高潮・土砂災害）が使う公式データについて、**配布元・取得可能性・利用条件の確認状況を、根拠付きで機械可読に記録する**。将来のData Managerと取得Pipelineが、配布元・取得状態・更新確認・利用条件を参照できるようにする。

最上位方針: 公式防災情報を原典に忠実に提供する。取得元の違いを隠さない。**取得できないデータを、取得可能と扱わない。** ダウンロードの可否と、加工・API提供・再配信の許可を、別々に評価する。

## 2. 既存の設計との責務の違い

既存の仕組みと重複しないよう、台帳は「**公式の配布についての調査事実**」だけを持つ。

| 記録 | 何の正本か | 台帳との関係 |
|---|---|---|
| **取得元台帳**（本書） | 公式の配布元・配布単位・取得の可否・利用条件の確認状況（根拠・確認日・確認者付き）。API横断 | — |
| Data Source Definition（`api/<api>/conf/sources.json`。[データソース定義](data-source-definition-v0.1.md)） | これから取得する予定の設定（APIごと）。取得アダプター・URL・承認参照 | 台帳で `download_url_confirmed` 以上になった配布元から、OWNERの判断で定義を作る。定義から台帳のエントリを参照する項目（`survey_ref`）の追加を提案する（第5章 OL-C1。既存Schemaは変更しない） |
| Acquisition Record | 特定の取得の実績（日時・URL・SHA-256） | 台帳の `download_verified`・`automation_verified` は、取得記録（調査の記録またはAcquisition Record）を根拠として参照する。台帳は取得記録を複製しない |
| Source Catalog（Flood。[Catalog / Identity契約](flood-source-catalog-identity-contract-v0.1.md)） | 公開世代に含めた公式データの系列と所属 | 台帳のエントリは配布ファイル単位、Catalogは公開する系列単位。Catalogの `lineage_ref` の要約は、台帳ではなく取得・処理の証跡から作る |
| Dataset Registry（[Registry](dataset-registry-v0.1.md)） | 公開中のデータの正本 | 台帳は公開状態を持たない |
| 利用条件の承認（本番実行認可・決定記録） | OWNERの承認 | 台帳の `usage_terms.status = approved` は、OWNERの承認記録への参照（`approval_ref`）がある場合だけ。**調査担当は `approved` を設定しない** |

既存のSource Definitionを拡張する案も検討した。しかし、Source Definitionは「取得予定の正本」であり、確認済みの事実・調査の状態を入れない（データソース定義 §2）。また、ハザードごとのSchemaは標高にしかない。そのため、台帳を調査の記録として独立させ、Source Definitionとは参照で結ぶ（新しい処理系は作らない）。

## 3. 状態の定義

### 3.1 取得の状態（`availability.status`）

| 値 | 意味 | 根拠に必要なもの |
|---|---|---|
| `discovered` | 公式の配布情報を発見した | 公式ページ |
| `download_url_confirmed` | 具体的な取得先（URLまたはURLテンプレート）を確認した。**取得の成功ではない** | 公式ページのリンク、またはHTTPのHEAD（本文なし）の応答 |
| `download_verified` | 取得試験に成功した（実ファイルを取得し、サイズ・ハッシュを記録した） | 取得の記録（日時・サイズ・SHA-256） |
| `automation_verified` | 自動取得の試験に成功した（Pipeline・取得アダプターによる取得） | Acquisition Record |
| `manual_only` | 手動取得だけが確認され、自動取得はできない・認められない | 手動取得の記録と、自動化できない理由 |
| `access_blocked` | 取得できない、または制限がある | 失敗の記録・制限の根拠 |
| `unknown` | 未確認 | — |

- 配布ページを閲覧しただけで `download_verified` にしない。
- 認証が必要な配布元は、`login_required = yes` を記録する。認証の自動化・回避はしない。認証情報は台帳に記録しない。
- 状態は**調査・取得方式の区分**であり、利用条件の承認とは独立である。取得に成功しても、`usage_terms.status` は変えない。
- `download_verified` には、手動の単発取得の結果 `download_verification`（取得日時・要求URL・最終URL・リダイレクト数・HTTPステータス・実サイズ・SHA-256・ZIPの検証・格納形式・メタデータ・問題点）を付けられる。`download_verification` があるエントリの状態は `download_verified` または `automation_verified` に限る。**手動の単発取得の成功は `automation_verified` ではない**（自動取得の継続運用の評価は別）。

### 3.2 利用条件の状態（`usage_terms.status`）

| 値 | 意味 |
|---|---|
| `unverified` | 利用条件を確認していない |
| `review_required` | 利用条件を確認したが、未解決の事項がある、またはOWNERの判断が必要 |
| `approved` | OWNERが承認した（`approval_ref` が必須。調査担当は設定しない） |
| `prohibited` | 利用条件上、HereRiskの利用形態が認められない |

加えて、商用利用・加工・再配信・API提供を、それぞれ `allowed`・`conditional`・`prohibited`・`not_stated`・`unknown` で記録する。**「規約に禁止の記載がない」ことを `allowed` としない**（明記されている場合だけ `allowed`。記載がなければ `not_stated`）。

## 4. 運用の規則［提案］

1. 台帳は、調査のたびに版（`ledger_version`）を更新する。過去の版はgitの履歴で保持する。
2. 各事実に、根拠（公式ページ・HEADの応答・取得記録・外部機関の回答記録・手元のファイルの確認）・確認日時・確認者を付ける。確認の時刻が分からない記録は、日付（`observed_on`）だけを記録し、`observed_at = null`・`time_precision = date` とする。**架空の時刻を補完しない。**検索エンジンの要約は `web_search_hint` として記録し、事実の根拠にしない。
3. 更新の確認は、HEADの `Last-Modified`・`ETag`・`Content-Length` と、データページの版の表記の比較で行う（本文の取得をしない）。変化を検出しても、自動で取得・公開しない。
4. 実データの取得（`download_verified` にする試験を含む）は、対象ファイル・容量・方法・利用条件を示してOWNERの承認を得てから行う。
5. 台帳の `approved` は、OWNERの承認記録を参照する場合だけ。承認記録のSchemaは未決定（Integration契約 OI-27）。

## 5. Data Managerへの接続方針と既存契約への提案

Data Managerは、次の4つを**それぞれの正本から**表示する。台帳に取得・公開の状態を書き戻さない。

| 表示 | 正本 |
|---|---|
| 配布元・配布単位・取得の可否・利用条件の確認状況・更新の確認 | 取得元台帳 |
| 取得予定の設定・承認の参照 | Data Source Definition |
| 取得・検証・Integrationの実行状態 | Acquisition Record・各工程のRecord |
| 公開状態 | Dataset Registry・Publish記録 |

既存契約への提案（**未決定。既存契約は変更していない**）:

| No | 既存契約 | 提案 |
|---|---|---|
| OL-C1 | データソース定義（`sources.schema.json`） | 取得設定に、台帳のエントリへの参照 `survey_ref`（`entry_id` と台帳の版）を追加する。`official_page_url`・`documentation_checked_on`・`usage.terms_url` が台帳と一致することを、実行前検証で照合する |
| OL-C2 | 基本アーキテクチャ（Data Manager） | Data Managerの表示の対象に、取得元台帳を加える（読取専用。編集は調査の工程とgitの履歴で行う） |
| OL-C3 | 本番実行認可 | 利用条件の承認記録を、台帳の `usage_terms.approval_ref` から参照できる形にする |

## 6. 未決定事項

| No | 事項 |
|---|---|
| OL-U1 | 台帳の保存先（現在は `docs/data-sources/`）と、Data Managerからの読み方 |
| OL-U2 | `survey_ref` の採否（OL-C1） |
| OL-U3 | 更新の確認の頻度と、変化を検出したときの通知先 |
| OL-U4 | 他のハザードのSource Definition（Schema）を作る時期 |

本書の採用は、実データの取得・製品実装・公開の承認ではない。
