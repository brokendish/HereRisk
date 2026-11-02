# 洪水の参考解析API v0.1（Phase 4-G、初期実装）

- 状態: Phase 4-G で実装、Phase 4-I で文言 v0.2・`cause` を追加（2.4節）。**初期値は無効**。管理者が `diagnosis.api_enabled: true` を設定したときだけ公開される。一般公開の経路（リバースプロキシ）にはつないでいない。
- 実装: `hererisk.location.flood_diagnostics`（処理）、`hererisk.flood.reason_messages.interpret`（1区域分の解釈と文言）、`hererisk.common.polygon_reasons`（文言のカタログ）。
- 前提: 分類は Phase 4-E の `flood-diagnosis-adoption-v1`、文言は [Polygon判定理由カタログ v0.2](polygon-reason-catalog-v0.2.md)（Phase 4-F・4-I、9章に結果の文言）、位置の指定は [Location API v0.1](location-api-v0.1.md) 第2章と同じ。

**公式データによる判定（`official_assessment`）と、HereRiskの参考解析（`diagnostic`）は別の情報である。** 参考解析は防災上の公式判定を置き換えない。正式な洪水判定への採用（昇格）は対象外。

## 1. エンドポイント

```
GET /api/v1/diagnostics/flood?lat=<緯度>&lon=<経度>
```

| パス | 役割 | 位置 |
|---|---|---|
| `GET /api/v1/location` | 正式な応答（変更なし） | クエリで指定 |
| `GET /api/v1/diagnostics/flood` | 1地点の正式な洪水判定と参考解析を並べて返す（本書） | クエリで指定 |
| `GET /api/v1/diagnostics/flood-shadow` | Shadowの件数（Phase 4-E、変更なし） | なし |

- 入力の規則は `/api/v1/location` と同じ関数（`parse_point`）で検証する。`lat`・`lon` を1回ずつ、十進数で。範囲外・形式違い・余分なパラメータは 422 `invalid_input`。値を丸めたり入れ替えたりしない。
- GET以外は 405、無効のときは 404（従来どおり）。想定外の失敗は 500 `internal_error`（例外の内容・ファイルパスは返さない）。
- 応答には `Cache-Control: no-store` を付ける。

## 2. 応答（HTTP 200）

```json
{
  "schema_version": "flood-diagnostic-v0.1",
  "hazard_type": "flood",
  "location": {"lat": 35.0, "lon": 139.0},
  "official_assessment": {"provider": "flood-a31a-local", "status": "unknown", "sources": ["…"], "…": "…"},
  "diagnostic": {
    "status": "complete",
    "complete": true,
    "official": false,
    "certainty": "diagnostic_only",
    "method": "local-contour-winding-v1 (Phase 4-C local_analysis)",
    "adoption_version": "flood-diagnosis-adoption-v1",
    "message_version": "v0.2",
    "diag_index": {"built_at": "…", "status": "complete", "derived_from_flood_index_built_at": "…"},
    "radii_m": [5, 10, 25, 50, 100],
    "targets_total": 9,
    "max_targets": 32,
    "interpretations": [
      {
        "source_id": "local-a31a-2025-83",
        "zone_ref": "loc-zn-…",
        "classification": "candidate",
        "relation": "inside",
        "interpretation": "candidate_inside",
        "assessment_kind": "diagnostic_candidate",
        "assessment_label_ja": "参考解釈の候補（正式な判定ではありません）",
        "certainty": "diagnostic_only",
        "official": false,
        "depth_class_in_source": {"scheme_id": "ksj-a31a-water-depth-rank", "class_code": "3", "label": "3.0～5.0m未満", "…": "…"},
        "message": {"kind": "candidate_inside",
                    "message_ja": "この浸水深の想定区域に含まれる可能性があります。",
                    "detail_ja": "元の区域データを独自に解析した結果です。正式な判定ではありません。浸水深は原典の区分をそのまま示しています。"},
        "reasons": ["all_conditions_met"],
        "reason_messages": [{"code": "all_conditions_met", "known": true, "cause": "result", "message_ja": "…", "detail_ja": "…"}],
        "method": "local-contour-winding-v1 (Phase 4-C local_analysis)",
        "adoption_version": "flood-diagnosis-adoption-v1"
      }
    ],
    "reason": null,
    "notice": {"message_ja": "HereRiskが元の浸水想定区域データを独自に解析した参考情報です。正式な判定ではありません。",
               "detail_ja": "…"}
  },
  "evaluated_at": "2026-11-02T13:00:00Z"
}
```

