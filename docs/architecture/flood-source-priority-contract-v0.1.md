# Flood Source Priority & Risk Aggregation Contract v0.1（案）— **SUPERSEDED / HISTORICAL**

> **履歴資料（2026-10-25 Phase 2-B.17で表示を更新）: 本書は現行の仕様ではない。実装・API・UI・テストの根拠として使用禁止。** 本書の後継だった [Flood Source Selection Contract](flood-source-selection-contract-v0.1.md) も、Phase 2-B.17で履歴資料となった。現行の正本は [Flood Official Data Presentation Contract（案）](flood-official-data-presentation-contract-v0.1.md) と [Flood API MVP Contract（案）](../api/flood-api-mvp-contract-v0.1.md) である。下の「移行案内」で「後継へ引き継いだ」とした事項のうち、ソース内の集約・安全上の比較は、Phase 2-B.17で廃止した。

> **移行案内（2026-10-25 Phase 2-B.10）**: 本書の「提供主体の優先順位に基づく自動代表選択」は、設計案の改訂により採用しないことになった。後継の設計案は [Flood Source Selection Contract v0.1（案）](flood-source-selection-contract-v0.1.md)（利用者によるデータソースの選択）である。変更の内容は [Phase 2-B.10 レビュー](../../reviews/phase2/phase2b10-source-selection-redesign.md) を参照。
>
> - **本書は履歴資料として残す。** 本書の規則を、実装・API契約・UIの根拠として使わない。
> - 「置き換え（superseded）」は**設計案の変更履歴**を指す。本書も後継の設計案も、OWNERに正式採用されていない。
> - 後継へ引き継いだ事項: 提供主体の区分とその確定（第3章。ただし順位を持たない）、原典の保持・来歴・版管理・内容ハッシュによる固定、unknownの独立した保持、区域ごとの状態（境界接触・unknown・評価範囲不明）、浸水深区分の正規化と比較の規則・確認項目CQ-1〜CQ-8（同一ソース内の集約と安全上の比較に限定）。
> - **廃止した事項**: Source Priority Policy（第4章・第5章）、`source_category_order`・`fallback_rule`、優先順位による代表結果の選択（第7章）、`representative`・`selection_reason`・`priority`・`finality`、区分ごとの状態（第7.2節）、異なる区分にまたがる「同順位」の集約（第8章。同一ソース内の集約へ再定義）、優先順位を描画順とするレイヤー表示（第9章）。
> - 以下の本文は、Phase 2-B.9の時点の内容のまま変更していない。

- Task: Phase 2-B.9 Flood API MVP Scope / Source Priority & Risk Aggregation Contract
- 状態: **置き換え済みの設計案（履歴資料）**。Phase 2-B.9の時点では契約案（OWNERレビュー待ち。正式採用されていない）。本書は製品実装・ポリシーの承認・有効化・実データの処理・公開の承認ではない
- 作成: 2026-10-24（Claude）
- 基準コミット: `a701921540e4cf1e109b8932fcac2de1777d0870`
- 前提: [Flood Normalize Contract v0.1（案）](flood-normalize-contract-v0.1.md)、[Flood Integration Contract v0.1（案）](flood-integration-contract-v0.1.md)、[Phase 2-B.8 監査対応表](../../reviews/phase2/phase2b8-codex-audit-remediation.md)
- 関連: [Flood API MVP Contract v0.1（案）](../api/flood-api-mvp-contract-v0.1.md)、[共通API契約](../api/common-contract-v0.1.md)、[Dataset Registry設計](dataset-registry-v0.1.md)、[Data Publish設計](data-publish-v0.1.md)、[データソース定義設計](data-source-definition-v0.1.md)、[本番実行認可設計](production-authorization-v0.1.md)
- 検討の記録: [Phase 2-B.9 レビュー](../../reviews/phase2/phase2b9-flood-mvp-scope-and-priority.md)

区分: **［確定］** 既存の承認済み契約に由来、**［実測］** Phase 2-A.1〜B.5の調査で報告された値（対象集合を併記）、**［提案］** 本書の設計提案（未承認）、**［未決定］** OWNER判断が必要

## 1. 目的と設計原則

同じ地点に複数のA31a浸水想定区域が重なる場合に、APIが返す**代表結果**を決める規則と、その規則を版付きで管理・承認・有効化する仕組みを定める。

設計原則: **内部は厳密に。外部はシンプルに。不確実性は隠さない。**

| 原則 | 内容 |
|---|---|
| SP-1 選択と保持の分離 | 優先順位は**代表結果の選択**だけに使う。原典Feature・該当区域・unknownを、優先順位を理由に削除・非表示にしない |
| SP-2 選択と安全評価の分離 | 代表結果は「どのソースの値を代表として表示するか」の運用設定であり、危険度の評価・提供主体の優劣・精度の評価ではない。代表より深い浸水想定が他ソースにあれば、その事実を消さない |
| SP-3 unknownの独立 | unknown（判定保留）は優先順位の選択とは独立した情報として、順位にかかわらず全件保持する。unknownを非該当として扱わない |
| SP-4 非該当の禁止 | A31aにPolygonがないことだけで、調査済み・浸水なしと確定しない。A31aは評価済み範囲を持たない［実測: Phase 2-A.1］ |
| SP-5 設定による変更 | 優先順位の変更は、ポリシーの新版の承認・有効化で行い、Normalize・Integrationの成果物を修正・削除・再生成しない |
| SP-6 承認された版だけ | 本番の判定には、承認済みで有効化された版のポリシーだけを使う。リクエストごとのポリシー指定・上書きを禁止する |
| SP-7 決定性 | 同じ公開世代・同じ地点からは、常に同じ代表結果・同じ並び順の結果を返す |

