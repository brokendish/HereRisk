# Flood Source Selection Contract v0.1（案）

- Task: Phase 2-B.10 Flood Source Selection Contract 設計改訂
- 状態: **契約案（OWNERレビュー待ち。正式採用されていない）**。本書は製品実装・設定の承認・実データの処理・公開の承認ではない
- 作成: 2026-10-25（Claude）
- 改訂: 2026-10-25 Phase 2-B.12 — Codex独立契約監査（Phase 2-B.11、FAIL: HIGH 3 / MEDIUM 4）の指摘 B11-01〜B11-07 への契約訂正。基準コミット `c3ace814c59e62d99c08a9983c4ba021ab570642`。対応の全体は [監査対応表](../../reviews/phase2/phase2b12-source-selection-audit-remediation.md)
  - 所属の完全性と空の目録（第3.4節・第3.5節）［B11-02・B11-05］、ソースの事実と状態の導出順序・全体の状態の決定表（第5.2節）［B11-04］、区分の同一性のキー（第5.3節）［B11-06］、`deeper_in_other_sources` の三値判定（第7章）［B11-03］、変更の区分と統合成果物の再利用（第8.3節）［B11-01］、全件の計算（第5.1節）［B11-07］、回帰テスト SS-17〜SS-36
  - **本改訂は文書上の訂正であり、Codex監査のPASS・実装の開始・公開を意味しない**
- 改訂: 2026-10-25 Phase 2-B.14 — Codex独立再監査（Phase 2-B.13、FAIL: HIGH 1 / MEDIUM 3）の指摘 B13-01〜B13-04 への訂正。基準コミット `7ef60043ce4638ad2417dcb17b723ce4411c43bc`。対応の全体は [再監査対応表](../../reviews/phase2/phase2b14-codex-reaudit-remediation.md)
  - 状態の導出の正本を第5.2節に一本化（第3.5節・SS-03・SS-32）［B13-01］、ソース間の比較の承認の適用範囲と判定の順序（第7章）［B13-02］、版をまたぐ比較・集約をMVPの対象外に（第5.3節）［B13-03］、比較を実施しない場合の件数（第7章）［B13-04］、回帰テスト SS-37〜SS-51
  - **本改訂も文書上の訂正であり、Codex監査のPASS・実装の開始・公開を意味しない**
- 基準コミット: `fdf4f2df7d7a29f18519183ff8d2b931e6f4adc5`
- 置き換える設計案: [Flood Source Priority & Risk Aggregation Contract v0.1（案）](flood-source-priority-contract-v0.1.md)（Phase 2-B.9）。旧案は履歴資料として残す。**「置き換え」は設計案の変更履歴であり、どちらの案もOWNERに正式採用されていない**
- 前提: [Flood Normalize Contract v0.1（案）](flood-normalize-contract-v0.1.md)、[Flood Integration Contract v0.1（案）](flood-integration-contract-v0.1.md)、[Phase 2-B.8 監査対応表](../../reviews/phase2/phase2b8-codex-audit-remediation.md)
- 関連: [Flood API MVP Contract v0.1（案）](../api/flood-api-mvp-contract-v0.1.md)、[共通API契約](../api/common-contract-v0.1.md)、[Dataset Registry設計](dataset-registry-v0.1.md)、[Data Publish設計](data-publish-v0.1.md)、[データソース定義設計](data-source-definition-v0.1.md)、[本番実行認可設計](production-authorization-v0.1.md)
- 検討の記録: [Phase 2-B.10 レビュー](../../reviews/phase2/phase2b10-source-selection-redesign.md)

区分: **［確定］** 既存の承認済み契約に由来、**［実測］** Phase 2-A.1〜B.5の調査で報告された値（対象集合を併記）、**［提案］** 本書の設計提案（未承認）、**［未決定］** OWNER判断が必要

## 1. 目的と設計原則

同じ地点に複数の提供主体の浸水想定が公表されている場合に、**システムが代表を選ばず**、利用者が表示したいデータソースを選べるようにする。そのための契約を定める。

設計原則: **内部は厳密に。外部はシンプルに。不確実性は隠さない。**

| 原則 | 内容 |
|---|---|
| SS-1 優劣を付けない | サービスは、公表データの提供主体どうしの信頼性・精度に独自の順位を付けない。提供主体の区分は分類・表示・フィルターにだけ使い、既定の信頼順位を与えない |
| SS-2 自動代表の禁止 | 複数のソースから1つを自動で代表に選び、「総合的な代表リスク」として1つの浸水深を示すことをしない |
| SS-3 選択は表示の指定 | 利用者の選択は「どのソースの結果を主表示にするか」の指定である。原典の削除・他ソースの無効化・判定結果の変更ではない。選択を「そのソースの方が正確と確認された」という意味に解釈しない |
| SS-4 未選択を正式に許す | 利用者がソースを選んでいない状態（`overview`）は正式な状態であり、特定ソースを暗黙に代表にしない |
| SS-5 隠さない | 未選択のソースの存在・判定状態・公表元、他ソースのより深い浸水想定、unknownを、選択の有無にかかわらず確認できる |
| SS-6 非該当の禁止 | A31aにPolygonがないことだけで、評価済み・浸水なし・データなしと確定しない。A31aは評価済み範囲を持たない［実測: Phase 2-A.1］ |
| SS-7 ソースの独立 | 各ソースの地点判定は、他のソースから独立して行う。異なるソース間で浸水深を自動統合しない |
| SS-8 決定性 | 同じ公開世代・同じ地点・同じ選択からは、常に同じ結果・同じ並び順を返す |

責務の分離（UNIX的な分離）:

| 担当 | 責務 | しないこと |
|---|---|---|
| Source Discovery | 地点に関係するソースの候補を列挙する（第4章） | 判定・選択 |
| Point Assessment | ソースごとに独立して地点を判定する（第5章） | ソース間の統合・選択 |
| Source Selection | 明示された選択を検証・解決する（第6章） | 判定結果の変更・代表の自動選択 |
| Flood API | 結果・来歴・不確実性を返す（API契約） | 安全・浸水なしへの変換 |
| UI（将来） | 利用者の比較・選択を支援する（第9章） | 判定・選択の代行 |
| Data Management（将来） | ソースの登録・公開資格・分類と根拠・表示順の設定・公開世代の管理（第9章） | 承認の代行、原典・統合成果物の変更 |

## 2. 範囲

本書は、データソースのモデル（第3章）、Source Discovery（第4章）、ソースごとのPoint Assessmentとソース内の集約（第5章）、Source Selection（第6章）、安全上の情報（第7章）、表示順の設定と世代（第8章）、UI・データ管理の責務（第9章）、Phase 2-B.9からの変更（第10章）を扱う。

APIの入出力は [Flood API MVP Contract](../api/flood-api-mvp-contract-v0.1.md) で定める。Normalize・Integration・既存のRegistry / Publish / Authorization・共通API契約は変更しない（論点は第11章）。

## 3. データソースのモデル

### 3.1 識別子［提案］

| 識別子 | 意味 | 例（初期） |
|---|---|---|
| `source_id` | 利用者が選ぶ単位となる、公開用の不透明な識別子 | 東京都管理河川の想定最大規模、関東地方整備局管理河川の想定最大規模 |
| `source_category` | 提供主体の区分。**分類・表示・フィルターだけに使う。順位を持たない** | `local_government`、`national_government`、`other` |
| `product_id` | 原典の成果品ID（ZIPメンバーの幹）。内部の識別子 | `A31a-20-25_83_8303040001_10` |
| `zone_ref` | 地点に関係した区域（構成Polygon）の公開用の不透明な識別子 | — |

- `source_id`・`zone_ref` は不透明な識別子とする。**内部のファイル名・ZIPメンバー名・ローカルパス・`record_key` を公開しない**（共通API契約 §5）。公開世代の中で安定し、内部の原典（原典ZIPのSHA-256・成果品・Feature・構成Polygon）へ戻せること。生成規則は［未決定: SS-U4］。
- **`source_id` の粒度**（初期案）: 「提供主体（河川管理者）×シナリオ×原典の配布単位の系列」とする。東京都管理河川は2つのZIP（`_13_10`・`_13_20`）を1つの `source_id`、関東地方整備局は1つの `source_id` とする案である。成果品（河川）ごとに `source_id` を分ける案もある。その場合は選択肢が多く（関東地方整備局は48成果品［実測］）、利用者にとって単純でなくなる。粒度は［未決定: SS-U1］。
- **粒度は安全上の情報の意味を変える**（Phase 2-B.11監査 §5）。東京都を1つの `source_id` にすると、隅田川（0.5m未満）と神田川（5〜10m）の重なりは同一ソース内で集約される（第5.3節）。成果品ごとに分けると、神田川は「他ソース」になり、`other_sources_count`・`deeper_in_other_sources` の対象になる。粒度を決めるときは、所属集合（第3.4節）・IDの世代間の継続性・安全上の情報の意味を一緒に固定する。
- 1つの `source_id` に属する成果品・Featureの一覧は、公開世代に固定する（Source Catalog。第3.3節）。所属の完全性は第3.4節で検証する。

### 3.2 提供主体の区分の確定（Source Category Assignment）［提案。Phase 2-B.9から維持］

区分は、原典ZIPのダウンロード元（URL・ファイル名）だけで自動確定しない。次の根拠を確認し、版付き・承認付きの **Source Category Assignment Record** に保存する。

