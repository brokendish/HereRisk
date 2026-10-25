# Flood Official Data Presentation Contract v0.1（案）

- Task: Design Contract Realignment — 公式データ忠実提示方式への全面移行
- 作成: 2026-10-25（Claude）
- 状態: **Floodの公式データ提示の現行の正本**（契約案。正式採用はOWNERのレビュー待ち）。第1章の方針は**OWNERが決定した正式仕様**［確定］。その他の契約の文言は［提案］。本書は実装・実データの処理・公開の承認ではない
- 基準コミット: `bb7c438d6aa04a741f8d3ee867a0df4002512a48`
- 改訂: 2026-10-25 Phase 2-B.19 — Phase 2-B.18 Codex監査のLOW指摘への文書訂正。B18-01: 区域の来歴の参照（`zone_ref`・`lineage_ref`・`product_ref` の責務の区別。`product_ref` は契約案。第4.1節・第4.3節・第7.1節・PD-U10）。B18-02: 第9章のPD-U3の章番号の訂正。機能・方式は変更していない
- 上位: [Design Principles](design-principles-v1.0.md)
- 前提: [Flood Normalize Contract（案）](flood-normalize-contract-v0.1.md)、[Flood Integration Contract（案）](flood-integration-contract-v0.1.md)
- API: [Flood API MVP Contract（案）](../api/flood-api-mvp-contract-v0.1.md)
- 置き換えた設計案（履歴資料。**実装根拠として使用禁止**）: [Flood Source Selection Contract](flood-source-selection-contract-v0.1.md)（Phase 2-B.10〜B.16）、[Flood Source Priority Contract](flood-source-priority-contract-v0.1.md)（Phase 2-B.9）
- 検討の記録: [Phase 2-B.17 設計の全面整合レビュー](../../reviews/phase2/phase2b17-official-data-presentation-realignment.md)

区分: **［確定］** OWNERが決定した事項、**［実測］** 調査で報告された値、**［提案］** 本書の設計提案（未承認）、**［未決定］** OWNER判断が必要

## 1. 方針［確定］

**現在地に関係する公式防災情報を、原典の内容・出典・条件を保持して、複数あればすべて独立して提供する。**

- HereRiskは、異なる公式データの正誤・信頼性・優劣を判定しない。
- 複数の公式データを比較し、独自の代表値や危険度を算出しない。
- 利用者にデータの正当性判断を要求しない。
- 公式データ間の違いが存在することを、利用者が認識できるようにする。
- 原典にない説明や結論を付与しない。
- 検索対象として採用・公開されたデータは、欠落なく返却する。
- unknown、取得失敗、未収録、評価範囲不明を、安全や危険なしに置き換えない。

これはMVPの縮小ではなく、HereRiskの正式仕様である。

## 2. 正本の分担

同じ規則を複数の文書に複製しない。

| 対象 | 正本 |
|---|---|
| 最上位の原則 | [Design Principles](design-principles-v1.0.md) |
| 原典の保持・妥当性の評価 | [Flood Normalize Contract](flood-normalize-contract-v0.1.md) |
| 統合成果物・判定用の形状・unknownの範囲・Publication Readiness | [Flood Integration Contract](flood-integration-contract-v0.1.md) |
| データソースのモデル・目録・所属の完全性・ソースごとの地点検索・結果の区別・提示の規則・公開世代の構成 | **本書** |
| APIの入出力・エラー・世代の追跡 | [Flood API MVP Contract](../api/flood-api-mvp-contract-v0.1.md) |

## 3. 廃止した機能（再導入禁止）［確定］

次の機能は、HereRiskの公式防災データの提示から**廃止**した。現行の契約・実装・テストに導入しない。

