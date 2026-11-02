# Polygon Engine 共通契約 v0.2（Phase 4-I）

- 状態: **責務・状態・識別子・エラー・世代・精度の扱いを確定**（[ADR-002](../decisions/2026-11-03-polygon-engine-responsibility.md)、2026-11-03 ACCEPTED）。**Engine本体（`hererisk.common.polygon`）は未実装**で、本書は共通Engineの内部の将来契約である。既存の Flood Provider・`/api/v1/location`・`/api/v1/diagnostics/flood` に、本書の `geometry_state`・`analysis_state` は追加しない。
- 作成: 2026-11-03（Claude）。基準コミット `43ba17003a7339cf616f5c2cebbd1487b1093c4b`
- 前の版: [契約案 v0.1](polygon-engine-contract-draft-v0.1.md)（Phase 4-H・4-H.1、記録として残す）。v0.1 からの変更は第0章
- 関連: [設計レビュー](../architecture/polygon-engine-review-v0.1.md)、[移行計画](../architecture/polygon-engine-migration-plan-v0.1.md)、[Polygon判定理由カタログ v0.2](polygon-reason-catalog-v0.2.md)、[洪水の参考解析API](flood-diagnostic-api-v0.1.md)、[共通API契約](common-contract-v0.1.md)

## 0. 確定度

| 区分 | 事項 | 本書の章 |
|---|---|---|
| **確定**（ADR-002） | 共通Engineの責務と、Providerの責務の分け方 | 第1章 |
| **確定** | `geometry_state` と `analysis_state` を独立した情報にし、排他的に分類しない。値の列挙 | 3.3・3.4節 |
| **確定** | 構成の評価の状態（`evaluated` / `pending_geometry`）と関係（`inside` / `on_boundary`）。外側は列挙しない。判定保留を外側にしない | 3.1節 |
| **確定** | 呼び出し全体の処理の状態（`complete` / `limit_exceeded` / `timeout` / `busy` / `failed`）と、一部だけを返さない規則 | 第4章 |
| **確定** | 識別子（`source_id`・`feature_ref` をそのまま運ぶ。作り替えない） | 第5章 |
| **確定** | 世代の照合（`derived_from`）と、正式索引・診断索引の組での切替 | 第6章 |
| **確定** | 座標・距離の前提（変換しない、経度・緯度の平面の位相、局所の平面近似、最大半径1,000m）と、精度プロファイルを索引の世代の属性として固定すること | 第7章 |
| **確定・実装済み**（Phase 4-I） | 理由コードの `cause`（と定義上確かな場合の `background_cause`） | 3.6節、[カタログ v0.2](polygon-reason-catalog-v0.2.md) |
| **案のまま** | 入出力のJSONの具体的なフィールド名・型（例として示す） | 第2・3章の例 |
| **案のまま** | 問題箇所の正当性 `legality` を判定に使うか（U-12） | 3.5節 |
| **案のまま** | 全体の読み `far_reading` の採用（U-11）。記録することだけを確定 | 3.3節 |
| **未決定**（OWNER判断） | 精度プロファイル（整数・8桁）の採用、WGS84 と JGD2011 の扱い、局所輪郭法の正本、次のハザード、索引の世代管理（Data Publish）、共通の既定の採用方針 | ADR-002「この決定に含まれないこと」 |
| **未検証** | 自己交差・同一直線上の重なり（洪水の実データで未観測）、他のハザード・他の地域での局所輪郭法の精度 | 設計レビュー 4.2節 |

v0.1（案）からの変更:

- 第0章（確定度）を追加した。
- 3.6節の `cause` を実装済みにした（値・対応はカタログ v0.2 が正本）。
- 第7章の精度の扱いを確定事項にした（新しい精度プロファイルの採用は未決定のまま）。
- 試験項目（第10章）は v0.1 と同じ（G-1〜G-31）。

## 1. 位置付け

