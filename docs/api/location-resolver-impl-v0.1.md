# Location Resolver 実装仕様 v0.1（Phase 4-N.2）

- 状態: **実装済み・製品から未使用**。`hererisk.location.admin_index`（N03索引の構築）・`hererisk.location.resolver`（`LocationResolver`）。住所・洪水・津波Provider、Location API からは呼び出していない（テストで確認）。
- 作成: 2026-11-03（Claude）。基準コミット `cf0eea1d4c0dbd1a706c779ce1f35a0f77291432`
- 契約: [Location Resolver / Source Resolver / Regional Index Loader 契約 v0.1](location-resolver-contract-v0.1.md) 第2章。設計: [全国対応の設計 v0.1](../architecture/nationwide-location-index-design-v0.1.md)
- 計測の記録: [resolver-4n2-summary.json](../research/nationwide-v0.1/resolver-4n2-summary.json)（MiB は 2²⁰ バイト）

## 1. 責務

地点と、登録したN03（国土数値情報 行政区域）の関係だけを返す。住所の文字列、ソースの選択、ハザードの判定はしない。ハザードのパッケージ・Polygon Engine に依存しない（テストで確認）。

## 2. N03索引（`hererisk-admin-index-v0.1`）

```sh
python -m hererisk.location.admin_index build   --regions <regions.json> --output <admin.sqlite>
python -m hererisk.location.admin_index resolve --index <admin.sqlite> --regions <regions.json> --point 35.68,139.76 --region 13 --region 13,14
```

| 表 | 内容 |
|---|---|
| `areas` | N03のFeature 1件につき1行: `prefecture_code`・`municipality_code`（`N03_007`）・`feature_index`・`unassigned`（`xx000`）・都道府県名・市区町村名（`N03_003`＋`N03_004`＋`N03_005`）・倍精度の外接矩形・頂点数・**原典のGeometry（WKB）** |
| `area_rtree` | SQLite R-tree（`id`・外接矩形）。32ビット浮動小数で外側に丸められる |
| `meta` | 形式・作成時刻・登録した都道府県（順序つき）・ファイルごとの名前・SHA-256・基準日・Feature数・`coverage`（47都道府県すべてなら `national`、それ以外 `partial`）・最大の頂点数・最大のWKB・`status: complete` |

- 読込みと属性の検査は既存の `n03_municipality._read_file` をそのまま使う（ZIP内のGeoJSONが1つ、`N03_007` が5桁でファイルの都道府県のもの、Polygon / MultiPolygon）。
- **市区町村ごとの結合をしない**（原典のFeatureのまま保存）。修復・簡略化をしない。
- 一時ファイルに書き、完了してから置き換える。失敗しても既存の索引は変わらない（テストで確認）。
- ローカル検証の成果物。公開Registry・Data Publishの公開実体ではない。

## 3. Python API

```python
res = LocationResolver(index, regions_file=None, connections=4, acquire_wait_s=0.5, verify_sources=True)
loc = res.resolve(lat, lon)              # -> ResolvedLocation（不正な座標は ResolverInputError）
res.region_relation(loc, {"13", "14"})   # -> "inside" | "boundary" | None（failed の loc は ValueError、混雑は ResolverBusy）
loc.view()                               # -> 公開用の辞書（候補の形状を含まない）
res.close()
```

- 起動時に、索引の形式・`status`、`regions_file` を渡した場合は登録の都道府県（順序つき）・ファイル名・N03 ZIPのSHA-256（`verify_sources`）を照合する。違えば `AdminIndexError`（起動しない）。
- 起動時に読むのは meta だけ。形状は読まない。

出力例（東京駅、東京＋神奈川の索引）:

```json
{"status": "inside", "complete": true,
 "prefectures": [{"code": "13", "relation": "inside"}],
 "municipalities": [{"code": "13101", "prefecture_code": "13", "unassigned": false, "name": "千代田区",
                     "prefecture": "東京都", "contains_point": true}],
 "tolerance_m": 10.0, "coverage": "partial",
 "source": {"dataset": "N03", "index_format": "hererisk-admin-index-v0.1", "built_at": "…",
            "files": [{"prefecture_code": "13", "file": "N03-20260101_13.geojson", "reference_date": "2026-01-01"}, …]}}
```