| 根拠 | 確認内容 |
|---|---|
| 原典の属性 | 対象の全Featureの `A31a_203`（河川管理者番号。01〜47 都道府県、81〜90 地方整備局等［実測: 製品仕様書］）と `A31a_204`（河川管理者）。`source_id` の全Featureで一致すること |
| 原典のメタデータ | ZIP内のメタデータ・製品仕様書の作成種別コードの定義 |
| 公式の掲載情報 | データページ・掲載河川一覧の管理区分（国管理・都道府県管理） |

- 分類できないソースを `other` へ割り当てない。根拠が一致しない場合は `unclassified` とし、理由を記録する。`unclassified` のソースは一覧に表示する（隠さない）。ただし、公開世代への収録は、Publication Readinessで阻害することを提案する（第11章 SS-C3）。
- 区分の変更では、Integration成果物を作り直さない（区分は公開世代で結び付ける。第8章）。
- 区分は信頼順位ではない。区分の並び（表示上のグループの順）は表示順の設定（第8章）の一部であり、判定にも選択にも影響しない。

### 3.3 Source Catalog（ソースの目録）［提案］

公開世代ごとに、選択できるソースの目録を固定する。

| 項目 | 内容 |
|---|---|
| `source_id` | 公開用の識別子 |
| `source_category` | 区分（割当記録による） |
| `source_organization` | 公表元・管理主体の名称（例: 「東京都」「国土交通省 関東地方整備局」） |
| `title` | データの正式名称（例: 国土数値情報 洪水浸水想定区域データ（想定最大規模）の該当部分。文言は［未決定］） |
| `rivers` | 対象河川・流域等の原典情報（成果品ごとの `A31a_201`・`A31a_202`。代表河川名であり、個別の区域の原因河川ではない［実測］） |
| `scenario` | 浸水想定のシナリオ（`maximum`＝想定最大規模） |
| `data_version` | 公表データの版・時点（A31aの年度。原典の基準日の対応は［未決定: 共通API契約 §5の `data_reference_date`］） |
| `attribution` | 出典・加工の表示（文言は［未決定: Integration契約 OI-10］） |
| `lineage_ref` | 来歴（Lineage Manifest）への公開用の参照。内部パスは含めない |
| `eligibility` | 現在の公開世代での利用資格（`eligible` のみが目録に載る。資格のないソースは公開世代に入らない） |
| `service_region` | そのソースのサービス対象地域の参照（初期は統合の対象地域＝東京都本土で全ソース共通） |
| `assessed_extent` | 評価済み範囲の表現。**A31aは `unknown`**（評価済み範囲を持たない）。範囲を持つデータを将来扱う場合の値は予約 |
| `classification_scheme` | 浸水深区分の体系のID・版（第5.3節） |
| `products` | 内部の成果品の集合（公開しない。目録の内部版にだけ持つ）。各要素は（原典ZIPのSHA-256, `product_id`）の組。第3.4節の所属割当の単位 |
| `membership_digest` | 内部。第3.4節の照合に使う、ソースごとのFeatureキー集合のSHA-256と件数（公開しない） |

- **目録は1件以上のソースを持つ。空の目録は公開できない**（第3.5節）。各ソースは1件以上の成果品を持つ（成果品0件のソースは拒否）。
- 目録は、Source Category Assignment Record・表示順の設定とともに公開世代に固定する（第8章）。

### 3.4 所属の完全性（Catalog Membership Completeness）［提案。B11-02］

**公開対象として採用した統合成果物の全Feature・全構成Polygon・全unknownは、Source Catalogから所属先の `source_id` を一意に解決できなければならない。** 件数の一致だけでは合格としない。

**用語**:

| 用語 | 定義 |
|---|---|
| 公開対象集合（正本） | 公開世代が参照する統合成果物（DB）の `zone_record` の全行（Integration契約 第6.2節）。統合成果物に含まれる全原典Featureであり、`search_target`・`unknown_region` の全行はこのいずれかの行を参照する（Integration契約 IV-25） |
| Featureキー | `zone_record.record_key`（原典ZIPのSHA-256・正規化メンバー名・`feature_index`）。原典ハッシュを含み、安定している（Normalize契約 第4.3節） |
| 入力成果品集合 | Integration Manifestの全入力（Integration Recordが開始時に照合した値）の成果品の（原典ZIPのSHA-256, `product_id`）の組。Manifestの `products` で理由を記録して除外した成果品は含まない。採用（保持）0件の成果品は含む |
| 所属割当 | 目録の `products`。成果品の組 → `source_id` |

**所属の規則**:

1. 所属は成果品単位で割り当て、Featureの所属は、そのFeatureの成果品の所属から導く。Feature・構成Polygon・unknownの所属は、それぞれ `record_key` → 成果品 → `source_id` の順で解決する。
2. **初期MVPでは、1つの成果品（したがって1つのFeature）を複数の `source_id` に所属させない。** 別名・別視点による重複所属は、将来の拡張事項として保留する（SS-U12）。

**照合（Source Catalog Validate）**: 公開世代を作る前に、目録と統合成果物を照合し、**Source Catalog Validate Record**（対象の目録・統合成果物のハッシュ、結果）を新規に作る。次のすべてを検証する。

| No | 検証 | 検出する反例 |
|---|---|---|
| CV-1 | 目録の成果品の集合と入力成果品集合が、**集合として一致**する | 成果品の欠落・余分な成果品 |
| CV-2 | 目録の中で、同じ成果品の組が2回以上現れない（複数の `source_id` への所属、同じソース内の重複） | 二重所属 |
| CV-3 | 公開対象集合の全行について、`record_key` の原典ZIPのSHA-256と成果品が、目録の成果品の組のいずれかに一致する（未割当のFeatureが0件） | 未割当のFeature |
| CV-4 | 全 `search_target`・全 `unknown_region` の行が、所属を解決できる `zone_record` を参照する | unknownだけを持つFeatureの未割当、検索対象の未割当 |
| CV-5 | ソースごとに、公開対象集合から再計算したFeatureキーの集合のSHA-256と件数が、目録の `membership_digest` と一致する | 件数を保ったままのFeatureの差替え |
| CV-6 | 各ソースの全成果品が、目録のソースの `scenario` と同じシナリオのフォルダ（例: `20_想定最大規模`）に属する | シナリオの混在 |
| CV-7 | 各ソースの全Featureの `A31a_203`・`A31a_204` が、Source Category Assignment Recordのそのソースの根拠と一致する | 管理主体の混在・誤った所属 |
| CV-8 | 目録のソースが1件以上あり、各ソースの成果品が1件以上ある | 空の目録・空のソース |
| CV-9 | 目録の成果品の原典ZIPのSHA-256が、統合成果物の来歴（Lineage Manifest）にある | 来歴にない原典の混入 |

- いずれかが不成立なら、その組合せの公開世代を作らない（Publication Readinessの阻害理由とすることを提案。第11章 SS-C3）。
- **意図的な除外**: 公開対象から成果品を外す場合は、目録の段階ではなく、Integration Manifestの `products` の除外（理由と根拠の記録。Integration契約 第3章）で行う。その除外にはOWNERの承認記録を結び付ける。目録だけで、統合成果物にあるFeatureを除外・非表示にすることはできない（CV-3で拒否）。
- APIの起動時・公開世代の切替時にも、目録の内容ハッシュとSource Catalog Validate Recordの対象が一致することを確認し、不一致なら起動・切替をしない。
- **`candidate_completeness = not_guaranteed`（第4.2節）は、公開世代に登録されていない外部の公表データがありうることを表す。公開対象として採用したデータの所属漏れを許す意味ではない。**

### 3.5 空の目録［提案。B11-05］

初期MVPでは、**公開対象のFloodのSource Catalogが空の場合、公開を阻害する**（CV-8の不成立。Publication ReadinessをBLOCKEDとする方式を第一候補とする）。空の目録を「浸水想定なし」と解釈しない。次の4つを区別する。**ソース・全体の状態名はここでは決めない。状態の導出の正本は第5.2節である**（B13-01）。

| No | 状況 | 扱い |
|---|---|---|
| 1 | Floodが未公開（公開Registryにfloodのデータセットがない） | API: `no_data`（`flood_not_published`） |
| 2 | 公開候補の目録が空 | 公開しない（CV-8・Readinessで阻害）。万一、空の目録の公開世代を読んだ場合、APIは `indeterminate`（`flood_integrity_error`）とし、正常な「該当なし」を返さない |
| 3 | 目録にソースがあり、地点がサービス対象地域の内部または外縁上にある（確認済みの該当の有無を問わない） | API: `success`。各ソースの `assessment_status` と `overall_status` は、**第5.2節の導出順序と決定表で決める**（下表）。いずれの場合も浸水なしではない |
| 4 | 地点がサービス対象地域の外 | API: `no_data`（`outside_service_region`） |

意図的に空の公開世代（例: 公開停止の代わりの空世代）を将来認める場合は、別の契約とOWNERの承認を必要とする。

**確認済みの該当が0件の場合の状態**（第5.2節の導出の結果。全ソースが同じ状況の場合）:

| 条件 | ソースの `assessment_status` | `overall_status` |
|---|---|---|
| 該当0件＋L1 unknownあり | `unknown_only`（順5） | `unknown_only` |
| 該当0件＋境界接触あり | `unknown_only`（順5） | `unknown_only` |
| 地域の外縁上＋該当0件 | `unknown_only`（順5） | `unknown_only` |
| 地域の内部で、該当・unknown・境界接触がすべて0件 | `no_match_extent_unknown`（順6） | `no_match_extent_unknown` |
| 空の目録 | （ソースなし） | 状態を作らない。`indeterminate`・`flood_integrity_error`（そもそも公開しない） |

ソースごとに状況が異なる場合は、ソースごとに第5.2節の導出順序を適用し、`overall_status` は第5.2節の決定表で決める。`assessment_status`（ソースごと）と `overall_status`（全体の要約）を混同しない。

## 4. Source Discovery Contract［提案］

### 4.1 「利用可能」の5つの区別

Discoveryの「利用可能」は「浸水区域に該当する」と同義ではない。ソースごとに、次の5つを別々に返す。

| No | 区別 | 項目（ソースごと） | 値 |
|---|---|---|---|
| 1 | ソースが公開Registryに登録されている | （目録に載ること自体） | 目録にあるソースだけを返す |
| 2 | ソースのサービス対象地域に地点が含まれる | `service_region_relation` | `inside`・`boundary`・`outside` |
| 3 | 地点がソースの評価済み範囲に含まれる | `assessed_extent_relation` | `inside`・`outside`・`unknown`。**A31aでは常に `unknown`** |
| 4 | 有効な浸水区域が地点に該当する | `has_confirmed_match` | `true`・`false` |
| 5 | 地点の判定がunknownである | `has_unknown` | `true`・`false` |

- `has_confirmed_match = false` は「浸水しない」「データがない」「評価対象外」のいずれも意味しない。`assessed_extent_relation = unknown` と組み合わせて返す。
- 3が `unknown` である限り、そのソースについて「区域外」「浸水なし」と確定しない。

### 4.2 候補の列挙範囲と候補不足の可能性

MVPでは「現在地に関係するソース」を厳密に特定できない。A31aは評価済み範囲を持たず、また、公開世代に登録されていない公表データ（例: 東京都の浸水予想区域図、内水・高潮の想定、隣接県のA31a）がありうる［実測: Phase 2-A.1の注意事項］。そのため、Discoveryは次を返す。

| 項目 | 内容 |
|---|---|
| `candidate_scope` | 列挙の範囲。初期値は `registered_sources_in_service_region`（この公開世代に登録され、地点がサービス対象地域の内部または外縁上にあるソース） |
| `candidate_completeness` | `not_guaranteed`（初期は常にこの値）。登録されていない公表データがありうることを示す |
| `not_included_notice` | 列挙の対象外のデータの種類の説明（例: 内水・高潮・計画規模・隣接県）。列挙値と公開用の文言で返す（文言は［未決定］） |

- 地点がサービス対象地域の外（全ソースで `service_region_relation = outside`）の場合は、ソースを列挙せず、地域外として返す（API契約）。
- 地点がサービス対象地域の外縁上の場合は、ソースを列挙し、`boundary` と、情報が不完全でありうること（統合成果物は地域と接するだけのFeatureを保持しない。Integration契約 第4.1節）を示す。

### 4.3 並び順

一覧の並び順は、表示順の設定（第8章）で決める。**並び順は信頼性の順位を意味しない。** 設定がない場合の既定は `source_id` の昇順（中立な順序）とする。並び順は判定の結果・選択の可否・安全上の情報（第7章）に影響しない。

## 5. Point Assessment Contract［提案］

### 5.1 ソースごとの独立した判定

各 `source_id` について、そのソースに属する判定用の構成Polygon（Integration契約 `search_target`）・unknownの範囲（`unknown_region`、L1）だけを使い、他のソースを参照せずに地点を判定する。

| 出力（ソースごと） | 内容 |
|---|---|
| `zone_hits[]` | 地点を内部に含む判定用の構成Polygonの全件: `zone_ref`、成果品の河川情報、浸水深区分、原典への参照（内部） |
| `boundary_contacts[]` | 地点が判定用の構成Polygonの境界上にある全件（確認済みの該当ではない。Integration契約の点の判定の受入ケース） |
| `unknowns[]` | 地点がunknownの範囲（L1）に入る全件: `zone_ref`、理由（`invalid_geometry`・`feature_invalid_component`） |
| `assessment_status` | 第5.2節 |
| `depth` | ソース内の集約（第5.3節）の結果。該当がなければ `null` |
| 第4.1節の5つの区別 | `service_region_relation`・`assessed_extent_relation`・`has_confirmed_match`・`has_unknown` |

- 同じソースで複数の区域が該当する場合は、全件を保持する。
- 同じFeatureの有効な構成P（地点を含む）と判定保留の構成Q（L1の範囲に地点を含む）は、`zone_hits` と `unknowns` の両方に現れる（Integration契約 `has_area_match`・`has_unknown`）。どちらも削除しない。
- 判定器の判定保留・読込みの失敗は、該当なしとして扱わない（API契約のエラー・判定不能へ）。**1つのソースでも評価に失敗した場合は、応答全体をエラーとし（API契約 第6章。`retrieval_failed` 等、`result = null`）、成功したソースだけの成功応答にしない。** 失敗を正常な `not_evaluated` に置き換えない（第5.2節）。
- 判定・集約・安全上の情報（第7章）は、常に**全ソース・全区域**を使って計算する。応答の大きさの上限は計算の対象を減らさない（API契約 第5.4節）。
- 派生形状（`geometry_basis = derived`）はMVPで使わない（BLOCKED）。unknownの範囲はL1だけ。
- 異なるソース間の浸水深の統合は、Point Assessmentの責務に含めない（SS-7）。

### 5.2 ソースごとの事実と `assessment_status`［B11-04で改訂］

**本節は、ソースの `assessment_status` と `overall_status` の導出の唯一の正本である**（B13-01）。他の節・API契約・テストの状態名は、本節の導出の結果として書く。

**事実を独立して保持する。** 状態名は、事実から決まった順序で導く1つの要約であり、事実を置き換えない。

| 事実（ソースごと） | 値 |
|---|---|
| `has_confirmed_match` | 確認済みの該当の有無 |
| `has_unknown` | unknown（L1）の有無 |
| `has_boundary_contact` | 境界接触の有無 |
| `aggregation` | `ok`（集約できた）／`undetermined`（集約不能）／`not_applicable`（確認済みの該当なし） |
| `evaluation` | `succeeded`／`failed`。**`failed` のソースがあれば応答全体がエラーになり、ソースの結果は返らない**（第5.1節）。成功応答の中の値は常に `succeeded` |
| `service_region_relation` | `inside`／`boundary`／`outside` |

**`assessment_status` の導出順序**（上から順に、最初に当たった値。相互に排他的）:

| 順 | 条件 | `assessment_status` |
|---|---|---|
| 0 | `evaluation = failed` | （ソースの状態にしない。応答全体がエラー） |
| 1 | `service_region_relation = outside` | `not_evaluated`（**予約**。下記） |
| 2 | `has_confirmed_match` かつ `aggregation = undetermined` | `aggregation_undetermined` |
| 3 | `has_confirmed_match` かつ（`has_unknown` または `has_boundary_contact` または `service_region_relation = boundary`） | `partial_unknown` |
| 4 | `has_confirmed_match` | `determined_match` |
| 5 | `has_unknown` または `has_boundary_contact` または `service_region_relation = boundary` | `unknown_only` |
| 6 | 上記のいずれでもない | `no_match_extent_unknown` |

- **集約不能とunknown・境界接触が同時に成り立つ場合は、`aggregation_undetermined`**（順2）とし、unknown・境界接触は事実（`has_unknown`・`has_boundary_contact`）と `uncertainty_reasons`（全理由）で返す。状態名が1つでも、理由は失わない。
- `uncertainty_reasons` は、事実から独立に作る（重複なし・昇順）。`assessed_extent_unknown`（A31aでは常に付く）、`unknown_invalid_geometry`（`has_unknown`）、`zone_boundary_contact`（`has_boundary_contact`）、`aggregation_undetermined`（`aggregation = undetermined`）、`region_boundary`（`service_region_relation = boundary`）。
- **`not_evaluated` は予約値とする。** ソースごとに異なるサービス対象地域を持つ将来の構成で、地点がそのソースの対象地域の外にあり、他のソースの対象地域の内部にある場合だけに使う。初期MVPではサービス対象地域が全ソース共通であり、地点が対象地域の外なら応答全体が `no_data`（`outside_service_region`）になるため、**正常応答に `not_evaluated` は現れない**。読込み失敗・判定器の異常・整合性の異常を `not_evaluated` で表さない。
- 評価済みの区域外を表す値（`confirmed_no_match`）は予約とし、**A31aでは使わない**。

**全体の状態（`overall_status`）の決定表**（全ソースの `assessment_status` を入力とする。目録は空でない（第3.5節）。`not_evaluated` はMVPでは現れないが、現れた場合の扱いも示す）:

ここで「該当ソース」は `determined_match`・`partial_unknown`・`aggregation_undetermined` のいずれか、「不確実ソース」は `partial_unknown`・`aggregation_undetermined`・`unknown_only`・`not_evaluated` のいずれかとする。

