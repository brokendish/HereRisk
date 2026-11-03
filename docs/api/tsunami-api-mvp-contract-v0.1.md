# Tsunami API MVP 契約 v0.1（案、Phase 4-M）

- 状態: **契約案・ローカル検証のみ**。`hazards.tsunami`（Location API）の津波セクションの形を定める。実装は `hererisk.location.tsunami_provider`（既定では接続しない。`--tsunami-index` を明示したときだけ）。**一般公開・本番接続・第三者への配信の承認ではない。** 利用条件は `review_required`（取得元台帳 `ksj-a40-2024-13`）のまま。
- 作成: 2026-11-03（Claude）。基準コミット `d35c4ba5bfdb7c13dd56d9d2dd4cc960dca710de`
- 上位: [Location API v0.1](location-api-v0.1.md)（第4・5章の状態と `results`）、[Design Principles](../architecture/design-principles-v1.0.md)、[Polygon Engine 共通契約 v0.2](polygon-engine-contract-v0.2.md)、[有効性検証・正式な内外判定 v0.1](polygon-engine-validity-relation-v0.1.md)
- 参照: [Flood API MVP契約](flood-api-mvp-contract-v0.1.md)（同じ状態の規則を使う）、[移行計画 Step 3](../architecture/polygon-engine-migration-plan-v0.1.md)

## 1. 目的と範囲

指定した1地点について、登録した国土数値情報 A40（津波浸水想定）の各ソースを独立して検索する。**ソースごとに、地点を含む区域をそれぞれ、原典の浸水深の区分の文字列・出典とともに返す。** 安全・危険の判定、独自のスコア、代表値・最大値の選択、区域の統合はしない。

- 返すのは「原典の津波浸水想定の区域に含まれるか」だけである。区域が見つからないことを「津波の影響がない」（`not_affected` 等）として返さない。
- A40は評価した範囲（浸水想定を行った沿岸）を示していない。東京都の `A40-23_13` は島しょ部（経度139.12〜142.25度・緯度26.60〜34.80度）の区域だけを収録している。区部・多摩で区域がないことは、想定がないことか、浸水しないことかを区別できない。
- 原典の注意書き「**実際の津波はこの津波浸水想定よりも大きい場合があります。**」を、すべての検索結果（`available`・`unknown`・`no_match`）に `source_caution` として付ける。表示で省略しない。

## 2. 原典（A40）の読み方

| 項目 | 内容（製品仕様書 第2.2版・データページ・ZIPで確認） |
|---|---|
| ファイル | `A40-<yy>_<pref>_GML.zip`。1つのフォルダに GML（`.xml`）・GeoJSON・Shapefile・メタデータ（Shift-JIS） |
| 読む形式 | GeoJSON（索引）。GML は独立検証に使う |
| CRS・軸 | JGD2011（`EPSG:6668`）。GeoJSON は（経度, 緯度）、GML は（緯度 経度）・小数8桁 |
| `FID` | 整数。Featureの位置・`id` と同じ（違えば停止） |
| `A40_001` | 都道府県名（文字列） |
| `A40_002` | 都道府県コード（2桁の文字列、コードリスト）。登録の `prefecture_code` と同じ（違えば停止） |
| `A40_003` | 津波浸水深の区分（文字列）。「各都道府県の津波浸水想定調査報告書等に記載のある, 想定する浸水深のランク区分」。**原典の文字列のまま**（前後の空白・全角のチルダ「～」（U+FF5E）を含めてバイト単位で同じ）。数値・コードに変換しない。区分の境界・代表値・中央値を作らない。洪水（A31a）の区分と同じものとして扱わない |