## 4. 判定の方法

1. 許容距離 `tol` = 10m を経度の縮尺で度に換算（`10 / (111320 × cos(lat))`）。既存の `N03Municipalities`・`_Region` と同じ値。
2. R-tree で、外接矩形が地点の±`tol` の矩形と交わる区域を取る。**丸めは外側なので取りこぼさない。R-treeの一致を関係には使わない。**
3. 候補の形状（WKB）だけを読み、GEOS `dwithin(tol)` で許容距離の中の区域を決める。
4. 市区町村ごと、都道府県ごと、`region_relation` の集合ごとに、**許容距離の中の区域の形状をそのまま結合**（`union_all`）し、`contains` と「外縁が `tol` 以内か」を求める。許容距離より遠い区域は結果を変えないので読まない・結合しない。
   - 地点の周りの矩形で切ってから結合する方式は、実データの比較で不採用にした: `clip_by_rect`・矩形との `intersection` のどちらも、隣り合うFeatureの共有辺をそれぞれ作り直すため、結合しても継ぎ目が残った（東京＋神奈川の20,601点の試行で、それぞれ62点・35点が既存と食い違った）。
5. 状態:

| 状態 | 条件 |
|---|---|
| `inside` | 許容距離の中の市区町村が1つで、その結合が地点を含み、外縁が `tol` より遠い（既存 `locate()` の `inside`） |
| `near_boundary` | それ以外で、許容距離の中に区域がある（既存の `ambiguous`）。候補の市区町村・都道府県をすべて返す。各市区町村に `contains_point`（実際に含むか）を付け、境界付近であることと実際の所属を分けて返す |
| `outside_admin_area` | `coverage: national` で、許容距離の中に区域がない |
| `outside_registered_area` | `coverage: partial` で、許容距離の中に区域がない（海とは言わない） |
| `failed` | 読込み・解析の失敗（`reason: read_failed`）、空きの待ちの超過（`reason: busy`）。候補を返さない |

- 都道府県の `relation`: その県の区域だけの結合に対する `_Region.relation` と同じ規則（`inside` / `boundary`）。
- 所属未定地（`xx000`）: `unassigned: true`、`name: null`。
- 穴の中: 穴の縁から `tol` より遠ければ区域外（`outside_*`）。島: 島の区域として `inside`。

## 5. 同時アクセス・メモリ

- SQLiteの読取専用の接続を `connections` 本（既定4）持つプール。**1つの地点の判定（読込み・WKBの解析・GEOSの処理）の間は接続を保持する**ので、同時に動く判定は `connections` 件まで。呼び出すスレッドが増えても、一時メモリは増えない（テストで、32スレッドから呼んで同時の判定が3件以下を確認）。空きを `acquire_wait_s` 待って得られなければ `failed`（`busy`）。
- `region_relation` も同じ枠を使う（空きがなければ `ResolverBusy`。推測した関係を返さない）。
- `ResolvedLocation` は、その地点の候補の形状を `region_relation` のために保持する（呼び出し側が手放すまで）。**1リクエストの一時メモリ**として、将来の予算の式（設計 9.3節の `R_transient`）に数える。リクエストの間で共有しない。
- キャッシュは持たない（計測で不要と判断。第6章）。

Regional Index Loader との予算の共有（設計 9.3節への入力）:

| 項 | Resolverの値 |
|---|---|
| `M_base` への寄与 | 起動後の増加はほぼなし（meta と接続だけ。合成47県で起動後46MiB＝Python＋shapely の基本と同じ） |
| `S_sqlite` | 接続数4 × SQLiteの既定のページキャッシュ（未設定。実測は 4-N.4 の MB-4） |
| `R_transient` | 最大 `connections` × 1地点の候補の展開（東京＋神奈川で候補のWKBの合計は中央値159KiB、p95 735KiB、最大752KiB）＋保持中の `ResolvedLocation` |
| `C_admin` | 0（キャッシュなし） |