| 該当ソースがある | 不確実ソースがある | `overall_status` |
|---|---|---|
| はい | いいえ（全ソースが `determined_match` または `no_match_extent_unknown`） | `determined_match` |
| はい | はい | `partial_unknown` |
| いいえ | はい | `unknown_only` |
| いいえ | いいえ（全ソースが `no_match_extent_unknown`） | `no_match_extent_unknown` |

- `aggregation_undetermined` のソースがある場合の `overall_status` は `partial_unknown` である。全体の状態は浸水深を持たないため、集約不能を独立の値にしない（集約不能は、そのソースの `assessment_status` と理由で示す）。
- `assessed_extent_unknown` は全ソースに付くため、不確実ソースの判定には使わない（API契約 第5.7節）。

### 5.3 ソース内の集約（Within-Source Aggregation）［提案］

同じソースの複数の区域が地点に該当し、1つの浸水深を主表示する必要がある場合に限り、次の規則で集約する。**全該当は集約後も保持する。**

**規則（初期案）**: 比較可能な浸水深区分のうち、最も深い区分をそのソースの浸水深とする（`deepest_comparable_class`）。

- 原典の応用スキーマ文書は「一つのデータ内に複数のポリゴンがオーバーラップする場合は、浸水ランクコードの値の大きい方を優先する」と規定している［実測: Phase 2-A.1］。一方、1つの `source_id` は複数の成果品（ファイル）を含み、ファイル間の重複について原典には定めがない（例: 東京都の隅田川×神田川で、ランクが異なる重複が観測されている［実測: Phase 2-A.1の標本］）。そのため、本規則は原典の規定の延長ではなく、本書の提案である（SS-U2）。
- **原典のランク番号（`A31a_205` の1〜6）を数値として大小比較しない。** 区分を正規化した区間に変換して比較する。

| コード | 原典の定義 | `lower_m` | `upper_m` |
|---|---|---:|---:|
| 1 | 0～0.5m未満 | 0 | 0.5 |
| 2 | 0.5～3.0m未満 | 0.5 | 3.0 |
| 3 | 3.0～5.0m未満 | 3.0 | 5.0 |
| 4 | 5.0～10.0m未満 | 5.0 | 10.0 |
| 5 | 10.0～20.0m未満 | 10.0 | 20.0 |
| 6 | 20.0m以上 | 20.0 | `null` |

［実測: 製品仕様書・コードリスト。Phase 2-A.1］端点の包含（以上・未満）は原典で未規定であり、`bounds_inclusion = unspecified` とする。コード5の「内容」欄の記載（津波基準水位）は原典のまま記録し、解釈は確認事項とする（CQ-5）。

**比較の規則**:

| 関係 | 条件 | 扱い |
|---|---|---|
| 同じ | 比較の資格があり（下記）、同じ `class_code` | 同じ深さ。寄与した区域をすべて列挙する |
| Aの方が深い | 比較の資格があり、`A.lower_m >= B.upper_m`（`B.upper_m` が `null` でない） | Aを採る。端点だけを共有する場合（`A.lower_m = B.upper_m`）も、重なりは高々1点なので深い側をAとしてよい |
| 包含・長さを持つ重なり | 比較の資格があるが、一方の区間が他方を含む、または長さを持って重なる | **比較不能**（`aggregation_undetermined`） |
| 異なる体系・異なる版・異なる比較規則 | 比較の資格がない | **比較不能**（閾値が同じに見えても比較しない） |

- 比較不能の場合は任意の値を選ばない。`depth = null`・`aggregation_undetermined` とし、該当の全件を返す。

**区分の同一性のキーと比較の資格（B11-06）**:

- **区分の同一性のキー**は（`scheme_id`, `scheme_version`, `class_code`）の3つ組とする。ソース内の集約の結果、`matches[]` の各区域、`overview` の `depth_classes_present`、安全上の比較（第7章）で、同じキーを使う。
- **同じ `scheme_id`・同じ `class_code` でも、`scheme_version` が異なれば別の区分とする。** 重複排除でまとめず、比較不能として扱う。
- **比較の資格（MVP。B13-03で改訂）**: 2つの区分が比較可能なのは、次の3つがすべて一致するときだけである。`class_code` は個々の区分を識別する項目であり、異なる深さの区分を比較するために同じ値である必要はない。
  1. `scheme_id`
  2. `scheme_version`
  3. 区分体系の比較規則（`comparison_rule_id`。体系・版ごとにSource Catalogの `classification_scheme` に登録された、区間の順序づけの規則。内部の項目で、公開しない）
- ソース間の安全上の比較（第7章）は、上の3つの一致に加えて、**ソース間の比較の承認**（CQ-1・CQ-3の確認後のOWNERの承認）を要件とする。ソース内の集約は、上の3つの一致だけを要件とする（同じソースの中の区分の順序）。
- **MVPでは、浸水深区分の版をまたいだ比較・集約を行わない。** 異なる版の区分は、閾値が同じに見えても比較不能とする。版の同等性を承認して比較する仕組みは、将来の拡張事項としMVPの対象外とする（SS-U17）。
- 異なる版の区分も、原典の情報と区分（キー・`label`・区間）をそれぞれ保持してAPIへ返す。
- **集約の結果の識別子**: ソース内の集約の結果は、集約に使った区域と同じ（`scheme_id`, `scheme_version`, `class_code`）を持つ。MVPでは比較の資格が3つの一致を要件とするため、集約できる区域は常に同じ体系・同じ版であり、代表の識別子を選ぶ余地はない。**任意の版を選んで代表 `depth` の識別子に採用しない。** 同じソースに異なる版の区域が該当した場合は、集約不能（`aggregation = undetermined`、`depth = null`）とする。
- APIの各 `depth` は、`scheme_id`・`scheme_version`・`class_code` を必ず持つ（API契約 第5.5節）。
- 集約の結果の `depth` は、そのソースの「主表示の浸水深」であり、地点の唯一の正しい浸水深ではない（第7章）。

**比較仕様の確定に必要な確認項目**（Phase 2-B.9から維持）:

| No | 確認項目 |
|---|---|
| CQ-1 | 各原典ZIPが参照する浸水ランクコードのコードリストの版と、製品仕様書の版 |
| CQ-2 | `A31a_205` の型（東京都は文字列、関東地方整備局は整数［実測］）と値の範囲 |
| CQ-3 | 東京都と関東地方整備局が、同じ区分の閾値（0.5・3.0・5.0・10.0・20.0m）で作成しているか |
| CQ-4 | 端点の包含が未規定であることの、応答での表現 |
| CQ-5 | コード5の「内容」欄の記載の扱い |
| CQ-6 | 同じシナリオ（想定最大規模）であることの確認 |
| CQ-7 | 別の体系のデータ（浸水継続時間、家屋倒壊等氾濫想定区域等）を将来扱う場合の対応 |
| CQ-8 | 同一ファイル内の重複が原典で解消済みであることの、実データでの確認 |

## 6. Source Selection Contract［提案］

### 6.1 選択できる対象

利用者が指定できるのは、**現在の公開世代のSource Catalog（第3.3節）に載っている `source_id`** だけである。

| 指定 | 扱い |
|---|---|
| 目録にある `source_id` | 選択を受け付ける |
| 形式が不正な `source_id` | 入力エラー（`invalid_source_id`） |
| 形式は正しいが、現在の公開世代の目録にない `source_id`（旧世代のID・存在しないID） | 入力エラー（`source_not_available`）。別のソースへ黙って置き換えない。未選択として黙って処理しない |
| 複数の `source_id`（MVP） | 入力エラー（`multiple_sources_not_supported`） |

- 選択の受付は判定の結果を変えない。全ソースの判定は、選択の有無・内容にかかわらず同じである。
- 選択に使う値は `source_id` だけとする。区分（`source_category`）・提供主体名・優先順位を指定して、システムにソースを選ばせる入力を受け付けない（自動代表の禁止。SS-2）。

### 6.2 選択モード

| モード | MVP | 内容 |
|---|---|---|
| `overview` | 対象 | 未選択。全ソースの結果を一覧で返す。主表示のソースはない（`selected_source = null`） |
| `single_source` | 対象 | 利用者が指定した1つのソースの結果を主表示にする。他のソースの結果も同じ応答に含める |
| `multiple_sources` | 将来候補（実装しない） | 利用者が選んだ複数のソースを並べる |
| `compare` | 将来候補（実装しない） | 複数のソースを比較する。ソース間の比較の規則は別途定める |

- 将来のモードを追加しても、`overview`・`single_source` の意味を変えない（API契約の版の管理）。
- `selected_by` は `user` だけとする。**`system`（システムによる選択）の値は設けない。**

### 6.3 状態遷移

```text
              source_id を指定
 overview ────────────────────────► single_source(A)
    ▲                                   │     │
    │ source_id を外す                  │     │ 別の source_id(B) を指定
    └───────────────────────────────────┘     ▼
                                       single_source(B)

 single_source(A) で A が新しい公開世代の目録にない場合
   → 入力エラー（source_not_available）。overview・別ソースへ自動で移らない
```

- 状態はリクエストごとに決まる（サーバは利用者の選択を保存しない）。選択の保存・復元はUI（クライアント）の責務とする。
- 公開世代が切り替わって選択中のソースがなくなった場合、UIは利用者にその事実を示し、選び直しを求める（自動で別のソースに切り替えない）。

