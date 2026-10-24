# Flood API MVP Contract v0.1（案）

- Task: Phase 2-B.9 Flood API MVP Scope（作成）、Phase 2-B.10 Flood Source Selection Contract 設計改訂（改訂）
- 状態: **契約案（OWNERレビュー待ち。正式採用されていない）**。本書は製品実装・正式なレスポンスSchema・実データの公開の承認ではない
- 作成: 2026-10-24（Claude）
- 改訂: 2026-10-25 Phase 2-B.10 — 提供主体の優先順位による自動代表選択を廃止し、利用者によるデータソースの選択（`overview`・`single_source`）へ全面改訂した。旧版の `representative`・`selection_reason`・`priority`・`finality`・`category_states` は廃止した（第12章）。基準コミット `fdf4f2df7d7a29f18519183ff8d2b931e6f4adc5`
- 前提: [共通API契約 v0.1](common-contract-v0.1.md)、[Flood Source Selection Contract v0.1（案）](../architecture/flood-source-selection-contract-v0.1.md)、[Flood Integration Contract v0.1（案）](../architecture/flood-integration-contract-v0.1.md)
- 履歴: [Flood Source Priority & Risk Aggregation Contract v0.1（案。Phase 2-B.9、置き換え済みの設計案）](../architecture/flood-source-priority-contract-v0.1.md)
- 検討の記録: [Phase 2-B.9 レビュー](../../reviews/phase2/phase2b9-flood-mvp-scope-and-priority.md)、[Phase 2-B.10 レビュー](../../reviews/phase2/phase2b10-source-selection-redesign.md)

区分: **［確定］** 既存の承認済み契約に由来、**［実測］** 調査で報告された値、**［提案］** 本書の設計提案（未承認）、**［未決定］** OWNER判断が必要。**APIパス・フィールド名・型・列挙値・JSON例はすべてPROVISIONAL（暫定）であり、正式Schemaではない**（共通API契約 §1と同じ扱い）。

## 1. 目的

指定した1地点について、A31a（想定最大規模）の浸水想定を公表している各データソースの判定結果を返す。システムは代表のソースを選ばない。利用者がソースを選んだ場合はその結果を主表示とし、他のソースの存在・判定・unknownも同じ応答で返す。

設計原則: **内部は厳密に。外部はシンプルに。不確実性は隠さない。**

## 2. MVPの範囲

### 2.1 含めるもの［提案］

| 機能 | 本書の箇所 |
|---|---|
| 緯度・経度を指定した1地点のFlood判定 | 第3章 |
| 地点に関係するデータソースの列挙（Source Discovery） | 第5.3節 |
| 有効なA31a形状によるソースごとの浸水区域の該当判定 | 第5.4節 |
| ソースごとの浸水深区分（ソース内の集約） | 第5.5節 |
| 未選択（`overview`）と、利用者が指定した1ソースの主表示（`single_source`） | 第5.2節 |
| 公表元・データの名称・河川・シナリオ・版・出典の表示 | 第5.4節 |
| 全該当・unknown・境界接触の来歴参照 | 第5.4節 |
| 他ソースのより深い想定・unknownの通知 | 第5.6節 |
| 公開世代と各設定のID・版・内容ハッシュの参照 | 第7章 |

### 2.2 含めないもの

- システムによる代表ソースの自動選択・提供主体の優先順位（廃止。Selection契約 第10章）
- 異なるソース間の浸水深の統合・「総合的な代表リスク」の提示
- 複数ソースの選択（`multiple_sources`）・比較モード（`compare`）（将来候補）
- 無効ポリゴンの自動修復・派生形状の製品利用（Normalize契約 第10章。BLOCKED）
- unknownのL2（精密な範囲）への縮小（Integration契約 第4.4節。禁止）。**unknownの範囲はL1だけ**
- 避難経路の探索、複数地点・面の一括判定、地図タイルの生成、管理画面の実装
- 実データの公開（Flood用の認可プロファイル・利用条件が未成立。Integration契約 第9.5節）

## 3. 入力［提案］

**エンドポイント（仮案）**: `GET /api/flood?lat=<緯度>&lon=<経度>[&source_id=<公開用ID>]`

URLは仮案であり、既存のルーティング契約を変更しない。APIパス・メソッド・版の指定方式は共通API契約 §10と同じく未決定である。

| パラメータ | 必須 | 内容 |
|---|---|---|
| `lat` | ○ | 緯度（十進度） |
| `lon` | ○ | 経度（十進度） |
| `source_id` | 任意 | 主表示にするソースの公開用ID（Selection契約 第6.1節）。省略時は `overview` |

