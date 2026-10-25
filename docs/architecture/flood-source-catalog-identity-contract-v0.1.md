# Flood Source Catalog / Identity Contract v0.1（案）

- Task: Phase 2-C.1 Source Catalog / Identity Contract Finalization
- 作成: 2026-10-25（Claude）
- 状態: **実装契約案（OWNERレビュー待ち。正式採用されていない）**。本書は製品実装・実データの処理・公開の承認ではない
- 基準コミット: `07aeddd4452ca99ebfcbbcef5fa606ff569b8c2f`
- 上位: [ADR-001 複数の公式防災情報を独立して提示する](../decisions/2026-10-25-multiple-official-hazard-results.md)、[Design Principles](design-principles-v1.0.md)
- 親契約: [Flood Official Data Presentation Contract（案）](flood-official-data-presentation-contract-v0.1.md)（以下「提示契約」）。本書は提示契約 第4章・第5章・第10章の **Source Catalogのデータモデルと識別子の規則を具体化する正本**である。所属の完全性の検証 CV-1〜CV-9 の正本は提示契約 第5章のまま変えない
- 関連: [Flood API MVP Contract（案）](../api/flood-api-mvp-contract-v0.1.md)、[Flood Normalize Contract（案）](flood-normalize-contract-v0.1.md)、[Flood Integration Contract（案）](flood-integration-contract-v0.1.md)、[Dataset Registry](dataset-registry-v0.1.md)、[Data Publish](data-publish-v0.1.md)
- Schema案（すべて `docs/architecture/schemas/`）:
  - [flood-source-catalog.schema.json](schemas/flood-source-catalog.schema.json)（[例](schemas/flood-source-catalog.example.json)）
  - [flood-source-identity-ledger.schema.json](schemas/flood-source-identity-ledger.schema.json)（[例](schemas/flood-source-identity-ledger.example.json)）
  - [flood-source-category-assignment.schema.json](schemas/flood-source-category-assignment.schema.json)
  - [flood-public-lineage-summary.schema.json](schemas/flood-public-lineage-summary.schema.json)（[例](schemas/flood-public-lineage-summary.example.json)）
  - [flood-source-catalog-validate-record.schema.json](schemas/flood-source-catalog-validate-record.schema.json)
- 検討の記録: [Phase 2-C.1 レビュー](../../reviews/phase2/phase2c1-source-catalog-identity-contract.md)

区分: **［確定］** OWNER決定・既存の承認済み契約に由来、**［実測］** 調査で報告された値、**［提案］** 本書の設計提案（未承認）、**［未決定］** OWNER判断が必要。**Schema案・JSON例は正式Schemaではない**（提示契約・API契約の未決定事項 PD-U1・PD-U2・PD-U10・FA-U1 の具体案である）。

## 1. 目的と範囲

Source Catalogを実装できるデータモデルと、公開用・内部用の識別子の生成・対応・検証の規則を定める。**新しい判定機能は追加しない。** 公式の結果の比較・順位付け・代表値・集約を行わない（ADR-001、提示契約 第3章）。`source_id` の粒度は**データ管理の問題**であり、公式の結果を比較・順位付けするためのものではない。

本書が扱わないこと: 地点検索・結果の区別・提示の規則（提示契約）、APIの入出力の形（API契約）、Normalize・Integrationの処理（各契約）、Registry・Publish・Authorizationの正式仕様（第8章で契約差分として提案するだけ）。

## 2. 識別子の役割

| ID | 役割 | 公開 | 生成方式（第4章） | 正本 |
|---|---|---|---|---|
| `source_id` | 公式データ（公表データの系列）の識別 | 公開 | **割当台帳**（Source Identity Ledger）で割り当てる | 本書 |
| `zone_ref` | 個別区域（構成Polygon）の識別。**来歴は表さない** | 公開 | 内容由来（`record_key`・`polygon_index` のハッシュ） | 本書 |
| `product_ref` | 成果品への公開用の参照。区域から来歴をたどる | 公開 | 内容由来（原典ZIPのSHA-256・`product_id` のハッシュ） | 本書 |
| `lineage_ref` | ソースの公開用の来歴の要約への参照 | 公開 | 内容由来（要約の内容ハッシュ） | 本書 |
| `product_id` | 内部の成果品識別子（ZIPメンバー名の幹） | **内部** | 原典から導出（既存） | Normalize契約 第4.2節・第4.3節 |
| `record_key` | 内部の原典Feature追跡（原典ZIPのSHA-256・正規化メンバー名・`feature_index`） | **内部** | 原典から導出（既存） | Normalize契約 第4.3節、Integration契約 第6.2節 |