### 2.1 `official_assessment`

- `GET /api/v1/location` の `hazards.flood` と**同じセクション**（同じFlood Provider、同じ形の検査、同じ `notice`）。値も意味も変えない。
- 参考解析の結果で `status` を変えない（`unknown` を `available`・`no_match` にしない）。`zones`・`results` に参考解析を混ぜない。
- Flood Providerが失敗した場合は、`/api/v1/location` と同じ `error` セクション（`provider_failed`）になり、参考解析はしない（`no_targets`）。

### 2.2 `diagnostic`

| フィールド | 内容 |
|---|---|
| `status` | `complete`・`no_targets`・`limit_exceeded`・`timeout`・`busy`・`failed`（3章） |
| `complete` | `interpretations` が全件そろっているときだけ `true` |
| `official` / `certainty` | 常に `false` / `"diagnostic_only"` |
| `method` / `adoption_version` / `message_version` | 診断方式・分類規則・文言の版 |
| `diag_index` | 診断索引の作成日時と、作成元のflood索引の作成日時（起動時に一致を確認済み） |
| `targets_total` / `max_targets` | 診断の対象（Providerの `unknowns`）の件数と上限 |
| `interpretations` | 区域ごとの解釈（2.3節）。完了しなかったときは `null`（一部だけを返さない） |
| `reason` | 完了しなかった理由（理由コード・`cause`・日本語）。完了時は `null` |
| `notice` | 参考解析全体への注記 |

### 2.3 `interpretations[]`（1区域につき1件）

- 対象は、`official_assessment` の各ソースの `unknowns` にある `zone_ref` だけ（ソースの順、`unknowns` の順）。診断索引から区域を追加しない。別ソースの構成を当てはめない。
- 各要素は `source_id` と `zone_ref` に結び付く。同じ地点で `inside`・`outside`・`undetermined` が混在しても、すべてそのまま返す。区域・ソースをまとめた全体の判定、最大値・代表値は作らない。
- `classification`・`reasons`・`relation` は Phase 4-E の `DiagIndex.diagnose` の結果そのもの。

| 分類 | `interpretation` | `relation` | `depth_class_in_source` | `message` |
|---|---|---|---|---|
| `candidate` ＋ 内側 | `candidate_inside` | `inside` | 原典の浸水深区分（そのまま） | 「この浸水深の想定区域に含まれる可能性があります。」 |
| `candidate` ＋ 内側、原典の区分を確認できない | `candidate_inside_class_unknown` | `inside` | `null` | 「この浸水想定区域に含まれる可能性があります。」（浸水深は示さない） |
| `candidate` ＋ 外側 | `candidate_outside` | `outside` | `null` | 「参考解析では、この想定区域の外側と解釈されました。」（説明に「浸水しないことを意味しません」） |
| `undetermined` | `undetermined` | `null` | `null` | 理由コードの代表メッセージ（優先度順）。`message` に `code`・`cause` を含む |
| `rejected` | `rejected` | `null` | `null` | 使えない理由の代表メッセージ |

- 浸水深区分は原典の属性（`A31a_205` とその表）をそのまま返す。HereRiskが水深を計算したものではない。`candidate` で内側と読めた場合以外は、区分を推測して付けない。
- `candidate_outside` は「区域がない」「浸水しない」「安全」を意味しない。`no_match` にしない。
- `reasons` は全件を保持し、`reason_messages` に各コードの日本語と `cause`（定義上確かな場合は `background_cause` も）を付ける（未知のコードも `known: false`・`cause: null` で残す）。

