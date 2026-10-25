# Flood API MVP Contract v0.1（案）

- 作成: 2026-10-24（Claude。Phase 2-B.9）
- 改訂: 2026-10-25 Design Contract Realignment（Phase 2-B.17）— **公式データ忠実提示方式への全面移行**。OWNERの仕様変更により、ソース間の比較・代表値・状態の要約・ソースの選択の入力を廃止し、全面的に書き直した。基準コミット `bb7c438d6aa04a741f8d3ee867a0df4002512a48`。廃止した項目は第12章。経緯は [Phase 2-B.17 レビュー](../../reviews/phase2/phase2b17-official-data-presentation-realignment.md)
  - Phase 2-B.9〜B.16の版（`representative`・`deeper_in_other_sources`・`deeper_comparison`・`assessment_status`・`overall_status`・`source_id` の入力 等）は**廃止した設計**であり、実装根拠として使用禁止。旧版の内容はgitの履歴と各レビュー記録（履歴資料）にある
- 改訂: 2026-10-25 Phase 2-B.19 — Phase 2-B.18 Codex監査のLOW指摘B18-01への文書訂正。`sources[].lineage_ref` と区域ごとの `product_ref`（契約案）を追加し、区域から来歴をたどる対応を明記した（第5.2節・第5.3節・第7章・FA-11）。機能・方式は変更していない
- 状態: **契約案（OWNERレビュー待ち。正式採用されていない）**。本書は製品実装・正式なレスポンスSchema・実データの公開の承認ではない
- 上位: [Design Principles](../architecture/design-principles-v1.0.md)、[共通API契約 v0.1](common-contract-v0.1.md)
- 意味の正本: [Flood Official Data Presentation Contract v0.1（案）](../architecture/flood-official-data-presentation-contract-v0.1.md)（以下「提示契約」）。本書は入出力の形・エラー・世代の追跡だけを定め、データの意味・区別・提示の規則は提示契約を参照する
- 前提: [Flood Integration Contract v0.1（案）](../architecture/flood-integration-contract-v0.1.md)

区分: **［確定］** 既存の承認済み契約・OWNER決定に由来、**［実測］** 調査で報告された値、**［提案］** 本書の設計提案（未承認）、**［未決定］** OWNER判断が必要。**APIパス・フィールド名・型・JSON例はすべてPROVISIONAL（暫定）であり、正式Schemaではない**（共通API契約 §1と同じ扱い）。

## 1. 目的

指定した1地点について、検索対象として採用・公開したA31a（想定最大規模）の各データソースを独立して検索し、**ソースごとに、該当した区域をそれぞれ、原典の浸水深区分・出典・来歴とともに返す**。ソース間の比較・代表値・順位付け・安全／危険の判定は行わない（提示契約 第1章・第3章）。

設計原則: **公式情報の違いを隠さない。内部は厳密に。外部はシンプルに。不確実性は隠さない。**

## 2. MVPの範囲

**含めるもの**［提案］: 緯度・経度の1地点の検索、目録の全ソースの列挙、ソースごとの区域・unknown・境界接触の全件の返却、原典の浸水深区分・出典・河川・想定条件・版・来歴の返却、データ未収録・取得失敗・整合性エラーの区別、公開世代と設定の版の参照。

**含めないもの**: 提示契約 第3章の廃止した機能（ソース間の比較・代表値・順位付け・集約・安全／危険の判定）、ソースを選ぶ入力（提示契約 PD-U3）、派生形状の製品利用（BLOCKED）、unknownのL2（禁止）、避難経路、複数地点・面の一括判定、地図タイルの生成、管理画面の実装、実データの公開（Flood用の認可プロファイル・利用条件が未成立）。

## 3. 入力［提案］

**エンドポイント（仮案）**: `GET /api/flood?lat=<緯度>&lon=<経度>`

URLは仮案であり、既存のルーティング契約を変更しない。APIパス・メソッド・版の指定方式は共通API契約 §10と同じく未決定である。