| 層 | 契約 | 利用者 |
|---|---|---|
| **Polygon Engine（本書）** | Python内部の入出力。幾何の事実と処理の状態だけ | ハザードのProvider・索引の構築 |
| ハザードのProvider | 状態の対応・属性の提示・採用方針・文言 | Location API |
| 公開API（Location API・参考解析API） | 利用者に返すJSON。既存の契約のまま | 利用者 |

- **Engineの出力をそのまま公開APIで返さない。** Providerが、自分の契約の形に変換する（Engineの `relation` を `no_match` などに読み替えるのはProviderの責務）。
- Engineは「何が分かったか」と「何が分からなかったか」を返す。「安全」「該当しない」「候補として採用」は返さない。

## 2. 入力

```json
{
  "point": {"lat": 35.681236, "lon": 139.767125},
  "dataset": {
    "hazard_type": "flood",
    "source_id": "local-a31a-2025-13",
    "official_index": {"format": "hererisk-flood-index-v0.1", "generation": "…"},
    "diag_index": {"format": "hererisk-flood-diag-v0.1", "generation": "…"}
  },
  "mode": "official",
  "options": {"radii_m": [5, 10, 25, 50, 100], "max_features": 32, "budget_s": 1.0}
}
```

- `point`: 十進の緯度・経度。検証は公開APIの入力検証（`parse_point`）を通った値だけを受ける。Engineは値を丸め・入れ替え・補正しない。
- `dataset`: Providerが開いた索引の識別。世代の照合は**開くとき**（起動時）に済ませる（第6章）。
- `mode`: `official`（使える形状だけで関係を求める）／`diagnostic`（判定保留の構成の局所の読み）。1回の呼び出しで両方を混ぜない。
- `diagnostic` の対象は、同じ地点の `official` の結果の `pending` に入った `feature_ref` だけ（呼び出し側が渡す）。Engineは索引から対象を追加しない。

## 3. 出力（構成ごと）

```json
{
  "engine_version": "polygon-engine-v0.1",
  "mode": "official",
  "complete": true,
  "status": "complete",
  "features": [
    {
      "feature_ref": "loc-zn-…",
      "source_id": "local-a31a-2025-13",
      "evaluation": "evaluated",
      "relation": "inside",
      "geometry": {"validity": "valid"},
      "attributes": {"opaque": true}
    },
    {
      "feature_ref": "loc-zn-…",
      "source_id": "local-a31a-2025-13",
      "evaluation": "pending_geometry",
      "relation": null,
      "geometry": {"validity": "invalid_geometry", "validator": "GEOS 3.13.1 is_valid", "detail": "Ring Self-intersection"}
    }
  ],
  "provenance": {"official_index": {"format": "…", "built_at": "…", "source_sha256": {"…": "…"}},
                 "precision_profile": "float-json-v0", "crs": "EPSG:6668", "topology_plane": "lon_lat"}
}
```

### 3.1 構成の評価の状態（`evaluation`）と関係（`relation`）

| `evaluation` | `relation` | 意味 |
|---|---|---|
| `evaluated` | `inside` | 使える形状の内部（GEOS `contains`） |
| `evaluated` | `on_boundary` | 使える形状の境界線上（`intersects` かつ `contains` でない）。**データの形状の上の事実**で、測位誤差は含まない |
| `pending_geometry` | `null` | 形状が無効（`invalid_geometry`）、またはFeature内の重なりに関わる（`feature_invalid_component`）。外接矩形（境界を含む）に地点が入る |

- `outside` の構成は**列挙しない**（外接矩形に入らない構成は数えきれないため）。外側であることは、その構成が `features` にないことで表す。Providerは、それを「該当なし」と読むか（評価済みの範囲がある場合）、「登録された区域に該当しない」と読むか（A31a）を決める。
- 判定保留（`pending_geometry`）を外側として扱ってはならない。Providerは必ず `unknown` 相当の情報として返す。