## 2. 範囲

本書が扱うのは、提供主体の区分のモデル（第3章）、Source Priority Policy（第4章）と承認・有効化・世代管理（第5章）、地点判定・代表選択・集約の3段階（第6章〜第8章）、レイヤー表示との接続条件（第9章）、既存契約との責務分界（第10章）である。

APIの入出力は [Flood API MVP Contract](../api/flood-api-mvp-contract-v0.1.md) で定める。Normalize・Integration・既存のRegistry / Publish / Authorization契約は変更しない（既存契約との論点は第10.2節）。

## 3. 提供主体の区分とデータソース

### 3.1 2つの識別子を分ける［提案］

| 識別子 | 意味 | 例 |
|---|---|---|
| `source_category` | 提供主体の区分。代表結果の選択の単位 | `local_government`、`national_government`、`other` |
| `source_id` | 実際のデータソース（原典ZIP・成果品の系列）の安定した識別子 | 東京都管理河川の想定最大規模（`_13_10`・`_13_20`）、関東地方整備局の想定最大規模（`_83_10`） |
| `product_id` | 原典の成果品ID（ZIPメンバーの幹） | `A31a-20-25_83_8303040001_10` |

- 同じA31a形式で配布されていても、提供主体が異なるデータは別の `source_id` とする。原典の成果品ID・河川管理者番号（`A31a_203`）・河川管理者（`A31a_204`）・来歴は、Integrationの `zone_record` にそのまま保持されている（Integration契約 第5章・第6.2節）。
- `source_id` の命名規則は［未決定: SP-U4］。内部のファイル名・ZIP名・パスを、公開用の `source_id` にそのまま使わない（共通API契約 §5）。

### 3.2 初期の区分と優先順位［提案］

| priority | `source_category` | 表示名 | 該当する原典（初期） |
|---|---|---|---|
| 1 | `local_government` | 地方自治体 | 東京都管理河川のA31a（`A31a_203` が都道府県コード 01〜47［実測: 製品仕様書］の成果品） |
| 2 | `national_government` | 国土交通省（国の機関） | 関東地方整備局管理河川のA31a（`A31a_203` が地方整備局等のコード 81〜90［実測: 製品仕様書］の成果品） |
| 3 | `other` | その他 | **初期は該当なし**。資格は未決定（SP-U3） |

- この順序は**代表結果を選ぶための運用設定**であり、提供主体の優劣・精度・信頼性の評価ではない。
- 区分の一覧と順序はSource Priority Policyの内容（第4章）であり、コードに埋め込まない。

### 3.3 区分の確定（Source Category Assignment）［提案］

区分は、**原典ZIPのダウンロード元（URL・ファイル名）だけで自動確定しない**。次の根拠を確認し、版付きの割当記録として保存する。

| 根拠 | 確認内容 |
|---|---|
| 原典の属性 | 対象の全Featureの `A31a_203`（河川管理者番号）と `A31a_204`（河川管理者）。成果品の全Featureで一致すること |
| 原典のメタデータ | ZIP内のメタデータ・製品仕様書の作成種別コードの定義（01〜47 都道府県、81〜90 地方整備局等［実測: Phase 2-A.1］） |
| 公式の掲載情報 | データページ・掲載河川一覧の管理区分（国管理・都道府県管理） |

**Source Category Assignment Record**（割当記録。新規作成のみ・上書き禁止）:

| 項目 | 内容 |
|---|---|
| `assignment_id`・`version`・`content_sha256` | 割当記録の同一性（第4.2節と同じ固定の規則） |
| `entries[]` | `source_id`、対象の原典（原典ZIPのSHA-256、`product_id` の集合、またはNormalize成果物の `content_sha256`）、`source_category`、根拠（上表の各項目の参照・値・確認日）、`source_organization`（公開用の提供主体名。例: 「国土交通省 関東地方整備局」） |
| `approval` | 承認記録の参照（第5章） |

- **分類できないソースを `other` へ割り当てない。** 根拠が一致しない（例: 成果品内で `A31a_203` が混在する、属性と掲載情報が矛盾する）場合は `unclassified` とし、その理由を記録する。
- `unclassified` のソースは代表結果の選択に参加させない（第7.4節）。また、`unclassified` のソースを含む公開を、Publication Readiness（Integration契約 第7.3節）で阻害理由とすることを提案する（既存契約への追加の論点。第10.2節 SP-C3）。
- 区分は、1つの `source_id` に1つとする。1つの原典ZIPに複数の管理主体の成果品がある場合は、成果品の集合ごとに別の `source_id` に分ける。
- 割当記録は、Integration成果物の外に置く。**区分の変更でIntegration成果物を作り直さない**（Integrationは管理者番号等の原典属性を保持しており、区分は公開世代で結び付ける。第5.3節）。
- 指示書の「Source Registry」に相当する既存の契約はない。既存のSource Definitionは「取得予定の正本」であり、確認済みの事実を入れない（データソース定義 §2）。そのため割当記録は、Source Definitionとも公開Registryとも別の記録とする（第10.2節 SP-C2）。

## 4. Source Priority Policy［提案］

### 4.1 ポリシーの内容