### 6.4 選択の効力

- 選択したソースの結果（`assessment_status`・`depth`・該当・unknown）を主結果として返す。
- 同時に、他の全ソースの一覧・確認済みの該当・unknownを同じ応答に含める（SS-5）。
- 選択は、原典データの削除・他ソースの無効化・判定の変更ではない。
- 選択を「そのソースの方が正確であると確認された」という意味に解釈しない。応答・UIの文言でもそのように表現しない。

## 7. 安全上の情報［提案］

利用者の選択を尊重しつつ、防災情報として次を保証する。

| No | 保証 | 契約上の実現 |
|---|---|---|
| 1 | 未選択の公表データの存在を隠さない | `single_source` でも全ソースを `sources[]` に含める。`other_sources_count` |
| 2 | 選択ソースより深い浸水想定がほかにある場合、その事実を伝える | `deeper_in_other_sources`（下記） |
| 3 | 比較不能な浸水深区分を単純に大小比較しない | 第5.3節の比較の規則。比較不能は `null` |
| 4 | 他ソースのunknownを消さない | 全ソースの `unknowns` を返す。`has_unknown_in_other_sources` |
| 5 | 無効形状由来のunknownを浸水なしに変換しない | `unknown_only` を「浸水なし」と表現しない |
| 6 | 評価範囲不明を浸水区域外と断定しない | `assessed_extent_relation = unknown`、`no_match_extent_unknown` |
| 7 | 選択中の値を、地点の唯一の正しい浸水深として提示しない | `selected_result_is_exclusive = false`（常に `false`）。説明の文言 |

**`deeper_in_other_sources`（他ソースのより深い想定）の三値判定［B11-03で改訂］**:

`single_source` だけで返す。比較の基準は、選択中のソースのソース内の集約の結果 `S = depth`（第5.3節）とする。比較の対象は、**選択していない全ソースの、全確認済み区域**（`matches[]` の各区域。ソース内の集約の結果ではなく個別の区域）とする。unknown・境界接触は比較の対象にしない（独立して保持する）。

各対象区域 z を、第5.3節の比較の資格と規則で、次のどれかに分類する。

| 区域の分類 | 条件 |
|---|---|
| `deeper` | z と S が比較可能で、z が S より深い |
| `not_deeper` | z と S が比較可能で、z が S と同じ、または浅い |
| `incomparable` | 比較の資格がない（体系・版・比較規則の違い、ソース間の比較が未承認）、または区間の包含・長さを持つ重なり。**`incomparable` の区域について、深さの数値の比較は行わない** |

**判定の順序**（上から順に、最初に当たった値）:

| 順 | 条件 | 値 | `basis`（理由） |
|---|---|---|---|
| 1 | 選択中のソースに確認済みの該当がない（`S` を作れない） | `null` | `selected_has_no_confirmed_match` |
| 2 | 選択中のソースが `aggregation_undetermined`（`S = null`） | `null` | `selected_depth_unavailable` |
| 3 | 他のソースが0件 | `false` | `no_other_sources` |
| 4 | 他のソースに確認済み区域が0件（unknown・境界接触だけ、または何もない） | `false` | `no_confirmed_match_in_other_sources` |
| 5 | `deeper` の区域が1件以上 | `true` | `deeper_zone_found` |
| 6 | `deeper` の区域がなく、`incomparable` の区域が1件以上 | `null` | ソース間の比較が未承認なら `cross_source_comparison_unapproved`、承認済みなら `incomparable_zones_present` |
| 7 | 全対象区域が `not_deeper` | `false` | `all_compared_none_deeper` |

- **比較の承認の適用範囲（B13-02）**: ソース間の比較の承認が必要なのは、実際に異なるソースの浸水深区分を比較する場合（順5〜7）だけである。**比較の対象がない場合（順1〜4）は、承認の有無によって結果を変えない。** 一方、他のソースに確認済み区域があり、ソース間の比較が未承認なら、その全区域を `incomparable` とし、深さを比較しない（順6で `null`）。旧版（Phase 2-B.12）の「承認前は全ケース `null`」は、この規則に置き換えた。
- 順4と順5〜7の対象の集合は、他のソースの `matches[]` の全区域（確認済み区域）と一致する。順4の「0件」はこの集合が空であることを意味する。
- 順6の `basis` は、ソース間の比較が未承認なら常に `cross_source_comparison_unapproved`（未承認では全区域が `incomparable` になるため）、承認済みなら `incomparable_zones_present` とする。
- **`false` の意味は「確認済み区域について、選択中より深い結果を確認していない」であり、「より深い浸水の可能性がない」ではない。** unknown・評価範囲不明は、`false` の場合も別のフィールド（`has_unknown_in_other_sources`・各ソースの `uncertainty_reasons` 等）で返す。
- 判定できなかった場合（順1・2・6）は `null` とし、**`false` へ代替しない**。

**比較の件数（`deeper_comparison` の `deeper_zones`・`not_deeper_zones`・`incomparable_zones`。B13-04）**:

| 順 | 比較の実施 | 3つの件数 |
|---|---|---|
| 1・2 | **比較を実施していない**（比較の基準 `S` がない） | すべて `null`。他ソースの件数（0件を含む）にかかわらず、選択側の理由（`basis`）を優先する |
| 3・4 | 比較を実施した（対象が空） | すべて `0` |
| 5・6・7 | 比較を実施した | 各分類の区域の件数（0以上の整数）。3つの和は、他のソースの確認済み区域の総数に等しい |

- `null` は「比較を実施していない」、`0` は「比較を実施し、その分類の区域が0件」を意味し、区別する。
- `basis` と件数は常に対応する: `basis` が `selected_has_no_confirmed_match`・`selected_depth_unavailable` なら件数はすべて `null`、それ以外なら件数はすべて整数。
- 応答には値とあわせて `basis` と3つの件数を返す（API契約 第5.6節）。

**必須ケースの判定**（特に断らない限り、選択中 S＝3.0〜5.0m未満、ソース間の比較は承認済み、比較の対象の区域は S と同じ体系・同じ版・同じ比較規則。「比較不能な体系」は S と体系・版・比較規則のいずれかが異なる区域）:

| ケース | 他ソースの状況 | 値 | `basis` | 件数（deeper / not_deeper / incomparable） |
|---|---|---|---|---|
| 比較可能な深い区域＋比較不能な区域 | B: 5.0〜10.0m未満、C: 比較不能な体系の1区域 | `true` | `deeper_zone_found` | 1 / 0 / 1 |
| 浅い区域＋比較不能な区域 | B: 0.5〜3.0m未満、C: 比較不能な体系の1区域 | `null` | `incomparable_zones_present` | 0 / 1 / 1 |
| unknownのみのソース | B: unknownだけ | `false` | `no_confirmed_match_in_other_sources`（`has_unknown_in_other_sources = true`） | 0 / 0 / 0 |
| 選択中のソースの `depth` が `null` | 選択中が `aggregation_undetermined` | `null` | `selected_depth_unavailable` | null / null / null |
| 選択中のソースに確認済みの該当がない | 選択中が `unknown_only`・`no_match_extent_unknown` | `null` | `selected_has_no_confirmed_match` | null / null / null |
| 集約不能のソースの内部に深い区域 | B: `aggregation_undetermined`、区域 5.0〜10.0m未満と比較不能な体系の区域 | `true` | `deeper_zone_found` | 1 / 0 / 1 |
| 他ソースが0件 | — | `false` | `no_other_sources` | 0 / 0 / 0 |
| 他ソースに確認済みの該当がない | B: `no_match_extent_unknown` | `false` | `no_confirmed_match_in_other_sources` | 0 / 0 / 0 |
| 同じ深さだけ | B: 3.0〜5.0m未満 | `false` | `all_compared_none_deeper` | 0 / 1 / 0 |
| ソース間の比較が未承認、他ソースに確認済み区域あり | B: 5.0〜10.0m未満 | `null` | `cross_source_comparison_unapproved` | 0 / 0 / 1 |
| ソース間の比較が未承認、他ソース0件 | — | `false` | `no_other_sources` | 0 / 0 / 0 |
| ソース間の比較が未承認、他ソースunknownのみ | B: unknownだけ | `false` | `no_confirmed_match_in_other_sources` | 0 / 0 / 0 |
| 他ソース0件、選択中 `depth = null` | 選択中が `aggregation_undetermined` | `null` | `selected_depth_unavailable` | null / null / null |

**`depth_classes_present`（`overview`）**:

- 選択中のソースがないので `deeper_in_other_sources` は返さない。代わりに、全ソースの全確認済み区域の区分を、区分の同一性のキー（`scheme_id`, `scheme_version`, `class_code`）で重複排除して列挙する。各要素は、キー・`label`・区間と、その区分を持つ `source_id` の一覧を持つ。
- 並び順: 列挙した全区分が互いに比較可能（同じ体系・同じ版・同じ比較規則で、異なるソースの区分を含む場合はソース間の比較が承認済み）なら深さの順（浅い順。`ordering = by_depth`）、そうでなければ区分の同一性のキーの昇順（`ordering = by_key`）とする。任意の順で深さの順のように見せない。
- これは**ソース間の統合ではなく、事実の列挙**である。
- 比較はソース間で区分の深さの順序を示すだけであり、異なる提供主体の想定の条件（河川・降雨・計算条件）は異なる。この比較を「総合的な危険度」として示さない。
- ソース間の比較が意味を持つ前提は、各ソースの区分の体系が同じであることの確認（CQ-1・CQ-3）とその承認である。承認前は、比較の対象の区域がある場合に `null`（`cross_source_comparison_unapproved`）を返す。比較の対象がない場合は承認の有無にかかわらず判定の順序（順1〜4）のとおり。