- 形式・必須属性・座標（非有限値・閉じていない環・範囲外）が想定と違う場合は、索引を作らない（停止）。欠損・不正を区域外や浸水深0mに変換しない。
- 東京都の8区分（実データ、Feature数）: 「～0.3m未満」3,110、「0.3m以上 ～ 0.5m未満」1,802、「0.5m以上 ～ 1m未満」3,603、「1m以上 ～ 3m未満」8,184、「3m以上 ～ 5m未満」8,407、「5m以上 ～ 10m未満」6,079、「10m以上 ～ 20m未満」1,783、「20m以上」156。他の都道府県では区分の表記が異なりうる（表を持たず、文字列をそのまま運ぶ）。

## 3. 判定（共通Polygon Engine）

| 処理 | 実装 |
|---|---|
| 有効性 | `hererisk.common.polygon.validity.classify_components`（索引の構築時、構成ごと）。修復しない |
| 内外 | `hererisk.common.polygon.relation.ComponentIndex.search`（GEOS。有効な構成だけ。探索半径なし） |
| 原典の属性の対応付け | Provider（`zone_ref` → `A40_003`） |

- 有効な構成: `inside` → `zones`、`on_boundary` → `boundary_contacts`（確定した該当ではない）。
- 無効な構成（`invalid_geometry`・`feature_invalid_component`・`unverified`）: 外接矩形（境界を含む）に地点が入るとき `unknowns`（`unknown_level: "L1"`）。浸水深の区分を付けない。区域外として扱わない。
- 複数の区域・ソースは別々の要素で返す（重なりをまとめない）。

## 4. 応答（`hazards.tsunami`）

```json
{
  "provider": "tsunami-a40-local", "synthetic": false, "status": "available",
  "candidate_scope": "registered_sources_in_service_region", "candidate_completeness": "not_guaranteed",
  "limitations": ["single_geometry_validator", "coordinates_as_float", "no_integrated_validate_record",
                  "no_assessed_extent_in_source"],
  "identifiers": "provisional_local",
  "data_use_notice": "公式データの利用条件は確認中です。ローカルでの検証に限ります（一般公開の承認はありません）。",
  "source_caution": "実際の津波はこの津波浸水想定よりも大きい場合があります。",
  "region_state": "inside", "searched_sources": ["local-a40-2023-13"],
  "summary": {"sources_total": 1, "sources_with_zones": 1, "sources_with_unknown_or_boundary": 0},
  "sources": [{
    "source_id": "local-a40-2023-13", "organization": "東京都", "title": "津波浸水想定（東京都）",
    "category": "tsunami_inundation", "category_label": "津波浸水想定", "data_version": "2023", "spec_edition": "2.2",
    "attribution": {"text": "「国土数値情報（津波浸水想定データ）」（国土交通省）を加工して作成"},
    "source_caution": "実際の津波はこの津波浸水想定よりも大きい場合があります。",
    "data_use": {"scope": "local_verification_only", "usage_terms": "review_required", "public_approval": "unconfirmed"},
    "service_region_relation": "inside", "assessed_extent_relation": "unknown",
    "zones": [{"zone_ref": "loc-tz-…", "original_class": {"code": null, "label": "5m以上 ～ 10m未満"},
               "source_attribute": "A40_003"}],
    "boundary_contacts": [],
    "unknowns": [{"zone_ref": "loc-tz-…", "reason": "invalid_geometry", "invalid_kind": "ring_self_intersection",
                  "unknown_level": "L1"}]
  }],
  "results": [{"source": {"source_id": "local-a40-2023-13", "organization": "東京都", "title": "津波浸水想定（東京都）",
                          "data_version": "2023"},
               "feature_ref": "loc-tz-…", "original_class": {"code": null, "label": "5m以上 ～ 10m未満"},
               "source_attribute": "A40_003"}]
}
```