- **座標**: 共通API契約 §2に従う。欠落・`null`・非数値・非有限値・範囲外（lat −90〜90、lon −180〜180）を有効な地点として処理しない。latとlonを暗黙に交換しない。重複したパラメータは拒否する。名前は共通API契約の `lat`・`lon` とする（指示書の例 `latitude`・`longitude` との違いはFA-C1）。
- **座標系・精度**: 原典はJGD2011（EPSG:6668）。API入力との扱い・桁数・nano-degreeの格子に乗らない地点の扱いは未決定（Normalize契約 ON-11、Integration契約 OI-18）。**未決定のまま地点を丸めない。**
- **`source_id`**: 現在の公開世代のSource Catalogにある値だけを受け付ける。形式不正・目録にない値・旧世代の値・複数指定は入力エラーとする（第6章）。別のソースへ黙って置き換えない。未選択として黙って処理しない。
- **その他のパラメータは受け付けない。** 未知のパラメータは入力エラーとする。区分（`source_category`）・提供主体名・優先順位・表示順・ポリシーを指定する入力は、自動選択や判定の変更の経路になるため設けない。

### 3.1 エンドポイントの構成の検討

指示書の仮案は、Discovery（`GET /api/flood/sources?lat&lon`）と地点判定（`GET /api/flood?lat&lon[&source_id]`）を別のエンドポイントにする。

| 観点 | 別エンドポイント | 1つのエンドポイント（本書の提案） |
|---|---|---|
| 計算コスト | Discoveryもソースごとの判定状態を返すため、Point Assessmentを全ソースで行う必要がある。UIが両方を呼ぶと、同じ地点を2回判定する | 1回の判定で、一覧と主表示の両方を返す |
| 応答サイズ | 分けても、地点判定の応答に他ソースの一覧が必要（安全上の情報。Selection契約 第7章） | 初期のソースは2つ程度で、該当の区域も少ない（最大6成果品の重なりの観測［実測: Phase 2-A.4の標本］）。分ける利点が小さい |
| キャッシュ効率 | 地点を含むURLのキャッシュは、位置情報の保存になる（共通API契約 §5）。位置を含まない目録だけなら公開世代ごとにキャッシュできる | 選択は判定を変えないため、選択の違いは同じ判定結果の表示の違いにすぎない。サーバ側で地点をキーにしたキャッシュは持たない（位置情報の保存を避ける） |
| 一貫性 | 2回の呼出しの間に公開世代が切り替わると、一覧と主表示の世代が食い違いうる | 1つの応答が1つの公開世代に対応する |

**最小構成の提案**: MVPは `GET /api/flood`（1つ）だけとし、Discoveryの情報（`sources[]`）を地点判定の応答に含める。地点を含まない目録（公開世代のSource Catalogの一覧）が必要になった場合は、位置を含まない別エンドポイント（例: `GET /api/flood/catalog`）を将来追加する。目録は公開世代ごとにキャッシュできる。指示書の `GET /api/flood/sources?lat&lon` は、`GET /api/flood` と同じ判定を重複して行うため、MVPでは設けない［未決定: FA-U10］。

## 4. 処理の段階［提案］

| 段階 | 内容 | 正本 |
|---|---|---|
| Source Discovery | 公開世代のSource Catalogから、地点がサービス対象地域に入るソースを列挙する | Selection契約 第4章 |
| Point Assessment | ソースごとに独立して、判定用の構成Polygon（`search_target`）・unknownの範囲（L1）・境界接触を判定し、ソース内の集約を行う | Selection契約 第5章 |
| Source Selection | `source_id` の指定を検証し、主表示のソースを決める（指定がなければ `overview`） | Selection契約 第6章 |
| Response | ソースごとの結果、選択、安全上の情報、来歴・設定の版をまとめる | 本書 第5章 |

- APIは公開済みのRegistry・公開実体だけを読む［確定: 共通API契約 §5］。
- 1つの応答では1つの公開世代だけを使う（Selection契約 第8.2節）。
- 選択は判定を変えない。`source_id` の有無・値にかかわらず、`sources[]` の各要素の判定の項目は同じである。

## 5. 出力［提案］

### 5.1 全体の構成

共通API契約 §3の6フィールド（`hazard`・`location`・`status`・`result`・`dataset`・`error`）と `evaluated_at` に、`settings` を加える。