## 8. 表示順の設定と公開世代［提案］

### 8.1 Source Display Settings（表示順・グルーピングの設定）

| 項目 | 内容 |
|---|---|
| `settings_id`・`version`・`content_sha256` | 同一性（Integration契約 第3.1節と同じ固定の規則。不変の保存先・内容ハッシュの再計算） |
| `group_by` | `none` または `source_category` |
| `group_order` | グループの表示順（`group_by = source_category` の場合） |
| `source_order` | `source_id` の表示順。未指定のソースは `source_id` の昇順で後ろに並べる |
| `purpose_notice` | 「表示順は信頼性の順位ではない」ことを示す公開用の文言の参照 |

- **表示順は信頼性の順位を意味しない。** 表示順の変更は、地点判定の結果・選択の可否・安全上の情報（第7章）を変更しない。
- 表示順の変更だけで、Normalize・Integrationを再実行しない。
- 変更の手順: `draft` → `validated`（Schemaの検査、目録の全 `source_id` との整合、判定に関わる項目を含まないことの検査）→ `approved` → `active`。判定を変えない設定であるため、承認の主体・軽重は［未決定: SS-U6］とする。少なくとも、変更の履歴を残し、版を固定する。
- リクエストで表示順を指定させない（表示順はUIの並べ替えで変えてよいが、APIの応答の順序はこの設定で決まる）。

### 8.2 公開世代への固定

公開世代は、統合成果物（DB）・地域形状・Lineage Manifest（Integration契約 第9.3節）に加えて、次を内容ハッシュで同一の世代に固定する。

- Source Catalog（第3.3節）
- Source Category Assignment Record（第3.2節）
- Source Display Settings（第8.1節）
- unknownポリシー（Integration契約 第3.1節）

APIは1つの応答で1つの公開世代だけを使い、応答にその識別子と各設定の版・内容ハッシュを含める。キャッシュのキーには公開世代を含める。

### 8.3 変更の区分と統合成果物の再利用［B11-01で改訂］

**表示だけの変更と、統合成果物の意味を変える変更を分ける。** 旧版の「これらの変更だけなら統合成果物を再生成しない」は、unknownポリシーを含んでいたため、Integration契約（第3.1節・第11.2節「unknownポリシーの改版」）と矛盾していた。本節で置き換える。

| 変更 | 統合成果物（DB） | 必要な手順 | 再利用の条件 |
|---|---|---|---|
| **表示順・グルーピングだけ**（Source Display Settings） | **再利用する**（DBのファイルのSHA-256は不変） | 新しい表示設定の検証・承認 → 新しい公開世代 → Publication Readinessの再作成 → Publish | 目録・区分の割当・unknownポリシー・統合成果物・Integration Record・Integrated Validate Recordが旧世代と同じ（内容ハッシュ・`record_sha256` が一致） |
| **unknownポリシーの改版**（内容・版の変更） | **再生成する** | Integration契約に従い、新しいManifest → Integration → Integrated Validate → Publication Readiness → Publish。旧版の承認を新版へ適用しない | 再利用しない |
| **Source Category Assignment Recordの変更**（区分・根拠・公表元の名称） | 再利用してよい | 新しい割当記録の承認 → Source Catalog Validate（CV-7） → 新しい公開世代 → Readiness → Publish | 公開対象集合（DB）は変わらない。CV-1〜CV-9が新しい割当記録で成立する。`source_id` の意味（所属集合）を変えない |
| **Source Catalogの変更で、所属集合が変わらないもの**（名称・`title`・出典の文言・`lineage_ref` 等の表示項目） | 再利用してよい | 新しい目録 → Source Catalog Validate → 新しい公開世代 → Readiness → Publish | CV-1〜CV-9が成立し、各ソースの `membership_digest` が旧世代と同じ |
| **Source Catalogの変更で、所属集合が変わるもの**（成果品の別のソースへの移動・ソースの分割・統合） | 再利用してよい（DBの内容は変わらないため） | 新しい目録 → Source Catalog Validate → 新しい公開世代 → Readiness → Publish。`source_id` の継続性の規則（SS-U4）に従う | CV-1〜CV-9が成立する。**所属が変わったソースには、旧世代と同じ `source_id` を再利用しない**（同じIDの意味が世代で変わらないようにする）。安全上の情報の意味が変わるため（第3.1節）、変更の内容をOWNERの承認の対象に含める |
| **公開対象集合が変わる変更**（成果品の追加・削除・除外、原典の更新、地域定義・N03の変更、ソースの追加・削除） | **再生成する** | 新しいManifestから再統合（Integration契約 第11.2節） | 再利用しない |

- **異なるunknownポリシーのDBと公開設定を結び付けない。** 公開世代の `settings.unknown_region`（ID・版・内容ハッシュ）は、統合成果物の `metadata` のunknownポリシー（Integration契約 第6.2節）・Integrated Validate Record・Publication Readiness Recordの値と一致しなければならない。Publication Readinessの作成時・Publish直前・APIの起動時・公開世代の切替時に照合し、不一致なら公開・起動・切替をしない。
- 統合成果物を再利用する場合も、**Publication Readiness Recordは新しい公開世代ごとに新規に作る**（Integration契約 第7.3節の照合を時点ごとに行うため）。Integration Record・Integrated Validate Recordは変更しない。
- 表示順だけの変更でも、Normalize・Integrationは再実行しない。

既存のData Publish・Registryには、公開世代にこれらを含める項目がない。追加の契約が必要な論点として記録する（第11章 SS-C1）。

## 9. UIとデータ管理の責務［提案。MVPでは画面を実装しない］

### 9.1 利用者向けUI

- 公表データの一覧（`sources[]`）を表示する。公表元・対象河川・シナリオ・版を表示する。
- データを切り替えられる（`source_id` の指定・解除）。
- 選択中のデータを明示する（`overview` では「未選択」であることを明示する）。
- 他のデータの存在を常に提示する（件数・一覧への導線）。
- より深い浸水想定（`deeper_in_other_sources`）・unknown（`has_unknown_in_other_sources`）を見落としにくくする（例: 選択中の結果の近くに注意を表示する）。具体的な表現は［未決定: SS-U8］。
- 一覧の並び順を「おすすめ」「信頼度順」と表現しない。

### 9.2 データ管理画面（将来）

- データソースの登録・公開資格の管理（公開世代への収録は既存のPublishの手順と承認による）。
- 提供主体の分類と根拠の管理（Source Category Assignment Record）。
- 一覧の表示順・グルーピングの設定（Source Display Settings）。表示順の設定は信頼性の順位ではない。
- 公開世代・来歴・承認の管理（閲覧と、承認の依頼。承認の代行はしない）。

## 10. Phase 2-B.9からの変更

| 区分 | 機能 | 本書での扱い |
|---|---|---|
| 維持 | 提供主体の区分とその確定（割当記録） | 第3.2節。ただし順位を持たない |
| 維持 | 原典の保持・来歴・版管理・内容ハッシュによる固定 | 第3章・第8章 |
| 維持 | unknownの独立した保持（全ソース・全件） | 第5章・第7章 |
| 維持 | 地点判定・区域ごとの状態（境界接触・unknown・評価範囲不明） | 第5章 |
| 維持 | 浸水深区分の正規化と比較の規則、確認項目CQ-1〜CQ-8 | 第5.3節（ソース内の集約と、安全上の比較に限定） |
| **廃止** | 提供主体の自動優先順位による代表結果の選択（Source Priority Policy、`source_category_order`、`fallback_rule`、`representative`・`selection_reason`・`priority`・`finality`） | 採用しない |
| 再定義 | ソースの選択 | 利用者の明示の選択（第6章） |
| 再定義 | 表示順 | 信頼性の順位ではない表示設定（第8章） |
| 再定義 | 同順位（同じ区分）の集約 | **同一ソース内の集約**（第5.3節）。異なるソース間では集約しない |
| 保留 | 複数ソースの並列表示・比較（`multiple_sources`・`compare`） | 将来候補（第6.2節） |
| 保留 | 高度な集約（全ソース中の最大浸水深の代表化等） | 採用しない。`depth_classes_present`・`deeper_in_other_sources` で事実を示すだけ |
| 保留 | 地図レイヤー表示（Layer Presentation） | 第10.1節 |

### 10.1 地図レイヤー表示（保留）

Phase 2-B.9の案（優先順位の高い提供主体を代表レイヤーとする）は採用しない。将来の地図表示では、次を前提とする。

- 選択中のソースのレイヤーを主表示とし、未選択のソースは「存在すること」が分かる表示を持つ（`overview` では全ソースを同等に扱う）。
- 重なりの描画順は表示の設定であり、信頼性の順位ではない。
- unknownの範囲（L1の外接矩形）は、区域の「なし」と区別して表示する。外接矩形は実際の区域より広いため、表現方法は別途決める。
- タイルの生成・キャッシュは公開世代ごとに分ける。