代表結果の選択規則を、版付きの独立した文書として管理する。

```json
{
  "schema": "hererisk-flood-source-priority-policy-v0.1",
  "policy_id": "flood-source-priority",
  "version": "v1",
  "source_category_order": [
    {"priority": 1, "category": "local_government", "label": "地方自治体"},
    {"priority": 2, "category": "national_government", "label": "国土交通省（国の機関）"},
    {"priority": 3, "category": "other", "label": "その他"}
  ],
  "same_priority_resolution": {
    "rule": "deepest_comparable_depth_class",
    "classification_scheme": {"id": "ksj-a31a-water-depth-rank", "version": "<コードリストの版>"},
    "on_incomparable": "aggregation_undetermined",
    "tie_order": ["source_id", "product_id", "zone_ref"]
  },
  "fallback_rule": "next_priority_with_confirmed_match",
  "unknown_handling": {
    "independent_of_selection": true,
    "retain_all_priorities": true,
    "mark_representative_provisional_if_higher_or_same_priority_unknown": true
  },
  "boundary_handling": "boundary_contact_is_not_confirmed_match",
  "unclassified_handling": "exclude_from_selection_and_report",
  "applies_to": {"api_id": "flood", "scenario": "maximum",
                 "region_rule_content_sha256": "<地域定義の内容ハッシュ>",
                 "category_assignment": {"assignment_id": "<…>", "version": "<…>", "content_sha256": "<…>"}},
  "approval_ref": null,
  "effective_generation": null
}
```

値はすべて例示であり、承認済みのポリシーではない。

| 項目 | 必須 | 内容 |
|---|---|---|
| `policy_id` | ○ | 不変のポリシーID |
| `version` | ○ | 版。同じ（`policy_id`, `version`）に異なる内容を割り当てない |
| `content_sha256` | ○ | ポリシー文書（`content_sha256`・`approval_ref`・`effective_generation` を除く）の正規化表現のSHA-256（Normalize契約 第11.1節の規則）。文書の外の記録（承認記録・有効化記録）でも同じ値を持つ |
| `source_category_order` | ○ | 区分と優先順位。priorityは1から始まる連番で重複なし。区分の重複なし |
| `same_priority_resolution` | ○ | 同順位の集約規則（第8章） |
| `fallback_rule` | ○ | 上位区分に確認済みの該当がない場合の規則。初期は `next_priority_with_confirmed_match`（次の順位の確認済み該当へ進む） |
| `unknown_handling` | ○ | unknownの扱い（第7.3節）。初期値の3項目は**変更不可の制約**とする（`false` にした版は検証で拒否する） |
| `applies_to` | ○ | 適用対象（API・シナリオ・地域定義・区分の割当記録の同一性） |
| `approval_ref` | ○（未承認は `null`） | 承認記録の参照（第5章） |
| `effective_generation` | ○（未有効化は `null`） | 有効化された公開世代（第5.3節） |

- `approval_ref`・`effective_generation` は、承認・有効化の後に**ポリシー文書の外の記録**（承認記録・有効化の記録）で与える。ポリシー文書そのものは書き換えない（`content_sha256` の対象外にした理由）。
- 本書の初期値（地方自治体 → 国土交通省 → その他）は、OWNERの承認があるまで**提案値**である。

### 4.2 同一性と固定

Integration契約 第3.1節（unknownポリシーの固定）と同じ規則を適用する。不変の保存先（内容ハッシュをパスに含む `records/policies/source_priority/<policy_id>/<version>/<content_sha256>.json`）、読み出すたびの内容ハッシュの再計算、承認の範囲の照合、期限・失効の検証を行う。同じ参照先の内容を差し替えても使えない。

## 5. 変更の手順・承認・有効化・世代管理［提案］

### 5.1 状態の遷移

```text
draft ─► validated ─► approved ─► active ─► superseded
  │          │            │          │
  └──────────┴────────────┴──────────┴─► withdrawn（取消し。再有効化しない）
```

| 状態 | 入る条件 | 記録 |
|---|---|---|
| `draft` | Data Managementで新しい版を作成 | ポリシー文書（不変の保存先に新規作成） |
| `validated` | 第5.2節の検証に全項目合格 | Policy Validate Record（対象の `content_sha256`） |
| `approved` | OWNERが承認 | 承認記録（対象の `policy_id`・`version`・`content_sha256`・適用対象・有効期間） |
| `active` | 公開世代に結び付けて有効化（第5.3節） | Publish記録・公開Registry |
| `superseded` | 新しい版が有効化された | 履歴として保持（削除しない） |
| `withdrawn` | 承認の取消し | 失効一覧。取消し後に、その版を含む公開世代を新たに公開しない |

- 状態は文書の書換えではなく、記録の追加で表す。過去の版・承認・有効化の履歴は削除しない。
- `draft` の内容を変える場合は、新しい版を作る（同じ版の内容を変更しない）。

### 5.2 Policy Validate（検証）

| No | 項目 |
|---|---|
| PV-1 | Schemaの検査。`priority` が1からの連番で重複なし、区分の重複なし |
| PV-2 | `unknown_handling` の3項目が `true`（unknownを捨てる版を拒否） |
| PV-3 | `applies_to.category_assignment` の割当記録が存在し、内容ハッシュが一致し、承認済みである |
| PV-4 | 適用対象の公開予定の全 `source_id` に区分があり、その区分がポリシーの区分の一覧に含まれる（`unclassified` があれば不合格） |
| PV-5 | `same_priority_resolution.classification_scheme` が、適用対象の全ソースの浸水深区分の体系と一致する（第8.2節） |
| PV-6 | 固定の検証地点の集合（合成データ・承認済みの検証地点）で、旧版と新版の代表結果の差分を算出して記録する（差分の報告。合否ではなく、承認の判断材料） |
| PV-7 | 検証は読取専用で、Normalize・Integration成果物を変更しない |