```json
{
  "hazard": "flood",
  "location": {"lat": 35.68, "lon": 139.76},
  "status": "success",
  "result": {
    "selection": {"mode": "single_source", "source_id": "example-source-b", "selected_by": "user"},
    "assessment": "affected",
    "overall_status": "partial_unknown",
    "region_state": "inside",
    "candidate_scope": "registered_sources_in_service_region",
    "candidate_completeness": "not_guaranteed",
    "not_included_notice": ["pluvial_flooding", "storm_surge", "planned_scale_scenario", "adjacent_prefectures"],
    "selected_result_is_exclusive": false,
    "safety": {
      "other_sources_count": 1,
      "deeper_in_other_sources": false,
      "has_unknown": true,
      "has_unknown_in_other_sources": true
    },
    "sources": [
      {"source_id": "example-source-a", "is_selected": false,
       "source_category": "local_government", "source_organization": "東京都",
       "title": "<データの正式名称>", "scenario": "maximum", "data_version": "2025",
       "service_region_relation": "inside", "assessed_extent_relation": "unknown",
       "has_confirmed_match": false, "has_unknown": true,
       "assessment_status": "unknown_only", "depth": null,
       "uncertainty_reasons": ["unknown_invalid_geometry", "assessed_extent_unknown"],
       "matches": [], "boundary_contacts": [],
       "unknowns": [{"zone_ref": "z-a1", "river_name_in_source": "<代表河川名>", "reason": "invalid_geometry", "unknown_level": "L1"}]},
      {"source_id": "example-source-b", "is_selected": true,
       "source_category": "national_government", "source_organization": "国土交通省 関東地方整備局",
       "title": "<データの正式名称>", "scenario": "maximum", "data_version": "2025",
       "service_region_relation": "inside", "assessed_extent_relation": "unknown",
       "has_confirmed_match": true, "has_unknown": false,
       "assessment_status": "determined_match",
       "depth": {"kind": "class", "scheme": "ksj-a31a-water-depth-rank", "class_code": "3",
                 "label": "3.0～5.0m未満", "lower_m": 3.0, "upper_m": 5.0, "bounds_inclusion": "unspecified",
                 "contributing_zones": ["z-b1"]},
       "uncertainty_reasons": ["assessed_extent_unknown"],
       "matches": [{"zone_ref": "z-b1", "river_name_in_source": "荒川",
                    "depth": {"kind": "class", "class_code": "3", "label": "3.0～5.0m未満", "lower_m": 3.0, "upper_m": 5.0, "bounds_inclusion": "unspecified"}}],
       "boundary_contacts": [], "unknowns": []}
    ]
  },
  "dataset": {"id": "example-flood", "publication_version": "example-v1",
              "published_at": "2026-10-01T00:00:00Z",
              "attribution": [{"text": "<利用条件が求める出典・加工の表示>"}]},
  "settings": {
    "source_catalog": {"id": "<…>", "version": "<…>", "content_sha256": "<…>"},
    "source_category_assignment": {"id": "<…>", "version": "<…>", "content_sha256": "<…>"},
    "source_display": {"id": "<…>", "version": "<…>", "content_sha256": "<…>"},
    "unknown_region": {"id": "<…>", "version": "<…>", "content_sha256": "<…>"}
  },
  "error": null,
  "evaluated_at": "2026-10-25T00:00:00Z"
}
```

値はすべて架空である（ケースBの形。第8.2節）。実在の地点の浸水想定・データの識別子・承認済みの設定を示さない。

**指示書の概念例との違い**: 概念例の `selected_result` と `other_sources` は、本書では1つの `sources[]` にまとめ、各要素の `is_selected` と `result.selection.source_id` で主表示を示す。`overview` と `single_source` で同じ形を使えるようにし、選択によって他ソースの情報の形が変わらないようにするためである。

### 5.2 選択（`result.selection`）

| 項目 | 内容 |
|---|---|
| `mode` | `overview`（未選択）または `single_source` |
| `source_id` | `single_source` の場合は指定された `source_id`。`overview` の場合は `null` |
| `selected_by` | `single_source` の場合は `user`。`overview` の場合は `null`。**`system` の値はない**（システムはソースを選ばない） |

`overview` では、どのソースも `is_selected = true` にならない。特定のソースを先頭に置く・強調する等の暗黙の代表化をしない（並び順は表示設定による。第5.3節）。

### 5.3 ソースの一覧（Discovery。`result.sources[]`）

| 項目 | 内容 |
|---|---|
| `candidate_scope` | 列挙の範囲。初期値 `registered_sources_in_service_region` |
| `candidate_completeness` | 初期値 `not_guaranteed`（登録されていない公表データがありうる） |
| `not_included_notice` | 列挙の対象外のデータの種類（列挙値）。公開用の文言は［未決定］ |
| `sources[]` | 目録のうち、地点がサービス対象地域の内部・外縁上にある全ソース。並び順は公開世代のSource Display Settings（Selection契約 第8.1節）による。**並び順は信頼性の順位ではない** |