## 11. 既存契約との論点（変更せず記録する）

| No | 既存契約 | 論点 |
|---|---|---|
| SS-C1 | Data Publish・Dataset Registry・Integration契約 第9.3節 | 公開世代にSource Catalog・区分の割当記録・表示設定・unknownポリシーを含める項目がない |
| SS-C2 | データソース定義 §2（3種類の情報の正本） | 区分の割当（確認済みの事実＋承認）とSource Catalogは、Source Definition（予定）にも公開Registryにも入らない。新設が必要 |
| SS-C3 | Integration契約 第7.3節（Publication Readiness） | 阻害理由に、`unclassified` のソース、Source Catalog Validate（第3.4節 CV-1〜CV-9）の不成立、空の目録（第3.5節）がない |
| SS-C4 | 共通API契約 §6、Dataset Registry §6 | 「複数データセットの優先順位・集約・競合時の扱いは未決定。先着順・最大値・最新という理由だけの選択を独断で導入しない」。本書は**システムによる優先順位・自動選択を導入しない**ため、この規定と整合する。ソース内の最大区分の集約（第5.3節）は、1つのソースの中の規則であり、OWNERの承認まで提案である |
| SS-C5 | 共通API契約 §2「利用者に都道府県やデータセットの選択を要求しない」 | 本書は選択を**要求しない**（`overview` が既定で、選択は任意）。ただし、データソースの任意の選択という入力が共通契約にないため、追加の論点とする |
| SS-C6 | 共通API契約 §3 `dataset` の複数件の形は未決定 | 1応答に複数ソースの根拠を含める形（`sources[]` と `dataset` の関係） |
| SS-C7 | 本番実行認可 | 設定の承認記録のSchemaがない（Integration契約 OI-27と同じ） |
| SS-C8 | Integration契約 第10章「有効な区域で該当しても、判定保留の区域のランクが分からないことを示す」 | unknownの区域の原典のランクを、可能性として返すか（API契約 FA-U5） |
| SS-C9 | Integration契約 第4.1節 選別 | 選別は全ソースの全Featureに同じ規則を適用しており、ソースの選択の影響を受けない（整合）。ソースの選択は公開世代の統合成果物を変えない |
| SS-C10 | Integration契約 第7.3節・第11.2節 | Source Catalog Validate Record（第3.4節）をPublication Readinessの照合対象にする項目がない。公開世代の `settings.unknown_region` と統合成果物の `metadata` のunknownポリシーの一致の照合（第8.3節）も、Readinessの照合項目として追加が必要 |
| SS-C11 | 共通API契約 §3.1 | 応答の上限を超えた場合のエラーの `status`（API契約 第5.4節で `retrieval_failed` を提案）。共通契約の分類の意味（取得できない）に当てはめた提案であり、未承認 |

## 12. テストケース（設計のみ。いずれも実行していない）

| ID | 入力・条件 | 期待 |
|---|---|---|
| SS-01 | **ケースA**: 東京都ランク1（0～0.5m未満）、関東地方整備局ランク4（5.0～10.0m未満）。利用者が東京都を選択 | 東京都の浸水深を主表示。関東地方整備局の該当を `sources[]` に保持。`deeper_in_other_sources = true` |
| SS-02 | **ケースB**: 東京都がunknownだけ、関東地方整備局がランク3（3.0～5.0m未満）。利用者が関東地方整備局を選択 | 関東地方整備局の確認済みの結果（`determined_match`）を主表示。東京都のunknownを保持し、`has_unknown_in_other_sources = true`。応答全体の状態（`overall_status`。API契約）は `partial_unknown`（確定したように表示しない） |
| SS-03 | **ケースC**: どのソースにも確認済みの該当・unknown・境界接触がない（地域の内部） | 浸水深0m・浸水なし・安全と返さない。各ソースは `no_match_extent_unknown`・`assessed_extent_relation = unknown`。評価範囲不明を説明する（unknown・境界接触・外縁上がある場合はSS-37〜SS-39。Phase 2-B.14で前提を明記） |
| SS-04 | `overview`（未選択）で、ケースAの地点 | 主表示のソースはない（`selected_source = null`）。全ソースの結果を並べ、`depth_classes_present` に2つの区分。特定ソースを暗黙に代表にしない |
| SS-05 | 同じソースの2つの区域（ランク2とランク3）が地点に該当 | ソースの `depth` はランク3。両方の区域を保持 |
| SS-06 | 同じソース内で比較不能な体系の区域（合成データ） | そのソースは `aggregation_undetermined`・`depth = null`。全区域を保持 |
| SS-07 | 同じFeatureに有効な構成Pと判定保留の構成Q | そのソースの `zone_hits` と `unknowns` の両方に現れ、`partial_unknown` |
| SS-08 | 異なるソースの複数unknown | 全ソースのunknownを保持。選択中かどうかで削除しない |
| SS-09 | 目録にない `source_id`・旧世代の `source_id`・形式不正・複数指定 | それぞれ入力エラー。別ソース・未選択へ黙って置き換えない |
| SS-10 | 表示順の設定だけを変更した新しい公開世代 | 統合成果物は再生成されない。全ソースの判定結果・安全上の情報が旧世代と同一で、並び順だけが変わる |
| SS-11 | 選択の有無・選択するソースを変えて同じ地点を判定 | 全ソースの判定結果（`sources[]` の各要素の判定の項目）が同一 |
| SS-12 | 区分・提供主体名でソースを指定する入力 | 入力エラー（自動選択の経路を作らない） |
| SS-13 | ランク番号の数値比較の誤り（文字列の比較を含む）の模擬 | 正規化した区間の比較と一致しない場合に検出 |
| SS-14 | 区分の体系の同一性が未承認の状態で、ケースAを判定 | `deeper_in_other_sources = null`（比較を主張しない）。両方の該当は保持 |
| SS-15 | 地点が地域の外縁上 | ソースを列挙し、`service_region_relation = boundary` と不完全でありうることを示す |
| SS-16 | 同じ公開世代・同じ地点・同じ選択で繰り返し | 結果・並び順が同一 |

**Phase 2-B.12の回帰テスト（B11-01〜B11-07）**。いずれも設計上の受入条件で、テストコードは作成・実行していない。

| ID | 入力・条件 | 期待 | 指摘 |
|---|---|---|---|
| SS-17 | unknownポリシーv1で生成したDBに、v2のunknownポリシーを設定した公開世代を結び付ける | Readiness・Publish直前・API起動時の照合で拒否（第8.3節） | B11-01 |
| SS-18 | 表示順だけを変更した新しい公開世代 | 同じDBを再利用し、DBのファイルのSHA-256が不変。Readiness Recordは新規作成。判定・安全上の情報は同一 | B11-01 |
| SS-19 | 目録から成果品を1つ欠落させる | CV-1で拒否 | B11-02 |
| SS-20 | 所属の件数を保ったまま、Featureキーを別のFeatureへ差し替える | CV-5で拒否（件数の一致だけで合格しない） | B11-02 |
| SS-21 | unknownだけを持つFeatureの成果品の所属を欠落させる | CV-3・CV-4で拒否 | B11-02 |
| SS-22 | 同じ成果品（同じFeature）を異なる `source_id` に二重登録する | CV-2で拒否 | B11-02 |
| SS-23 | 1つの `source_id` に想定最大規模と計画規模の成果品が混在 | CV-6で拒否 | B11-02 |
| SS-24 | 選択中3.0〜5.0m、他ソースに5.0〜10.0m＋比較不能な区域 | `true`（`deeper_zone_found`） | B11-03 |
| SS-25 | 選択中3.0〜5.0m、他ソースに0.5〜3.0m＋比較不能な区域 | `null`（`incomparable_zones_present`）。`false` にしない | B11-03 |
| SS-26 | 他ソースがunknownだけ | `false`（`no_confirmed_match_in_other_sources`）。`has_unknown_in_other_sources = true` | B11-03 |
| SS-27 | 選択中の `depth = null`（集約不能）、または選択中に確認済みの該当なし | `null`（`selected_depth_unavailable`・`selected_has_no_confirmed_match`）。件数はすべて `null`（比較を実施していない。Phase 2-B.14で追記） | B11-03・B13-04 |
| SS-28 | 他ソースが0件（選択中に `depth` がある場合） | `false`（`no_other_sources`）。`other_sources_count = 0`。件数はすべて `0`。選択中の `depth = null` の場合はSS-51（Phase 2-B.14で前提を明記） | B11-03・B13-04 |
| SS-29 | 他ソースが集約不能で、その内部に選択中より深い個別区域がある | `true`（`deeper_zone_found`） | B11-03 |
| SS-30 | 1つのソースで集約不能＋unknown＋境界接触が同時に成立 | `assessment_status = aggregation_undetermined`（導出順2）。`has_unknown`・`has_boundary_contact` が真、`uncertainty_reasons` に全理由 | B11-04 |
| SS-31 | ソースAは評価に成功、ソースBは読込みに失敗 | 応答全体が `retrieval_failed`・`result = null`。Aだけの成功応答・Bの `not_evaluated` にしない | B11-04 |
| SS-32 | 空の目録の公開候補、および非空の目録で全ソース該当0件 | 空の目録はCV-8・Readinessで阻害（万一読んだ場合は `indeterminate`・`flood_integrity_error`）。非空の該当0件は `success` で、状態は第5.2節で導出する（unknown・境界接触・外縁上があれば `unknown_only`、地域の内部でいずれもなければ `no_match_extent_unknown`。SS-37〜SS-40）。Phase 2-B.14で期待値を訂正 | B11-05・B13-01 |
| SS-33 | 同じ `scheme_id`・`class_code` で `scheme_version` が異なる2区域 | 別の区分として返し、重複排除でまとめない。MVPでは版をまたぐ比較を行わず、常に比較不能（Phase 2-B.14で訂正。SS-46・SS-47） | B11-06・B13-03 |
| SS-34 | 応答の上限の直後に、最も深い区域がある | 部分結果を返さず、明示的なエラー（API契約 第5.4節）。上限内の場合は全件を返す | B11-07 |
| SS-35 | 応答の上限の直後にunknownがある、または同じ深さの寄与区域が上限の外にある | SS-34と同じ。`contributing_zones` の参照先が欠けた成功応答を返さない | B11-07 |
| SS-36 | `source_id` を変更（なし・A・B）しても、他ソースの判定の項目が変わらない | 全ソースの事実・`assessment_status`・`depth`・区域の一覧が同一 | 独立性 |