### 5.3 有効化と世代の固定

- **ポリシーは公開世代に結び付けて有効化する。** 公開世代は、統合成果物（DB）・地域形状・Lineage Manifest（Integration契約 第9.3節）に加えて、**Source Priority Policy・Source Category Assignment Record・unknownポリシー**を、それぞれの内容ハッシュで同一の世代として固定する。
- 優先順位だけを変更する場合は、**同じ統合成果物を参照する新しい公開世代**を作り、既存のData Publishの原子的な切替えで有効化する。統合成果物は再生成しない（SP-5）。
- APIは、1つの応答の中で1つの公開世代だけを使う。旧版と新版のポリシーを混在させない。応答には公開世代とポリシーの識別子・版・内容ハッシュを含める（API契約 第6章）。
- APIの起動時・世代切替時に、ポリシー文書の内容ハッシュが公開世代の記録と一致することを確認し、不一致なら起動・切替をしない（Integration契約 第6.4節の地域形状の世代の固定と同じ考え方）。
- キャッシュ（応答・ポリシー・判定結果）のキーには公開世代の識別子を含める。世代の切替えで旧世代のキャッシュを使わない。
- ロールバックは、既存のRestore → Publishの契約で、旧世代（旧ポリシーを含む組）を戻す。ポリシーだけを個別に巻き戻さない。

**既存契約との関係**: 既存のData Publish・Registryは、公開世代にポリシーを含める項目を持たない。これは追加の契約が必要な論点として記録し、本書では既存契約を変更しない（第10.2節 SP-C1）。

### 5.4 禁止事項

- リクエストのパラメータ・ヘッダー等で、ポリシーの指定・上書き・優先順位の変更を受け付けること。
- 未承認・期限切れ・取消し済みの版で本番の判定を行うこと。
- 管理画面の操作で、承認を経ずに即時に有効化すること。
- 優先順位の変更を理由に、Normalize・Integration成果物・原典Featureを修正・削除すること。

## 6. 3段階の処理

```text
地点 ─► A. Point Assessment ─► B. Source Priority Resolution ─► C. Risk Aggregation / API Response
         （全ソース・全区域の事実）   （代表ソースの選択）              （代表値・全該当・unknown・説明）
```

各段階の出力は次の段階の入力であり、**後段は前段の事実を削除・変更しない**。

### 6.1 A. Point Assessment［提案］

公開世代の統合成果物の全ソース（利用資格のあるもの）について、地点と各区域の関係を判定する。

| 出力 | 内容 |
|---|---|
| `zone_hits[]` | 地点を内部に含む判定用の構成Polygon（`search_target`）ごとに: 原典Featureへの参照、`source_id`、浸水深区分、`relation = inside` |
| `boundary_contacts[]` | 地点が判定用の構成Polygonの境界上にあるもの（`relation = boundary`）。Integration契約の点の判定の受入ケース（外周・穴の境界上は判定保留）に従う |
| `unknown_hits[]` | 地点が `unknown_region`（L1）の範囲に入るもの: 原典Featureへの参照、`source_id`、理由（`invalid_geometry`・`feature_invalid_component` 等）、原典の浸水深区分 |
| `region_state` | `inside`・`outside`・`region_boundary`（Integration契約 第6.4節） |
| `source_states[]` | 第7.2節のソースごとの状態 |

- 1つの原典Featureの有効な構成Pに地点が含まれ、同じFeatureの判定保留の構成QのL1範囲にも入る場合は、`zone_hits` と `unknown_hits` の両方に記録する（Integration契約 第4.1節 `has_area_match`・`has_unknown`）。
- Point Assessmentは優先順位を参照しない。全ソースを同じ規則で判定する。
- 判定器の判定保留・読込みの失敗は、該当なしとして扱わない（API契約のエラー・判定不能の分類へ）。

### 6.2 B. Source Priority Resolution［提案］

第7章の規則で、代表結果に使うソース（区分）を選ぶ。入力はPoint Assessmentの結果と、公開世代に固定されたポリシー・区分の割当記録だけである。

### 6.3 C. Risk Aggregation / API Response［提案］

代表値の集約（第8章）と、全該当・unknown・ソースごとの状態・説明をまとめる。公開用の表現への変換はAPI契約で行う。

## 7. Source Priority Resolution の規則［提案］

### 7.1 確認済みの該当

**確認済みの該当（confirmed match）**は、次のすべてを満たす `zone_hits` の要素である。

- 判定用の形状（`geometry_basis = original`。派生形状はMVPでは使わない）の内部に地点がある（境界上ではない）
- 区分が承認済み（`unclassified` ではない）
- 浸水深区分が、ポリシーの分類体系で解釈できる

境界上（`boundary_contacts`）とunknown（`unknown_hits`）は、確認済みの該当ではない。

### 7.2 ソースごとの状態

上位の区分に確認済みの該当がない理由を区別するため、`source_id` ごと・区分ごとに次の状態を付ける。