### 5.4 ソースごとの結果（`sources[]` の要素）

| 項目 | 内容 |
|---|---|
| `source_id`・`is_selected` | 公開用ID、主表示かどうか |
| `source_category`・`source_organization` | 提供主体の区分（分類・表示だけ。順位なし）と公表元の名称 |
| `title`・`scenario`・`data_version` | データの正式名称、シナリオ（`maximum`）、公表データの版・時点 |
| `service_region_relation` | `inside`・`boundary`（Selection契約 第4.1節） |
| `assessed_extent_relation` | A31aでは `unknown` |
| `has_confirmed_match`・`has_unknown` | 確認済みの該当、unknownの有無 |
| `assessment_status` | Selection契約 第5.2節の値: `determined_match`・`partial_unknown`・`aggregation_undetermined`・`unknown_only`・`no_match_extent_unknown`・`not_evaluated` |
| `depth` | ソース内の集約の結果（第5.5節）。該当なし・集約不能は `null` |
| `uncertainty_reasons[]` | 列挙値（重複なし・昇順）: `assessed_extent_unknown`・`unknown_invalid_geometry`・`zone_boundary_contact`・`aggregation_undetermined`・`region_boundary` |
| `matches[]` | 確認済みの該当の全件: `zone_ref`・`river_name_in_source`（成果品の代表河川名。個別の区域の原因河川ではない［実測］）・`depth` |
| `unknowns[]` | unknownの範囲（L1）に地点が入る全件: `zone_ref`・`river_name_in_source`・`reason`（`invalid_geometry`・`feature_invalid_component`）・`unknown_level`（`L1`） |
| `boundary_contacts[]` | 境界上にある全件 |

- `matches`・`unknowns`・`boundary_contacts` の並び順は `zone_ref` の昇順で決定的とする。
- 同じFeatureの有効部分の該当とunknownは、`matches` と `unknowns` の両方に現れうる。どちらも削除しない。
- **件数の上限で黙って切り捨てない。** 上限を設ける場合は `truncated` と全件数で示す（上限値は［未決定: FA-U7］）。
- `zone_ref` は公開用の不透明な識別子とする。内部の `record_key` は原典のZIPメンバー名（ファイル名）を含むため、公開しない（共通API契約 §5）。
- unknownの区域の原典のランクを「該当した場合の可能性」として返すかは未決定（FA-U5）。MVPの案では返さない。

### 5.5 浸水深区分（`depth`）

共通API契約 §4.2の候補（`kind`・`category`・`lower_m`・`upper_m`）に沿う。

| 項目 | 内容 |
|---|---|
| `kind` | `class`（階級）。数値の浸水深ではない |
| `scheme` | 区分の体系のID |
| `class_code`・`label` | 原典のコード（文字列に正規化）・定義の文言 |
| `lower_m`・`upper_m` | 区間の下限・上限。上限なし（コード6）は `null` |
| `bounds_inclusion` | `unspecified`（A31aでは端点の包含が原典で未規定） |
| `contributing_zones` | ソースの `depth` に寄与した全区域の `zone_ref`（同じ深さの区域はすべて） |

- ソースの `depth` は、そのソースの中の集約（Selection契約 第5.3節。同じ体系の正規化した区間で最も深い区分）の結果である。異なるソース間では集約しない。
- 範囲・階級から架空の代表値（中央値等）を作らない［確定: 共通API契約 §4.2］。
- 指示書の概念例の `depth_range_m: {min, max}` は、共通API契約の候補に合わせて `lower_m`・`upper_m` とした。

### 5.6 安全上の情報（`result.safety`）

| 項目 | モード | 内容 |
|---|---|---|
| `other_sources_count` | 両方 | 主表示以外のソースの数（`overview` では全ソースの数） |
| `has_unknown` | 両方 | いずれかのソースにunknownがある |
| `has_unknown_in_other_sources` | `single_source` | 選択していないソースにunknownがある |
| `deeper_in_other_sources` | `single_source` | 選択していないソースに、選択中のソースの `depth` より深い区分の確認済みの該当がある（`true`／`false`）。比較不能・区分の体系の同一性が未承認・選択中の `depth` が `null` の場合は `null`（Selection契約 第7章） |
| `depth_classes_present` | `overview` | 全ソースの確認済みの該当の区分の一覧（重複なし、比較可能なら深さの順）。**ソース間の統合ではなく事実の列挙** |