1. 公表主体間の信頼性の順位による自動選択
2. 複数ソースからの唯一の代表浸水深の決定
3. 異なるソース間の浸水深の大小比較
4. `deeper_in_other_sources`
5. `deeper_comparison`
6. `deeper_zones`・`not_deeper_zones`・`incomparable_zones`
7. `cross_source_comparison_unapproved` 等、廃止した比較機能専用の判定・承認規則
8. 公式の結果を独自に順位付けする処理
9. 独自の最大浸水深・最大ランクの集約（同一ソース内の集約を含む）
10. 公表の結果から独自の安全・危険判定を生成する処理
11. 上記を前提とする状態の導出（`assessment_status`・`overall_status` 等）・比較の資格・版の同等性の承認の契約

廃止の経緯と、旧文書の検出箇所の扱いは [Phase 2-B.17 レビュー](../../reviews/phase2/phase2b17-official-data-presentation-realignment.md) に記録した。**原典の浸水深区分・版・区域・取得・検証・来歴・公開認可は維持する**（第5章〜第10章）。

## 4. データソースのモデル［提案］

### 4.1 識別子

| 識別子 | 意味 |
|---|---|
| `source_id` | 公表データの単位（例: 東京都管理河川の想定最大規模、関東地方整備局管理河川の想定最大規模）の公開用の不透明な識別子 |
| `source_category` | 提供主体の区分（`local_government`・`national_government`・`other`）。**分類・表示・絞り込みの属性であり、順位を持たない** |
| `product_id` | 原典の成果品ID（ZIPメンバーの幹）。内部の識別子 |
| `zone_ref` | 地点に関係した区域（構成Polygon）の公開用の不透明な識別子。**区域を識別するだけで、来歴は表さない** |
| `product_ref`［契約案。B18-01］ | 区域が属する成果品の、公開用の不透明な参照。そのソースの `lineage_ref`（第4.3節）が指す公開用の来歴の要約の中で、成果品の項目に解決できる。同じソースの複数の成果品から複数の区域を返す場合も、区域ごとに来歴を追跡するために使う |

- `source_id`・`zone_ref`・`product_ref` は不透明な識別子とする。内部のファイル名・ZIPメンバー名・ローカルパス・`record_key`・`product_id` を公開しない（共通API契約 §5）。公開世代の中で安定し、内部の原典へ戻せること。生成規則は［未決定: PD-U2］。
- **来歴の追跡の責務**: 区域の識別は `zone_ref`、成果品は `product_ref`、ソースの来歴の要約は `lineage_ref` が担う。区域 → `product_ref` → `lineage_ref` の要約の成果品の項目 → （内部で）Lineage Manifest・原典ZIPのSHA-256・Acquisition Record、の順にたどる。`zone_ref` から内部の原典（`record_key`・`polygon_index`）への対応は内部だけで持ち、公開しない。
- `source_id` の粒度（提供主体×シナリオ×配布単位の系列か、成果品ごとか）は［未決定: PD-U1］。粒度は、一覧の単位と所属集合（第5章）を決める。比較・集約を行わないため、粒度によって安全上の判定が変わることはない。
- 河川別・提供主体別・個別ソース別の探索は、データに付与された属性（`source_category`・河川の情報・`source_id`）で行う。**分類の目的で原典を重複して登録しない**（第5章 CV-2）。

### 4.2 提供主体の区分の確定（Source Category Assignment Record）

区分は、原典ZIPのダウンロード元（URL・ファイル名）だけで自動確定しない。次の根拠を確認し、版付き・承認付きの割当記録に保存する。

| 根拠 | 確認内容 |
|---|---|
| 原典の属性 | 対象の全Featureの `A31a_203`（河川管理者番号。01〜47 都道府県、81〜90 地方整備局等［実測: 製品仕様書］）と `A31a_204`（河川管理者）。`source_id` の全Featureで一致すること |
| 原典のメタデータ | ZIP内のメタデータ・製品仕様書の作成種別コードの定義 |
| 公式の掲載情報 | データページ・掲載河川一覧の管理区分（国管理・都道府県管理） |

分類できないソースを `other` へ割り当てない。根拠が一致しない場合は `unclassified` とし、公開世代への収録はPublication Readinessで阻害することを提案する（第11章 PD-C3）。

### 4.3 Source Catalog（ソースの目録）

公開世代ごとに、提示するソースの目録を固定する。