### 2.4 Phase 4-I の差分（意図した契約変更）

| 項目 | Phase 4-G | Phase 4-I |
|---|---|---|
| `diagnostic.message_version` | `v0.1` | `v0.2` |
| `reason_messages[].cause`・`message.cause`（理由コードの場合）・`diagnostic.reason.cause` | なし | 追加（[カタログ v0.2](polygon-reason-catalog-v0.2.md) 2.1節） |
| `reason_messages[].background_cause` | なし | 定義上確かなコードだけに追加 |
| `no_local_boundary` の文言 | 「周辺の境界情報だけでは、浸水想定区域内かどうかを確実に判定できません。」 | 「周辺{max_radius_m}mの範囲では判定に必要な浸水想定区域の境界を確認できないため、判定を保留しています。」 |
| `defect_within_decision_radius`・`ambiguous_nearest` の文言、`defect_within_max_radius` の説明 | v0.1 | v0.2（カタログ v0.2 第10章） |

- **`{max_radius_m}` の値**: その記録で、局所の探索が最大半径まで境界なしで終わったときの `evidence.stopped_at_m`（実際に調べた最大半径。設定の半径の列の最後の値と同じ）。API側の定数は使わない。設定の半径の列が `[5, 10, 25, 50]` なら「周辺50m」と表示される（テストで確認）。値のない記録は、数値なしの文言になる。
- **変えていないもの**: `official_assessment`、診断対象の `source_id`・`zone_ref`、分類（`candidate` / `undetermined` / `rejected`）、`relation`、浸水深区分、理由コードの配列と代表の優先順位、`schema_version`、上限・時間切れ・混雑の扱い、Shadow。
- **`schema_version` を `flood-diagnostic-v0.1` のまま据え置いた理由**: 変更はフィールドの追加と文言（`message_version` で版を管理）だけで、既存のフィールドの削除・名称・型・意味は変えていない。ただし共通API契約 第8章では「追加フィールドを許容する規則」が未決定であり、追加を自動的に互換とはしていない。本APIは初期値が無効で、利用者がいないため据え置いたが、**この判断はOWNERの確認事項とする**（第7章 5）。

## 3. 実行方式・上限・異常時

Phase 4-E のShadow（非同期・キュー）はそのまま。本APIはリクエストごとの**同期処理**で、次の上限を持つ。

| 項目 | 値 | 超えたとき |
|---|---|---|
| 診断索引の接続 | 2本（`WORKERS`）。1本を同時に1リクエストだけが使う | 0.25秒（`ACQUIRE_TIMEOUT_S`）待って空かなければ `busy`（`diagnosis_busy`） |
| 1地点の対象区域数 | 32件（`MAX_TARGETS`） | 診断せず `limit_exceeded`（`diagnosis_limit_exceeded`） |
| 1地点の処理時間 | 1秒（`DIAGNOSIS_BUDGET_S`） | `timeout`（`diagnosis_timeout`） |
| その他の失敗 | — | `failed`（`diagnosis_failed`） |

- 上限超過・時間切れ・混雑・失敗のときは `interpretations: null`、`complete: false`。一部だけの一覧を完全なもののように返さない。`unknown` を `outside` に変えない。どの場合も `official_assessment` はそのまま返す。
- 時間の上限は、接続ごとのSQLite進行ハンドラ（接続ごとの期限）と、区域ごとの確認で守る。ある接続の中断は、別のリクエストの接続に影響しない（テストで確認）。
- 診断索引は読み取り専用で開く。原典ZIPはリクエストごとに読まない（起動時も読まない）。
- 起動時、2本の接続それぞれで、診断索引が `complete` であること、形式・方式の版、作成元のflood索引（`index_format`・`built_at`・`zip_sha256`）が使用中のflood索引と一致することを確認する。違えば起動しない（終了コード3）。

## 4. 有効化・無効化