| `status` | 条件 | 付く情報 |
|---|---|---|
| `available` | 区域（`zones`）が1件以上 | `results` に全ソースの全区域。`unknowns`・`boundary_contacts` もそのまま残す |
| `unknown` | 区域がなく、判定保留・境界上・対象地域の境界（10m）のいずれか | `results: null`、`reasons`（`pending_geometry_zone` / `zone_boundary_contact` / `service_region_boundary`） |
| `no_match` | 対象地域の内側で、登録ソースのいずれにも該当なし | `results: []`、`scope_notice`（「津波の影響がないことを意味しません」＋原典の注意書き） |
| `not_available` | 対象地域の外、または津波Providerを接続していない | `reason: outside_service_region`（接続していない場合は既定の未接続セクション） |
| `error` | 列挙が500件を超えた（`tsunami_response_limit_exceeded`）、Engineの失敗・例外（`provider_failed`） | 一部だけを返さない。他のセクション（住所・標高・洪水）は影響を受けない |

- `original_class.code` は `null`（A40にコードはない）。`label` が原典の文字列。
- `zone_ref`（`loc-tz-`）は原典ZIPのSHA-256・メンバー・Feature番号・構成番号から作る（衝突しない。洪水の `loc-zn-` と別の領域）。内部の追跡は `python -m hererisk.tsunami trace`（応答には出さない）。
- 位置を含むリクエストはログに残さない（Location API 第7章のまま）。

## 5. 登録・索引

- 登録: 地域ファイルの `tsunami_sources`（`hererisk.tsunami.registry`）。`source_id`・`organization`・`title`・`format: ksj-a40-geojson`・`data_year`・`prefecture_code`・`service_region.prefecture_codes`・`files[{path, ledger_entry}]`。都道府県ごとのコードはなく、全国はデータと登録の追加で対応する。
- 索引: `python -m hererisk.tsunami build`（`hererisk-tsunami-index-v0.1`、SQLite）。原典ZIPのSHA-256（取得元台帳の取得記録との一致も記録）、製品仕様書の版、登録の写し、検証器の版、構成ごとの有効性・理由、原典の属性、WKB。一時ファイルに書き、完了してから置き換える（`meta.status: complete`）。**公開用のRegistry・Data Publishの公開実体ではない**（ローカル検証の成果物）。
- Providerの起動時に、登録・原典ZIP・N03のSHA-256・`status` を照合し、違えば起動しない。

## 6. 公開制限と未決定事項（OWNER判断）

| No | 事項 |
|---|---|
| TU-1 | 利用条件（`review_required`）: 都道府県ごとの利用条件、API提供の扱い（利用規約に名指しの記載なし）、メタデータの「国土情報利用約款」と現行の利用規約の表記の不一致 |
| TU-2 | 出典・加工表示の文言（洪水の OI-10 と同じ） |
| TU-3 | 一般公開に必要な承認（本実装・テストの成功は承認ではない） |
| TU-4 | 対象地域の登録: 東京都全域を登録すると、区部・多摩では常に `no_match`（注記つき）になる。島しょ部だけを対象にするか、データの収録範囲を利用者にどう示すか |
| TU-5 | 無効な76構成（頂点の自己接触）を判定保留のままにするか（洪水と同じ扱いにするか。参考解析は対象外） |
| TU-6 | 過年度データとの関係（データページ「過年度整備分データと合わせてご利用ください」「重複する箇所は最新年度」）。本実装は登録したファイルだけを検索し、年度の選択・統合をしない |

## 7. 検証結果（Phase 4-M、東京都 `A40-23_13_GML.zip`、SHA-256 `b8e24973…dc5c`、取得元台帳の記録と一致）

### 7.1 読込み・索引

