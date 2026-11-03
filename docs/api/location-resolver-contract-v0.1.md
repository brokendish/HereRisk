# Location Resolver / Source Resolver / Regional Index Loader 契約 v0.1（案、Phase 4-N.1）

- 状態: **契約案（OWNERレビュー待ち）・未実装**。Python内部の契約で、HTTP APIは新設しない（必要になった段階で検討）。Location API の応答契約は変えない。
- 作成: 2026-11-03（Claude）。基準コミット `4519f1a017c9a4033af7ccdc4a772d316ac4ab85`
- 設計: [全国対応の現在地判定・地域別データ参照基盤 設計 v0.1](../architecture/nationwide-location-index-design-v0.1.md)
- 関連: [Location API v0.1](location-api-v0.1.md)、[Polygon Engine 共通契約 v0.2](polygon-engine-contract-v0.2.md)、[Dataset Registry](../architecture/dataset-registry-v0.1.md) 第6章、[Data Publish](../architecture/data-publish-v0.1.md) 第7・10章
- フィールド名・型は**PROVISIONAL**（例として示す）。確定するのは責務・状態・規則。

## 1. 共通の規則

- 座標は経度 `x`・緯度 `y`（GeoJSONの順）、原典の CRS（JGD2011）のまま。変換・丸めをしない。入力の検証（有限・範囲）は Location API の `parse_point` を通った値だけを受ける。
- どの層も「安全」「区域外」「該当なし」を返さない。判定できないことは、判定できないと返す（`failed`・`complete: false`）。
- 不完全な結果を完全な結果として返さない。上限・失敗では一部のリストを返さない。
- 例外の文字列・パス・座標を外へ出さない。位置をログに残さない。
- 依存の向き: Hazard Provider → Source Resolver → Location Resolver、Hazard Provider → Regional Index Loader → Polygon Engine。**Location Resolver・Source Resolver・Loader はハザードのパッケージ（`hererisk.flood` 等）をimportしない。Polygon Engine はこの3つをimportしない。**

## 2. Location Resolver

### 2.1 責務

地点と行政区域（国土数値情報 N03）の関係を返す。住所の文字列・ソースの選択・ハザードの判定は行わない。

### 2.2 入出力（PROVISIONAL）

```python
resolver = LocationResolver(admin_index)          # 起動時。N03の索引（検証済み・complete）を開く。失敗は例外（起動しない）
loc = resolver.resolve(lat, lon)                   # -> ResolvedLocation
rel = resolver.region_relation(loc, {"13", "14"})  # -> "inside" | "boundary" | None
```

```json
{
  "status": "near_boundary",
  "prefectures": [{"code": "13", "relation": "boundary"}, {"code": "14", "relation": "boundary"}],
  "municipalities": [{"code": "13209", "contains_point": true}, {"code": "14137", "contains_point": false}],
  "tolerance_m": 10.0,
  "coverage": "partial",
  "source": {"dataset": "N03", "files": [{"prefecture_code": "13", "file": "N03-20260101_13.geojson",
             "reference_date": "2026-01-01"}]}
}
```

### 2.3 状態

| `status` | 条件 | `prefectures` |
|---|---|---|
| `inside` | 1つの市区町村の内側で、どの市区町村の境界からも許容距離（10m）より遠い | 1件、`relation: inside` |
| `near_boundary` | 許容距離の中に市区町村の境界がある（同じ県の市区町村の境界・県境・海岸） | 許容距離の中にある全都道府県。各県の `relation` は、その県の外縁から10m以内なら `boundary`、そうでなければ `inside`。**1つに確定しない** |
| `outside_admin_area` | `coverage: national`（全国のN03を登録）で、どの区域からも許容距離より遠い（海上など） | なし |
| `outside_registered_area` | `coverage: partial` で、登録した区域のどれからも許容距離より遠い。海か未登録の県かを区別できない | なし |
| `failed` | リクエスト時の読込み失敗・上限 | なし（`complete: false`） |