### 3.2 参考の読み（`mode: diagnostic`）

```json
{
  "feature_ref": "loc-zn-…",
  "reading": {
    "outcome": "inside",
    "method": "local-contour-winding-v1",
    "decided_at_m": 25,
    "stopped_at_m": 25,
    "evidence": {"edge_m": 19.0, "local_side": "inside", "winding": 1, "parity_inside": true,
                 "rings": 3, "holes_in_winding": true, "defect_within_max_m": null, "defect_kind": null}
  }
}
```

| `outcome` | 意味 |
|---|---|
| `inside` / `outside` | 局所の読みと全輪郭の回転数が一致した（偶奇の一致・問題箇所の有無は `evidence` に事実として入れる。採用するかは分類の層が決める） |
| `on_boundary` | 地点が輪郭上（1mm未満） |
| `defect_within_radius` | 判定に使う半径の中に問題箇所がある |
| `no_boundary_within_max_radius` | 最大半径の中に輪郭がない |
| `ambiguous_nearest` | 最寄りの輪郭が複数あり、側が食い違う |
| `orientation_unknown` | 面積0の環で向きが決まらない |
| `defect_location_unknown` | 無効だが問題箇所の位置を特定できない |
| `inconsistent_winding` | 局所の読みと回転数が一致しない |

- Engineは `candidate` / `undetermined` / `rejected` を返さない。分類はハザードの採用方針（洪水では `flood.adoption`、`flood-diagnosis-adoption-v1`）が `reading` を入力にして行う。
- 理由コード（`hererisk.common.polygon_reasons`）への対応は、採用方針の層で付ける。Engineの `outcome` は理由コードではない（同じ名前を持つものはあるが、意味の正本はカタログ）。

### 3.3 2つの独立した情報（Phase 4-H.1）

参考の読みの記録は、次の2つを**別々のフィールド**に持つ。どちらか一方で他方を代用しない。排他的な分類にしない。

```json
{
  "feature_ref": "loc-zn-…",
  "geometry_state": {
    "validity": "invalid_geometry",
    "validator": "GEOS 3.13.1 is_valid",
    "detail": "Ring Self-intersection",
    "defects": {"count": 13, "kinds": {"touch": 13}, "located": true},
    "zero_area_rings": 0
  },
  "analysis_state": {
    "kind": "search_limit",
    "outcome": "no_boundary_within_max_radius",
    "method": "local-contour-winding-v1",
    "limit": {"type": "search_radius", "radii_m": [5, 10, 25, 50, 100], "max_radius_m": 100,
              "boundary_found_within_m": null},
    "far_reading": {"winding": 1, "crossings": 3, "parity_inside": true, "zero_area_rings": false,
                    "defects_unlocated": false, "reading": "inside", "adopted": false}
  }
}
```

| フィールド | 内容 | 地点に依存 |
|---|---|---|
| `geometry_state.validity` | `valid` / `invalid_geometry` / `feature_invalid_component` / `unverified` | しない |
| `geometry_state.defects` | 問題箇所の数・種類（touch / touch_on_edge / overlap / crossing）・位置の特定の可否。**正当な接触を含みうる**（3.5節） | しない |
| `analysis_state.kind` | 3.4節の区分 | する |
| `analysis_state.outcome` | 3.2節の局所の結果 | する |
| `analysis_state.limit` | 上限に達した場合、その種類と値（探索半径・件数・時間）。上限に達していなければ `null` | する |
| `analysis_state.far_reading` | 全体のリング構造による読み（回転数・交差数・偶奇・不確定の条件）。**記録のみで、採用の判断はしない**（`adopted` は分類の層が決める） | する |

### 3.4 探索・解析状態の区分（`analysis_state.kind`）

