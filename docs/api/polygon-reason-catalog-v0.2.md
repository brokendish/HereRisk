# Polygon判定理由の共通仕様と日本語メッセージカタログ v0.2

- 状態: Phase 4-I で実装（`hererisk.common.polygon_reasons`、`message_version: v0.2`）。v0.1（Phase 4-F・4-G）を置き換える。旧版: [v0.1](polygon-reason-catalog-v0.1.md)（記録として残す）。
- v0.1 からの変更: 各コードに原因の区分 `cause`（と、定義上確かな場合だけ `background_cause`）を追加した。文言に、記録の値を差し込む項目（`params`）を追加した。`no_local_boundary`・`defect_within_decision_radius`・`ambiguous_nearest` の文言と、`defect_within_max_radius` の説明を改めた（10章）。**コード・`category`・`concept`・`priority`・`scope` は v0.1 から変えていない**（テストで固定）。
- 対象: Polygon由来の判定（洪水から開始。津波・高潮・土砂災害などのProviderも同じ機能を使える）。
- 関連: [Polygon Engine 共通契約 v0.2](polygon-engine-contract-v0.2.md)、[ADR-002](../decisions/2026-11-03-polygon-engine-responsibility.md)、[洪水の参考解析API](flood-diagnostic-api-v0.1.md)

## 1. 責務

| 部品 | 責務 | 持たないもの |
|---|---|---|
| `hererisk.common.polygon_reasons` | 理由コード・概念・分類・日本語の文言・解決規則 | ハザードの一覧・意味（浸水深・警戒区域の区分）、Polygonの解析 |
| ハザードのモジュール（例: `hererisk.flood.reason_messages`） | そのハザードの文言（例:「浸水想定区域」）とハザード固有のコード | 共通コードの意味・優先度の変更 |
| Provider・診断（例: `hererisk.flood.adoption`） | 理由コードを付ける | 表示用の文章 |

- 理由コードは機械判定用の安定した識別子で、文言を変えてもコードは変えない。
- 文言の更新は `message_version` で管理する。
- 既存の理由コード（Phase 4-A のProvider、Phase 4-E の分類）は、名前を変えずにそのまま使う。変換規則は不要。

## 2. 概念と分類

| concept | 意味 |
|---|---|
| inside | 対象区域の内側 |
| outside | 対象区域の外側 |
| on_boundary | 対象区域の境界線上 |
| geometry_inconsistency | 区域データの形状に不整合がある |
| boundary_interpretation_uncertain | 境界の解釈が定まらない |
| local_information_insufficient | 周辺の情報だけでは判断できない |
| coverage_boundary | データの対象地域の境界付近 |
| outside_coverage | データの対象地域の外 |
| data_inconsistency | 入力データ・索引の整合性を確認できない |
| processing_failure | 処理が完了しなかった |
| information_missing | 判断に必要な情報がない |
| conditions_met | 定義した条件をすべて満たした（参考解釈） |

`category` は `geometry`（形状・境界）、`coverage`（データの対象地域）、`data`（入力データ・索引）、`processing`（処理）、`result`（結果）のいずれか。

判定の種類（`ASSESSMENT_KINDS`）は、正式な判定と診断上の解釈を分けて扱う。

| 種類 | 表示 | 洪水の分類（Phase 4-E） |
|---|---|---|
| `official` | 公式データによる判定 | Flood Providerの `status`・`zones` |
| `diagnostic_candidate` | 参考解釈の候補（正式な判定ではありません） | `candidate` |
| `undetermined` | 判定保留 | `undetermined` |
| `not_applicable` | 判定対象外・利用不能 | `rejected` |

### 2.1 原因の区分（`cause`、v0.2）

| cause | 意味 | 原典の問題として集計するか |
|---|---|---|
| `source_geometry` | 原典の形の事実（無効な形状・輪郭の接点・交点・面積0の環） | 構成の形状状態（`geometry_state`）として、構成の単位で数えうる |
| `search_scope` | 探索の条件（探索半径など）による。原典の品質の評価ではない | 数えない |
| `analysis_method` | 解析方式の限界・適用条件による | 数えない |
| `point_position` | 地点と区域の形の位置関係（境界線上など） | 数えない |
| `coverage` | データの対象地域・登録範囲による | 数えない |
| `index_data` | HereRiskの索引・データの世代の問題 | 数えない |
| `analysis_scope` | 診断の対象外 | 数えない |
| `processing` | 処理の上限・失敗 | 数えない |
| `result` | 結果（定義した条件の成立） | 数えない |