- `product_id`・`record_key` の既存の定義は置き換えない。公開用の参照は、これらから一方向に導出する（公開用の参照から内部の識別子を逆算できる必要はない。内部の対応表で戻る）。
- **公開しないもの**: `product_id`・`record_key`・ZIP名・ZIPメンバー名・ローカルパス・`run_id`・Recordの保存先・承認記録の内部参照（共通API契約 §5）。原典の配布ファイル名を公開用の来歴の要約に含めるかは［未決定: PD-U10］。

## 3. `source_id` の粒度（PD-U1の検討）

| 観点 | A. 公表主体単位 | B. 公表主体×想定条件×配布系列 | C. 原典成果品単位 |
|---|---|---|---|
| 原典との対応 | 1つのIDに複数のシナリオ・データ種別が混ざりうる（CV-6のシナリオの一致に反する） | 公表主体・シナリオ・配布系列（例: 国土数値情報A31aの東京都分・関東地方整備局分）と1対1 | 成果品（ZIPメンバー）と1対1 |
| 複数河川 | 属性（`rivers`）で扱う | 属性（`rivers`）で扱う | IDが河川ごとに分かれる（統合成果品は複数河川を含む［実測］） |
| 更新時の安定性 | 高い | 高い（同じ系列の更新は同じID・新しい `source_revision`） | 低い。成果品の分割・統合・改名でIDが変わる |
| Catalogの管理コスト | 低い | 低い（初期は2件） | 高い（関東地方整備局だけで想定最大規模48成果品［実測］） |
| 属性による検索・絞り込み | 主体内のシナリオの区別に別の属性が要る | 公表主体・河川・シナリオの属性で絞り込める | 河川で絞り込めるが、一覧が長い |
| 全国展開 | 主体が複数の系列を持つと破綻する | 都道府県・地方整備局ごとの系列が自然に増える | 成果品数に比例して増える |
| 重複所属の防止 | 主体内の系列の混在を防げない | 系列キー（第4.1節）の一意性で防げる | 成果品と1対1で、二重所属は起きにくい |

**推奨: B**［提案。OWNER承認前に確定扱いしない］。系列キーは（データセット、公表主体のコード、シナリオ、配布系列）とする（第4.1節）。東京都管理河川の2つのZIP（`_13_10`・`_13_20`）は同じ系列の1つの `source_id`、関東地方整備局（`_83_10`）は1つの `source_id` となる。河川別の探索は、`rivers` の属性で行い、IDを分けない（提示契約 第4.1節）。

## 4. 識別子の生成・維持の規則［提案］

### 4.1 `source_id`（割当台帳）

内容由来にしない理由: 同じ系列のデータが毎年更新されても、利用者・UIから見て同じ公式データとして識別できる必要がある。内容のハッシュでは更新のたびに変わる。

- **形式**: `fl-src-` に続く小文字英数字10文字（`^fl-src-[0-9a-z]{10}$`）。意味を持たない値を割当台帳で割り当てる（公表主体名・河川名・ファイル名を埋め込まない）。
- **割当台帳**（Source Identity Ledger。Schema: [flood-source-identity-ledger.schema.json](schemas/flood-source-identity-ledger.schema.json)）: 各エントリは `source_id`・状態（`active`・`retired`）・系列キー・割当日・廃止日・後継・承認の参照を持つ。台帳は新規作成のみで、既存のエントリの書換えをしない（状態の変更は新しい版の台帳で表し、旧版を保持する）。
- **系列キー**（`series_key`）: `dataset`（例: `ksj-a31a`）・`publisher_code`（`A31a_203`。例: `13`・`83`）・`scenario`（`maximum`）・`distribution_series`（配布系列。例: 国土数値情報の配布ZIPの地域コード `13`・`83`）。
- **一意性**: `active` のエントリの間で、`source_id` と `series_key` はそれぞれ一意。`source_id` は、`retired` を含む全エントリの間で一意で、**再利用しない**。
- **継続性**:

| 変更 | `source_id` | `source_revision` |
|---|---|---|
| 同じ系列のデータの更新（新しい取得・新しいZIPのSHA-256・成果品の内容の変更） | **同じ** | 1増やす |
| 同じ系列で、成果品の追加・削除（原典の配布単位の中の変更） | 同じ | 1増やす |
| 構造的な変更（系列の分割・統合、成果品の別の系列への移動、系列キーの変更） | **新しいIDを割り当て、旧IDは `retired`**（後継を記録） | 新しいIDで1から |
| 系列の公開の終了 | 旧IDは `retired`（後継なし） | — |

- 提示契約 第10章の「所属が変わったソースに旧世代の `source_id` を再利用しない」は、上の**構造的な変更**を指す。同じ系列のデータの更新は「所属の変更」に当たらない（本書で明確化）。
- 割当・廃止はOWNERの承認を要する（承認記録のSchemaは未決定: Integration契約 OI-27・提示契約 PD-C4）。

### 4.2 `product_ref`（内容由来）

- **形式**: `fl-prd-` に続く小文字16進16文字（`^fl-prd-[0-9a-f]{16}$`）。
- **生成**: 次の正規化JSON（Normalize契約 第11.1節の規則）のSHA-256の先頭16文字。

```json
{"domain":"hererisk-flood-product-ref-v1","product_id":"<内部のproduct_id>","zip_sha256":"<原典ZIPのSHA-256>"}
```

- **性質**: 同じ原典ZIP・同じ成果品なら世代をまたいで同じ値になる。原典の更新（ZIPのSHA-256の変更）で値が変わる（内容が変わったため、正しい）。`product_id` を復元できる情報を含まない。
- **一意性**: 公開世代の中で、異なる成果品の `product_ref` が一致したら（衝突）、Source Catalog Validateを不合格とする（ID-2）。黙って別名を付けない。

### 4.3 `zone_ref`（内容由来）

- **形式**: `fl-zn-` に続く小文字16進20文字（`^fl-zn-[0-9a-f]{20}$`）。
- **生成**: 次の正規化JSONのSHA-256の先頭20文字。`record_key` の正規化表現はIntegration契約 第6.2節と同じ。

```json
{"domain":"hererisk-flood-zone-ref-v1","polygon_index":0,"record_key":{"feature_index":0,"zip_member":"<正規化メンバー名>","zip_sha256":"<原典ZIPのSHA-256>"}}
```

- **性質**: 同じ原典・同じ構成Polygonなら世代をまたいで同じ値。原典の更新で変わる。ハッシュであり、ZIPメンバー名（ファイル名）を公開しない。
- **対応表**: 公開世代ごとに、`zone_ref` → （`record_key`, `polygon_index`, `product_ref`, `source_id`）の内部の対応表を持つ。区域（`search_target`）・unknown（`unknown_region`）・境界接触のいずれも、同じ構成Polygonなら同じ `zone_ref` になる（同じFeatureの有効な構成Pと判定保留の構成Qは、`polygon_index` が異なるので別の `zone_ref`）。
- **一意性**: 公開世代の中で衝突したら不合格（ID-3）。

### 4.4 `lineage_ref`（内容由来）

- **形式**: `fl-lin-` に続く小文字16進64文字（`^fl-lin-[0-9a-f]{64}$`）。
- **生成**: 公開用の来歴の要約（Public Lineage Summary。Schema: [flood-public-lineage-summary.schema.json](schemas/flood-public-lineage-summary.schema.json)）の正規化表現のSHA-256。要約は自身の `lineage_ref` を含まない。
- **要約の単位**: ソース（`source_id`, `source_revision`）ごとに1つ。成果品ごとの項目（`product_ref`）を持つ。公開世代の識別子を含めない。そのため、同じデータなら世代をまたいで同じ `lineage_ref` になる。
- **非公開の証跡との分離**: 要約は、Integration契約 第9.3節のLineage Manifest（非公開）から、公開してよい項目だけを写した**別の文書**である。要約の各項目は、内部でLineage Manifestの対応する項目に照合できる（ID-5）。