- `coverage`: Resolverに登録したN03が47都道府県すべてなら `national`、そうでなければ `partial`。
- 所属未定地（`N03_007` が `xx000`）は、そのコードを `unassigned: true` として返し、市区町村名を付けない（住所Providerの現在の扱い: 都道府県までの精度、`municipality_unassigned_in_source`）。
- 判定はGEOS（`contains`・`dwithin`）で行う。N03のPolygonは修復・簡略化しない。

### 2.4 `region_relation(loc, prefecture_set)`

ソースの対象地域（都道府県の集合の和）に対する関係。現在の `_Region.relation`（洪水・津波）と同じ規則:

- 集合のどの県からも許容距離より遠い → `None`（検索しない）
- 集合の和の内側にあり、和の外縁から許容距離より遠い → `inside`（集合の内部の県境は境界ではない）
- それ以外 → `boundary`

全体の結合形状を常駐させない。地点の周り（許容距離の外接矩形）にある、集合に属する市区町村の形状だけで局所的に求める（局所の和の外縁＝全体の和の外縁、の範囲で同値。4-N.2 で全テスト地点の一致を確認する）。

## 3. Source Resolver

### 3.1 責務

`ResolvedLocation` と登録情報から、ハザードごとに検索すべきソースを選ぶ。Polygonの判定・索引の読込みはしない。原典の評価範囲を推定しない。

### 3.2 入出力（PROVISIONAL）

```python
selection = source_resolver.select("tsunami", loc)    # -> SourceSelection
```

```json
{
  "hazard": "tsunami",
  "complete": true,
  "sources": [{"source_id": "local-a40-2023-13", "service_region_relation": "inside",
               "index": {"format": "hererisk-tsunami-index-v0.2", "generation": "…", "sha256": "…"}}],
  "missing": [{"prefecture_code": "14", "reason": "no_source_registered"}],
  "location_status": "near_boundary"
}
```

### 3.3 規則

| 規則 | 内容 |
|---|---|
| SR-1 | 候補の都道府県（`prefectures`）のいずれかを対象地域に含むソースをすべて選ぶ。`region_relation` が `None` のソースは選ばない |
| SR-2 | 複数の都道府県を対象とするソースは1件として選ぶ（重複させない）。関係は集合の和に対して求める（2.4節） |
| SR-3 | 候補の都道府県のうち、そのハザードのソースが1件も登録されていない県を `missing` に入れる |
| SR-4 | `location_status` が `failed` なら `complete: false`、`sources: null`。Providerは `error` とする |
| SR-5 | `outside_admin_area` / `outside_registered_area` なら `sources: []`、`complete: true`。Providerは現状どおり `not_available`（`outside_service_region`）。区域外・安全と表現しない |
| SR-6 | 選択は登録順（ソースの登録順）。優先順位・統合・代表を作らない（DP-11） |
| SR-7 | 登録の正本は当面、地域ファイルの `flood_sources`・`tsunami_sources`。Dataset Registry の公開済みエントリへ移すときも、この契約の出力は変えない |

Providerの対応（Location API の既存の状態を変えない）:

| 選択の結果 | 現在の応答への対応 |
|---|---|
| ソースなし（SR-5） | `not_available`（`outside_service_region`） |
| `service_region_relation` に `boundary` がある | 区域がなければ `unknown`（`service_region_boundary`）。現状と同じ |
| `missing` がある | 現在の規則では、県境の地点は対象地域の `boundary` になり `unknown` になる。`missing` を応答に出すかは O-6（設計 第12章） |
| `complete: false` | `error` |

## 4. Regional Index Loader

### 4.1 責務

Source Resolverが選んだソースの索引だけを開き、地点の候補の構成を返す。内外の判定・属性の解釈はしない。

### 4.2 入出力（PROVISIONAL）