- `source_geometry` の理由コードを地点ごとに数えた件数を、原典の不整合の件数にしない（同じ構成が多くの地点で数えられる）。原典の不整合は、構成の形状の検査結果で数える（[共通契約 v0.2](polygon-engine-contract-v0.2.md) 第6章）。
- `search_scope`（探索半径など）・`analysis_method`（解析方式）は、原典の品質の評価ではない。

## 3. 定義の属性

| 属性 | 内容 |
|---|---|
| `code` | 安定した機械判定用コード |
| `message_ja` | 一般利用者向けの短い日本語 |
| `detail_ja` | 判定できない理由の詳しい説明 |
| `category` | geometry / coverage / data / processing / result |
| `cause` | 直接の原因の区分（2.1節）。v0.2で追加 |
| `background_cause` | 背景の原因。**コードの定義上確かな場合だけ**持つ（記録ごとに推測して付けない）。v0.2で追加 |
| `params` | 文言に差し込める項目の名前（例: `max_radius_m`）。v0.2で追加 |
| `concept` | 共通の意味（第2章） |
| `scope` | `common`、またはハザードの種類（例: `flood`） |
| `priority` | 代表メッセージを選ぶ順（小さいほど優先。共通コードで重複なし） |
| `message_version` | 文言の定義の版 |

文言は言語ごとに `text: {"ja": {"message", "detail"[, "fallback"]}}` の形で持つ。返却時の名前は `message_<locale>`・`detail_<locale>`。差し込みの項目を使う文言は、数値を含まない `fallback` を必ず持つ。

## 4. 解決規則

`resolve_reason(code, hazard_type=None, locale="ja", params=None)`（`params` は v0.2 で追加。省略可）

1. ハザードの文言が登録されていれば、それを使う。
2. なければ、共通の文言を使う。
3. 未知のコードは汎用の文言（「判定の理由を表示できません。」）を返し、`code` をそのまま保持して `known: false` とする。
4. 未対応の言語は日本語を返し、`locale_fallback: "ja"` を付ける。

5. `params` は、そのコードが `params` で宣言した項目だけを使う（他は無視）。値は数値（真偽値・文字列は不可）で、範囲内（`max_radius_m`: 0より大きく10,000以下）のときだけ差し込む。表示は小数3桁までで丸める。値がない・不正な場合は `fallback`（数値なし）の文言を返す。差し込んだ値は `params` として返す。
6. 差し込みは、宣言した名前の `{名前}` を置き換えるだけで、テンプレートを評価しない（`str.format` を使わない）。画面に `{` `}` が残らないことを登録時に検査する。

`resolve_reasons(codes, ..., params=None)` は、全コードを順序どおりに返し、1件も落とさない。代表メッセージ（`representative`）は `priority`、次にコード名で選ぶ。理由の配列の順序には依存しない。

ハザードの文言は `register_hazard_messages(hazard_type, definitions)` で登録する。共通コードの category・concept・priority・cause・params は引き継ぎ、ハザードは変えられない（文言だけを持つ）。ハザードだけのコードは、category・concept・priority・cause を必ず指定する。空の文言・宣言していない項目・`fallback` のない差し込みは登録できない。

## 5. 文言の規則（テストで確認）

- 判定できない結果を「安全」と表現しない。危険の判定もしない。
- 「境界上」は、地点が境界線上にあると確認できたコード（concept `on_boundary`）にだけ使う。原典の形状の不整合と、地点が境界付近にあることを混同しない。
- 原典の形状の不整合を「データの誤り」「整備の不足」などと断定しない。事実（形状の検査で有効と判定されなかったこと）だけを書く。
- 共通の文言はハザードに依存しない表現（「対象区域」「区域データ」）にする。
- GPSの測位精度はPolygonの不整合とは別の概念として扱い、このカタログの理由にしない。
- （v0.2）探索範囲・解析方式による判定保留を、原典の不整合として説明しない。輪郭の接点・交点を、未検証のまま「不整合」と断定しない。
- （v0.2）探索半径などの値を固定の文字列として書かない。記録の値を `params` で差し込む。

## 6. 理由コード一覧（v0.2）