### 4.5 来歴の追跡

```text
API: zones[i].zone_ref ─┐
     zones[i].product_ref ──► sources[j].lineage_ref が指す要約 .products[] の同じ product_ref の項目
                                  （河川・管理者・版・原典ZIPのSHA-256 など公開してよい項目）
内部: zone_ref ─► 対応表 ─► record_key・polygon_index ─► Normalize成果物・原典ZIP・Acquisition Record
      product_ref ─► Catalogの products[]（zip_sha256・product_id）─► Lineage Manifest（非公開）
```

同じソースの異なる成果品から複数の区域が返された場合、各区域の `product_ref` が異なり、それぞれが要約の正しい成果品の項目に解決する（受入条件 CE-3）。

## 5. Source Catalogのデータモデル［提案］

Schema: [flood-source-catalog.schema.json](schemas/flood-source-catalog.schema.json)。例: [flood-source-catalog.example.json](schemas/flood-source-catalog.example.json)。Catalogは**内部の文書**であり、APIは公開用の項目だけを射影して返す（各項目の「公開」欄）。

### 5.1 Catalog全体

| 項目 | 型 | 必須 | null | 内容・検証 |
|---|---|---|---|---|
| `schema` | string（定数） | ○ | 不可 | `hererisk-flood-source-catalog-v0.1` |
| `catalog_id`・`version` | string | ○ | 不可 | 目録の同一性（Integration契約 第3.1節と同じ固定の規則） |
| `based_on` | object | ○ | 不可 | 対象の統合成果物（`integration_manifest_content_sha256`・`integrated_db_logical_sha256`）、区分の割当記録（`id`・`version`・`content_sha256`）、割当台帳（`version`・`content_sha256`） |
| `sources` | array（1件以上） | ○ | 不可 | 第5.2節。空は不可（CV-8） |

内容ハッシュ（`content_sha256`）は、Catalog文書の外（公開世代の設定の参照。API契約 第7章 `settings.source_catalog`）に置く。Catalog文書自身には含めない。

### 5.2 ソース（`sources[]` の要素）

| 項目 | 型 | 必須 | null | 公開 | 内容・検証 |
|---|---|---|---|---|---|
| `source_id` | string（`^fl-src-[0-9a-z]{10}$`） | ○ | 不可 | 公開 | 割当台帳の `active` のエントリ（ID-1） |
| `source_revision` | integer（≥1） | ○ | 不可 | 公開 | 第4.1節 |
| `series_key` | object | ○ | 不可 | 内部 | 割当台帳のエントリと一致（ID-1） |
| `source_category` | string（`local_government`・`national_government`・`other`） | ○ | 不可 | 公開 | 区分の割当記録と一致（CV-7）。順位を持たない。`unclassified` は公開の目録に載せない |
| `source_organization` | string（1文字以上） | ○ | 不可 | 公開 | 公表元の名称。公開の解釈は未承認（API契約 FA-C3） |
| `title` | string（1文字以上） | ○ | 不可 | 公開 | データの正式名称（文言は［未決定: PD-U5］） |
| `rivers` | array（1件以上） | ○ | 不可 | 公開 | 各要素は `river_code`（`A31a_201`。文字列）・`river_name_in_source`（`A31a_202`）・`product_refs`（その河川の情報を持つ成果品の `product_ref`）。代表河川名であり、個別の区域の原因河川ではない［実測］ |
| `scenario` | string（`maximum`） | ○ | 不可 | 公開 | 全成果品のシナリオと一致（CV-6） |
| `data_version` | object | ○ | 不可 | 公開 | `reference_year`（原典の年度。文字列）、`data_reference_date`（原典の基準日。確認できなければ `null`。推測で補完しない） |
| `attribution` | object | ○ | 不可 | 公開 | `text`（必須・1文字以上）、`license`・`url`（未解決の間は `null` を許す。**`null` のままでは公開できない**: Publication Readinessの `usage_terms_unresolved`。Integration契約 第7.3節） |
| `lineage_ref` | string（`^fl-lin-[0-9a-f]{64}$`） | ○ | 不可 | 公開 | そのソース・版の公開用の来歴の要約の内容ハッシュ（ID-4） |
| `service_region` | object | ○ | 不可 | 公開（参照だけ） | `region_rule_content_sha256`（地域定義の内容ハッシュ。Integration契約 第3章） |
| `assessed_extent` | object | ○ | 不可 | 公開 | `kind`: `unknown`（A31a）。`reference` は予約（評価済み範囲を持つデータ用。MVPでは使わない） |
| `depth_class_scheme` | object | ○ | 不可 | 公開 | `scheme_id`・`scheme_version`・`classes[]`（`class_code`・`label`・`lower_m`・`upper_m`（上限なしは `null`）・`bounds_inclusion`（`unspecified`））。原典の区分の表現（提示契約 第7.2節）。比較に使わない |
| `products` | array（1件以上） | ○ | 不可 | **内部** | 第5.3節 |
| `membership_digest` | object | ○ | 不可 | **内部** | `feature_count`（integer ≥0）・`feature_key_set_sha256`（昇順の `record_key` の正規化表現の配列のSHA-256）（CV-5） |

