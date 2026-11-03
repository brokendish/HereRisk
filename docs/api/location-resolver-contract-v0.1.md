# Location Resolver / Source Resolver / Regional Index Loader 契約 v0.1（案、Phase 4-N.1）

- 状態: **契約案（OWNERレビュー待ち）**。第2章 Location Resolver は Phase 4-N.2 で、第3章 Source Resolver は Phase 4-N.3 で実装済み・製品から未使用（[Location Resolver 実装仕様](location-resolver-impl-v0.1.md)、[Source Resolver 実装仕様](source-resolver-impl-v0.1.md)）。第4章は未実装。Python内部の契約で、HTTP APIは新設しない（必要になった段階で検討）。Location API の応答契約は変えない。
- 作成: 2026-11-03（Claude）。基準コミット `4519f1a017c9a4033af7ccdc4a772d316ac4ab85`
- 設計: [全国対応の現在地判定・地域別データ参照基盤 設計 v0.1](../architecture/nationwide-location-index-design-v0.1.md)
- 関連: [Location API v0.1](location-api-v0.1.md)、[Polygon Engine 共通契約 v0.2](polygon-engine-contract-v0.2.md)、[Dataset Registry](../architecture/dataset-registry-v0.1.md) 第6章、[Data Publish](../architecture/data-publish-v0.1.md) 第7・10章
- フィールド名・型は**PROVISIONAL**（例として示す）。確定するのは責務・状態・規則。
- 改訂: 2026-11-03 Phase 4-N.1 追加要件 — 4.4節（同時実行）・4.5節（資源の設定）と試験項目 C-1〜C-7 を追加した
- 補正: 2026-11-03 Phase 4-N.1 設計補正 — 3.4節（`missing` と Location API の状態の対応・不変条件）、4.5節（メモリ予算の式と予約）を補正した

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

全体の結合形状を常駐させない。許容距離の中にある、集合に属する区域の形状だけを結合して求める（許容距離より遠い区域は結果を変えない）。

Phase 4-N.2 の実装で確定したこと:

- 候補の区域は**切り取らずに**結合する。地点の周りの矩形で切ってから結合すると、隣り合うFeatureの共有辺が別々に作り直され、継ぎ目が残る（実データで確認、[実装仕様](location-resolver-impl-v0.1.md) 4節）。
- 既存の `_Region` との差異は、原典のN03の微小な隙間（1m²未満）の近くだけで、Resolverは `boundary`、既存は全体の結合で隙間が消えると `inside`（結合する集合によって変わる）。扱いは OWNERが決定した（O-14、[ADR-003](../decisions/2026-11-03-n03-micro-gap-boundary.md)）: 修復・隙間の自動補完をせず、10m以内は `boundary`。既存との差異は原因（`source_micro_gap` / `reference_union_depends_on_set`）を明示した仕様上の差異として受け入れ、説明できない差異は許容しない。
- `municipalities` の各要素は `code`・`prefecture_code`・`unassigned`・`name`・`prefecture`・`contains_point`。`failed` は `reason`（`read_failed` / `busy`）を持つ。`region_relation` は、空きがなければ `ResolverBusy`、`failed` の地点には ValueError（推測しない）。

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

| SR-8 | `missing` が空でない選択は `coverage: "partial"` とする。Providerは、選んだソースの関係に関わらず、この地点を**対象地域の境界**として扱う（`region_state: "region_boundary"`）。`inside` に読み替えない |
| SR-9 | Location Resolver が `coverage: "partial"`（登録したN03が一部の都道府県だけ）のとき、未登録の県は `missing` に現れない（Resolverが知らない）。この場合の取りこぼしは、登録した区域の外縁から10m以内が `boundary` になること（2.4節）で防ぐ。外縁から10mより外は `outside_registered_area`（SR-5） |

Phase 4-N.3 の実装で確定したこと（[実装仕様](source-resolver-impl-v0.1.md)）:

- 入力の登録は共通の `SourceEntry(hazard, source_id, service_prefectures, index)`。各ハザードの検査済みの登録から `source_id`・`service_prefectures` だけを取り出す（`entries_from_registrations`）。`index` は呼び出し側が知る参照だけで、現在は `null`（推測しない）。
- 出力は 3.2節の項目に加え、`hazard_registered`（ハザードにソースが1件でもあるか）、`region_state`（SR-8 を反映。ソースがなければ `null`）、`location_coverage`（SR-9 の区別）、`complete: false` のときの `reason`（`location_read_failed` / `location_busy`）を持つ。
- 全対象都道府県が Location Resolver に登録されていない登録は、作成時に拒否する。

### 3.4 Location API の状態への対応（補正、2026-11-03）

選択の結果と検索の結果から、ハザードのセクションの `status` を次の順に決める（上の行が優先）。**Location API の状態・理由の値は増やさない**（既存の `not_available`・`error`・`available`・`unknown`・`no_match` と、既存の理由 `outside_service_region`・`service_region_boundary`・`pending_geometry_zone`・`zone_boundary_contact` だけを使う）。

| No | 条件 | `status` | 理由・付く情報 |
|---|---|---|---|
| S-1 | 選択が `complete: false`（Resolverの失敗、SR-4）、または選んだソースの1つでも検索が完了しない（索引を開けない・待ちの超過・上限・例外） | `error` | 一部のソースの結果だけを返さない（洪水 MVP 契約「1つのソースでも失敗したら全体をエラー」と同じ） |
| S-2 | 選んだソースが0件（行政区域外・登録区域外・候補の県のどれにもソースがない） | `not_available` | `outside_service_region`。`missing` だけの地点もここ（例: 神奈川県内で、神奈川の津波ソースが未登録） |
| S-3 | どれかのソースに区域（`zones`）がある | `available` | 見つかった区域はすべて返す（安全上の情報を隠さない、DP-08）。`missing` があれば `region_state: "region_boundary"`（SR-8）。**完全性は主張しない**（`candidate_completeness: "not_guaranteed"` は既存のまま） |
| S-4 | 区域がなく、判定保留・境界上・対象地域の境界・**`missing` あり**のどれか | `unknown` | 既存の理由。`missing` ありは `service_region_boundary`（SR-8 により境界として扱うため） |
| S-5 | 上のどれでもない | `no_match` | `scope_notice` つき（既存） |

不変条件（実装段階の試験で必ず確かめる）:

| No | 不変条件 |
|---|---|
| INV-1 | `no_match` になるのは、選択が `complete: true` かつ `missing` が空、かつ選んだ全ソースの関係が `inside`、かつ全ソースの検索が完了し、区域・判定保留・境界上がどれもないときだけ |
| INV-2 | `missing` が空でない地点は、どの検索結果でも `no_match` にならない（S-3 か S-4、ソースがなければ S-2） |
| INV-3 | 一部のソースの検索が失敗した地点は `error` で、他のソースの結果を `available`・`no_match` として返さない |
| INV-4 | 県境の地点（候補の県が2つ以上）で、`region_state` が `inside` にならない。ただし、候補の県がすべて同じソースの対象地域に含まれ、そのソースの和の内側にある場合（県境の継ぎ目、2.4節）は `inside` でよい |
| INV-5 | `not_available` は「区域外」「安全」を意味しない（既存の通知文のまま） |

例（東京・神奈川の県境から5m、東京側。津波のソースは東京だけ登録）:

| 東京のソースの検索 | `status` | 備考 |
|---|---|---|
| 区域あり | `available` | 東京の区域を返す。`region_state: region_boundary`。神奈川の区域があるかは分からない |
| 区域なし・保留なし | `unknown`（`service_region_boundary`） | `no_match` にしない（神奈川側を検索していない） |
| 失敗 | `error` | — |

`missing` の詳細（どの県のソースが未登録か）を応答に出すのは、Location API の項目の追加になるため O-6 の判断を待つ。それまでは、上の対応により「不完全な検索を完全な判定として返さない」ことを状態だけで保証する。

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

### 4.4 同時実行（設計 第14章）