**Phase 2-B.14の回帰テスト（B13-01〜B13-04）**。いずれも設計上の受入条件で、テストコードは作成・実行していない。

共通の前提（特に断らない限り）: 地点はサービス対象地域の内部。区分の体系は国土数値情報の浸水ランクコードで、同じ体系・同じ版・同じ比較規則。ソース間の比較は承認済み。選択中のソースはA。「比較不能な体系の区域」は、Aの区分と体系・版・比較規則のいずれかが異なる区域。Aにunknown・境界接触はない。

| ID | 入力・条件 | `assessment_status` | `overall_status` | `deeper_in_other_sources` / `basis` / 件数（deeper・not_deeper・incomparable） | 指摘 |
|---|---|---|---|---|---|
| SS-37 | 非空の目録（ソースAだけ）、`overview`。Aに確認済みの該当0件、L1 unknownあり | A: `unknown_only` | `unknown_only` | 返さない（`overview`） | B13-01 |
| SS-38 | 非空の目録（Aだけ）、`overview`。Aに該当0件、境界接触あり | A: `unknown_only` | `unknown_only` | 返さない | B13-01 |
| SS-39 | 非空の目録（Aだけ）、`overview`。地点が地域の外縁上、Aに該当・unknown・境界接触なし | A: `unknown_only`（`region_boundary`） | `unknown_only` | 返さない | B13-01 |
| SS-40 | 非空の目録（Aだけ）、`overview`。地域の内部、Aに該当・unknown・境界接触なし | A: `no_match_extent_unknown` | `no_match_extent_unknown` | 返さない | B13-01 |
| SS-41 | ソース間の比較が**未承認**。目録はAだけ（他ソース0件）。Aは3.0〜5.0m未満の確認済み該当 | A: `determined_match` | `determined_match` | `false` / `no_other_sources` / 0・0・0 | B13-02 |
| SS-42 | ソース間の比較が**未承認**。A: 3.0〜5.0m未満。他ソースBはunknownだけ | A: `determined_match`、B: `unknown_only` | `partial_unknown` | `false` / `no_confirmed_match_in_other_sources` / 0・0・0。`has_unknown_in_other_sources = true` | B13-02 |
| SS-43 | ソース間の比較が**未承認**。A: 3.0〜5.0m未満。B: 5.0〜10.0m未満の確認済み区域1件 | A・B: `determined_match` | `determined_match` | `null` / `cross_source_comparison_unapproved` / 0・0・1。深さの数値比較を行わない | B13-02 |
| SS-44 | Aに確認済みの該当なし（unknownだけ）。他ソースB・Cにそれぞれ確認済み区域1件（0.5〜3.0m未満、5.0〜10.0m未満） | A: `unknown_only`、B・C: `determined_match` | `partial_unknown` | `null` / `selected_has_no_confirmed_match` / null・null・null | B13-04 |
| SS-45 | Aが集約不能（Aに異なる版の2区域）。他ソースB・Cにそれぞれ確認済み区域1件 | A: `aggregation_undetermined`、B・C: `determined_match` | `partial_unknown` | `null` / `selected_depth_unavailable` / null・null・null | B13-04 |
| SS-46 | 異なる版の同深度区分: (a) A内に版v1のコード3と版v2のコード3、(b) A: v1のコード3（単独）、B: v2のコード3 | (a) A: `aggregation_undetermined`（`depth = null`）。(b) A・B: `determined_match` | (a) `partial_unknown`、(b) `determined_match` | (a) `overview` では `depth_classes_present` に2要素、`ordering = by_key`。(b) `null` / `incomparable_zones_present` / 0・0・1 | B13-03 |
| SS-47 | 異なる版の異なる深度区分: (a) A内にv1のコード3とv2のコード4、(b) A: v1のコード3、B: v2のコード4 | (a) A: `aggregation_undetermined`。(b) A・B: `determined_match` | (a) `partial_unknown`、(b) `determined_match` | (b) `null` / `incomparable_zones_present` / 0・0・1（`true` にしない） | B13-03 |
| SS-48 | 同一体系・同一版の異なる深度区分: (a) A内にコード2とコード3、(b) A: コード3、B: コード4 | (a) A: `determined_match`（`depth` はコード3）。(b) A・B: `determined_match` | `determined_match` | (b) `true` / `deeper_zone_found` / 1・0・0 | B13-03 |
| SS-49 | 深い区域＋比較不能な区域: A: 3.0〜5.0m未満、B: 5.0〜10.0m未満、C: 比較不能な体系の区域 | A・B・C: `determined_match` | `determined_match` | `true` / `deeper_zone_found` / 1・0・1 | B13-02 |
| SS-50 | 浅い区域＋比較不能な区域: A: 3.0〜5.0m未満、B: 0.5〜3.0m未満、C: 比較不能な体系の区域 | A・B・C: `determined_match` | `determined_match` | `null` / `incomparable_zones_present` / 0・1・1 | B13-02 |
| SS-51 | 他ソース0件（目録はAだけ）、Aの `depth = null`（Aに比較不能な2区域） | A: `aggregation_undetermined` | `partial_unknown` | `null` / `selected_depth_unavailable` / null・null・null（他ソース0件より選択側の理由を優先） | B13-04 |

## 13. 未決定事項とOWNER判断事項

| No | 事項 | 本書の提案 |
|---|---|---|
| SS-U1 | `source_id` の粒度 | 提供主体×シナリオ×配布単位の系列（東京都・関東地方整備局の2つ）。成果品ごとに分ける案は将来 |
| SS-U2 | ソース内の集約の正式な規則 | 同じ体系の正規化した区間で最も深い区分。CQ-1〜CQ-8の確認後に確定 |
| SS-U3 | ソース間の比較（`deeper_in_other_sources`・`depth_classes_present`）を返すことと、その前提（区分の体系の同一性の承認） | 返す。承認前は、比較の対象の区域がある場合に `null`（第7章。Phase 2-B.14で適用範囲を明確化） |
| SS-U4 | `source_id`・`zone_ref` の生成規則 | 公開世代の中で安定し、内部の原典へ戻せる不透明な識別子 |
| SS-U5 | `other` に含められるデータの資格 | 初期は該当なし |
| SS-U6 | 表示設定の承認の主体・軽重 | 版の固定と履歴は必須。承認の主体はOWNER判断 |
| SS-U7 | Source Catalogの `title`・`not_included_notice` 等の文言 | 未決定 |
| SS-U8 | UIでの、より深い想定・unknownの見せ方 | 見落としにくい表示。具体はUI設計で決める |
| SS-U9 | 将来のモード（`multiple_sources`・`compare`）の採否と、ソース間の比較の規則 | 保留 |
| SS-U10 | 公開世代に目録・設定を含める追加契約（SS-C1）、目録・割当記録の保存先（SS-C2） | Publish・Registryの追加契約として別途設計 |
| SS-U11 | 境界接触を確認済みの該当にしないこと | 提案どおり |
| SS-U12 | 同一Featureの複数 `source_id` への所属（別名・別視点） | 初期MVPでは禁止（CV-2）。将来の拡張として、別名関係と件数・比較への扱いを定める |
| SS-U13 | 意図的な除外の承認 | Integration Manifestの除外に、理由とOWNERの承認記録を結び付ける（第3.4節） |
| SS-U14 | 所属集合が変わる目録の変更の承認と `source_id` の継続性 | 所属が変わったソースに旧IDを再利用しない。承認の対象に含める（第8.3節） |
| SS-U15 | ソース間の比較の承認（`deeper_in_other_sources` の資格） | CQ-1・CQ-3の確認後にOWNERが承認。未承認の間は、比較の対象の区域がある場合に `null`。版の同等性の承認はMVPの対象外（SS-U17） |
| SS-U17 | 浸水深区分の版の同等性を承認して、版をまたいで比較・集約する仕組み | **MVPの対象外**（Phase 2-B.14）。将来、同等性の適用範囲・同深度の判定・集約の出力の識別子を定めて別途設計する |
| SS-U16 | 意図的な空の公開世代 | 初期MVPでは認めない（第3.5節） |

本書の採用は、製品実装・設定の承認・実データの処理・公開の承認ではない。