| 状態 | 意味 |
|---|---|
| `confirmed_match` | 確認済みの該当がある |
| `unknown` | 確認済みの該当はなく、unknownがある |
| `boundary_only` | 確認済みの該当もunknownもなく、境界上の接触がある |
| `no_polygon_extent_unknown` | 地点が対象地域の内部で、そのソースに該当もunknownも境界の接触もない。**A31aは評価済み範囲を持たないため、非該当とは確定しない**（「評価範囲不明」） |
| `not_registered` | その区分のソースが、公開世代に1つも登録されていない（「データ未登録」） |
| `not_evaluated` | ソースは登録されているが、その地点を評価できない（地域外・判定不能・読込失敗）（「判定不能」） |
| `confirmed_no_match` | **予約**。評価済み範囲を持つデータで、範囲内かつ該当なしと確定した場合。**A31aでは使わない**（MVPでは発生しない） |

- 区分の状態は、その区分に属する全ソースの状態から決める。優先度の高い順に `confirmed_match` ＞ `unknown` ＞ `boundary_only` ＞ `not_evaluated` ＞ `no_polygon_extent_unknown` ＞ `not_registered`。
- 「非該当」は、評価済み範囲の内部で確定した場合（`confirmed_no_match`）だけに使う。MVPのA31aでは発生しない（SP-4）。

### 7.3 選択の手順

1. 確認済みの該当（第7.1節）を抽出する。
2. 確認済みの該当がある区分のうち、priorityが最も小さい（優先順位が最も高い）区分を**採用区分**とする。
3. 採用区分の中に確認済みの該当が複数ある場合は、同順位の集約規則（第8章）を適用する。
4. 代表結果の採用区分・採用ソース・priority・選択理由（第7.5節）を記録する。
5. 採用区分以外の確認済みの該当、全unknown、全境界接触を、来歴付きで保持する（削除しない）。
6. **代表結果の確定性**を記録する。採用区分より上位、または採用区分と同じ区分に、`unknown`・`boundary_only`・`not_evaluated` のソースがある場合、代表結果は `provisional`（暫定）とする。それらが判明すれば代表結果が変わりうるためである。それ以外は `final`。

- unknownは、手順1〜3の選択の候補にならない。unknownを非該当として扱って下位へ進む規則ではない。下位へ進むのは「上位に**確認済みの該当がない**」からであり、上位のunknownは手順6と第7.6節で必ず残す。
- 確認済みの該当が1件もない場合、代表結果は `null` とし、その理由を `selection_reason` で示す。

### 7.4 未分類のソース

`unclassified` のソースは選択に参加させない。そのソースの該当・unknownは、`unclassified` として全件を応答の詳細に残し、代表結果を `provisional` とする（どの順位に入るか分からないため）。Readinessで阻害する提案（第3.3節）が採用されれば、公開世代には現れない。

### 7.5 選択理由（`selection_reason`）の列挙値［提案］

| 値 | 条件 |
|---|---|
| `highest_priority_confirmed_match` | priority 1の区分に確認済みの該当があり、それを採用した |
| `no_higher_priority_confirmed_match` | 採用区分より上位の全区分に確認済みの該当がなく、それらにunknown・境界接触・判定不能もない |
| `higher_priority_uncertain` | 採用区分より上位の区分に確認済みの該当はないが、unknown・境界接触・判定不能のいずれかがある（代表は `provisional`） |
| `no_confirmed_match` | 全区分に確認済みの該当がない（代表結果なし） |
| `aggregation_undetermined` | 採用区分の中で同順位の集約ができない（第8.4節。代表の浸水深なし） |

- `selection_reason` と、上位区分の状態の詳細（第7.2節の状態ごと）は、どちらも応答に含める。自由記述の説明は列挙値から生成する（API契約）。

### 7.6 ケース別の期待結果

| No | 状況 | 代表結果 | 選択理由・確定性 | 保持する情報 |
|---|---|---|---|---|
| 1 | 優先1に確認済みの該当、優先2にも確認済みの該当 | 優先1 | `highest_priority_confirmed_match`・`final` | 優先2の該当を来歴付きで保持。優先2の方が深い場合は、その事実を示す（第8.5節） |
| 2 | 優先1に確認済みの該当なし（`no_polygon_extent_unknown`）、優先2に確認済みの該当 | 優先2 | `no_higher_priority_confirmed_match`・`final` | 優先1の状態は「評価範囲不明」。**優先1のデータが存在しない・浸水しないとは断定しない** |
| 3 | 優先1がunknown、優先2に確認済みの該当 | 優先2 | `higher_priority_uncertain`・`provisional` | 優先1のunknownを保持。`assessment_status` は `partial_unknown`（API契約 第5.2節。判定済みだけで完結させない） |
| 4 | 全ソースで確認済みの該当なし、unknownなし（対象地域の内部） | なし | `no_confirmed_match` | 「安全」「浸水なし」と返さない。状態は「評価範囲不明」 |
| 5 | 同じFeatureに有効な構成P（地点を含む）と判定保留の構成Q（L1範囲に地点を含む） | Pの区分・ソース（他の該当との比較の結果） | Qと同じ区分なら `provisional` | `has_area_match` と `has_unknown` の両方を保持。Pの該当とQのunknownの両方を返す |
| 6 | 異なる区分の複数unknownが同じ地点に存在 | 確認済みの該当があればその規則による。なければなし | unknownの順位にかかわらず | **低順位のunknownも削除しない**。全unknownを区分・ソースごとに返す |
| 7 | 優先1に境界接触だけ、優先2に確認済みの該当 | 優先2 | `higher_priority_uncertain`・`provisional` | 境界接触を保持 |
| 8 | 優先1の中で、比較できない2つの区分の該当 | なし（浸水深）。採用区分は優先1 | `aggregation_undetermined` | 両方の該当を保持 |
| 9 | 地点が対象地域の外・外縁上 | 判定しない | — | API契約の地域外・外縁の扱い（`no_data`・`region_boundary`） |