| 項目 | 結果 |
|---|---|
| Feature / 構成 / 穴 | 33,124 / 33,124（すべてPolygon）/ 90（Phase 2-C.6 と一致） |
| 有効性（共通 `validity`） | `valid` 33,048、`invalid_geometry` 76（全件 GEOS `Ring Self-intersection`）、`feature_invalid_component` 0 |
| 76件の照合 | Phase 2-C.6 の「原典の異常 76件」と一致。**単位**: A40東京都は全FeatureがPolygon（1構成）のため、Feature単位＝構成単位。区分別の内訳（「～0.3m未満」9、「0.5m以上 ～ 1m未満」7、「1m以上 ～ 3m未満」16、「3m以上 ～ 5m未満」18、「5m以上 ～ 10m未満」15、「10m以上 ～ 20m未満」11）も一致 |
| 浸水深の区分 | 8区分・件数が Phase 2-C.3 / 2-C.6 と一致。原典の文字列のまま |
| 索引 | 15.7MB、作成約1秒 |

### 7.2 独立検証（`python -m hererisk.tsunami verify`、共通Engine・shapelyを使わない。[集計](../research/tsunami-a40-v0.1/tokyo-a40-verify-summary.json)）

| 項目 | 結果 |
|---|---|
| Feature数（GML と索引） | 一致（33,124） |
| FID と GML の `gml:id` | 33,124件一致 |
| 属性（都道府県名・コード・浸水深の区分、文字列の完全一致） | 33,124件一致 |
| 形状（環・頂点の数と順序、索引の座標を8桁に四捨五入して GML と比較） | 33,124構成一致 |
| 形状不整合の分類（整数座標での厳密な線分検査） | 33,124構成で索引の分類と一致。無効76件はすべて環の自己接触（頂点の重複） |
| 地点（9,366点、うち対象地域内9,297点: 頂点3,015、辺の両側6,042、穴の辺の両側102、保留の外接矩形の中心・角138） | `TsunamiProvider.lookup` と偶奇判定（穴を含む）・境界距離の期待が全点一致。頂点はすべて `boundary_contacts`。厳密比較: 内側4,750、外側（同じ0.01度の格子の候補）5,427,323、保留864。境界から2×10⁻⁸度以内の6,397件は内外を厳密に比較しない（未検証） |
| 複数区域の重なり | 実データの検査点では0件（重なりは合成Fixtureで確認） |

未検証: 3つ以上の環の接触の連鎖による内部の非連結、境界から2×10⁻⁸度以内の内外、属性の意味（製品仕様書の文言以上のこと）。

### 7.3 メモリ・時間（Mac上の Docker、aarch64、メモリ上限1GBのコンテナ、別プロセスで計測。[集計](../research/tsunami-a40-v0.1/tokyo-a40-measure-summary.json)）

| 構成 | 起動 | ピークRSS | 検索（津波の点2,000）中央値 / p95 |
|---|---|---|---|
| 津波Providerだけ | 1.5秒 | 205MB | 0.015ms / 0.021ms |
| 洪水Providerだけ | 3.5秒 | 546MB | — |
| 洪水＋津波 | 4.6秒 | 647MB | 0.035ms / 0.042ms（両方の合計） |
| Location API全体（住所＋洪水＋津波、`build_server`） | 6.3秒 | 818MB | 0.61ms / 0.92ms（1リクエスト全体） |

- 1GBの上限で起動の失敗はなかった。余裕は約200MB。津波Providerの増分は約100MB（N03の対象地域の結合を含む）。データを減らしていない。
- 既定の `location-api`（住所＋洪水）は津波を接続しない（変更なし）。
- 未測定: VPS（x86_64）、同時アクセス、全国規模の索引。

### 7.4 洪水の回帰

| 項目 | 結果 |
|---|---|
| `diag-api-verify`・`shadow-verify`（601地点・2,113組） | `candidate_inside` 118・`candidate_outside` 355・`undetermined` 1,640、ケースA 15組・B 521組すべて `undetermined`、正式判定601地点一致（変更なし） |
| 津波の接続あり・なし（601地点、`evaluated_at` を除く） | `hazards.flood`・`address`・`elevation` が全地点一致。津波なしは既存の応答と全地点一致（津波は `not_available`） |
| 津波の失敗 | 津波セクションだけ `error`（`provider_failed`）。他のセクションは変わらない（合成テスト） |