| コード | category | concept | 優先度 | cause | 共通の文言（message_ja） | 洪水の文言 |
|---|---|---|---:|---|---|---|
| `diag_index_not_complete` | data | data_inconsistency | 10 | `index_data` | 判定に使用するデータの準備が完了していません。 | （共通の文言） |
| `diag_index_identity_mismatch` | data | data_inconsistency | 11 | `index_data` | 判定に使用するデータの整合性を確認できませんでした。 | （共通の文言） |
| `zone_ref_not_in_diag_index` | data | data_inconsistency | 12 | `index_data` | 判定に使用するデータの整合性を確認できませんでした。 | （共通の文言） |
| `zone_ref_not_in_provider_unknowns` | data | data_inconsistency | 13 | `analysis_scope` | この区域は診断の対象ではありません。 | （共通の文言） |
| `diagnosis_limit_exceeded` | processing | processing_failure | 14 | `processing` | 診断の対象となる区域が多すぎるため、参考の解析結果を表示できません。 | （共通の文言） |
| `diagnosis_failed` | processing | processing_failure | 15 | `processing` | 判定の処理が完了しませんでした。 | （共通の文言） |
| `diagnosis_timeout` | processing | processing_failure | 16 | `processing` | 判定の処理が時間内に完了しませんでした。 | （共通の文言） |
| `diagnosis_busy` | processing | processing_failure | 18 | `processing` | 混み合っているため、参考の解析を実行できませんでした。 | （共通の文言） |
| `outside_service_region` | coverage | outside_coverage | 20 | `coverage` | この地点は、登録している区域データの対象地域の外です。 | この地点は、登録している浸水想定区域データの対象地域の外です。 |
| `service_region_boundary` | coverage | coverage_boundary | 21 | `coverage` | 提供データの対象地域の境界付近にあるため、判定できません。 | （共通の文言） |
| `on_boundary` | geometry | on_boundary | 30 | `point_position` | 対象区域の境界上にあるため、区域内かどうかを確定できません。 | 浸水想定区域の境界上にあるため、区域内かどうかを確定できません。 |
| `zone_boundary_contact` | geometry | on_boundary | 31 | `point_position` | 対象区域の境界上にあるため、区域内かどうかを確定できません。 | 浸水想定区域の境界上にあるため、区域内かどうかを確定できません。 |
| `pending_geometry_zone` | geometry | geometry_inconsistency | 40 | `source_geometry` | 区域データの形状に不整合がある範囲のため、区域内かどうかを確定できません。 | 浸水想定区域のデータの形状に不整合がある範囲のため、区域内かどうかを確定できません。 |
| `invalid_geometry` | geometry | geometry_inconsistency | 41 | `source_geometry` | 区域データの形状に不整合があるため、この区域では判定できません。 | （共通の文言） |
| `feature_invalid_component` | geometry | geometry_inconsistency | 42 | `source_geometry` | 区域データの形状に不整合があるため、この区域では判定できません。 | （共通の文言） |
| `feature_level_invalidity_not_analyzed` | geometry | geometry_inconsistency | 43 | `analysis_method`（背景 `source_geometry`） | 区域データの形状に不整合があるため、正確に判定できません。 | （共通の文言） |
| `defect_within_decision_radius` | geometry | geometry_inconsistency | 44 | `source_geometry` | 判定に必要な範囲に、区域データの輪郭が接する・交わる箇所があるため、判定を保留しています。 | 判定に必要な範囲に、区域データの輪郭が接する・交わる箇所があるため、判定を保留しています。 |
| `defect_within_max_radius` | geometry | geometry_inconsistency | 45 | `source_geometry` | 元の区域データの境界に不整合があるため、正確に判定できません。 | 元の区域データの境界に不整合があるため、正確に判定できません。 |
| `defect_location_unknown` | geometry | geometry_inconsistency | 46 | `analysis_method`（背景 `source_geometry`） | 区域データの形状に不整合があるため、正確に判定できません。 | （共通の文言） |
| `orientation_unknown` | geometry | boundary_interpretation_uncertain | 50 | `source_geometry` | 区域データの輪郭の向きを確定できず、区域内かどうかを判断できません。 | （共通の文言） |
| `ambiguous_nearest` | geometry | boundary_interpretation_uncertain | 51 | `analysis_method` | 近くに複数の区域境界があり、どちらの側かを区別できないため、判定を保留しています。 | （共通の文言） |
| `local_far_disagree` | geometry | boundary_interpretation_uncertain | 52 | `analysis_method` | 区域の境界の解釈が定まらないため、判定結果を確定できません。 | （共通の文言） |
| `even_odd_winding_disagree` | geometry | boundary_interpretation_uncertain | 53 | `analysis_method` | 区域の境界の解釈が定まらないため、判定結果を確定できません。 | （共通の文言） |
| `no_local_boundary` | geometry | local_information_insufficient | 60 | `search_scope` | 周辺{max_radius_m}mの範囲では判定に必要な区域の境界を確認できないため、判定を保留しています。 | 周辺{max_radius_m}mの範囲では判定に必要な浸水想定区域の境界を確認できないため、判定を保留しています。 |
| `all_conditions_met` | result | conditions_met | 90 | `result` | 参考の解釈です。正式な判定ではありません。 | （共通の文言） |
| `flood_response_limit_exceeded` | processing | processing_failure | 17 | `processing` | （洪水だけのコード） | 該当する浸水想定区域が多すぎるため、結果を表示できません。 |