| `kind` | 対応する `outcome` | 意味 |
|---|---|---|
| `decided` | `inside` / `outside` | 指定範囲で必要な輪郭を確認し、局所と全体の読みが一致した |
| `search_limit` | `no_boundary_within_max_radius` | 最大探索半径まで調べたが、判定に必要な境界がなかった。**原典の品質の評価ではない** |
| `point_on_boundary` | `on_boundary` | 地点が輪郭上 |
| `defect_proximity` | `defect_within_radius`（および決定後の最大半径内の問題箇所） | 判定に使う範囲に、輪郭の接点・交点がある |
| `ambiguous_candidates` | `ambiguous_nearest` | 最寄りの境界を区別できない |
| `reading_disagreement` | `inconsistent_winding`（および偶奇の不一致） | 局所と全体、または回転数と偶奇の読みが一致しない |
| `method_not_applicable` | `orientation_unknown` / `defect_location_unknown`（および構成どうしの不整合） | 方式の適用条件を満たさない |
| `resource_limit` | — | 件数・時間・同時実行の上限（第4章） |

- `resource_limit` と `system_failure`（第4章）は呼び出し全体の状態で、構成ごとの `analysis_state` とは分ける。
- 有効なPolygon（`geometry_state.validity: valid`）は正式判定（3.1節）で判定し、`mode: diagnostic` の対象にしない。検証の目的で有効なPolygonに局所の方式を当てる場合は、結果を正式判定の代わりにしない。

### 3.5 問題箇所と正当な接触

- `defects` は「隣り合わない線分どうしの交点・接点」であり、原典の不整合と、有効な形の正当な接触（穴が外周に1点で接する等）の両方を含みうる。
- 契約案: 問題箇所ごとに `same_ring`（同じ環どうしか）と `legality`（`unknown` / `legal_contact` / `invalidity`）を持つ。現行の診断索引は `same_ring` だけを持ち、`legality` は判定していない（`unknown`）。
- `legality` を判定に使うか（正当な接触を `defect_proximity` から外すか）は未決定（設計レビュー U-12）。

### 3.6 理由コードの原因の区分（`cause`、Phase 4-I で実装）

既存の理由コード・`category`・`concept`・`priority`・`scope` は変えない。各コードに `cause` を追加した（`hererisk.common.polygon_reasons`、カタログ v0.2）。`background_cause` は、コードの定義上確かな場合だけ持ち（`feature_level_invalidity_not_analyzed`・`defect_location_unknown` → `source_geometry`）、記録ごとに推測して付けない。

| `cause` | 意味 | データ品質レポートで提供元の問題として数えるか |
|---|---|---|
| `source_geometry` | 原典の形の事実（無効・問題箇所・面積0の環） | 数えうる（構成の単位） |
| `search_scope` | 探索半径などの探索条件 | 数えない |
| `analysis_method` | 解析方式の限界・適用条件 | 数えない |
| `point_position` | 地点と形の関係（境界上） | 数えない |
| `coverage` | 対象地域・登録範囲 | 数えない |
| `index_data` | HereRiskの索引・世代 | 数えない |
| `analysis_scope` | 診断の対象外 | 数えない |
| `processing` | 処理の上限・失敗 | 数えない |
| `result` | 結果（条件の成立） | — |

- 1つの記録に複数の理由がある場合、コードごとに `cause` を持つ。記録には `geometry_state`（背景）も残す。
- `cause: source_geometry` の理由を地点ごとに数えた件数は、原典の不整合の件数ではない。原典の不整合は `geometry_state` を構成の単位で数える（第6章の世代ごと）。

## 4. 処理の状態とエラー

構成の判定保留（幾何の事実）と、処理の失敗（Engineの状態）を分ける。

| `status`（呼び出し全体） | `complete` | `features` | 意味 |
|---|---|---|---|
| `complete` | true | 全件 | 評価を終えた（0件を含む） |
| `limit_exceeded` | false | `null` | 対象の構成の数が上限を超えた。**一部だけを返さない** |
| `timeout` | false | `null` | 時間の上限を超えた |
| `busy` | false | `null` | 同時実行の上限で待てなかった（診断） |
| `failed` | false | `null` | 索引の読取の失敗など。例外の内容・パスは外へ出さない |