### 5.3 成果品（`products[]` の要素。内部）

| 項目 | 型 | 必須 | 内容・検証 |
|---|---|---|---|
| `product_ref` | string（`^fl-prd-[0-9a-f]{16}$`） | ○ | 第4.2節の再計算と一致（ID-2） |
| `zip_sha256` | string（64桁16進） | ○ | 入力成果品集合・来歴と一致（CV-1・CV-9） |
| `product_id` | string | ○ | 内部の成果品識別子 |
| `scenario_folder` | string | ○ | 例: `20_想定最大規模`（CV-6） |
| `normalize_content_sha256` | string | ○ | その成果品を含むNormalize成果物の内容ハッシュ |
| `manager_code`・`manager_name` | string | ○ | `A31a_203`・`A31a_204`（CV-7） |
| `river_code`・`river_name_in_source` | string | ○ | `A31a_201`・`A31a_202` |

## 6. 関連のRecord［提案］

| Record | Schema | 役割 |
|---|---|---|
| Source Identity Ledger | [flood-source-identity-ledger.schema.json](schemas/flood-source-identity-ledger.schema.json) | `source_id` の割当・廃止・後継（第4.1節） |
| Source Category Assignment Record | [flood-source-category-assignment.schema.json](schemas/flood-source-category-assignment.schema.json) | 区分と根拠（提示契約 第4.2節）。`unclassified` を含めて記録する |
| Public Lineage Summary | [flood-public-lineage-summary.schema.json](schemas/flood-public-lineage-summary.schema.json) | `lineage_ref` が指す公開用の来歴の要約（第4.4節） |
| Source Catalog Validate Record | [flood-source-catalog-validate-record.schema.json](schemas/flood-source-catalog-validate-record.schema.json) | CV-1〜CV-9（提示契約 第5章）と ID-1〜ID-6（第7章）の結果 |

各Recordは新規作成のみ・上書き禁止で、内容ハッシュで固定する（Normalize契約 第11.1節の正規化の規則）。保存先は未決定（提示契約 PD-C2）。

**Schemaで表せない検証**: JSON Schema案は、項目・型・必須性・null・形式・列挙値・未知のキーの拒否を表す。次の検証はSchemaでは表せないため、Source Catalog Validate（第7章・提示契約 第5章）で行う: 同じ成果品の二重登録（CV-2）、`source_id`・`series_key` の一意性と台帳との一致（ID-1）、ハッシュの再計算（ID-2〜ID-4）、集合の照合（CV-1・CV-3〜CV-5）、公開用の射影への内部識別子の漏えい（ID-6）。Schemaに適合することを、Source Catalog Validateの合格の代わりにしない。