- `{max_radius_m}` を含む文言は、値がないときは次の文言になる。共通: 「周辺の探索範囲では判定に必要な区域の境界を確認できないため、判定を保留しています。」、洪水: 「周辺の探索範囲では判定に必要な浸水想定区域の境界を確認できないため、判定を保留しています。」

詳しい説明（`detail_ja`）は `catalog()` で取得できる。

## 7. 洪水診断との接続

`hererisk.flood.reason_messages.explain(record)` は、Phase 4-E の分類記録（`adoption.classify` / `DiagIndex.diagnose`）を2層に分ける。分類そのものは変えない。

- `user`: 代表メッセージ（`message_ja`）と `certainty: "diagnostic_only"`。
- `technical`: 分類、全理由コードとその説明、ハザード、`source_id`、`zone_ref`、診断方式、分類規則の版、原典の浸水深区分、`official: false`、`message_version`。

理由コード・原典の識別子（`source_id`・`zone_ref`）・診断方式を、同じ記録に結び付けて持つ。将来のData Managerで、提供元別・区域別・問題の種類別に集計し、後から再検証できるようにするためである。集計画面と外部への報告機能は実装していない。

- v0.2: `explain` と `interpret` は、記録そのものから差し込みの値を取る（`message_params`）。`max_radius_m` は、局所の探索が最大半径まで境界なしで終わった記録の `evidence.stopped_at_m`（実際に調べた最大半径）。API側の定数は使わない。値がない記録は数値なしの文言になる。

## 8. 提示APIの責務の分け方

責務を次の5つに分ける（概念名であり、既存のLocation APIのフィールドは変えない）。Phase 4-G の [洪水の参考解析API](flood-diagnostic-api-v0.1.md) は、この分け方で実装した（`official_assessment`・`diagnostic.interpretations[]` の `reasons`・`message`・`source_id`/`zone_ref`）。下の例は概念の説明用。

| 概念 | 内容 |
|---|---|
| `official_assessment` | 公式データによる判定（現在の `status`・`zones`・`unknowns` など）。診断で変えない |
| `diagnostic_interpretation` | 参考解釈（`candidate` だけ。`certainty: "diagnostic_only"`） |
| `reasons` | 機械判定用の理由コード（全件） |
| `messages` | 日本語の説明（利用者向けの代表メッセージと、コードごとの詳細） |
| `source` | 原典と提供元（`source_id`・提供組織・版・出典・`zone_ref`） |

```json
{
  "official_assessment": {"status": "unknown", "reasons": ["pending_geometry_zone"]},
  "diagnostic_interpretation": {"kind": "diagnostic_candidate", "relation": "inside",
                                "depth_class_in_source": {"class_code": "3", "label": "3.0～5.0m未満"},
                                "method": "local-contour-winding-v1", "certainty": "diagnostic_only"},
  "reasons": ["all_conditions_met"],
  "messages": {"user_ja": "参考の解釈です。正式な判定ではありません。", "message_version": "v0.1"},
  "source": {"hazard_type": "flood", "source_id": "local-a31a-2025-83", "zone_ref": "loc-zn-…"}
}
```

- 共通部分はハザードの意味を解釈しない。浸水深（洪水・津波・高潮）や警戒区域の区分（土砂災害）は、各Providerが原典の属性のまま持ち、表示層で説明する。
- 提示の条件と未決定事項は [洪水診断の提示契約（Stage 3案）](flood-diagnosis-stage3-draft.md) に従う。

## 9. 結果の文言（Phase 4-G）