- 呼び出しの前提を満たさない場合は、呼び出さない（Providerの責務）: 地点が対象地域の外（`outside_service_region`）、データが未登録、索引が未作成・不完全・別世代（起動しない）。これらを `features: []`（＝外側）にしてはならない。
- 失敗・時間切れを、外側・該当なしに変換しない。Providerは自分の `error` / `unknown` に対応させる。

## 5. 識別子・出典

| 項目 | 発行者 | Engineでの扱い |
|---|---|---|
| `source_id` | ハザードの登録（地域ファイル・将来はSource Catalog） | そのまま運ぶ。別ソースの構成を当てはめない |
| `feature_ref` | ハザードの索引の構築（洪水: `zone_ref`、構成Polygon単位、内容由来） | そのまま運ぶ。作り替えない。粒度は構成Polygon |
| `record_key`・`polygon_index` | 原典の位置（ZIP・メンバー・Feature番号・構成番号） | 索引に保持し、追跡に使う（洪水の `trace`） |
| `attributes` | 原典パーサー | 不透明なJSONとして運ぶ。中身を読まない |
| 出典・利用条件 | ハザードの登録・取得元台帳 | Engineは扱わない（Provider） |

- 1つの地点で、複数のソース・複数の構成を返す。順序は索引の順（ソースの登録順・`feature_ref` の順）で、優先順位・最大値・代表値を作らない（DP-11）。

## 6. 世代と整合性

| 項目 | 内容 |
|---|---|
| 正式索引のmeta | `format`・`built_at`・原典ファイルのSHA-256・登録の写し・制限事項・検証器の版 |
| 診断索引のmeta | `format`・`method`・`status: complete`（最後に書く）・`derived_from`（正式索引の `format`・`built_at`・原典SHA-256）・作成時の照合結果 |
| 開くときの照合 | 診断索引の `status`・形式・方式・`derived_from` が、開いている正式索引と一致すること。不一致なら開かない（Providerは起動しない） |
| 精度プロファイル | 索引の属性として記録する（洪水の現状: `float-json-v0` に相当。整数・8桁の `coord-precision-round8-v1` は未実装） |
| 切替 | 正式索引と診断索引は組で切り替える（片方だけの更新を禁止） |

## 7. 座標・距離・精度の前提

- 座標参照系: 原典の宣言（国土数値情報は JGD2011 `EPSG:6668`、経度・緯度の順）。Engineは変換しない。API入力（WGS84想定）との差は補正しない（未決定 ON-11）。
- 位相（内外・接触）: 経度・緯度の平面で判定する（GEOSと同じ）。
- 距離: 地点の緯度での局所の平面近似（`111,320 m/度`、経度方向は `cos(lat)` 倍）。半径は最大1,000m。単位はメートル。
- 境界上: 1mm（`ON_BOUNDARY_M`）。同点: 1μm（`TIE_M`）。いずれも近似の上の値で、測位の精度ではない。
- 頂点の精度: 原典の分解能は約10⁻⁹度（約0.1mm）。浮動小数で読むことによる誤差は、それより十分小さい。ただし、精度プロファイルを変えると判定が変わりうるため、索引の世代ごとに固定する。
- 対象地域: 日本の範囲（東経122〜154度、北緯20〜46度）。経度180度を超える辺を拒否する。

## 8. 正式判定と参考解釈の分離（Providerが守ること）

- 正式の結果（`mode: official`）と参考の読み（`mode: diagnostic`）を、同じ配列・同じフィールドに入れない。
- 参考の読みで、正式の状態（`unknown`）を変えない。
- 参考の読みを使うのは、正式の結果で `pending_geometry` になった構成だけ。
- 参考の読みを利用者に示す場合は、分類・理由コード・文言・`certainty: "diagnostic_only"` を付ける（洪水: 参考解析API v0.1）。