| 項目 | 内容 |
|---|---|
| `source_id`・`source_category` | 第4.1節・第4.2節 |
| `source_organization` | 公表元の名称（例: 「東京都」「国土交通省 関東地方整備局」）。出典の表示に使う（公開の解釈はAPI契約 FA-C3） |
| `title` | データの正式名称（文言は［未決定］） |
| `rivers` | 対象河川・流域等の原典の情報（成果品ごとの `A31a_201`・`A31a_202`。代表河川名であり、個別の区域の原因河川ではない［実測］） |
| `scenario` | 想定の条件（`maximum`＝想定最大規模） |
| `data_version` | 公表データの版・時点 |
| `attribution` | 出典・加工の表示（文言は［未決定: Integration契約 OI-10］） |
| `lineage_ref` | ソースの来歴の、**公開用の要約**への参照（内部パスを含めない）。要約は、そのソースの成果品ごとの項目（`product_ref` で参照される）を持つ。Integration契約 第9.3節のLineage Manifest（非公開の証跡）そのものではない。要約に含める項目と形式は［未決定: PD-U10］ |
| `service_region` | サービス対象地域の参照（初期は統合の対象地域で全ソース共通） |
| `assessed_extent` | 評価済み範囲の表現。**A31aは `unknown`**（評価済み範囲を持たない［実測: Phase 2-A.1］） |
| `depth_class_scheme` | 原典の浸水深区分の体系のID・版（第7.2節）。原典のコードを、原典の定義の文言・区間に対応付けるために使う |
| `products` | 内部。成果品の集合（原典ZIPのSHA-256, `product_id`）。所属割当の単位 |
| `membership_digest` | 内部。第5章の照合に使う、ソースごとのFeatureキー集合のSHA-256と件数 |

## 5. 所属の完全性と空の目録［提案］

**公開対象として採用した統合成果物の全Feature・全構成Polygon・全unknownは、Source Catalogから所属先の `source_id` を一意に解決できなければならない。** 件数の一致だけでは合格としない。

| 用語 | 定義 |
|---|---|
| 公開対象集合（正本） | 公開世代が参照する統合成果物（DB）の `zone_record` の全行（Integration契約 第6.2節） |
| Featureキー | `zone_record.record_key`（原典ZIPのSHA-256・正規化メンバー名・`feature_index`） |
| 入力成果品集合 | Integration Manifestの入力の成果品の組。理由を記録して除外した成果品は含まない。保持0件の成果品は含む |
| 所属割当 | 目録の `products`。成果品の組 → `source_id`。Featureの所属は成果品の所属から導く |

初期MVPでは、1つの成果品（したがって1つのFeature）を複数の `source_id` に所属させない。

**Source Catalog Validate**（公開世代を作る前の照合。結果をSource Catalog Validate Recordとして新規に作る）:

| No | 検証 | 検出する反例 |
|---|---|---|
| CV-1 | 目録の成果品の集合と入力成果品集合が**集合として一致** | 成果品の欠落・余分 |
| CV-2 | 同じ成果品の組が目録に2回以上現れない | 二重所属・分類目的の重複登録 |
| CV-3 | 公開対象集合の全行の原典ZIP・成果品が、目録の成果品の組のいずれかに一致 | 未割当のFeature |
| CV-4 | 全 `search_target`・全 `unknown_region` の行が、所属を解決できる `zone_record` を参照 | unknownだけを持つFeatureの未割当 |
| CV-5 | ソースごとのFeatureキー集合のSHA-256と件数が `membership_digest` と一致 | 件数を保ったままの差替え |
| CV-6 | 各ソースの全成果品が、そのソースの `scenario` のフォルダに属する | シナリオの混在 |
| CV-7 | 各ソースの全Featureの `A31a_203`・`A31a_204` が割当記録の根拠と一致 | 管理主体の混在 |
| CV-8 | 目録のソースが1件以上、各ソースの成果品が1件以上 | 空の目録・空のソース |
| CV-9 | 目録の成果品の原典ZIPが、統合成果物の来歴にある | 来歴にない原典の混入 |