`result.selected_result_is_exclusive` は常に `false` とする。選択中の値が地点の唯一の正しい浸水深ではないことを、機械的に示す。

### 5.7 応答全体の状態（`result.overall_status`）

全ソースの `assessment_status` から求める**状態の要約**である。**浸水深を持たず、ソース間の浸水深の統合ではない。**

| 値 | 条件 |
|---|---|
| `determined_match` | いずれかのソースに確認済みの該当があり、どのソースにも不確実性（unknown・境界接触・集約不能・外縁上）がない |
| `partial_unknown` | いずれかのソースに確認済みの該当があり、いずれかのソースに不確実性がある |
| `unknown_only` | どのソースにも確認済みの該当がなく、いずれかのソースに不確実性がある |
| `no_match_extent_unknown` | どのソースにも確認済みの該当も不確実性もない。**評価範囲不明であり、浸水なし・区域外・安全と確定しない** |

- `assessed_extent_unknown` は全ソースに付くため、`overall_status` の判定の不確実性には数えない（数えると全ての状態が `partial_unknown`・`unknown_only` になり、区別できなくなる）。評価範囲不明であることは、各ソースの `assessed_extent_relation` と `uncertainty_reasons` で常に示す。
- `single_source` で選択中のソースが `determined_match` でも、他のソースにunknownがあれば `overall_status = partial_unknown` である（ケースB）。総合的に確定したように表示しない。
- 共通API契約の該当性 `result.assessment` との対応: `determined_match`・`partial_unknown` は `affected`、`unknown_only`・`no_match_extent_unknown` は `undetermined`（新しい値の提案。`not_affected` にしない。FA-C2）。`affected` は「いずれかのソースに確認済みの該当がある」の意味であり、浸水深の統合ではない。

### 5.8 地域外・地域の外縁上

| `region_state` | 扱い |
|---|---|
| `inside` | 第5.3節〜第5.7節のとおり |
| `region_boundary` | ソースを列挙して判定する。各ソースの `service_region_relation = boundary`、`uncertainty_reasons` に `region_boundary`。統合成果物は地域と接するだけのFeatureを保持しないため、情報が不完全でありうる |
| `outside` | 判定しない。`status = no_data`、`error.code = outside_service_region` |

`not_covered`（地域外）、`unknown`（評価範囲が不明・判定保留）、`outside_inundation_zone`（評価済みの区域外。MVPでは使わない）を混同しない（Integration契約 第10章）。

## 6. 共通の `status`・エラーと正常な判定不能の区別［提案］

**正常な判定不能（unknown・評価範囲不明・集約不能・外縁上）は、エラーではない。** `status = success` とし、内容を `result` に入れる。エラー（取得失敗・整合性の異常・入力の不正）は `result = null` とし、`status` と `error` で返す。

| 状況 | `status` | `result` | `error.code`（案） |
|---|---|---|---|
| 地域の内部・外縁上で判定できた（`overall_status` のいずれか） | `success` | あり | `null` |
| 地点が対象地域の外 | `no_data` | `null` | `outside_service_region` |
| Floodの公開データがない（未公開・公開停止） | `no_data` | `null` | `flood_not_published`（公開停止と未公開の区別は［未決定: FA-U8］） |
| 公開Registry・公開実体の読取り失敗 | `retrieval_failed` | `null` | `flood_read_failed` |
| 公開世代の不整合（目録・設定・地域形状の内容ハッシュの不一致、参照の欠落） | `indeterminate` | `null` | `flood_integrity_error` |
| 点の判定器の判定保留（有効な形状。通常は統合時にFAILEDとなり発生しない） | `indeterminate` | `null` | `flood_point_undecided` |
| 座標の不正・未知のパラメータ・重複 | 入力エラー（`invalid_input` の追加を提案。FA-C4） | `null` | `invalid_coordinates`・`unknown_parameter` |
| `source_id` の形式不正 | 入力エラー | `null` | `invalid_source_id` |
| `source_id` が現在の公開世代の目録にない | 入力エラー | `null` | `source_not_available` |
| `source_id` の複数指定 | 入力エラー | `null` | `multiple_sources_not_supported` |

- 地点がサービス対象地域の外の場合は、`source_id` の指定があっても `no_data`（`outside_service_region`）とする。地域外の判定を入力の検証より後に行うか先に行うかは、`source_id` が目録にあるかの検査を先に行う（入力の不正を先に返す）案とする。
- HTTPステータスとの対応は［未決定］。正常な判定不能に、エラーのHTTPステータスを使わないことを提案する。
- `no_data`・`retrieval_failed`・`indeterminate`・入力エラーのいずれも、非該当・浸水深0mに変換しない［確定: 共通API契約 §3.1］。
- `error.message` は公開用の説明とし、内部の例外の文字列・パスを含めない［確定: 共通API契約 §5］。