## 9. 洪水の既存実装との対応（変更しない）

| 本書 | 洪水の現状 |
|---|---|
| `mode: official` の `inside` / `on_boundary` / `pending_geometry` | `FloodProvider` の `zones` / `boundary_contacts` / `unknowns`（ソースごと） |
| `status: limit_exceeded` | `flood_response_limit_exceeded`（500件超で `error`） |
| `mode: diagnostic` の `reading` | `DiagIndex.analyze` の `local`（＋ `defect_within_max`） |
| 採用方針 | `flood.adoption.classify` |
| 処理の状態 | `flood_diagnostics` の `busy`・`limit_exceeded`・`timeout`・`failed` |

## 10. 合成Geometryの試験項目（共通Engine向け）

既存の洪水の合成データ（`tests/contract/test_flood_diag.py` の INVERTED・EIGHT・穴の接する正方形）に加え、次を用意する。各項目で、メモリ上の実装とSQLite上の実装の一致、GEOSの有効性の判定との一致を確認する。

| No | 形状・地点 | 期待 |
|---|---|---|
| G-1 | 正方形、内部・外部・辺上・頂点上 | inside / features にない / on_boundary / on_boundary |
| G-2 | 穴のある正方形、穴の中 | features にない（穴は外側） |
| G-3 | 穴が外周に1点で接する（有効） | valid |
| G-4 | 穴が外周に2点で接する（内部が非連結） | invalid_geometry、pending |
| G-5 | 蝶ネクタイ形（辺の交差） | invalid、defect `crossing` |
| G-6 | 頂点どうしの自己接触（反転した三角形） | invalid、defect `touch`。三角形の中は局所で outside |
| G-7 | 8の字（片側が逆向き） | 回転数が局所の読みと食い違う地点で `inconsistent_winding` |
| G-8 | 面積0の環 | `orientation_unknown` |
| G-9 | 連続する重複頂点 | 隣接する辺として扱い、問題箇所にしない |
| G-10 | スパイク（往復する辺） | **現状の扱いが未確認**（隣り合う辺は問題箇所の検出から除くため、`overlap` にならない可能性がある）。GEOSの判定と、問題箇所の有無・`defect_location_unknown` の扱いを確かめてから期待値を決める |
| G-11 | 同一直線上の重なり | defect `overlap` |
| G-12 | MultiPolygonの部分が重なる・辺を共有する | `feature_invalid_component` |
| G-13 | 入れ子の穴（穴の中の島が別Feature） | 各Featureを独立に評価 |
| G-14 | 最寄りの辺が2つ同距離で側が異なる | `ambiguous_nearest` |
| G-15 | 問題箇所がちょうど半径上 | 半径の内側として扱う（`<=`） |
| G-16 | 最大半径の中に輪郭がない大きな形状 | `no_boundary_within_max_radius` |
| G-17 | 北緯20度・46度、東経122度・154度付近の同じ形 | 距離の近似の誤差が契約の範囲内 |
| G-18 | 1m未満の小さな形状 | 内外・境界上が正しい |
| G-19 | 1地点に上限を超える構成 | `limit_exceeded`、一部を返さない |
| G-20 | 非有限値・経度180度を超える辺・閉じていない環 | 索引を作らない（例外） |
| G-21 | 同じ形の2つのFeature（A33型） | 2件とも独立に返す（統合しない） |

### 10.1 形状状態と探索状態を分ける試験項目（Phase 4-H.1）

有効なPolygonの正式判定（GEOS）と、無効なPolygonの参考解析を混同しないため、各項目に「正式」と「参考（無効の場合）」の期待を分けて書く。半径の列は現行の 5・10・25・50・100m とする。