- いずれかが不成立なら、その組合せの公開世代を作らない（Publication Readinessの阻害理由とすることを提案。第11章 PD-C3）。
- 意図的な除外は、Integration Manifestの成果品の除外（理由とOWNERの承認記録）で行う。目録だけで、統合成果物にあるFeatureを除外・非表示にしない。
- APIの起動時・公開世代の切替時に、目録とSource Catalog Validate Recordの対象が一致することを確認し、不一致なら起動・切替をしない。
- **空の目録は公開しない**（CV-8）。空の目録を「浸水想定なし」と解釈しない。万一、空の目録の公開世代を読んだ場合、APIは整合性エラーとする（API契約 第6章）。意図的な空の公開世代は、別の契約とOWNERの承認を必要とする。
- `candidate_completeness = not_guaranteed`（第6章）は、公開世代に登録されていない外部の公表データがありうることを表す。公開対象として採用したデータの所属漏れを許す意味ではない。

## 6. Source Discovery（候補の列挙）［提案］

地点がサービス対象地域の内部または外縁上にある場合、目録の**全ソース**を列挙し、各ソースについて第7章の検索結果を返す。

| 項目 | 内容 |
|---|---|
| `candidate_scope` | 列挙の範囲。初期値は `registered_sources_in_service_region` |
| `candidate_completeness` | `not_guaranteed`（初期は常にこの値）。登録されていない公表データ（例: 東京都の浸水予想区域図、内水・高潮の想定、計画規模、隣接県のA31a）がありうる［実測: Phase 2-A.1の注意事項］ |
| `not_included_notice` | 列挙の対象外のデータの種類（列挙値と公開用の文言。［未決定: PD-U5］） |

地点がサービス対象地域の外の場合は、ソースを列挙せず、地域外として返す（API契約 第6章）。

## 7. ソースごとの地点検索（Point Search）［提案］

### 7.1 独立した検索

各 `source_id` について、そのソースに属する判定用の構成Polygon（Integration契約 `search_target`）とunknownの範囲（`unknown_region`、L1）だけを使い、**他のソースを参照せずに**地点を検索する。ソース間で結果を比較・統合・順位付けしない。

| 出力（ソースごと） | 内容 |
|---|---|
| `zones[]` | 地点を内部に含む判定用の構成Polygon（確認済みの該当）の**全件**。各要素は `zone_ref`・`product_ref`（来歴の参照。第4.1節）・成果品の河川の情報・原典の浸水深区分（第7.2節） |
| `unknowns[]` | 地点がunknownの範囲（L1）に入る全件。各要素は `zone_ref`・`product_ref`・河川の情報・理由（`invalid_geometry`・`feature_invalid_component`）・`unknown_level`（`L1`） |
| `boundary_contacts[]` | 地点が判定用の構成Polygonの境界上にある全件（確認済みの該当ではない）。各要素は `zones[]` と同じ項目 |
| `service_region_relation` | `inside`・`boundary` |
| `assessed_extent_relation` | A31aでは `unknown` |

- **同じソースに複数の区域が該当した場合は、それぞれを個別に返す。** 1つの浸水深に集約しない（最大・代表を作らない）。
- 同じFeatureの有効な構成P（地点を含む）と判定保留の構成Q（L1の範囲に地点を含む）は、`zones` と `unknowns` の両方に現れる（Integration契約 `has_area_match`・`has_unknown`）。どちらも削除しない。
- 派生形状はMVPで使わない（BLOCKED）。unknownの範囲はL1だけ。
- **1つのソースでも検索に失敗した場合（読込み失敗・判定器の異常・整合性の異常）は、応答全体をエラーとする**（API契約 第6章）。成功したソースだけの成功応答にしない。失敗を「該当なし」として扱わない。
- **全件を返す。** 応答の大きさの上限を超える場合は、部分結果を返さず明示的なエラーとする（API契約 第5.4節）。

### 7.2 原典の浸水深区分の表現

各区域の浸水深区分は、原典のコードを、原典の定義の文言と区間で表す。これは原典の情報の表現であり、比較・集約のためのものではない。