## 6. 検証（実データ: 東京・神奈川のN03、読取専用。1GBのコンテナ）

### 6.1 既存との比較（`python -m hererisk.research.resolver_compare`）

地点: 洪水601地点、津波の区域の頂点・外接矩形の中心（各1,500）、N03の辺の頂点と、辺の両側 5m・9.9m・10.1m・15m（県境の辺・それ以外の辺を各3,000本）、登録範囲の一様乱数3,000点。

| 索引 | 地点 | `locate()`（住所） | `{13}` | `{14}` | `{13,14}` | 差異の分類 |
|---|---|---|---|---|---|---|
| 東京＋神奈川 | 60,601 | 全点一致 | 全点一致 | 全点一致 | 60,563一致・38差異 | 38件すべて `reference_union_depends_on_set` |
| 東京だけ | 33,601 | 全点一致 | 33,594一致・7差異 | — | — | 7件すべて `source_micro_gap` |

- 洪水の `_Region` と津波の `_Region` は全点で同じ答え（同じ規則）。
- 状態: `inside` 10,775、`near_boundary` 45,384（うち候補の都道府県が2つ 20,757）、`outside_registered_area` 4,442（東京＋神奈川）。

差異の原因（原典の形状で確認）:

- **原典のN03の微小な隙間**: 隣り合うFeatureの間に、1m²未満の隙間がある（東京48か所・最大0.0005m²、神奈川133か所・最大0.000002m²。例: 千代田区と新宿区、横須賀市と葉山町）。Resolverは、地点の近くの区域の結合で隙間が残るため、隙間の縁から10m以内を `boundary` と答える。
- **既存の全体結合の数値上の不安定**: 既存の `_Region` は都道府県（の集合）の全Polygonを1つに結合する。GEOSの結合で、この隙間が残る場合と消える場合があり、**結合する集合によって答えが変わる**（例: 横須賀市・葉山町の点で、`{14}` は `boundary`、`{13,14}` は `inside`）。
- 分類の規則: `reference_union_depends_on_set` = 候補がすべて1つの県Pにあり、既存の `{P}` がResolverと同じ答え。`source_micro_gap` = 候補の原典の区域どうしの結合に、許容距離の中で1m²未満の隙間がある（Resolverの判定を使わずに原典から確認）。未分類の差異は0件。
- Resolverの答えは原典の形状に忠実で、境界側（安全側）。**現在のProviderは `{13}` だけを使い、`{13}` の差異は「東京だけ」の索引の7点（隙間の近く）だけ**。Providerを切り替える段階（4-N.3 以降）で、隙間の周り10mの地点の対象地域の関係が `inside` から `boundary` に変わりうる（O-14）。

### 6.2 合成データ（`tests/contract/test_location_resolver.py`、15件）

都道府県の内部、同じ市区町村の2つのFeatureの継ぎ目、市区町村境界、県境（0・±5m・±9.9m・10.5m）、複数県の集合の内部の県境、穴、MultiPolygon、島、海岸の外縁、所属未定地、未登録の隣県、全国登録（47県）の行政区域外、不正な座標、読込み失敗、混雑、壊れた索引・構築中の索引・別の登録・原典の変更、構築失敗時の既存索引の保持。格子と境界の点で、既存の `locate()`・洪水と津波の `_Region` と全点一致。32スレッドの並列で逐次と全点一致。

## 7. 性能（1GBのコンテナ、1プロセス1構成）