| 規則 | 内容 |
|---|---|
| IL-10 | 索引のハンドルはソース×世代ごとに1つ。作成は single-flight（同時の要求は1回のオープンを待つ。待ちは `loader.open_wait_s` とリクエストの残り時間の短い方） |
| IL-11 | 形状キャッシュの要素の作成も single-flight。共有する形状は不変で、`prepare` はキャッシュに入れる前に1回だけ |
| IL-12 | ハンドル・キャッシュの要素は参照数を持つ。検索の間は参照を保持し、参照数0のものだけを閉じる・追い出す |
| IL-13 | リクエストは開始時に、各ソースの世代を1つ固定する。キャッシュの鍵は（ソース、世代、`feature_ref`）。1つの応答に同じソースの2つの世代を混ぜない |
| IL-14 | 同時検索数はプロセス全体のセマフォ（`search.max_concurrent`、CPUのため）で抑える。枠の待ちが上限・残り時間を超えたら `LoaderBusy`。Providerはそのセクションを `error` にし、部分的な結果を返さない |
| IL-15 | 一時メモリの予約: 検索は候補のWKBを読む前に、R-treeの検索と同時に各候補の `length(wkb)` を読み、キャッシュにない候補について `k × WKBの合計 ＋ 固定の部分` を `search.transient_budget_bytes` の枠から予約する。待てなければ `LoaderBusy`。必要量が枠全体を超える地点は `LoaderLimit`（`error`）。`MemoryError` は `error` とし、予約を返し、参照数0のキャッシュを捨てる |
| IL-17 | 展開した形状は、キャッシュ（上限に計上）か、そのリクエストの一時（予約に計上）のどちらか一方にだけ属する。キャッシュに入れるときは予約から計上を移す。参照中の要素ばかりで空きが作れなければ、キャッシュに入れずに一時のまま使い、リクエストの終わりに捨てる |
| IL-16 | 地点ごとの候補の列・`ComponentIndex`・結果はリクエストごとに作り、スレッド間で共有しない |

### 4.5 資源の設定（設計 第15章）

- 定義・型・範囲・既定値は `conf/common/`、環境ごとの値は `env/`。共通 Configuration Manager で起動時に解決し、実行中は変えない。リクエストで上書きしない。
- 起動時の整合性検査（設計 9.3〜9.5節）: `M_base + C_hazard + C_admin + S_sqlite + R_transient + F ≤ B_process ≤ L_container × r` を満たさない、`search.expansion_factor × 最大の構成のWKB > search.transient_budget_bytes`、待ちの上限 ≥ リクエストの期限、のどれかなら起動しない。`S_sqlite` はプロセス全体の接続数の上限 × 1接続のキャッシュで数える（索引の数 × 接続数ではない）。
- 数値の既定値は、設計 9.5節の手順と計測 MB-1〜MB-9 で決める（推測で確定しない）。
- 応答の上限（`MAX_ITEMS`）・Orchestratorの期限（Location API 第7章の2秒）は契約の値で、環境の設定で変えない（変えるなら契約の改訂）。

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
| SR-c | 3.4節 S-1〜S-5 の全組合せ（選択の完了・`missing`・関係・区域・保留・境界上・失敗） | 表のとおりの `status`。INV-1〜INV-5 が成り立つ |
| SR-d | 県境で片方の県のソースが未登録、区域なし | `unknown`（`service_region_boundary`）。`no_match` にならない |
| SR-e | 県境で両方の県のソースがあり、片方の索引が開けない | `error` |
| IL-a | R-treeの丸めの境界（外接矩形の辺・角ちょうどの地点） | 全件メモリの `ComponentIndex` と同じ結果 |
| IL-b | 形状キャッシュの上限を極端に小さくした場合 | 結果が同じ |
| IL-c | 索引なし・壊れた索引・別世代 | 開かない |
| C-1 | 登録量を1・5・10倍にした合成索引 | 起動時・定常のRSSが比例しない |
| C-2 | 地域を散らした地点の同時要求 | ピークRSSが予算内。結果は逐次と全件一致 |
| C-3 | 同じ地点への同時要求 | 索引のオープン・形状の解析が1回ずつ（計数） |
| C-4 | キャッシュ上限を極小にした同時検索 | 全件メモリの結果と全件一致。例外なし |
| C-5 | 検索中の世代の切替 | 各応答が1つの世代だけから作られる。旧世代は参照数0まで閉じない |
| C-6 | 同時検索数の枠を超える要求 | 超えた分は `error`（`no_match` にしない）。受け付けた分は逐次と同じ |
| C-7 | 2インスタンス（同じ世代） | 同じ地点の応答が一致 |