| 項目 | 内容 |
|---|---|
| `scheme_id`・`scheme_version` | 区分の体系（国土数値情報の浸水ランクコード等）のIDと版 |
| `class_code` | 原典のコード（文字列に正規化。原典の型と値は `source_properties` に保持） |
| `label` | 原典の定義の文言（例: 「3.0～5.0m未満」） |
| `lower_m`・`upper_m` | 原典の定義の区間（上限なしは `null`） |
| `bounds_inclusion` | `unspecified`（A31aでは端点の包含が原典で未規定［実測: 製品仕様書］） |

A31aの浸水ランクコード［実測: 製品仕様書・コードリスト。Phase 2-A.1］:

| コード | 原典の定義 | `lower_m` | `upper_m` |
|---|---|---:|---:|
| 1 | 0～0.5m未満 | 0 | 0.5 |
| 2 | 0.5～3.0m未満 | 0.5 | 3.0 |
| 3 | 3.0～5.0m未満 | 3.0 | 5.0 |
| 4 | 5.0～10.0m未満 | 5.0 | 10.0 |
| 5 | 10.0～20.0m未満 | 10.0 | 20.0 |
| 6 | 20.0m以上 | 20.0 | `null` |

- 原典のランク番号から、架空の代表値（中央値等）を作らない［確定: 共通API契約 §4.2］。
- 同じ `scheme_id`・`class_code` でも `scheme_version` が異なれば、別の区分として、それぞれの版のまま返す。
- 原典の表現に関する確認事項: (1) 各原典ZIPが参照するコードリスト・製品仕様書の版、(2) `A31a_205` の型（東京都は文字列、関東地方整備局は整数［実測］）、(3) 端点の包含が未規定であることの表現、(4) コード5の「内容」欄の記載（津波基準水位）の扱い（PD-U4）。

## 8. 結果の区別［提案］

状態名を派生させず、**事実を表す項目**で結果を区別する。次の5つを混同しない。

| No | 区別 | 表し方 |
|---|---|---|
| 1 | 確認済み区域への該当 | そのソースの `zones[]` が空でない |
| 2 | 検索したが確認済み該当なし | そのソースの `zones[]`・`unknowns[]`・`boundary_contacts[]` がすべて空。**安全・浸水の可能性なしを意味しない**（`assessed_extent_relation = unknown`） |
| 3 | 不明または判定不能 | `unknowns[]`（判定保留）・`boundary_contacts[]`（境界上）が空でない、または `service_region_relation = boundary`（地域の外縁上で情報が不完全でありうる） |
| 4 | データ未収録・対象外 | 地点がサービス対象地域の外、Floodが未公開（API: `no_data`）。目録外の公表データの可能性は `candidate_completeness = not_guaranteed` |
| 5 | 取得失敗・データ整合性エラー | 応答全体のエラー（API: `retrieval_failed`・`indeterminate`。`result = null`） |

- 1と3は同じソースで同時に成り立ちうる（どちらも返す）。
- 評価済みの区域外であること（「非該当」）を表す値は使わない。A31aだけでは成立しない（Integration契約 第10章）。
- 安全・危険の判定、総合的な状態の要約は生成しない。

## 9. 提示と絞り込み［提案］

- **APIは常に、列挙した全ソースの検索結果を返す**（`overview`。初期表示の基本。Design Principles DP-04）。
- 河川別・提供主体別・個別ソース別の表示・絞り込み・主表示の切替えは、**UI（クライアント）が応答の属性を使って行う**。MVPのAPIは、ソースを選ぶ入力を持たない（第13章 PD-U3）。
- UIで絞り込み・切替えをしても、他のソースの結果が存在すること（件数・一覧への導線）と、他のソースのunknownを参照できるようにする（Design Principles DP-08）。
- 絞り込み・主表示の切替えは、正誤・信頼性の判定ではない。「おすすめ」「信頼度順」と表現しない。
- 一覧の並び順は、公開世代のSource Display Settings（表示順・グルーピング。版付き・内容ハッシュで固定）で決める。設定がない場合の既定は `source_id` の昇順。**並び順は信頼性の順位ではなく、検索結果を変えない。** リクエストで並び順を指定させない。
- 応答には、事実の件数（`sources_total`・`sources_with_zones`・`sources_with_unknown_or_boundary`）を含めてよい（API契約 第5.6節）。これは計数であり、比較・順位付けではない。
- 結果が異なる原因の説明は生成しない。出典・提供主体・対象河川・想定条件・版を並べて示す（Design Principles DP-05）。