```python
loader = RegionalIndexLoader(limits)                      # 上限: 開く索引の数、形状キャッシュの頂点数／バイト数、SQLiteのキャッシュ
handle = loader.open(index_ref)                           # Registryが指す現行世代。形式・status・SHA-256を照合。失敗は LoaderError
cands = handle.candidates(x, y)                           # -> list[relation.Candidate]（外接矩形が地点を含む構成）。失敗は LoaderError
attrs = handle.attributes(feature_refs)                   # 該当した構成の原典属性（不透明なまま）
loader.release(index_ref)                                 # 参照が0になったら閉じる
```

### 4.3 規則

| 規則 | 内容 |
|---|---|
| IL-1 | 候補はR-treeで取る。R-treeの値は32ビット浮動小数で外側に丸められるため、候補は真の候補を必ず含む（取りこぼさない）。余分な候補は Polygon Engine の判定で落ちる |
| IL-2 | 判定保留（無効）の構成の外接矩形の判定は、本表の倍精度の外接矩形（または形状の `bounds`）で行う。R-treeの丸めた値で判定しない |
| IL-3 | 候補は `relation.Candidate`（`source_id`・`feature_ref`・WKBまたは形状・`validity`・`detail`）で返す。Providerは `relation.ComponentIndex(cands).search(x, y)` で判定する。Polygon Engine は変えない |
| IL-4 | 形状キャッシュは上限つき（LRU）。上限を超える1件はキャッシュせずに返す。キャッシュの有無で結果を変えない |
| IL-5 | 索引がない・壊れている・世代が違う・`status` が `complete` でない → 開かない（`LoaderError`）。起動時なら起動しない。リクエスト時ならそのセクションを `error` |
| IL-6 | 読込み中の失敗・上限超過は `LoaderError`。途中までの候補を返さない |
| IL-7 | 世代の切替は、新しい世代を開いて照合してから参照を差し替える。旧世代は参照が0になるまで閉じない（Publish 7.3節） |
| IL-8 | 同時実行: 接続はスレッドごと、または鍵つきで共有する（現在の洪水の `_Index` と同じ）。キャッシュは共有してよい |
| IL-9 | 全件メモリロードへの退避をしない（メモリ不足を理由に方式を変えない） |

## 5. 試験項目（実装段階で作る）

| No | 項目 | 期待 |
|---|---|---|
| LR-1 | 都道府県の内側の地点 | `inside`、候補1県 |
| LR-2 | 同じ県の市区町村境界から5m | `near_boundary`、候補1県、県の `relation: inside` |
| LR-3 | 東京・神奈川の県境から5m（両側） | 候補2県、両方 `boundary`。1つに確定しない |
| LR-4 | 県境の継ぎ目（両県を対象とするソース） | `region_relation({13,14})` は `inside`（現在の `test_service_region_is_per_source` と同じ） |
| LR-5 | 海岸から5m・海上 | `near_boundary`（外縁）/ `outside_registered_area`（partial）・`outside_admin_area`（national） |
| LR-6 | 隣県のN03が未登録の県境 | `outside_registered_area` または `boundary`。「海」と言わない |
| LR-7 | 所属未定地 | `unassigned: true`、市区町村名なし |
| LR-8 | 読込み失敗の注入 | `failed`、Source Resolverは `complete: false`、セクションは `error` |
| LR-9 | 既存との一致 | `locate()`（住所）・`_Region.relation`（洪水・津波）と全テスト地点で一致 |
| SR-a | 県境で両県のソースを選ぶ | 両方選ぶ。重複しない |
| SR-b | 候補の県にソースが未登録 | `missing` に入る。`no_match` にしない |
| IL-a | R-treeの丸めの境界（外接矩形の辺・角ちょうどの地点） | 全件メモリの `ComponentIndex` と同じ結果 |
| IL-b | 形状キャッシュの上限を極端に小さくした場合 | 結果が同じ |
| IL-c | 索引なし・壊れた索引・別世代 | 開かない |