```json
{
  "local_analysis": {"enabled": false, "initial_radius_m": 5, "expansion_radii_m": [10, 25, 50, 100], "max_radius_m": 100},
  "diagnosis": {"shadow_enabled": false, "api_enabled": true}
}
```

- `diagnosis.api_enabled` は省略可（既定 `false`）。Phase 4-E の設定ファイルはそのまま読める。
- `shadow_enabled`（Shadow）と `api_enabled`（本API）は独立したスイッチ。どちらかを有効にするときは `--flood-diag-index` が必要。どちらも無効なのに `--flood-diag-index` を指定した場合と、有効なのに指定がない場合は、終了コード2。
- `local_analysis.enabled`（正式判定への組み込み）は引き続き `true` を拒否する。
- 起動: `python -m hererisk.location.server ... --flood-index <index> --flood-settings <settings> --flood-diag-index <diag>`。Composeでは検証用の `location-api-diagnostic`（`--profile diagnostic-api`、`127.0.0.1:8012`、設定 [deploy/flood/flood-settings.diagnostic-api.json](../../deploy/flood/flood-settings.diagnostic-api.json)）。通常の `location-api` は無効のまま。

## 5. プライバシー・セキュリティ

- 緯度・経度をアクセスログ・診断ログに出さない（サーバーの標準アクセスログは無効。Phase 3-A から）。位置の履歴を保存しない。リクエストを処理したあと、位置は保持しない。
- 応答の `location` は、要求した本人への返答であり、記録ではない。
- 例外の内容・内部のファイルパスは応答に出さない。
- 診断の内部状態は応答に必要な範囲（版・索引の作成日時・上限）だけを返す。
- **リバースプロキシ**: 本リポジトリにはリバースプロキシの設定はない。VPSのCaddy（リポジトリ外、OWNERが管理）は `POST /api/v1/elevation` だけを中継し、本APIは中継していない。将来中継する場合は、事前に次を満たすことが必要（OWNER判断）。
  - Caddyのアクセスログで、クエリ（`lat`・`lon`）を削除またはマスクする（例: `log` の `format filter` で `request>uri` のクエリを削除する）。
  - エラーログ・監視ツールにもURLのクエリを残さない。

## 6. 検証（`python -m hererisk.flood diag-api-verify`）

Phase 4-C の固定シードの地点（自動生成、利用者の位置ではない）で、Location APIのリクエスト→応答関数を通して確認する。Compose: `docker compose --profile verify run --rm flood-diag-api-verify --baseline /reports/<4-C> --cases-dir /reports/<4-D compare>`。

1. `/api/v1/location` が、本APIの有効・無効で同一。`official_assessment` が `hazards.flood` およびFlood Providerの答えと同一。
2. 解釈の対象が `unknowns` と完全に一致（ソース・区域・順序）。分類・理由・内外が Phase 4-E と同一。全理由コードがカタログで説明できる。浸水深は `candidate_inside` の原典の区分だけ。
3. Phase 4-D のケースA（15組）・ケースB（521組）が `candidate` にならない。
4. 並列（指定スレッド数と、その4倍）で、逐次と同一の答え、または明示的な `busy`。

## 7. 未決定事項（OWNER判断）

1. 本APIを一般公開の経路につなぐか。つなぐ場合のログ設定（5章）と利用条件の確認。
2. 画面での表示方法（公式の区域と見た目で区別し、注記を必ず添える）。
3. 上限値（接続数2・対象32件・1秒）を運用環境に合わせて見直すか。
4. Stage 3案（[洪水診断の提示契約](flood-diagnosis-stage3-draft.md)）の条件（`candidate` 以外を提示しない等）との関係。本APIは「参考情報の取得」のための独立したエンドポイントで、`undetermined`・`rejected` も理由とともに返す。正式な応答（`/api/v1/location`）への提示は引き続きStage 3案の条件とOWNERの承認による。
5. Phase 4-I の追加フィールド（`cause` など）で `schema_version` を据え置いたことの確認（2.4節）。