理由コード（なぜ確定できないか）とは別に、参考解析で「何と読めたか」を示す文言を、同じ仕組み（共通の中立な文言＋ハザードの文言の登録）で持つ。`resolve_result(kind, hazard_type)` で解決する。未知の種類はエラーにする（結果の種類はコードが決めるもので、データから受け取らない）。

| 種類（kind） | 共通の文言（message_ja） | 洪水の文言 |
|---|---|---|
| `candidate_inside` | 参考解析では、この区域に含まれると解釈されました。 | この浸水深の想定区域に含まれる可能性があります。 |
| `candidate_inside_class_unknown` | 参考解析では、この区域に含まれると解釈されました。 | この浸水想定区域に含まれる可能性があります。 |
| `candidate_outside` | 参考解析では、この区域の外側と解釈されました。 | 参考解析では、この想定区域の外側と解釈されました。 |
| `diagnostic_notice` | HereRiskが元の区域データを独自に解析した参考情報です。正式な判定ではありません。 | HereRiskが元の浸水想定区域データを独自に解析した参考情報です。正式な判定ではありません。 |

- どの文言の説明（`detail_ja`）にも「正式な判定ではありません」（または「正式な判定ではなく」）を含める（テストで確認）。
- `candidate_outside` の洪水の説明には「浸水しないことを意味しません」を含める。区域外であることを確定した表現（「区域外です」「該当しません」）や「安全」は使わない。
- `candidate_inside_class_unknown` は、原典の浸水深区分を確認できない場合に使う。浸水深は示さない。
- `undetermined`・`rejected` には結果の文言を使わず、理由コードの代表メッセージ（6章）を示す。

## 10. v0.1 → v0.2 の文言の差分

コード・`category`・`concept`・`priority`・`scope` は変えていない。変えたのは次の文言だけである。

| コード | 範囲 | v0.1 | v0.2 |
|---|---|---|---|
| `no_local_boundary` | 共通 message | 周辺の境界情報だけでは、区域内かどうかを確実に判定できません。 | 周辺{max_radius_m}mの範囲では判定に必要な区域の境界を確認できないため、判定を保留しています。（値なし: 周辺の探索範囲では判定に必要な区域の境界を確認できないため、判定を保留しています。） |
| `no_local_boundary` | 洪水 message | 周辺の境界情報だけでは、浸水想定区域内かどうかを確実に判定できません。 | 周辺{max_radius_m}mの範囲では判定に必要な浸水想定区域の境界を確認できないため、判定を保留しています。（値なし: 周辺の探索範囲では判定に必要な浸水想定区域の境界を確認できないため、判定を保留しています。） |
| `no_local_boundary` | 共通・洪水 detail | 調べる範囲の中に（浸水想定）区域の境界がなく、周辺の情報だけでは内外を確定できないため、判定を保留しています。 | 設定した探索範囲（半径{max_radius_m}m）の中に（浸水想定）区域の境界がありませんでした。探索範囲による結果で、区域データの不整合を示すものではありません。 |
| `defect_within_decision_radius` | 共通・洪水 message | 判定に必要な範囲で、区域データの形状に不整合が見つかりました。 | 判定に必要な範囲に、区域データの輪郭が接する・交わる箇所があるため、判定を保留しています。 |
| `defect_within_decision_radius` | 共通・洪水 detail | …輪郭が自身と接する・交わる箇所があるため、判定を保留しています。 | …輪郭が接する・交わる箇所があります。原典の形状の不整合とは限りませんが、この範囲では内外の読みを確定していません。 |
| `ambiguous_nearest` | 共通 message | 周辺の区域境界が複雑なため、判定結果を確定できません。 | 近くに複数の区域境界があり、どちらの側かを区別できないため、判定を保留しています。 |
| `defect_within_max_radius` | 共通・洪水 detail | 周辺の輪郭からは内外を読めましたが、調べる範囲の中に輪郭の不整合箇所があるため、その読みを確定していません。 | この（浸水想定）区域データの形状には不整合があります。周辺の輪郭からは内外を読めましたが、調べる範囲の中に輪郭が接する・交わる箇所があるため、その読みを確定していません。 |

- `defect_within_max_radius` の message（「元の区域データの境界に不整合があるため、正確に判定できません。」）は変えていない。このコードは、正式な検索で判定保留とされた構成（構成そのものが無効、または同じ地物の構成どうしに不整合がある）にだけ付く。説明では、不整合は構成の事実であり、地点の近くの接点・交点がその不整合の箇所とは限らないことを分けて書いた。
- その他のコードの文言は変えていない（`cause` と矛盾しないことを確認した）。