## 7. データ・設定の世代の追跡［提案］

| 項目 | 内容 |
|---|---|
| `dataset.id`・`dataset.publication_version`・`dataset.published_at` | 公開Registryの識別・版（共通API契約 §5） |
| `dataset.attribution` | 利用条件が求める出典・加工の表示（A31a・N03。文言は［未決定: Integration契約 OI-10］） |
| `settings.source_catalog` | Source CatalogのID・版・内容ハッシュ |
| `settings.source_category_assignment` | 区分の割当記録のID・版・内容ハッシュ |
| `settings.source_display` | 表示設定のID・版・内容ハッシュ |
| `settings.unknown_region` | unknownポリシーのID・版・内容ハッシュ（Integration契約 第3.1節） |
| `evaluated_at` | 評価時刻（データの基準日・公開日とは別） |

- これらはすべて同じ公開世代に属する（Selection契約 第8.2節）。応答の中で世代を混在させない［確定: 共通API契約 §5］。
- 内部の `run_id`・ファイルパス・統合成果物のファイル名・承認記録の内部参照は公開しない。
- 旧版の `policy.source_priority`（Source Priority Policy）は廃止した。

## 8. ケース別のレスポンス（すべて架空・暫定）

以下は `result` の要点だけを示す。

### 8.1 ケースA: 東京都ランク1、関東地方整備局ランク4、利用者が東京都を選択

```json
{"selection": {"mode": "single_source", "source_id": "example-source-a", "selected_by": "user"},
 "overall_status": "determined_match", "selected_result_is_exclusive": false,
 "safety": {"other_sources_count": 1, "deeper_in_other_sources": true,
            "has_unknown": false, "has_unknown_in_other_sources": false},
 "sources": [
   {"source_id": "example-source-a", "is_selected": true, "source_organization": "東京都",
    "assessment_status": "determined_match",
    "depth": {"kind": "class", "class_code": "1", "label": "0～0.5m未満", "lower_m": 0, "upper_m": 0.5, "bounds_inclusion": "unspecified"}},
   {"source_id": "example-source-b", "is_selected": false, "source_organization": "国土交通省 関東地方整備局",
    "assessment_status": "determined_match",
    "depth": {"kind": "class", "class_code": "4", "label": "5.0～10.0m未満", "lower_m": 5.0, "upper_m": 10.0, "bounds_inclusion": "unspecified"}}]}
```

東京都の浸水深を主表示する。関東地方整備局の該当を保持し、`deeper_in_other_sources = true` で、より深い公表情報があることを示す（区分の体系の同一性が承認されていることが前提。未承認なら `null`）。

### 8.2 ケースB: 東京都がunknown、関東地方整備局ランク3、利用者が関東地方整備局を選択

第5.1節の例のとおり。関東地方整備局の確認済みの結果（`determined_match`）を主表示にする。東京都のunknownを保持する（`has_unknown_in_other_sources = true`）。`overall_status = partial_unknown` であり、総合的に確定したように表示しない。

### 8.3 ケースC: どのソースにも確認済みの該当がない（地域の内部）

```json
{"selection": {"mode": "overview", "source_id": null, "selected_by": null},
 "assessment": "undetermined", "overall_status": "no_match_extent_unknown",
 "safety": {"other_sources_count": 2, "has_unknown": false, "depth_classes_present": []},
 "sources": [
   {"source_id": "example-source-a", "assessment_status": "no_match_extent_unknown",
    "assessed_extent_relation": "unknown", "has_confirmed_match": false, "depth": null},
   {"source_id": "example-source-b", "assessment_status": "no_match_extent_unknown",
    "assessed_extent_relation": "unknown", "has_confirmed_match": false, "depth": null}]}
```

浸水深0m・浸水なし・安全と返さない。説明の文言は「この地点は、登録されている浸水想定区域に該当しません。ただし、評価範囲が示されていないため、浸水しないことを意味しません」等の趣旨とする（文言は［未決定: FA-U4］）。

### 8.4 未選択（`overview`）でケースAの地点

`selection.mode = overview`。どのソースも `is_selected = false`。`safety.depth_classes_present` に「0～0.5m未満」と「5.0～10.0m未満」の2つの区分が並ぶ。主表示の浸水深はなく、特定のソースを暗黙に代表にしない。

### 8.5 地域外