| パラメータ | 必須 | 内容 |
|---|---|---|
| `lat` | ○ | 緯度（十進度） |
| `lon` | ○ | 経度（十進度） |

- 共通API契約 §2に従う。欠落・`null`・非数値・非有限値・範囲外（lat −90〜90、lon −180〜180）を有効な地点として処理しない。latとlonを暗黙に交換しない。重複したパラメータは拒否する。
- 原典はJGD2011（EPSG:6668）。API入力との扱い・桁数・nano-degreeの格子に乗らない地点の扱いは未決定（Normalize契約 ON-11、Integration契約 OI-18）。**未決定のまま地点を丸めない。**
- **その他のパラメータは受け付けない**（未知のパラメータは入力エラー）。ソース・区分・提供主体・優先順位・並び順を指定する入力は設けない。絞り込み・主表示の切替えはUIで行う（提示契約 第9章）。
- Discovery（ソースの一覧）と検索を別のエンドポイントにしない。一覧にも各ソースの検索結果が必要で、分けると同じ地点を2回検索することになり、2回の呼出しの間に公開世代が食い違いうるためである。位置を含まない目録の一覧が将来必要になった場合は、別のエンドポイント（例: `GET /api/flood/catalog`）を追加する［未決定: FA-U10］。

## 4. 処理［提案］

1. 公開世代のSource Catalogから、地点がサービス対象地域に入る全ソースを列挙する（提示契約 第6章）。
2. 各ソースを独立して検索する（提示契約 第7章）。
3. ソースごとの結果と、公開世代・設定の版をまとめて返す。

- APIは公開済みのRegistry・公開実体だけを読む［確定: 共通API契約 §5］。
- 1つの応答では1つの公開世代だけを使う（提示契約 第10章）。
- 1つのソースでも検索に失敗した場合は、応答全体をエラーにする（第6章）。

## 5. 出力［提案］

### 5.1 全体の構成

共通API契約 §3の6フィールド（`hazard`・`location`・`status`・`result`・`dataset`・`error`）と `evaluated_at` に、`settings` を加える。

