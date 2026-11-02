# Polygon Engine 内部契約案 v0.1（Phase 4-H）

- 状態: **契約案（未承認・未実装）**。本書のJSONは設計例であり、確定したスキーマではない。既存の洪水の索引・Provider・`/api/v1/location`・`/api/v1/diagnostics/flood` の形は変えない。
- 作成: 2026-11-02（Claude）。基準コミット `c8845dabde601c41eede00355518802cc3ebf3f2`
- 関連: [設計レビュー](../architecture/polygon-engine-review-v0.1.md)、[移行計画](../architecture/polygon-engine-migration-plan-v0.1.md)、[Polygon判定理由の共通仕様](polygon-reason-catalog-v0.1.md)、[洪水の参考解析API](flood-diagnostic-api-v0.1.md)、[共通API契約](common-contract-v0.1.md)

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
