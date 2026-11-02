# Polygon判定理由の共通仕様と日本語メッセージカタログ v0.1

> **この版は [v0.2](polygon-reason-catalog-v0.2.md)（Phase 4-I）で置き換えた。** 記録として残す。実装の現行の版は v0.2。

- 状態: Phase 4-F で実装（`hererisk.common.polygon_reasons`、`message_version: v0.1`）。正式なLocation APIの応答には追加していない。Phase 4-G で、結果の文言（9章）と処理状態のコード2つ（`diagnosis_limit_exceeded`・`diagnosis_busy`）を追加し、[洪水の参考解析API](flood-diagnostic-api-v0.1.md) で使用している。
- 対象: Polygon由来の判定（洪水から開始。津波・高潮・土砂災害などのProviderも同じ機能を使える）。

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

## 3. 定義の属性

| 属性 | 内容 |
|---|---|
| `code` | 安定した機械判定用コード |
| `message_ja` | 一般利用者向けの短い日本語 |
| `detail_ja` | 判定できない理由の詳しい説明 |
| `category` | geometry / coverage / data / processing / result |
| `concept` | 共通の意味（第2章） |
| `scope` | `common`、またはハザードの種類（例: `flood`） |
| `priority` | 代表メッセージを選ぶ順（小さいほど優先。共通コードで重複なし） |
| `message_version` | 文言の定義の版 |

文言は言語ごとに `text: {"ja": {"message", "detail"}}` の形で持つ。返却時の名前は `message_<locale>`・`detail_<locale>`。

## 4. 解決規則

`resolve_reason(code, hazard_type=None, locale="ja")`

1. ハザードの文言が登録されていれば、それを使う。
2. なければ、共通の文言を使う。
3. 未知のコードは汎用の文言（「判定の理由を表示できません。」）を返し、`code` をそのまま保持して `known: false` とする。
4. 未対応の言語は日本語を返し、`locale_fallback: "ja"` を付ける。

`resolve_reasons(codes, ...)` は、全コードを順序どおりに返し、1件も落とさない。代表メッセージ（`representative`）は `priority`、次にコード名で選ぶ。理由の配列の順序には依存しない。

ハザードの文言は `register_hazard_messages(hazard_type, definitions)` で登録する。共通コードの category・concept・priority は引き継ぐ。ハザードだけのコードは、それらを必ず指定する。空の文言は登録できない。

## 5. 文言の規則（テストで確認）

- 判定できない結果を「安全」と表現しない。危険の判定もしない。
- 「境界上」は、地点が境界線上にあると確認できたコード（concept `on_boundary`）にだけ使う。原典の形状の不整合と、地点が境界付近にあることを混同しない。
- 原典の形状の不整合を「データの誤り」「整備の不足」などと断定しない。事実（形状の検査で有効と判定されなかったこと）だけを書く。
- 共通の文言はハザードに依存しない表現（「対象区域」「区域データ」）にする。
- GPSの測位精度はPolygonの不整合とは別の概念として扱い、このカタログの理由にしない。

## 6. 理由コード一覧（v0.1）