## 8. 同順位の集約（Risk Aggregation）［提案］

### 8.1 初期の規則

**比較可能な浸水深区分のうち、最も深い区分を代表とする**（`deepest_comparable_depth_class`）。原典の応用スキーマ文書には、「一つのデータ内に複数のポリゴンがオーバーラップする場合は、浸水ランクコードの値の大きい方を優先する」という規定がある［実測: Phase 2-A.1］。この規則は、その規定と同じ向きである。ただし、異なるデータ（ファイル）間の重複については原典に定めがない。そのため本規則は、原典の規定の延長ではなく、本書の提案である。

### 8.2 浸水深区分の正規化

原典のランク番号（`A31a_205` の1〜6）を**数値として大小比較しない**。区分を、次の正規化した区間に変換して比較する。

| 項目 | 内容 |
|---|---|
| `classification_scheme` | 区分の体系のID・版（例: 国土数値情報の浸水ランクコード `water_depth_code` の版） |
| `class_code` | 原典のコード（文字列・整数の型の違いは正規化。原典の値は `source_properties` に保持） |
| `lower_m`・`upper_m` | 区間の下限・上限（メートル）。上限なしは `null` |
| `lower_inclusive`・`upper_inclusive` | 端点の包含。**A31aでは原典で未規定**［実測: 製品仕様書］であり、`unspecified` とする |
| `label` | 原典の定義の文言（例: 「0.5～3.0m未満」） |

A31aの浸水ランクコード［実測: 製品仕様書・コードリスト。Phase 2-A.1］:

| コード | 原典の定義 | `lower_m` | `upper_m` |
|---|---|---:|---:|
| 1 | 0～0.5m未満 | 0 | 0.5 |
| 2 | 0.5～3.0m未満 | 0.5 | 3.0 |
| 3 | 3.0～5.0m未満 | 3.0 | 5.0 |
| 4 | 5.0～10.0m未満 | 5.0 | 10.0 |
| 5 | 10.0～20.0m未満 | 10.0 | 20.0 |
| 6 | 20.0m以上 | 20.0 | `null` |

- 原典の定義の文言に「未満」とあるが、製品仕様書は境界値の「以上」「未満」が規定されていないと明記している。そのため、端点の包含は `unspecified` として保持し、推測で確定しない。
- コード5の「内容」欄は「津波基準水位を表現する」となっており、洪水の説明として不自然である［実測］。区間の値は定義の欄から取り、内容の欄の解釈はOWNERの確認事項とする（SP-U1）。

### 8.3 比較の規則

2つの区分AとBについて:

| 関係 | 条件 | 扱い |
|---|---|---|
| 同じ | 同じ体系・同じ版・同じコード | 同順位（タイ）。浸水深は同じ |
| AがBより深い | 同じ体系・同じ版で、`A.lower_m >= B.upper_m`（`B.upper_m` が `null` でない） | Aを代表とする |
| 端点だけを共有 | 上の条件で `A.lower_m = B.upper_m`（包含が `unspecified`） | 区間の重なりは高々1点であり、**深い側をAとしてよい**（重なる1点を実際の値として返さない） |
| 包含・部分的な重なり | 一方の区間が他方を含む、または長さを持って重なる | **比較不能**（`aggregation_undetermined`） |
| 異なる体系・異なる版 | 体系の対応が検証・承認されていない | **比較不能** |

- 区間の上限が大きいという理由だけで、常に危険度を厳密に比較できるとは仮定しない。比較できるのは、同じ体系の互いに素な（端点だけを共有する）区間の順序だけである。
- 比較不能の場合は任意の値を選ばない。代表の浸水深を `null` とし、`aggregation_undetermined` と、比較できなかった区分の組を記録する。

### 8.4 同じ深さの複数ソース（タイ）

最も深い区分が複数のソース・区域で同じ場合は、浸水深は一意に決まる。代表結果には**その深さに寄与した全ソース・全区域**を列挙し、1つの `source_id` を任意に選ばない。表示用に1つが必要な場合は、`tie_order`（`source_id` → `product_id` → `zone_ref` の昇順）で決定的に並べた先頭を `primary` とし、`primary` が任意の順序で選ばれたことを応答で示す（`tie_break: deterministic_order`）。

### 8.5 代表より深い他の該当（安全上の情報）

代表結果は優先順位で選ぶため、**代表より深い浸水想定が下位の区分にある**場合がある（例: 優先1の地方自治体がランク1、優先2の国がランク4）。

- 下位の該当は必ず保持し、応答に含める（SP-1・SP-2）。
- 応答に `deeper_match_outside_representative`（真偽値。比較不能を含む場合は `null`）を含めることを提案する。「代表より深い区分の確認済みの該当が、他の区分にある」ことを示す。
- **拡張案（未決定: SP-U2）**: 代表結果とは別に、全区分の比較可能な確認済みの該当のうち最も深い区分を `max_depth_among_matches` として返す。異なる提供主体の想定（河川・降雨・計算条件）は異なる。そのため、この値は「全ソースの中の最大の浸水想定区分」の事実であり、総合的な危険度の評価ではない。ユーザーへの見せ方・安全上の扱いはOWNER判断とする。