```json
{
  "hazard": "flood",
  "location": {"lat": 35.68, "lon": 139.76},
  "status": "success",
  "result": {
    "region_state": "inside",
    "candidate_scope": "registered_sources_in_service_region",
    "candidate_completeness": "not_guaranteed",
    "not_included_notice": ["pluvial_flooding", "storm_surge", "planned_scale_scenario", "adjacent_prefectures"],
    "summary": {"sources_total": 2, "sources_with_zones": 1, "sources_with_unknown_or_boundary": 1},
    "sources": [
      {"source_id": "example-source-a", "source_category": "local_government", "source_organization": "東京都",
       "title": "<データの正式名称>", "scenario": "maximum", "data_version": "2025",
       "attribution": {"text": "<出典・加工の表示>"}, "lineage_ref": "<公開用の来歴の要約への参照>",
       "service_region_relation": "inside", "assessed_extent_relation": "unknown",
       "zones": [],
       "unknowns": [{"zone_ref": "z-a1", "product_ref": "p-a1", "river_name_in_source": "<代表河川名>", "reason": "invalid_geometry", "unknown_level": "L1"}],
       "boundary_contacts": []},
      {"source_id": "example-source-b", "source_category": "national_government", "source_organization": "国土交通省 関東地方整備局",
       "title": "<データの正式名称>", "scenario": "maximum", "data_version": "2025",
       "attribution": {"text": "<出典・加工の表示>"}, "lineage_ref": "<公開用の来歴の要約への参照>",
       "service_region_relation": "inside", "assessed_extent_relation": "unknown",
       "zones": [
         {"zone_ref": "z-b1", "product_ref": "p-b1", "river_code": "<A31a_201>", "river_name_in_source": "荒川",
          "depth_class": {"scheme_id": "ksj-a31a-water-depth-rank", "scheme_version": "<版>", "class_code": "3",
                          "label": "3.0～5.0m未満", "lower_m": 3.0, "upper_m": 5.0, "bounds_inclusion": "unspecified"}}],
       "unknowns": [], "boundary_contacts": []}
    ]
  },
  "dataset": {"id": "example-flood", "publication_version": "example-v1", "published_at": "2026-10-01T00:00:00Z"},
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

値はすべて架空である。実在の地点の浸水想定・データの識別子・承認済みの設定を示さない。

### 5.2 ソースの一覧（`result.sources[]`）

| 項目 | 内容 |
|---|---|
| `source_id`・`source_category`・`source_organization` | 提示契約 第4章。`source_category` は分類の属性で、順位を持たない |
| `title`・`scenario`・`data_version`・`attribution` | 提示契約 第4.3節 |
| `lineage_ref` | ソースの公開用の来歴の要約への参照（提示契約 第4.3節）。内部パス・Lineage Manifestそのものを指さない |
| `service_region_relation`・`assessed_extent_relation` | 提示契約 第7.1節 |
| `zones[]`・`unknowns[]`・`boundary_contacts[]` | 第5.3節 |

- `sources[]` は、列挙した全ソースを含む。並び順は公開世代のSource Display Settingsによる（既定は `source_id` の昇順）。**並び順は信頼性の順位ではない。**
- `candidate_scope`・`candidate_completeness`・`not_included_notice` は提示契約 第6章。

### 5.3 区域・unknown・境界接触

| 配列 | 各要素の項目 |
|---|---|
| `zones[]`（確認済みの該当） | `zone_ref`、`product_ref`［契約案］、`river_code`・`river_name_in_source`（成果品の代表河川。個別の区域の原因河川ではない［実測］）、`depth_class`（第5.5節） |
| `unknowns[]`（判定保留） | `zone_ref`、`product_ref`［契約案］、`river_code`・`river_name_in_source`、`reason`（`invalid_geometry`・`feature_invalid_component`）、`unknown_level`（`L1`） |
| `boundary_contacts[]`（境界上） | `zone_ref`、`product_ref`［契約案］、`river_code`・`river_name_in_source`、`depth_class` |

- **同じソースに複数の区域が該当した場合は、それぞれを要素として返す。** 集約した浸水深の項目は持たない。
- 各配列の並び順は `zone_ref` の昇順（決定的）。
- `zone_ref` は区域を識別する公開用の不透明な識別子であり、来歴は表さない。内部の `record_key`（原典のZIPメンバー名を含む）を公開しない。
- `product_ref` は、区域が属する成果品の公開用の不透明な参照で、同じソースの `lineage_ref` の要約の中の成果品の項目に解決できる。同じソースの複数の成果品から複数の区域を返す場合も、区域ごとに来歴を追跡できる。`product_ref` の採否と、要約に含める項目は未決定（提示契約 PD-U10。正式Schema FA-U1と同時に確定）。
- unknownの区域の原典のランクを返すかは未決定（FA-U5）。MVPの案では返さない。

### 5.4 全件の返却

- 全ソース・全区域・全unknown・全境界接触を、1つの応答で返す。切り捨てない（黙った切捨ても、通知付きの切捨ても行わない）。
- 応答の大きさ（区域の件数・バイト数）が受入可能な上限を超える場合は、**部分結果を返さず、明示的なエラー**とする（第6章 `flood_response_limit_exceeded`）。上限の値は性能検証の後に確定する（FA-U7）。
- 将来、部分返却が必要になった場合は、公開世代を固定したカーソル方式など、全件の取得を保証する独立の契約とする。

### 5.5 原典の浸水深区分（`depth_class`）

提示契約 第7.2節のとおり、`scheme_id`・`scheme_version`・`class_code`・`label`・`lower_m`・`upper_m`・`bounds_inclusion` を持つ。原典の情報の表現であり、比較・集約に使わない。共通API契約 §4.2の深さの候補（`lower_m`・`upper_m`・`category`）に沿う。範囲・階級から架空の代表値を作らない。

### 5.6 事実の件数（`result.summary`）

| 項目 | 内容 |
|---|---|
| `sources_total` | 列挙したソースの数 |
| `sources_with_zones` | `zones[]` が空でないソースの数 |
| `sources_with_unknown_or_boundary` | `unknowns[]` または `boundary_contacts[]` が空でないソースの数 |

これは計数であり、比較・順位付け・状態の要約ではない。安全・危険を表す項目、ソース間で浸水深を比べる項目、代表値の項目は設けない。

### 5.7 地域

| `result.region_state` | 扱い |
|---|---|
| `inside` | 全ソースを列挙して検索する |
| `region_boundary` | 全ソースを列挙して検索する。各ソースの `service_region_relation = boundary`（情報が不完全でありうる。提示契約 第8章 区別3） |
| `outside` | 検索しない。`status = no_data`、`error.code = outside_service_region` |

## 6. 共通の `status` とエラー［提案］

結果の5つの区別（提示契約 第8章）と、APIの `status` の対応は次のとおり。**unknown・評価範囲不明・境界上・外縁上は、正常な検索結果であり、エラーではない。**

| 状況 | `status` | `result` | `error.code`（案） |
|---|---|---|---|
| 地域の内部・外縁上で、全ソースの検索に成功（区域・unknownの有無を問わない） | `success` | あり | `null` |
| 地点が対象地域の外 | `no_data` | `null` | `outside_service_region` |
| Floodの公開データがない（未公開・公開停止） | `no_data` | `null` | `flood_not_published`（公開停止と未公開の区別は［未決定: FA-U8］） |
| 公開Registry・公開実体の読取り失敗（1つのソースだけの失敗を含む） | `retrieval_failed` | `null` | `flood_read_failed` |
| 公開世代の不整合（目録・設定・地域形状の内容ハッシュの不一致、所属の照合の不成立、DBと公開設定のunknownポリシーの不一致、空の目録、参照の欠落） | `indeterminate` | `null` | `flood_integrity_error` |
| 点の判定器の判定保留（有効な形状。通常は統合時にFAILEDとなり発生しない） | `indeterminate` | `null` | `flood_point_undecided` |
| 応答の大きさが受入可能な上限を超える | `retrieval_failed`（提案。FA-C11） | `null` | `flood_response_limit_exceeded` |
| 座標の不正・未知のパラメータ・重複 | 入力エラー（`invalid_input` の追加を提案。FA-C4） | `null` | `invalid_coordinates`・`unknown_parameter` |

- `no_data`・`retrieval_failed`・`indeterminate`・入力エラーのいずれも、該当なし・浸水深0mに変換しない［確定: 共通API契約 §3.1］。
- `error.message` は公開用の説明とし、内部の例外の文字列・パス・件数等の診断情報を含めない［確定: 共通API契約 §5］。
- HTTPステータスとの対応は［未決定］。正常な検索結果に、エラーのHTTPステータスを使わないことを提案する。

## 7. データ・設定の世代の追跡［提案］

| 項目 | 内容 |
|---|---|
| `dataset.id`・`dataset.publication_version`・`dataset.published_at` | 公開Registryの識別・版（共通API契約 §5） |
| `sources[].attribution` | 利用条件が求める出典・加工の表示（ソースごと） |
| `sources[].lineage_ref`・区域ごとの `product_ref` | 区域 → `product_ref` → `lineage_ref` の要約の成果品の項目、の順に来歴をたどる（提示契約 第4.1節）。公開世代の中で安定し、内部パス・`record_key`・`product_id` を含めない |
| `settings.source_catalog`・`settings.source_category_assignment`・`settings.source_display` | 目録・区分の割当記録・表示設定のID・版・内容ハッシュ |
| `settings.unknown_region` | unknownポリシーのID・版・内容ハッシュ。公開世代の統合成果物の `metadata` のunknownポリシーと一致する（提示契約 第10章） |
| `evaluated_at` | 評価時刻（データの基準日・公開日とは別） |

これらはすべて同じ公開世代に属する。内部の `run_id`・ファイルパス・統合成果物のファイル名・承認記録の内部参照は公開しない。

## 8. ケース別のレスポンス（すべて架空・暫定）

| ケース | `result` の要点 |
|---|---|
| A: 東京都にランク1、関東地方整備局にランク4の区域 | 東京都の `zones` にランク1の区域、関東地方整備局の `zones` にランク4の区域。`summary.sources_with_zones = 2`。どちらが深いか・代表値は返さない |
| B: 東京都がunknownだけ、関東地方整備局にランク3の区域 | 第5.1節の例。東京都の `unknowns` と関東地方整備局の `zones` が両方返る |
| C: どのソースにも区域・unknown・境界接触がない（地域の内部） | 全ソースの3つの配列が空。`assessed_extent_relation = unknown`。説明の文言は「この地点は、登録されている浸水想定区域に該当しません。ただし、評価範囲が示されていないため、浸水しないことを意味しません」等の趣旨（文言は［未決定: FA-U4］） |
| 同じソースの2区域（ランク2・ランク3） | 2つの区域を個別に返す |
| 地域外 | `status = no_data`、`result = null`、`error.code = outside_service_region` |

## 9. 共通API契約との整合

共通API契約は、本改訂にあわせて、複数データの独立した返却と、比較・代表値の禁止を明記した（共通API契約 §4.2・§6）。残る論点は次のとおり。

| No | 共通API契約 | 論点 |
|---|---|---|
| FA-C1 | §2 入力は `lat`・`lon` | 本書も `lat`・`lon`。名前の最終決定は共通契約の詳細設計 |
| FA-C3 | §5「管理主体を公開レスポンスへ含めない」 | `source_organization`（公表元の名称）を返す。共通契約の「管理主体」はシステムの管理情報を指すと解釈した。公表元は出典に当たり、利用条件の表示にも必要。**解釈は未承認** |
| FA-C4 | §2 入力エラーの形式は詳細設計 | `invalid_input` の追加を提案 |
| FA-C6 | §3 追加フィールドの規則は未決定 | `settings` を追加 |
| FA-C9 | §3 `dataset` の複数件の形 | 公開世代の `dataset` は1つ、ソースごとの出典は `sources[]` に置く |
| FA-C11 | §3.1 | 応答の上限超過のエラーの `status`（`retrieval_failed` を提案。未承認） |

## 10. セキュリティ・プライバシー

- 位置情報（`lat`・`lon`・位置を含むURL・本文）を、アプリログ・アクセスログ・プロキシ・トレース・エラー収集に残さない［確定: 共通API契約 §5］。地点をキーにしたサーバ側のキャッシュを持たない。
- 応答には内部パス・ファイル名・`record_key`・`run_id`・承認記録の内部参照・スタックトレースを含めない。

## 11. 契約テストの受入条件（将来の実装時。いずれも実行していない）

| ID | 入力・状況 | 受入条件 |
|---|---|---|
| FA-01 | 提示契約 PD-01〜PD-15の合成データ | 提示契約の期待どおり |
| FA-02 | 座標の欠落・`null`・非数値・非有限値・範囲外・重複、未知のパラメータ（`source_id`・`priority` 等を含む） | 入力エラー。`no_data`・該当なしに変換しない |
| FA-03 | 地域外・外縁上・内部の境界上 | `no_data`（`outside_service_region`）／`success`＋`region_boundary`／`inside` |
| FA-04 | 公開データなし・公開停止 | `no_data`（`flood_not_published`） |
| FA-05 | 公開実体の読取り失敗（1ソースだけを含む）・設定の内容ハッシュの不一致・空の目録 | `retrieval_failed`／`indeterminate`。正常結果を生成しない |
| FA-06 | 公開世代の切替え中の連続した要求 | 各応答の `dataset.publication_version` と `settings` の各ハッシュが同じ世代に対応する |
| FA-07 | 応答の全体 | 廃止した項目（`representative`・`deeper_in_other_sources`・`deeper_comparison`・`assessment_status`・`overall_status`・`selection` 等）が現れない。内部パス・ファイル名・`record_key`・`run_id` が現れない |
| FA-08 | 正常・異常時のログ | 位置情報を含まない |
| FA-09 | 応答の大きさが上限を超える地点（合成データ） | 部分結果を返さず `flood_response_limit_exceeded` |
| FA-10 | 同じ地点・同じ世代で繰り返し | 結果と並び順が同一 |
| FA-11 | 同じソースの異なる成果品の2区域が地点に該当（合成データ） | 区域ごとに異なる `product_ref` が返り、それぞれが同じソースの `lineage_ref` の要約の中の成果品の項目に解決できる。`zone_ref`・`product_ref`・`lineage_ref` に内部パス・`record_key`・ZIPメンバー名が現れない |

## 12. 廃止した項目（Phase 2-B.9〜B.16の版から）

| 旧版の項目 | 扱い |
|---|---|
| `representative`・`selection_reason`・`priority`・`finality`・`category_states` | 廃止（Phase 2-B.10で既に廃止済み） |
| `source_id` の入力、`result.selection`（`overview`・`single_source`・`selected_by`）、`is_selected`、`selected_result_is_exclusive` | 廃止。APIは常に全ソースを返す。絞り込み・主表示の切替えはUIで行う |
| `safety.deeper_in_other_sources`・`deeper_comparison`（`basis`・`deeper_zones`・`not_deeper_zones`・`incomparable_zones`）・`depth_classes_present` | 廃止（ソース間の比較） |
| `sources[].depth`（ソース内の集約）・`contributing_zones`・`aggregation` | 廃止（独自の集約）。区域ごとの `depth_class` だけを返す |
| `sources[].assessment_status`・`result.overall_status`・`uncertainty_reasons`・`has_confirmed_match`・`has_unknown`・`has_boundary_contact` | 廃止（派生状態）。配列（`zones`・`unknowns`・`boundary_contacts`）と `summary` の件数で事実を示す |
| `result.assessment`（`affected`・`undetermined`） | 廃止（全体の該当性の要約）。共通API契約 §4.2の改訂による |
| `matches[]` | `zones[]` に改名 |
| 入力エラー `invalid_source_id`・`source_not_available`・`multiple_sources_not_supported` | 廃止（`source_id` の入力がないため） |

## 13. 未決定事項とOWNER判断事項

| No | 事項 | 本書の提案 |
|---|---|---|
| FA-U1 | 正式なレスポンスSchema（型・必須性・null・省略） | 本書の構成を叩き台とする。`product_ref`・`lineage_ref` の要約の形式（提示契約 PD-U10）を含む |
| FA-U4 | 説明文言（評価範囲不明・判定保留・他ソースの存在） | 「安全」「浸水なし」「おすすめ」「信頼度順」と誤読されない文言。OWNERが確定 |
| FA-U5 | unknownの区域の原典ランクを返すか | MVPでは返さない |
| FA-U7 | 応答の大きさの上限の値 | 全件返却。超過は明示的なエラー。値は性能検証の後 |
| FA-U8 | 公開停止と未公開の区別 | 公開応答では区別しない案 |
| FA-U9 | API入力の座標系・精度・格子外の地点の扱い | 未決定のまま地点を丸めない |
| FA-U10 | エンドポイントの構成・APIパス・HTTPメソッド・HTTPステータス・API版の指定方式 | 1つのエンドポイント |
| FA-U11 | 「洪水による浸水なし（内水のみ）」の成果品の表示（Integration契約 OI-16） | 未決定 |
| FA-U12 | `not_included_notice` の列挙値と文言 | 提示契約 PD-U5 |

本書の採用は、製品実装・正式Schema・実データの公開の承認ではない。