| コード | category | concept | 優先度 | 共通の文言（message_ja） | 洪水の文言 |
|---|---|---|---:|---|---|
| `diag_index_not_complete` | data | data_inconsistency | 10 | 判定に使用するデータの準備が完了していません。 | （共通の文言） |
| `diag_index_identity_mismatch` | data | data_inconsistency | 11 | 判定に使用するデータの整合性を確認できませんでした。 | （共通の文言） |
| `zone_ref_not_in_diag_index` | data | data_inconsistency | 12 | 判定に使用するデータの整合性を確認できませんでした。 | （共通の文言） |
| `zone_ref_not_in_provider_unknowns` | data | data_inconsistency | 13 | この区域は診断の対象ではありません。 | （共通の文言） |
| `diagnosis_limit_exceeded` | processing | processing_failure | 14 | 診断の対象となる区域が多すぎるため、参考の解析結果を表示できません。 | （共通の文言） |
| `diagnosis_failed` | processing | processing_failure | 15 | 判定の処理が完了しませんでした。 | （共通の文言） |
| `diagnosis_timeout` | processing | processing_failure | 16 | 判定の処理が時間内に完了しませんでした。 | （共通の文言） |
| `diagnosis_busy` | processing | processing_failure | 18 | 混み合っているため、参考の解析を実行できませんでした。 | （共通の文言） |
| `outside_service_region` | coverage | outside_coverage | 20 | この地点は、登録している区域データの対象地域の外です。 | この地点は、登録している浸水想定区域データの対象地域の外です。 |
| `service_region_boundary` | coverage | coverage_boundary | 21 | 提供データの対象地域の境界付近にあるため、判定できません。 | （共通の文言） |
| `on_boundary` | geometry | on_boundary | 30 | 対象区域の境界上にあるため、区域内かどうかを確定できません。 | 浸水想定区域の境界上にあるため、区域内かどうかを確定できません。 |
| `zone_boundary_contact` | geometry | on_boundary | 31 | 対象区域の境界上にあるため、区域内かどうかを確定できません。 | 浸水想定区域の境界上にあるため、区域内かどうかを確定できません。 |
| `pending_geometry_zone` | geometry | geometry_inconsistency | 40 | 区域データの形状に不整合がある範囲のため、区域内かどうかを確定できません。 | 浸水想定区域のデータの形状に不整合がある範囲のため、区域内かどうかを確定できません。 |
| `invalid_geometry` | geometry | geometry_inconsistency | 41 | 区域データの形状に不整合があるため、この区域では判定できません。 | （共通の文言） |
| `feature_invalid_component` | geometry | geometry_inconsistency | 42 | 区域データの形状に不整合があるため、この区域では判定できません。 | （共通の文言） |
| `feature_level_invalidity_not_analyzed` | geometry | geometry_inconsistency | 43 | 区域データの形状に不整合があるため、正確に判定できません。 | （共通の文言） |
| `defect_within_decision_radius` | geometry | geometry_inconsistency | 44 | 判定に必要な範囲で、区域データの形状に不整合が見つかりました。 | 判定に必要な範囲で、区域データの形状に不整合が見つかりました。 |
| `defect_within_max_radius` | geometry | geometry_inconsistency | 45 | 元の区域データの境界に不整合があるため、正確に判定できません。 | 元の区域データの境界に不整合があるため、正確に判定できません。 |
| `defect_location_unknown` | geometry | geometry_inconsistency | 46 | 区域データの形状に不整合があるため、正確に判定できません。 | （共通の文言） |
| `orientation_unknown` | geometry | boundary_interpretation_uncertain | 50 | 区域データの輪郭の向きを確定できず、区域内かどうかを判断できません。 | （共通の文言） |
| `ambiguous_nearest` | geometry | boundary_interpretation_uncertain | 51 | 周辺の区域境界が複雑なため、判定結果を確定できません。 | （共通の文言） |
| `local_far_disagree` | geometry | boundary_interpretation_uncertain | 52 | 区域の境界の解釈が定まらないため、判定結果を確定できません。 | （共通の文言） |
| `even_odd_winding_disagree` | geometry | boundary_interpretation_uncertain | 53 | 区域の境界の解釈が定まらないため、判定結果を確定できません。 | （共通の文言） |
| `no_local_boundary` | geometry | local_information_insufficient | 60 | 周辺の境界情報だけでは、区域内かどうかを確実に判定できません。 | 周辺の境界情報だけでは、浸水想定区域内かどうかを確実に判定できません。 |
| `all_conditions_met` | result | conditions_met | 90 | 参考の解釈です。正式な判定ではありません。 | （共通の文言） |
| `flood_response_limit_exceeded` | processing | processing_failure | 17 | （洪水だけのコード） | 該当する浸水想定区域が多すぎるため、結果を表示できません。 |

詳しい説明（`detail_ja`）は `catalog()` で取得できる。

## 7. 洪水診断との接続

`hererisk.flood.reason_messages.explain(record)` は、Phase 4-E の分類記録（`adoption.classify` / `DiagIndex.diagnose`）を2層に分ける。分類そのものは変えない。

- `user`: 代表メッセージ（`message_ja`）と `certainty: "diagnostic_only"`。
- `technical`: 分類、全理由コードとその説明、ハザード、`source_id`、`zone_ref`、診断方式、分類規則の版、原典の浸水深区分、`official: false`、`message_version`。

理由コード・原典の識別子（`source_id`・`zone_ref`）・診断方式を、同じ記録に結び付けて持つ。将来のData Managerで、提供元別・区域別・問題の種類別に集計し、後から再検証できるようにするためである。集計画面と外部への報告機能は実装していない。

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