## 7. 識別子の検証（Source Catalog Validateの追加項目）［提案］

Source Catalog Validateは、提示契約 第5章の **CV-1〜CV-9（変更しない）** に加えて、次を検証する。結果はSource Catalog Validate Recordに記録し、1つでも不成立なら公開世代を作らない（Publication Readinessの阻害理由とすることを提案。提示契約 PD-C3）。

| No | 検証 | 検出する反例 |
|---|---|---|
| ID-1 | 全ソースの `source_id` が割当台帳の `active` のエントリにあり、`series_key` が一致する。目録の中で `source_id` が重複しない | 未割当・廃止済みのIDの使用、系列の取り違え |
| ID-2 | 全成果品の `product_ref` を第4.2節の規則で再計算して一致し、公開世代の中で衝突がない | 改ざん・衝突 |
| ID-3 | 公開世代の全構成Polygon（`search_target`・`unknown_region` が参照するもの）の `zone_ref` を第4.3節の規則で再計算して一致し、衝突がない。対応表の全行が、所属を解決できる（CV-3・CV-4と同じ集合） | 対応表の欠落・改ざん・衝突 |
| ID-4 | 各ソースの `lineage_ref` が、公開世代に格納した要約の内容ハッシュと一致し、要約の `products[]` の `product_ref` の集合が、目録のそのソースの `products[]` の集合と一致する | 来歴の参照の解決不能・成果品の欠落 |
| ID-5 | 要約の各項目が、非公開のLineage Manifestの対応する項目（原典ZIPのSHA-256・取得・処理の版）と一致する | 要約と証跡の食い違い |
| ID-6 | 公開用の射影（API・要約）に、`product_id`・`record_key`・ZIP名・ZIPメンバー名・ローカルパス・`run_id` が含まれない（文字列の照合で検査） | 内部識別子の漏えい |

## 8. 既存契約との接続（契約差分の提案。既存契約は変更しない）

| No | 既存契約 | 提案する差分 | 状態 |
|---|---|---|---|
| CI-1 | Data Publish・Dataset Registry・Integration契約 第9.3節（公開世代の構成） | 公開世代に、Source Catalog（版・内容ハッシュ）・区分の割当記録・割当台帳の版・ソースごとの公開用の来歴の要約・`zone_ref` の対応表を含める。ロールバック時も組で戻す | 提示契約 PD-C1の具体化。**未決定** |
| CI-2 | データソース定義 §2（3種類の情報の正本） | 割当台帳・区分の割当記録・Catalogの保存先を、Source Definition・公開Registryとは別に新設する | PD-C2の具体化。**未決定** |
| CI-3 | Integration契約 第7.3節（Publication Readiness） | 阻害理由に `source_catalog_validation_failed`（CV-1〜CV-9・ID-1〜ID-6の不成立）を追加する | PD-C3の具体化。**未決定** |
| CI-4 | Integration契約 第6.2節（統合成果物の論理構造） | `zone_ref` の対応表を、統合成果物の中に持つか、公開世代のsidecarにするか。本書は「公開世代のsidecar（統合成果物から決定的に再生成できる）」を候補とする | **未決定** |
| CI-5 | 本番実行認可（承認記録のSchema） | 割当台帳の割当・廃止、区分の割当、Catalogの承認を表すSchema | Integration契約 OI-27・PD-C4。**未決定** |
| CI-6 | Data Publish（世代の保持） | 公開用の来歴の要約は、それを参照する公開世代が保持されている間は解決できること（旧世代の参照の保持の既存規則に従う） | 既存の規則の適用の確認。**未決定** |
| CI-7 | API契約 第5.3節・第7章 | `zone_ref`・`product_ref`・`lineage_ref` の形式を本書の第4章とする | 本書の採用時に参照で接続（API契約の正式Schema FA-U1） |

## 9. 反例と受入条件［提案］