### 8.6 比較仕様の確定に必要な確認項目

| No | 確認項目 | 理由 |
|---|---|---|
| CQ-1 | 各原典ZIPが参照する浸水ランクコードのコードリストの版と、製品仕様書の版 | 同じ体系・同じ版であることが比較の前提 |
| CQ-2 | `A31a_205` の型（東京都は文字列、関東地方整備局は整数［実測］）と、値の範囲（1〜6） | 型の正規化の規則 |
| CQ-3 | 東京都と関東地方整備局が、同じ区分の閾値（0.5・3.0・5.0・10.0・20.0m）で作成しているか | 同じコードが同じ区間を表すことの確認 |
| CQ-4 | 端点の包含が未規定であることの、応答での表現 | 推測で確定しない |
| CQ-5 | コード5の「内容」欄の記載（津波基準水位）の扱い | 原典の誤記か、別の意味か |
| CQ-6 | 同じシナリオ（想定最大規模）であることの確認（ZIPのフォルダ `20_想定最大規模`） | 異なるシナリオの区分を比較しない |
| CQ-7 | 浸水継続時間・家屋倒壊等氾濫想定区域など、別の体系のデータを将来扱う場合の対応 | 体系が異なれば比較不能 |
| CQ-8 | 同一ファイル内の重複は原典で解消済み（値の大きい方を優先）とされていることの、実データでの確認 | 同一成果品内の重なりは標本調査で見つかっていない［実測］ |

## 9. レイヤー表示（Layer Presentation Policy）との接続［提案。MVPでは実装しない］

将来の地図UIでは、重複地点で優先順位の高い提供主体の区域を代表レイヤーとして描画する。これは**表示上のポリシー**であり、本書の代表結果の選択とは別に版管理するか共通化するかは未決定（SP-U13）。

Layer Presentation Policyが持つべき項目:

| 項目 | 内容 |
|---|---|
| 提供主体の区分 | 本書の `source_category` と同じ値・同じ割当記録 |
| レイヤーの優先順位 | 描画順（上に重ねる順） |
| 代表表示に使用したソース | 地点・区域ごとに、代表として描画したソースの識別 |
| 下位ソースの重複 | 代表の下に別の区分の区域が重なっていることの表示（凡例・ハッチング等） |
| unknownの可視化 | unknownの範囲（L1の外接矩形）を、区域の「なし」と区別して表示する必要性。外接矩形をそのまま描くと実際の区域より広く見えるため、表現方法は別途決める |

**APIの代表結果と地図の描画が矛盾しないための条件**:

1. 同じ公開世代のSource Priority Policy（または、それと内容ハッシュで対応付けたLayer Presentation Policy）・区分の割当記録を使う。
2. 地図の描画順は、代表結果の選択の順序（priority）と一致する。異なる順序にする場合は、地図上の代表とAPIの代表が異なることを明示する。
3. 同順位の区域の描画は、第8章の集約（最も深い区分）と同じ結果になる描画順とする（深い区分を上に描く）。比較不能の重なりは、どちらかを隠さずに表示する。
4. 下位の区分の区域・unknownは、描画で隠れても、存在することが分かる表示を持つ。
5. タイルの生成・キャッシュは公開世代ごとに分け、ポリシーの切替えで旧世代のタイルを使わない。

## 10. 責務分界と既存契約との整合

### 10.1 責務

| 担当 | 責務 | 禁止 |
|---|---|---|
| Normalize | 原典の完全保持・幾何妥当性の評価 | 提供主体の優先順位によるデータの削除・選別 |
| Integration | 全原典の来歴、有効な検索形状、判定保留情報の保持 | 優先順位による原典の切捨て。代表ランクの格納（Integration契約 第5章 原則4） |
| Point Assessment | 地点と各有効形状・unknown範囲・地域との関係の判定 | 優先順位の参照 |
| Source Priority Resolver | 承認済みのポリシーによる代表ソースの選択 | 該当・unknownの削除。未承認のポリシーの使用 |
| Risk Aggregator | 比較可能な浸水深区分の集約、複数ソース・unknownの情報の維持 | ランク番号の数値比較。比較不能時の任意の選択 |
| Flood API | 代表結果・選択理由・採用元・不確実性の表示 | unknownを非該当・安全に変換すること。ポリシーの上書き |
| Data Management（将来） | ポリシー・区分の割当の登録・変更・承認の依頼・有効化の依頼・履歴の管理 | 承認の代行。原典・統合成果物の変更。即時の無承認有効化 |
| Data Publish | ポリシーを含む公開世代の原子的な切替え（既存契約） | — |

- 優先順位・区分の変更では、Normalize・Integrationの実データを作り直さない（SP-5）。
- ソースの追加・削除・原典の更新は、Normalize・Integrationの再処理を伴う別の問題として扱う（Integration契約 第11.2節）。

### 10.2 既存契約との論点（変更せず記録する）