| No | 形状・地点 | 正式判定（有効の場合） | 参考解析（無効の場合、または検証のための当て込み） | 期待する理由コードと `cause` |
|---|---|---|---|---|
| G-22 | 有効な巨大Polygon（一辺5km）の中央。100m以内に輪郭がない | `inside`（GEOS。半径に依存しない） | 検証の当て込み: `search_limit`、`far_reading` は `inside`。正式判定を置き換えない | 製品の理由コードなし |
| G-23 | 有効な細長いPolygon（幅300m・長さ5km）の中央。両側の平行線は150m先、5km先で閉じる | `inside` | 同じ形を自己接触で無効にした場合（端で1点の接触）: `search_limit`、`far_reading` は `inside`（採用しない） | 無効の場合 `no_local_boundary`（`search_scope`）。`geometry_state.validity: invalid_geometry` を別に持つ |
| G-24 | U字型（腕の幅40m、間隔60m）。腕の中・U字の切れ込みの中・底の近く | 腕の中 `inside`、切れ込み `outside` | 無効にした場合: 腕の中・切れ込みとも局所で `decided`（20〜30m以内に輪郭）。問題箇所が100m以内になければ `all_conditions_met` | 切れ込みの中で2つの腕から等距離・異なる側なら `ambiguous_nearest`（`analysis_method`） |
| G-25 | 外周と穴が3mで近接。外周と穴の間・穴の中 | 間 `inside`、穴 `outside` | 無効にした場合: 局所で `decided`（5mの半径で両方の輪郭が入り、最寄りの側が一致） | 穴が外周に2点で接する変形では `defect_within_decision_radius`（`source_geometry`） |
| G-26 | 最寄りの輪郭が100.5m（最大半径の直外）。比較として100.0m | どちらも正式判定は半径に依存しない | 100.5m: `search_limit`。100.0m: 100mで `decided`（距離 ≤ 半径） | 100.5m は `no_local_boundary`（`search_scope`）。境界値の扱いを固定する |
| G-27 | 無効Polygon（遠方500mに頂点の自己接触）。地点は輪郭から20m | — | `decided`、最大半径内に問題箇所なし → `all_conditions_met`（洪水の採用方針の場合） | `all_conditions_met`（`result`）。`geometry_state.validity: invalid_geometry` は残る |
| G-28 | 無効Polygon、局所範囲（100m）に輪郭がない | — | `search_limit`。`far_reading` を記録（採用しない） | `no_local_boundary`（`search_scope`）。**`source_geometry` として集計しない** |
| G-29 | 全体の回転数と局所の読みが矛盾（8の字の反転した部分の近く） | — | `reading_disagreement`（局所は内側、回転数は −1） | `local_far_disagree`（`analysis_method`）、偶奇の不一致があれば `even_odd_winding_disagree` も |
| G-30 | 有効なPolygonで、穴が外周に1点で接する点の5m以内 | `inside` または `outside`（GEOS） | 検証の当て込み: `defect_proximity`（正当な接触が問題箇所として記録される）。`legality: unknown` | 製品の理由コードなし。参考解析の文言で「不整合」と断定しないこと（設計レビュー 13.4節） |
| G-31 | 無効Polygonで、局所範囲に輪郭はなく、問題箇所の位置が特定できない | — | `method_not_applicable`（`defect_location_unknown`。現行は半径に関わらずこれを返す）。探索の上限を併記するかは未決定 | `defect_location_unknown`（`analysis_method`、背景 `source_geometry`） |

- いずれの項目も、メモリ上の実装とSQLite上の実装の一致を確認する。
- G-22・G-23・G-26 は、有効なPolygonで探索の上限が起きることを示し、`search_limit` を原典の品質の指標にしないことの回帰に使う。
- 現行の `analyze` は、問題箇所の位置が特定できない構成では、半径に関わらず `defect_location_unknown` を返す（`evaluate` の最初の確認）。G-31 の期待はこの現行の挙動に合わせる。