```json
{"hazard": "flood", "location": {"lat": 35.0, "lon": 135.0}, "status": "no_data", "result": null,
 "dataset": null, "settings": null,
 "error": {"code": "outside_service_region", "message": "この地点は、洪水の浸水想定を提供している対象地域の外です。"}}
```

### 8.6 目録にない `source_id`

`result = null`、入力エラー、`error.code = source_not_available`。未選択の結果や別のソースの結果を返さない。

## 9. 共通API契約との整合［既存契約は変更しない］

| No | 共通API契約 | 本書 | 論点 |
|---|---|---|---|
| FA-C1 | §2 入力は `lat`・`lon` | `lat`・`lon`（指示書の例は `latitude`・`longitude`） | 名前の最終決定 |
| FA-C2 | §3.1・§4.2 該当性は `affected`・`not_affected` | `affected`・`undetermined`（`not_affected` を使わない） | `undetermined` の追加 |
| FA-C3 | §5「管理主体を公開レスポンスへ含めない」 | `source_organization`（公表元・管理主体の名称）を返す | 共通契約の「管理主体」はシステムの管理情報を指すと解釈した。原典の公表元は出典（`source.provider` の公開用要約）に当たり、利用条件の表示にも必要である。解釈の確認が必要 |
| FA-C4 | §2 入力エラーの形式は詳細設計 | `invalid_input` の追加を提案 | `status` の列挙への追加の可否 |
| FA-C5 | §3.1 `success` は「要求された取得・評価が成立」 | unknown・評価範囲不明でも `success` とし、`overall_status`・ソースごとの `assessment_status` で区別 | 共通契約 §4.2は部分結果の `status` を未決定としている |
| FA-C6 | §3 6フィールド。追加フィールドの規則は未決定 | `settings` を追加 | 追加フィールドの規則 |
| FA-C7 | §6 複数データセットの優先順位・集約は未決定。最大値等を独断で導入しない | システムによる優先順位・ソース間の集約は導入しない。ソース内の集約（最も深い区分）だけを提案 | ソース内の集約もOWNERの承認まで提案 |
| FA-C8 | §2「利用者に都道府県やデータセットの選択を要求しない」 | 選択は任意（既定は `overview`）。要求はしない | データソースを任意に選ぶ入力は共通契約にない。追加の論点 |
| FA-C9 | §3 `dataset` の複数件の形は未決定 | 公開世代の `dataset` は1つ、ソースごとの来歴は `sources[]` に置く | 複数根拠の表現 |
| FA-C10 | §5 位置情報をログに残さない | 同じ。地点をキーにしたサーバ側のキャッシュも持たない | — |

## 10. セキュリティ・プライバシー

- 位置情報（`lat`・`lon`・位置を含むURL・本文）を、アプリログ・アクセスログ・プロキシ・トレース・エラー収集に残さない［確定: 共通API契約 §5］。`source_id` 自体は位置情報ではないが、地点と組み合わせて記録しない。
- サーバは利用者の選択を保存しない（Selection契約 第6.3節）。
- 応答には内部パス・ファイル名・`record_key`・`run_id`・承認記録の内部参照・スタックトレースを含めない。
- 選択・表示順・ポリシーをリクエストで変更させない（`source_id` は表示の指定であり、判定を変えない）。

## 11. 契約テストの受入条件（将来の実装時。いずれも実行していない）

| ID | 入力・状況 | 受入条件 |
|---|---|---|
| FA-01 | ケースA（東京都を選択） | 東京都を主表示、関東地方整備局を保持、`deeper_in_other_sources = true` |
| FA-02 | ケースB（関東地方整備局を選択） | 関東地方整備局を主表示、東京都のunknownを保持、`overall_status = partial_unknown` |
| FA-03 | ケースC | `no_match_extent_unknown`・`assessment = undetermined`。浸水深0・`not_affected`・安全にならない |
| FA-04 | `overview` でケースAの地点 | `is_selected = true` のソースがない。`depth_classes_present` に2区分 |
| FA-05 | 同じ地点で、`source_id` なし・A・Bの3通り | `sources[]` の各要素の判定の項目が3通りで同一。違いは `selection`・`is_selected`・`safety` の選択依存の項目だけ |
| FA-06 | 同じFeatureの有効Pと判定保留Q | そのソースの `matches` と `unknowns` の両方に現れ、`partial_unknown` |
| FA-07 | `source_id` の形式不正・目録にない・旧世代・複数指定 | それぞれの入力エラー。未選択・別ソースの結果を返さない |
| FA-08 | `source_category`・`priority`・`policy` 等のパラメータ | 未知のパラメータとして入力エラー |
| FA-09 | 座標の欠落・`null`・非数値・非有限値・範囲外・重複 | 入力エラー。`no_data`・非該当に変換しない |
| FA-10 | 地域外・外縁上・内部の境界上 | `no_data`（`outside_service_region`）／`success`＋`region_boundary`／`inside` |
| FA-11 | 公開データなし・公開停止 | `no_data`（`flood_not_published`） |
| FA-12 | 公開実体の読取り失敗・設定の内容ハッシュの不一致 | `retrieval_failed`／`indeterminate`。正常結果を生成しない |
| FA-13 | 公開世代の切替え中の連続した要求 | 各応答の `dataset.publication_version` と `settings` の各ハッシュが同じ世代に対応する |
| FA-14 | 表示設定だけを変更した新しい公開世代 | `sources[]` の並び順だけが変わり、判定・安全上の情報は同一 |
| FA-15 | 応答の全体 | 内部パス・ファイル名・`record_key`・`run_id` を含まない。`selected_by` に `system` が現れない |
| FA-16 | 正常・異常時のログ | 位置情報を含まない |
| FA-17 | 該当が上限を超える地点（合成データ） | 黙って切り捨てず、`truncated` と全件数を示す |
| FA-18 | 同じ地点・同じ世代・同じ選択で繰り返し | 結果と並び順が同一 |