| No | 既存契約 | 論点 |
|---|---|---|
| SP-C1 | Data Publish・Dataset Registry・Integration契約 第9.3節 | 公開世代にSource Priority Policy・区分の割当記録・unknownポリシーを含める項目がない。追加の契約が必要 |
| SP-C2 | データソース定義 §2（3種類の情報の正本） | 区分の割当（確認済みの事実＋承認）は、Source Definition（予定）にも公開Registryにも入れられない。指示書の「Source Registry」に相当する記録を新設する必要がある |
| SP-C3 | Integration契約 第7.3節（Publication Readiness） | 阻害理由に、Source Priority Policyの未承認・`unclassified` のソースの存在を追加する必要がある（現行の列挙にない） |
| SP-C4 | 共通API契約 §6、Dataset Registry §6 | 「優先順位・集約は未決定。先着順・最大値・最新という理由だけの選択を独断で導入しない」。本書の優先順位と最大区分の規則は、**OWNERの承認があるまで提案**であり、承認前に導入したとは扱わない |
| SP-C5 | 本番実行認可設計 | ポリシーの承認記録のSchemaがない（Integration契約 OI-27と同じ論点） |
| SP-C6 | Integration契約 第10章「有効な区域で該当しても、判定保留の区域のランクが分からないことを示す」 | 判定保留のFeatureの原典のランクは属性として分かるが、その区域に地点が含まれるかが分からない。応答でランクを「可能性」として示すか、示さないかは未決定（API契約 FA-U5） |

## 11. テストケース（設計のみ。いずれも実行していない）

| ID | 入力・条件 | 期待 |
|---|---|---|
| SP-01 | 第7.6節のケース1〜9（合成データ） | それぞれの期待どおり |
| SP-02 | ランク番号の数値比較を行う実装の模擬（コード `"10"` 等の文字列比較の誤りを含む） | 正規化した区間の比較と一致しない場合に検出される |
| SP-03 | 異なる体系の区分が同じ順位で重なる | `aggregation_undetermined`。任意の値を選ばない |
| SP-04 | 同じ深さの3ソースのタイ | 代表の浸水深は一意。寄与した全ソースを列挙。`primary` は決定的な順序の先頭 |
| SP-05 | 同じ公開世代・同じ地点で100回判定 | 結果・並び順が同一 |
| SP-06 | 優先1がランク1、優先2がランク4 | 代表は優先1。優先2の該当を保持し、`deeper_match_outside_representative = true` |
| SP-07 | `unknown_handling` を `false` にした版 | Policy Validate（PV-2）で拒否 |
| SP-08 | `unclassified` のソースを含む適用対象 | PV-4で拒否 |
| SP-09 | 未承認・期限切れ・取消し済みの版を含む公開世代 | Readiness・Publish直前の再確認で拒否（SP-C3の採用後） |
| SP-10 | リクエストでポリシーを指定 | 拒否（入力エラー）。本番の判定は変わらない |
| SP-11 | 優先順位だけを変更した新版の有効化 | 統合成果物は再生成されず（同じファイルのSHA-256）、新しい公開世代で原子的に切り替わる。切替え中の応答に新旧が混在しない |
| SP-12 | 区分の割当記録の内容を同じ参照先で差し替え | 内容ハッシュの不一致で使わない |
| SP-13 | 優先1の区分に属するソースが0件の公開世代 | 優先1の状態は `not_registered`。優先1を「非該当」とは返さない |

## 12. 未決定事項とOWNER判断事項

| No | 事項 | 本書の提案 |
|---|---|---|
| SP-U1 | 同順位内での浸水深比較の正式な規則 | 同じ体系の正規化した区間で最も深い区分（第8章）。CQ-1〜CQ-8の確認後に確定 |
| SP-U2 | 代表結果と別に、全ソース中の最大浸水深区分を併記するか | `deeper_match_outside_representative` は返す。`max_depth_among_matches` の併記と見せ方は判断待ち |
| SP-U3 | `other` に含められるデータの資格 | 初期は該当なし。資格（公的機関の範囲、作成方法、利用条件）を決めるまで割り当てない |
| SP-U4 | 提供主体の区分をどの原典情報から確定するか | `A31a_203`・`A31a_204`・メタデータ・掲載情報の一致（第3.3節）。`source_id` の命名規則も含む |
| SP-U5 | 区分を横断した比較可能性 | 同じ体系なら数値上は比較できるが、想定の条件が異なる。代表の選択には使わず、事実の提示（第8.5節）に限る |
| SP-U6 | 未評価・未登録・unknown・非該当の区別 | 第7.2節の状態。非該当（`confirmed_no_match`）はA31aでは使わない |
| SP-U7 | 優先順位を変更した際の世代管理とキャッシュの無効化 | 公開世代に固定し、キャッシュのキーに世代を含める（第5.3節） |
| SP-U8 | Data Managementによる承認・有効化の権限 | 作成と承認の分離。承認はOWNER。有効化はPublishの認可に従う |
| SP-U9 | 未分類のソースの扱い | 選択に参加させず、Readinessで阻害（SP-C3） |
| SP-U10 | 境界接触を確認済みの該当にしないこと | 提案どおり（`boundary_only`・`provisional`） |
| SP-U11 | 公開世代にポリシーを含める契約（SP-C1） | Publish・Registryの追加契約として別途設計 |
| SP-U12 | 区分の割当記録の保存先（SP-C2） | Source Definition・Registryとは別の記録として新設 |
| SP-U13 | Source Priority PolicyとLayer Presentation Policyを共通化するか | 別の版管理とし、区分の割当記録と優先順位を内容ハッシュで参照する案を候補とする |

本書の採用は、製品実装・ポリシーの承認・有効化・実データの処理・公開の承認ではない。