| No | 反例 | 許容する状態 | 拒否する状態 | 検証箇所 |
|---|---|---|---|---|
| CE-1 | 同一公表主体が複数河川のデータを提供する | 1つの `source_id` に複数の成果品・河川。`rivers[]` に全河川、各区域に自分の `product_ref` | 河川ごとに原典を重複登録する | CV-2、Schemaの `rivers`・`products` |
| CE-2 | 同一地点に複数の公式区域が重なる（同じソース・異なるソース） | 区域ごとに別の `zone_ref` で全件を返す。比較・集約しない | 区域をまとめる・代表を作る | 提示契約 第7章、ID-3 |
| CE-3 | 同一ソース内に複数の原典成果品がある | 各区域の `product_ref` が異なり、要約の正しい成果品の項目に解決する | 要約にない `product_ref`、別の成果品への解決 | ID-2・ID-4 |
| CE-4 | 原典の更新で成果品の内容が変わる | 同じ `source_id`、`source_revision` が増え、`product_ref`・`zone_ref`・`lineage_ref` が新しい値。新しいManifestから再統合 | 旧い `product_ref` を新しい内容に使う | 第4章、提示契約 第10章、ID-2〜ID-4 |
| CE-5 | `source_id` の名称（タイトル）は同じでも、所属する成果品が構造的に変わる（分割・統合・移動） | 新しい `source_id`、旧IDは `retired`、後継を記録 | 旧IDを新しい所属集合で再利用 | 割当台帳、ID-1 |
| CE-6 | 同一成果品が二重登録される | — | 2つのソース、または同じソースに同じ（`zip_sha256`, `product_id`） | CV-2、ID-2（同じ `product_ref` の重複） |
| CE-7 | FeatureがCatalogに所属していない | — | 公開対象集合のFeatureの成果品が目録にない | CV-3、ID-3 |
| CE-8 | unknownだけが存在するFeature | `unknown_region` だけを持つFeatureも所属を解決でき、`zone_ref` を持つ | 判定用の形状がないことを理由に所属・対応表から漏れる | CV-4、ID-3 |
| CE-9 | 原典のファイル名や内部 `record_key` が公開APIへ漏れる | — | 公開の射影にZIP名・メンバー名・`product_id`・`record_key`・パスが現れる | ID-6、API契約 FA-07 |
| CE-10 | 公開世代を切り替えたとき、来歴参照が解決できなくなる | 新しい世代の応答は新しい世代の要約に解決。同じデータの `lineage_ref` は世代をまたいで同じ値。旧い世代が保持されている間は旧い要約も解決できる | 現行の世代で、`lineage_ref` が指す要約が公開世代に格納されていない | ID-4、CI-6 |

## 10. 未決定事項とOWNER判断事項

| No | 事項 | 本書の提案 |
|---|---|---|
| CI-U1 | `source_id` の粒度（PD-U1） | B（公表主体×想定条件×配布系列）。初期は2件 |
| CI-U2 | `source_id` を割当台帳で管理し、その他の公開用の参照を内容由来とする方式（PD-U2） | 第4章のとおり。割当・廃止にOWNERの承認を要する |
| CI-U3 | 同じ系列の更新（成果品の追加・削除を含む）を「所属の変更」に含めない解釈（提示契約 第10章の明確化） | 第4.1節の表のとおり |
| CI-U4 | `product_ref`（契約案）の採否と、公開用の来歴の要約の項目（PD-U10） | 採用。要約に原典の配布ファイル名を含めない案（含める場合は共通API契約 §5との関係を判断） |
| CI-U5 | ハッシュの長さ（`product_ref` 16桁・`zone_ref` 20桁） | 衝突は検証で検出して不合格。長さは実データの件数で再評価 |
| CI-U6 | `zone_ref` の対応表の格納先（CI-4） | 公開世代のsidecar |
| CI-U7 | 承認記録・保存先・公開世代の構成の追加契約（CI-1〜CI-3・CI-5・CI-6） | 別途、Publish・Registry・認可の追加契約として設計 |
| CI-U8 | `data_reference_date`（原典の基準日）の対応先（共通API契約 §5） | 確認できなければ `null` |

本書の採用は、製品実装・実データの処理・公開の承認ではない。