## 12. Phase 2-B.9の版からの変更

| 旧版の項目 | 扱い | 理由・置き換え |
|---|---|---|
| `representative`（代表結果） | **廃止** | システムは代表を選ばない。主表示は利用者が選んだソースの `sources[]` の要素 |
| `selection_reason` | **廃止** | 選択の理由はない（利用者の選択）。`selection.mode`・`selected_by` に置き換え |
| `priority`（提供主体の優先順位） | **廃止** | 区分に順位を与えない。並び順は表示設定（信頼性の順位ではない） |
| `finality`（`final`・`provisional`） | **廃止** | 代表がないため不要。不確実性は `overall_status`・`uncertainty_reasons`・`safety` で示す |
| `category_states` | **廃止** | 区分ごとではなく、ソースごとの `assessment_status`・第4.1節の5つの区別に置き換え |
| `deeper_match_outside_representative` | 再定義 | `safety.deeper_in_other_sources`（選択中のソースとの比較） |
| `matches`・`unknowns`・`boundary_contacts`（全ソースを1つの配列） | 再定義 | ソースごとの配列（`sources[].matches` 等） |
| `assessment_status`（応答全体） | 再定義 | ソースごとの `assessment_status` と、状態の要約 `overall_status`（浸水深を持たない） |
| `policy.source_priority` | **廃止** | `settings.source_catalog`・`source_display` 等に置き換え |
| 任意パラメータを受け付けない | 変更 | `source_id` だけを受け付ける |

## 13. 未決定事項とOWNER判断事項

| No | 事項 | 本書の提案 |
|---|---|---|
| FA-U1 | Flood APIの正式なレスポンスSchema（型・必須性・null・省略） | 本書の構成を叩き台とする |
| FA-U2 | 全ソース中の最大浸水深の代表化 | 採用しない。`deeper_in_other_sources`・`depth_classes_present` で事実だけを示す |
| FA-U3 | 共通契約との論点 FA-C1〜FA-C9 | 第9章 |
| FA-U4 | 説明文言（評価範囲不明・判定保留・未選択・他ソースの存在・より深い想定） | 「安全」「浸水なし」「おすすめ」「信頼度順」と誤読されない文言。OWNERが確定 |
| FA-U5 | unknownの区域の原典ランクを可能性として返すか | MVPでは返さない |
| FA-U6 | `source_id`・`zone_ref` の生成規則・粒度（Selection契約 SS-U1・SS-U4） | 公開世代の中で安定した不透明な識別子 |
| FA-U7 | 応答の大きさの上限 | 黙って切り捨てない条件付きで設定 |
| FA-U8 | 公開停止と未公開の区別 | 公開応答では区別しない案 |
| FA-U9 | API入力の座標系・精度・格子外の地点の扱い | 未決定のまま地点を丸めない |
| FA-U10 | エンドポイントの構成（Discoveryを別にするか）・APIパス・HTTPメソッド・HTTPステータス・API版の指定方式 | 1つのエンドポイント。位置を含まない目録は将来の別エンドポイント |
| FA-U11 | 「洪水による浸水なし（内水のみ）」の成果品の表示（Integration契約 OI-16） | 未決定 |
| FA-U12 | `not_included_notice` の列挙値と文言 | 未決定 |

本書の採用は、製品実装・正式Schema・実データの公開の承認ではない。