## 10. 公開世代と変更の区分［提案］

公開世代は、統合成果物（DB）・地域形状・Lineage Manifest（Integration契約 第9.3節）に加えて、Source Catalog・Source Category Assignment Record・Source Display Settings・unknownポリシー（Integration契約 第3.1節）を、内容ハッシュで同一の世代に固定する。APIは1つの応答で1つの公開世代だけを使う。

| 変更 | 統合成果物（DB） | 必要な手順・条件 |
|---|---|---|
| 表示順・グルーピングだけ | 再利用する（ファイルのSHA-256は不変） | 新しい表示設定の検証・承認 → 新しい公開世代 → Publication Readinessの再作成 → Publish |
| unknownポリシーの改版 | **再生成する** | Integration契約に従い、新しいManifestから再統合・再検証 |
| 区分の割当記録の変更 | 再利用してよい | CV-1〜CV-9が成立。`source_id` の所属集合を変えない |
| 目録の表示項目の変更（所属集合は不変） | 再利用してよい | CV-1〜CV-9が成立し、`membership_digest` が旧世代と同じ |
| 目録の所属集合の変更（成果品の移動・ソースの分割・統合） | 再利用してよい | CV-1〜CV-9が成立。**所属が変わったソースに旧世代の `source_id` を再利用しない** |
| 公開対象集合の変更（成果品の追加・削除・除外、原典の更新、地域定義・N03の変更） | **再生成する** | 新しいManifestから再統合（Integration契約 第11.2節） |

- 異なるunknownポリシーのDBと公開設定を結び付けない。公開世代のunknownポリシーは、DBの `metadata`・Integrated Validate Record・Publication Readiness Recordの値と一致しなければならない。
- DBを再利用する場合も、Publication Readiness Recordは公開世代ごとに新規に作る。

## 11. 既存契約との論点（変更せず記録する）

| No | 既存契約 | 論点 |
|---|---|---|
| PD-C1 | Data Publish・Dataset Registry・Integration契約 第9.3節 | 公開世代に目録・区分の割当記録・表示設定・unknownポリシーを含める項目がない。追加の契約が必要 |
| PD-C2 | データソース定義 §2 | 区分の割当と目録は、Source Definition（予定）にも公開Registryにも入らない。保存先の新設が必要 |
| PD-C3 | Integration契約 第7.3節（Publication Readiness） | 阻害理由に、`unclassified` のソース・Source Catalog Validate（CV-1〜CV-9）の不成立・空の目録がない。公開設定とDBのunknownポリシーの一致の照合もない |
| PD-C4 | 本番実行認可 | 目録・区分の割当・表示設定の承認記録のSchemaがない（Integration契約 OI-27と同じ） |
| PD-C5 | Integration契約 第10章「有効な区域で該当しても、判定保留の区域のランクが分からないことを示す」 | unknownの区域の原典のランクを返すか（API契約 FA-U5） |

## 12. テストケース（設計のみ。いずれも実行していない）