| 構成 | 索引 | 構築（コンテナの起動を含む） | 起動 | 起動後RSS | 逐次6万点の後 | 検索 中央値 / p95 / 最大 | 8・32スレッド後のRSS |
|---|---|---|---|---|---|---|---|
| Resolver 東京 | 9.3MB | 1.3秒 | 0.11秒 | 75MiB | 94MiB | 0.21 / 1.21 / 34ms | 230 / 268MiB |
| 既存 N03 東京 | — | — | 1.25秒 | 180MiB | 188MiB | 0.05 / 0.35 / 9ms | 250 / 254MiB |
| Resolver 東京＋神奈川 | 12.7MB | 0.9秒 | 0.13秒 | 75MiB | 94MiB | 0.33 / 1.59 / 35ms | 228 / 289MiB |
| 既存 N03 東京＋神奈川 | — | — | 1.33秒 | 203MiB | 212MiB | 0.06 / 0.30 / 8ms | 281 / 287MiB |

- R-treeの候補の数: 中央値2、p95 4、最大16（東京＋神奈川）。
- 並列は全スレッドが休まず要求する飽和の負荷。Resolverは計算された結果がすべて逐次と一致し、待ちの超過（`failed: busy`）が8スレッドで0.3〜0.4%、32スレッドで2.3〜2.5%（待ちの上限0.5秒）。既存のメモリ上の方式は1回の検索が約5倍速く、超過はない。
- 並列時のRSSの増加は、主にスレッドごとのメモリ領域（glibc の arena）。判定の数を接続数で抑える前の計測では、32スレッドで591MiB（`MALLOC_ARENA_MAX=2` で385MiB）。抑えた後は268〜289MiB。

登録地域数の増加（合成: 神奈川のN03を格子状にずらして47県分を作成。計測専用、登録しない。同じ200点で検索）:

| 登録数 | Feature | 索引 | Resolver 起動 / 起動後 / ピーク | 既存 N03 起動 / 起動後 |
|---|---|---|---|---|
| 1 | 1,247 | 3.4MB | 0.10秒 / 46MiB / 67MiB | 0.30秒 / 73MiB |
| 10 | 12,470 | 33.6MB | 0.11秒 / 46MiB / 64MiB | 2.1秒 / 237MiB |
| 47 | 58,609 | 157.7MB | 0.16秒 / 46MiB / 66MiB | 9.9秒 / 830MiB |

- **Resolverの常駐メモリ・検索時間（中央値0.35〜0.38ms）は登録数によらずほぼ一定。既存の方式は登録数に比例して増え、47県で1GBのコンテナの上限に近い。**
- 実際の全国のN03（47都道府県の実データ）は未計測（O-2: 全国のN03の保存・加工の可否の確認が先）。

## 8. 未解決事項・制約

1. 原典の微小な隙間の周りの関係（O-14）: Resolverは原典どおり `boundary`。既存は `inside` になることが多いが、結合の集合で変わる。Providerの切替の前に扱いを決める（隙間を埋めるのは原典の修正にあたるので、本工程ではしない）。
2. 1回の検索が既存の約5倍遅い（WKBの解析と結合を毎回行う）。飽和の負荷では待ちの超過が出る。キャッシュ・接続数・待ちの上限は 4-N.4 の計測（MB-1〜MB-9）で決める。
3. 並列時のRSSの多くは glibc の arena。`MALLOC_ARENA_MAX` の採否は計測だけ（設計 MB-5）。
4. SQLiteのページキャッシュは既定値のまま（未設定）。
5. 全国の実データのN03、VPS（x86_64）、同時アクセスの実運用での性能は未計測。

## 9. 次工程（4-N.3 Source Resolver）への引継ぎ

- `resolve()` の `prefectures`（候補の県と、県ごとの `relation`）と `region_relation(loc, 集合)` を、ソースの選択（契約 3.3節 SR-1〜SR-9）の入力にする。ソースの対象地域の関係は `region_relation(loc, service_prefectures)` で求める。
- `failed`（`busy` / `read_failed`）と `ResolverBusy` は、選択の `complete: false`（S-1: `error`）に対応させる。
- `outside_registered_area` / `outside_admin_area` は S-2（`not_available`）。
- 回帰の基準: 現在のProviderの `searched_sources`・`service_region_relation` との一致。差異が出るのは原典の微小な隙間の近くだけの見込み（本書 6.1節）。その扱いは O-14 の判断に従う。