| ID | 入力・条件 | 期待 |
|---|---|---|
| PD-01 | 東京都のソースにランク1、関東地方整備局のソースにランク4の区域が地点に該当 | 両方のソースの `zones` にそれぞれの区域が、原典の区分のまま返る。代表値・比較・どちらが深いかの判定を返さない |
| PD-02 | 東京都のソースがunknownだけ、関東地方整備局のソースにランク3の区域 | 東京都の `unknowns`、関東地方整備局の `zones` が両方返る。全体を確定したように表す項目がない |
| PD-03 | どのソースにも区域・unknown・境界接触がない（地域の内部） | 各ソースは区別2（検索したが確認済み該当なし）。`assessed_extent_relation = unknown`。浸水深0・浸水なし・安全の値を返さない |
| PD-04 | 同じソースの2区域（ランク2・ランク3） | 2つの区域を個別に返す。集約しない |
| PD-05 | 同じFeatureの有効Pと判定保留Q | 同じソースの `zones` と `unknowns` の両方に現れる |
| PD-06 | 同じ `scheme_id`・`class_code` で `scheme_version` が異なる2区域 | 別の区分として、それぞれの版のまま返る |
| PD-07 | ソースAは検索に成功、ソースBは読込みに失敗 | 応答全体がエラー（`retrieval_failed`）。Aだけの成功応答にしない |
| PD-08 | 目録から成果品を1つ欠落・同件数でFeatureを差替え・unknownだけのFeatureを未割当・二重所属・シナリオの混在 | CV-1・CV-5・CV-3/CV-4・CV-2・CV-6で拒否 |
| PD-09 | 空の目録の公開候補、および万一読んだ場合 | 公開しない。読んだ場合は整合性エラー |
| PD-10 | unknownポリシーv1のDBに、v2の公開設定を結び付ける | 照合で拒否 |
| PD-11 | 表示順だけを変更した新しい公開世代 | DBは再利用（SHA-256不変）。検索結果は同一で、並び順だけが変わる |
| PD-12 | 応答の大きさが上限を超える地点（上限の直後に区域・unknownがある場合を含む） | 部分結果を返さず、明示的なエラー |
| PD-13 | 地域の外縁上で区域・unknownなし | ソースを列挙し、`service_region_relation = boundary`（区別3）。地域の外ならソースを列挙せず地域外 |
| PD-14 | 応答の全体 | 廃止した項目（第3章）が現れない。内部パス・ファイル名・`record_key` が現れない |
| PD-15 | 同じ地点・同じ公開世代で繰り返し | 結果・並び順が同一 |

## 13. 未決定事項とOWNER判断事項

| No | 事項 | 本書の提案 |
|---|---|---|
| PD-U1 | `source_id` の粒度 | 提供主体×シナリオ×配布単位の系列（東京都・関東地方整備局の2つ）を候補 |
| PD-U2 | `source_id`・`zone_ref` の生成規則・世代間の継続性 | 公開世代の中で安定した不透明な識別子。所属が変わったソースに旧IDを再利用しない |
| PD-U3 | ソースを選ぶ入力（サーバ側の絞り込み）をAPIに設けるか | MVPでは設けない。絞り込み・主表示の切替えはUIで行う。将来設ける場合も、他のソースの存在を返し、検索結果を変えない |
| PD-U4 | 原典の浸水深区分の表現の確認事項（第7.2節の(1)〜(4)） | 実データの確認の後に確定 |
| PD-U5 | `title`・`not_included_notice`・説明の文言 | 「安全」「浸水なし」「おすすめ」「信頼度順」と誤読されない文言。OWNERが確定 |
| PD-U6 | 表示設定の承認の主体・軽重 | 版の固定と履歴は必須 |
| PD-U7 | `other` に含められるデータの資格 | 初期は該当なし |
| PD-U8 | 同一Featureの複数 `source_id` への所属（別名・別視点） | 初期MVPでは禁止。分類の目的では属性を使う |
| PD-U9 | 意図的な除外の承認、意図的な空の公開世代 | 除外はManifestで承認付き。空の世代は認めない |
| PD-U10 | 公開用の来歴の要約（`lineage_ref` が指すもの）に含める項目・形式と、`product_ref` の採否（B18-01） | `product_ref` は契約案。要約には成果品ごとに、公開してよい項目（河川の情報、管理者、公表データの版、原典ZIPのSHA-256等）だけを含める案。原典の配布ファイル名・ZIPメンバー名を公開するかは、共通API契約 §5（ファイル名を公開しない）との関係で未決定。正式Schema（API契約 FA-U1）と同時に確定する |

本書の採用は、製品実装・実データの処理・公開の承認ではない。
