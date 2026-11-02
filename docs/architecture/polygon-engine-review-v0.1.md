# Polygon判定処理の共通化 設計レビュー v0.1（Phase 4-H）

- 状態: **設計レビュー（提案。OWNERレビュー待ち）**。本書は実装・データ再構築・既存の契約の変更の承認ではない。
- 作成: 2026-11-02（Claude）
- 基準コミット: `c8845dabde601c41eede00355518802cc3ebf3f2`（Phase 4-G）
- 関連: [契約案](../api/polygon-engine-contract-draft-v0.1.md)、[移行計画](polygon-engine-migration-plan-v0.1.md)、[ADR-002案](../decisions/2026-11-02-polygon-engine-responsibility-draft.md)、[Design Principles](design-principles-v1.0.md)、[ADR-001](../decisions/2026-10-25-multiple-official-hazard-results.md)、[Dataset Registry](dataset-registry-v0.1.md)、[Data Publish](data-publish-v0.1.md)、[共通API契約](../api/common-contract-v0.1.md)、[座標精度方針（案）](hazard-source-format-precision-policy-v0.1.md)、[Polygon判定理由の共通仕様](../api/polygon-reason-catalog-v0.1.md)

## 0. 結論（要約）

1. **共通化の対象は「幾何の事実」だけにする。** 内外・境界上・形状の有効性・距離・局所輪郭の読み・判定に使った方式と世代を返す。浸水深・区域区分・採用基準（`candidate` の条件）・利用者への文言・状態（`no_match` など）の意味づけは、各ハザードのProviderが持つ。
2. **今すぐ共通化できるものは少ない。** すでに共通化済みのもの（理由コードのカタログ、位置入力の検証）を除くと、すぐに切り出せるのは副作用のない幾何の関数（形状の有効性の分類、局所輪郭法の計算、距離の近似）と、診断の実行枠（接続ごとの期限・件数上限・混雑時の応答）である。
3. **洪水は最後に移行する。** 次のハザードが共通部品を使い、洪水の既存実装との差分テストに合格するまで、洪水のコード・索引・応答は変えない。既存の洪水APIを変えずに進められる。
4. **次のハザードは津波（A40）を推奨する**（第8章）。必要な共通基盤は「形状の有効性の分類」と「正式な内外判定（使える形状だけ）＋判定保留の外接矩形」の2つで、参考解析は最初は不要（判定保留のまま返せば、安全側に倒れる）。
5. **独立検証（`verify.py`）は共通化しない。** 検証される側と同じ部品を使うと、独立性がなくなる。

## 1. 範囲と方法

- 調査対象: `src/hererisk/flood/`（全モジュール）、`src/hererisk/location/` の洪水・N03・API・サーバー、`src/hererisk/common/polygon_reasons.py`、関係するテスト、`compose.yaml`、上記の仕様書、Phase 2-C.4〜2-C.8 の他ハザードの実データ調査（東京都のA40・A49・A33・N03）。
- 方法: import関係と呼び出し関係をコードから追った。数値は既存の検証記録（README・レビュー記録）からの引用で、本工程では新たな計測・データ再構築をしていない。

## 2. 現状の構成

### 2.1 データの流れ（洪水）

```
原典ZIP（A31a, 読取専用）
  └─ flood.a31a（形式の検査・属性の読取）
       └─ flood.index.build_index ──▶ flood索引 SQLite（components: WKB・外接矩形・属性・usable/pending）
             │                              │
             │                              ├─▶ location.flood_provider.FloodProvider（起動時に usable をメモリへ。STRtree）
             │                              │       └─▶ GET /api/v1/location の hazards.flood（正式）
             │                              │
             └─ flood.diag.build ◀──────────┘（pending 行だけ。ZIPのSHA-256を再確認）
                   └─▶ 診断索引 SQLite（comps・chunks・defects・R-tree、derived_from）
                          ├─▶ location.flood_shadow（Shadow、非同期、件数だけ）
                          └─▶ location.flood_diagnostics（GET /api/v1/diagnostics/flood、同期・上限付き）

flood.verify（原典ZIPから独立に再計算）── flood索引を照合（Phase 4-B）
flood.local_analysis（メモリ上の局所輪郭法、PoC）── 診断索引の結果と全件一致（Phase 4-D）
```

### 2.2 import関係（`hererisk.` 内）

| モジュール | 依存先 | 主な使用者 |
|---|---|---|
| `common.polygon_reasons` | 標準ライブラリだけ | `flood.reason_messages`、`location.flood_diagnostics` |
| `flood.a31a` | 標準ライブラリだけ | `flood.index`、`flood.registry` |
| `flood.registry` | `flood.a31a`、`location.address_regions`、`location.address_provider` | `flood.index`、`flood.diag`、`flood.verify`、`location.flood_provider` |
| `flood.index` | shapely、`flood.a31a`・`registry`・`errors`、`location.address_regions`、`location.n03_municipality` | `location.flood_provider`、`flood.diag` |
| `flood.local_analysis` | numpy、shapely、`flood.verify`、`flood.settings` | `flood.diag.build`（`Prepared`）、PoCのCLI |
| `flood.diag` | numpy、sqlite3、`flood.errors`・`settings`（構築時だけ shapely・`index`・`local_analysis`・`registry`） | Shadow・参考解析API・検証CLI |
| `flood.adoption` | なし（純粋関数） | `flood.diag.diagnose` |
| `flood.reason_messages` | `common.polygon_reasons` | 参考解析API・検証CLI |
| `location.flood_provider` | shapely、`flood.*`、`location.*`、`data_inventory` | サーバー、検証CLI |
| `location.flood_shadow` / `flood_diagnostics` | `flood.diag`・`adoption`・`reason_messages`、`location.model` | サーバー |
| `location.n03_municipality` | shapely | 住所Provider、`flood.index`、`flood_provider`（対象地域） |

観察:

- `common` は `flood`・`location` に依存していない（Phase 4-F のテストで確認している）。この向きは維持する。
- `flood` は `location`（地域ファイル・N03）に依存している。対象地域の判定（N03）は洪水固有ではないため、共通化の候補になる（2.3節 A-12）。
- 局所輪郭法は**2つの実装**を持つ（メモリ上の `local_analysis.Prepared` と、SQLite上の `diag.DiagIndex`）。Phase 4-D で全2,113組の一致を確認しており、規則は同じである。共通化の際の正本は1つにする（第5章 R-4）。

### 2.3 棚卸し（関数・クラスごと）

分類: **A** 共通Polygon処理 / **B** ハザード固有 / **C** 仕組みは共通・条件は個別 / **T** 検証・PoCの道具（製品の経路ではない）

| ID | 対象 | 入力 → 出力 | 使用箇所 | 分類 | 理由 |
|---|---|---|---|---|---|
| A-1 | `flood.index.classify` | 1 Featureの構成Polygonの座標 → 構成ごとの（usable、保留理由、GEOSの理由） | `build_index` | **A** | 形状の有効性（GEOS `is_valid`）と、Feature内の構成どうしの重なり・辺の共有の検出。ハザードの意味を持たない |
| A-2 | `flood.a31a.check_coordinates` | 座標配列 → 例外または通過 | `build_index` | **A** | 有限・2次元・範囲・閉じた環・経度180度を超える辺の拒否。A31a固有の条件はない |
| A-3 | `local_analysis.Prepared` | shapely Polygon → 線分・環の向き・内側の側・問題箇所 | `diag.build`、PoC | **A** | 局所輪郭法の前処理 |
| A-4 | `local_analysis.Prepared.evaluate` / `staged` / `plus_far` | 地点・半径 → 局所の読み | PoC | **A** | 局所輪郭法の規則（メモリ上の実装） |
| A-5 | `diag._defect_kinds` | 前処理 → 問題箇所の種類（touch / touch_on_edge / overlap / crossing） | `diag.build` | **A** | 自己接触・自己交差の分類 |
| A-6 | `diag._scale` | 緯度 → 経度・緯度1度の長さ（m） | 診断全体 | **A** | 局所の距離の近似（4.3節） |
| A-7 | `DiagIndex._segments_in` / `_nearest` / `_side` / `winding` / `defect_distance_m` / `edge_distance_m` / `evaluate` / `analyze` | 構成・地点・半径 → 局所の読み・回転数・距離 | `diagnose`、`lookup` | **A** | 局所輪郭法の規則（SQLite上の実装） |
| A-8 | `diag.build` の索引の形（`chunks`・`defects`・R-tree・`RING_DTYPE`） | 保留中の構成 → 診断索引 | CLI | **A＋B** | 幾何の格納形式は共通。`comps` の列（`river_code`・`river_name`・`manager`・`depth_class`）はA31a固有 |
| A-9 | `flood_provider._Source.search` の幾何部分 | 地点 → 含む／境界に接する／判定保留（外接矩形） | `FloodProvider.lookup` | **A** | 使える形状だけで `contains`・`intersects`、保留中の構成は外接矩形（境界を含む）で `unknowns` に入れる（L1） |
| A-10 | `flood_diagnostics._Slot` と上限（接続数・期限・件数） | — | 参考解析API | **A** | 接続ごとのSQLite進行ハンドラ・期限。ハザードの意味を持たない |
| A-11 | `location.api.parse_point` | クエリ → (lat, lon) | 全API | **A（共通化済み）** | 位置入力の検証 |
| A-12 | `flood_provider._Region`・`n03_municipality` の許容幅10m | 地点 → 対象地域の内／境界付近／外 | 洪水・住所 | **A** | N03の対象地域の判定。洪水固有ではない |
| A-13 | `common.polygon_reasons` | 理由コード → 文言 | 洪水 | **A（共通化済み）** | Phase 4-F・4-G |
| B-1 | `flood.a31a`（`open_zip`・`scenario_members`・`spec_edition`・`iter_features`・`_check_feature`・`depth_class`） | ZIP → Feature・属性・浸水深区分 | `build_index` | **B** | A31aの配置・属性名・製品仕様書の区分表 |
| B-2 | `flood.registry`（`load_flood_sources`・`registration_view`） | 地域ファイル → 登録 | 構築・Provider | **B** | 河川管理者コード・想定・配布単位 |
| B-3 | `flood_provider._Source.public`・`data_use`・`_item` | 登録・行 → 出典・利用条件・属性 | Provider | **B** | 洪水の提示契約の形 |
| B-4 | `FloodProvider.lookup` の状態の対応（`available`・`unknown`・`no_match`・`not_available`） | 検索結果 → 状態 | Provider | **B** | A31aは評価済みの範囲を持たないため、`no_match` は「該当なし」だけを意味する（共通API契約 4.2）。津波・土砂災害で同じとは限らない |
| B-5 | `reason_messages.FLOOD`・`FLOOD_RESULTS` | — | 参考解析API | **B** | 「浸水想定区域」「浸水深」の文言 |
| B-6 | `reason_messages.interpret` の浸水深の扱い | 記録 → 解釈 | 参考解析API | **B** | 浸水深を出す条件（`candidate` ＋ 内側だけ） |
| C-1 | `flood.adoption.classify` | 文脈・構成・解析 → 分類と理由 | `diagnose` | **C** | 条件の大半は幾何の事実だが、どの条件で `candidate` にするかは採用方針。ハザードごとに版を付けて選ぶ |
| C-2 | `DiagIndex.diagnose` | 地点・対象（ソース、対象地域の関係、zone_ref） → 記録 | Shadow・API | **C** | 「正式な検索の判定保留だけを診断する」「別ソースの構成を当てはめない」は共通の約束。対象の取り出し方は各Providerの応答の形に依存する |
| C-3 | `index.zone_ref`・`product_ref`（内容由来の識別子） | ZIPのSHA-256・メンバー・番号 → ID | 構築 | **C** | 生成の仕組みは共通にできるが、`domain`・粒度・接頭辞はハザードの識別子契約が決める |
| C-4 | `index.read_meta`・`diag._flood_identity`・`DiagIndex.__init__` の照合 | 索引のmeta → 受け入れ／拒否 | 起動時 | **C** | 世代の整合性の確認は共通。どの項目で同一とみなすかは索引の形式ごと |
| C-5 | `flood.settings`（半径、`shadow_enabled`、`api_enabled`、`local_analysis.enabled` の拒否） | 設定ファイル → 検査済みの設定 | サーバー・CLI | **C** | 半径の検査は共通にできる。スイッチの意味（何を有効にするか）はハザードごと |
| C-6 | `flood_shadow.ShadowFloodProvider` | Provider → 同じ答え＋件数 | サーバー | **C** | 包む仕組みは共通。`unknowns` の取り出しは洪水の応答の形 |
| C-7 | `flood_diagnostics.FloodDiagnosisApi` | 地点 → 正式＋参考 | サーバー | **C** | 実行枠はA-10、正式と参考を並べる形は共通にできる。中身はハザードごと |
| C-8 | `FloodProvider` の `MAX_ITEMS`（500件を超えたら `error`） | — | Provider | **C** | 一部だけを返さない規則は共通。上限値はハザードごと |
| T-1 | `flood.verify` | 原典ZIP → 独立の期待値 | Phase 4-B | **T（共通化しない）** | 独立検証。検証される部品と実装を共有してはならない（第5章 R-6） |
| T-2 | `local_analysis` の `Analyzer`・`run`・SVG・レポート、`diag.compare`・`replay`・`bench`、`shadow_verify`、`diag_api_verify` | — | 検証CLI | **T** | 洪水の回帰基準を作る道具。共通化の差分テストで再利用する |

## 3. 共通Engineの責務（返すもの・返さないもの）

| 返す（幾何の事実と状態） | 返さない（Providerが持つ） |
|---|---|
| 構成ごとの形状の有効性（`valid` / `invalid_geometry` / `feature_invalid_component`）とGEOSの理由 | 浸水深・区域区分（警戒・特別警戒）・想定規模・河川名などの属性の意味 |
| 正式な関係（使える形状だけ）: `inside` / `on_boundary` / `outside`、判定保留（外接矩形に入る保留中の構成） | `available` / `no_match` / `not_affected` などの状態への対応 |
| 参考の読み（保留中の構成だけ）: 局所の読み、回転数、偶奇、問題箇所までの距離と種類、判定に到達した半径 | `candidate` / `undetermined` / `rejected` の採用方針（ハザードが版付きで選ぶ。C-1） |
| 方式・版・半径・距離の単位・精度の前提 | 利用者への文言（カタログにハザードが登録） |
| 使用した索引・世代（作成元の照合結果） | 安全・危険、危険度、ハザード間の統合 |
| 処理の状態（完了／上限超過／時間切れ／混雑／失敗） | データの利用条件・公開の可否 |

## 4. 共有する判定アルゴリズムの分析

### 4.1 適用範囲

| 条件 | 現状の扱い | 共通化での扱い |
|---|---|---|
| Polygon / MultiPolygon | 構成Polygon（`polygon_index`）ごとに分ける。Feature内の重なり・辺の共有は `feature_invalid_component` | 同じ。構成単位を共通の単位にする |
| 外周と穴 | 回転数は穴を含めて正規化（外周 +1、穴 −1、環の向きで符号を補正）。偶奇も全環 | 同じ。`exterior_only`（穴を無視）は正解の参照にしない |
| 自己接触（頂点どうし） | 問題箇所として位置と種類を記録。実データ（洪水）は全52,602件が `touch` | 同じ。A40（76件）・A49（1,307件）も同じ型（Phase 2-C.6）だが、局所輪郭法は未検証 |
| 自己交差（辺どうし）・重なり | 種類は分類するが、洪水の実データにはない | **未検証**。合成データでのみ確認 |
| 近接する複数の境界 | 最寄りが複数（差1μm以内）で側が食い違えば `ambiguous_nearest` | 同じ |
| 局所半径 | 5→10→25→50→100m（設定、最大1,000m） | 半径の列は設定。ハザードごとに検証が必要 |
| 面積0の環 | `orientation_unknown` | 同じ |
| 問題箇所の位置が特定できない無効形状 | `defect_location_unknown` | 同じ |

### 4.2 不適用・未検証の条件（明示する）

- 洪水（東京都、A31a）での一致（`make_valid`・偶奇との全件一致、ケースA・B）は、**他のハザード・他の地域の精度保証ではない。**
- 自己交差（crossing）・同一直線上の重なり（overlap）・穴と外周の交差は、実データで未観測。局所の読みを `candidate` にする根拠がない。
- 1つのFeatureの構成どうしが重なる場合（`feature_invalid_component`）は、局所輪郭法の対象外（`feature_level_invalidity_not_analyzed`）。
- **Feature間の重なり**（A33で同じ形のFeatureが23組、区域区分が重なること自体は正当）: 共通Engineは重なりを解消・統合しない。各Featureを独立に返す。
- 離島（小笠原など、北緯20〜27度）・北海道（北緯45度付近）: 距離の近似の誤差は小さい（4.3節）が、実データで未検証。
- 日付変更線をまたぐ形状: 日本の範囲（東経122〜154度）では起きない前提。`check_coordinates` が経度180度を超える辺を拒否する。

### 4.3 座標・距離の前提

- 座標: 原典の経度・緯度（JGD2011、`EPSG:6668`）をそのまま平面として扱う。内外・接触の位相判定は経度・緯度の平面で行う（GEOSも同じ）。
- 距離: 地点の緯度で経度方向を縮めた局所の平面近似（`M_PER_DEG = 111,320 m`、`cos(lat)`）。半径1,000m以内での誤差は、楕円体の距離に対して1%未満（子午線方向の1度の長さが緯度で約1%変わることが主因）と見込む。境界上の判定（1mm）・同点の判定（1μm）はこの近似の上の値で、**測位の精度とは無関係**。
- API入力（GPS、WGS84想定）とJGD2011の違いは変換しない（Normalize契約 ON-11 は未決定）。数十cm程度の差がありうるが、本Engineは補正しない。`on_boundary` は「データの形状の上で境界線上にある」という事実で、測位誤差を含まない。
- 頂点の精度: 洪水の索引は座標をJSONの浮動小数で読む（`coordinates_as_float`、索引の制限事項）。精度方針（案）の整数・小数8桁の精度プロファイル（`coord-precision-round8-v1`）は**未実装**。共通Engineで精度プロファイルを導入すると洪水の結果が変わりうるため、**洪水は浮動小数のまま固定**し、精度プロファイルは版付きの選択肢として契約に置く（第5章 R-5）。

## 5. リスク（共通化すると危険な処理）

| ID | リスク | 対策 |
|---|---|---|
| R-1 | 採用基準（`candidate` の条件）を共通Engineに入れると、未検証のハザードに洪水の基準を強制する | Engineは事実だけを返す。分類はハザードの方針モジュール（版付き）。共通の既定方針を置く場合も、ハザードが明示的に選んだときだけ使う |
| R-2 | 状態の意味（`no_match` と `not_affected`）を共通化すると、評価済みの範囲を持たないデータで「該当しない」を断定する | 状態の対応はProvider（B-4）。Engineの関係は `inside` / `outside` / `on_boundary` / 判定保留だけ |
| R-3 | 無効形状の自動修復（`make_valid`）を共通部品に入れると、正式判定へ流れ込む | Engineに修復の関数を置かない。派生形状の利用はNormalize契約 ON-15・ON-16 の承認まで禁止のまま |
| R-4 | 局所輪郭法の2つの実装（メモリ上・SQLite上）のどちらかを変えると、Phase 4-D の一致が崩れる | 共通化では1つを正本にし、もう一方は差分テストの参照として残す（正本の候補: SQLite上の実装。製品の経路で使っているため） |
| R-5 | 座標の精度プロファイル（整数・8桁）を共通部品の既定にすると、洪水の索引・結果が変わる | 精度プロファイルは索引の世代の属性として記録し、既存の洪水は `float-json-v0`（現状）に固定する |
| R-6 | 独立検証（`flood.verify`）を共通部品で書き直すと、検証の独立性がなくなる | 検証は共通Engineを使わない。むしろ共通Engineの検証に使う |
| R-7 | 複数ハザードの索引を1つのファイル・1つのRegistryにまとめると、世代・所有権・公開の切替が連動する | 索引はハザード（API）ごと・ソースごとに分け、形式（スキーマとコード）だけを共有する（第6章） |
| R-8 | 共通Engineが肥大化し、属性の解釈やAPIの形まで持つ | 依存関係の規則（第7章）をテストで強制する |
| R-9 | 1つの巨大なサービスにまとめると、低メモリ環境で全ハザードが同時に落ちる | 初期はライブラリとして共有し、プロセスはAPIごと（第9章） |
| R-10 | Feature間の重なり・同一形状（A33）を共通部品が除外・統合する | 除外・統合しない。各Featureを独立に返す（DP-02・DP-11） |

## 6. データパイプラインと索引

### 6.1 推奨する層

```
[ハザード固有] 原典パーサー（A31a / A40 / A49 / A33）── 形式・属性・区分表・登録の検査（失敗で停止）
        │  中間表現: 構成Polygon（座標・環・record_key・polygon_index）＋ 不透明な属性（JSON）＋ 出典
        ▼
[共通] 形状の検査（A-1・A-2）── usable / pending と理由。修復しない
        ▼
[共通の形式・ハザードの所有] 正式索引（usable のWKB・外接矩形・属性JSON）／診断索引（pending の線分・問題箇所）
        ▼
[ハザード固有] Provider（状態の対応・属性の提示・文言）
```

- **中間表現**は「幾何＋不透明な属性」とする。共通部分は属性の中身を読まない（浸水深・区域区分を解釈しない）。属性の列名は索引の形式でハザードが宣言する。
- **正式索引と診断索引は役割を分けたまま**とする。診断索引は正式索引の pending 行からだけ作り、作成元の世代（`index_format`・`built_at`・原典ZIPのSHA-256）を `derived_from` に持つ。起動時に照合し、一致しなければ起動しない（fail-closed）。
- **所有権**: 索引ファイル・設定・公開世代はハザード（API）ごと。`/data/<api>/` の分離（Dataset Registry 改訂2026-10-16）に合わせる。共通部品はファイルを持たない。
- **世代と公開**: 洪水の索引は現状「ローカル検証の成果物で、Publish・Dataset Registryの世代ではない」（`flood.index` の注記）。正式な公開には、Data Publish（現行1＋過去2世代、原子的切替、旧世代の保持）への接続が必要で、**本工程の範囲外**（未決定事項 U-3）。
- **ロールバック**: 索引は一時ファイルに書いてから置き換える（既存の方式）。公開の切替を導入する場合は、正式索引と診断索引を**同じ世代の組として**切り替え、片方だけの切替を禁止する（世代の不一致は起動時の照合で拒否されるため、組で戻せばよい）。
- **欠損・不整合**: 原典の形式違反・登録との不一致・識別できない重なり・往復の照合の不一致は、索引を作らない（既存の方式。部分的な成功にしない）。

### 6.2 識別子

- 共通の参照（Engineの入出力）は、ハザードが発行した `feature_ref`（洪水では `zone_ref`、構成Polygon単位）を**そのまま運ぶ**。Engineは識別子を作り替えない。
- 内容由来の識別子の生成（C-3）は共通にできるが、`domain` 文字列・粒度（Feature単位か構成単位か）・接頭辞はハザードの識別子契約（洪水: Catalog/Identity契約 4.3）が決める。洪水の `zone_ref` の生成式は変えない。

## 7. 依存関係の規則（肥大化を防ぐ）

| No | 規則 | 確認方法（案） |
|---|---|---|
| D-1 | 共通Engine（`hererisk.common.polygon`、新設する場合）は、標準ライブラリ・numpy・shapely・sqlite3だけに依存する。`hererisk.flood`・`hererisk.location`・他のハザードをimportしない | Phase 4-F と同じ「importされたモジュールの一覧」テスト |
| D-2 | ハザード → 共通は可。共通 → ハザードは不可。ハザード → ハザードは不可 | 同上 |
| D-3 | 共通Engineは属性の中身を読まない（不透明なJSONとして運ぶ）。属性のキー名をコードに書かない | `depth`・`river`・`A31a` などの文字列の禁止テスト |
| D-4 | 共通Engineは利用者向けの文章を持たない（文言はカタログ） | 日本語文字列の禁止テスト（カタログを除く） |
| D-5 | 共通Engineは `candidate` などの採用の分類を返さない（事実だけ） | 契約テスト |
| D-6 | 共通Engineは修復（`make_valid`・`buffer(0)` 等）を呼ばない | 呼び出しの禁止テスト |
| D-7 | 未使用の共通処理を将来のためだけに作らない（Dataset Registry 第2章）。2つ目の利用者（次のハザード）が使うときに切り出す | レビュー |
| D-8 | 独立検証（`flood.verify` など）は共通Engineをimportしない | import テスト |

## 8. 最初の対象ハザードの比較

東京都の実データ調査（Phase 2-C.4〜2-C.8）による。

| 項目 | 津波 A40 | 高潮 A49 | 土砂災害 A33 |
|---|---|---|---|
| 地物数・頂点数 | 33,124・283,058 | 59,039・1,081,414 | 30,043・803,194 |
| 原典の無効形状 | 76件（0.23%）、全て頂点の自己接触 | 1,307件（2.21%）、全て頂点の自己接触 | 0件（穴と外周の1点接触は有効） |
| 属性の意味 | 浸水深の区分（洪水に近い） | 浸水深の区分（洪水に近い） | 現象種別 × 区域区分（重なりが正当） |
| 独立の照合 | GMLの参照が健全で全件照合できる | GMLの参照が壊れている（Shapefileは未試験） | GML・Shapefileは別ZIP（未取得） |
| 共通化で確かめられること | 判定保留の経路（少数）・浸水深の不透明な受け渡し | 判定保留の経路（多数）・性能 | 属性の意味を持たないこと・Feature間の重なりを統合しないこと |

**推奨: 津波（A40）**

1. 構造が洪水に近く（Polygon＋浸水深の区分）、共通部品の適用可能性を、意味の違いに惑わされずに確かめられる。
2. 無効形状が少なく（76件）、判定保留（`unknowns`）の経路を小さい規模で確かめられる。参考解析を後回しにしても、利用者への影響（判定保留になる範囲）が小さい。
3. GMLとの全件照合ができ、独立検証（T-1に相当）を作りやすい。
4. 次点は土砂災害（A33）。属性の意味が大きく違うため、「共通Engineが意味を持たない」ことの確認に向く。ただし区域区分の重なりの提示契約（共通API契約 4.3）が未決定のため、2番目以降とする。
5. 高潮（A49）は無効形状が多く、GMLの照合の根拠がないため、最後にする。

## 9. パフォーマンス

### 9.1 現状（東京都・洪水、既存の記録）

| 項目 | 正式（Shapely、メモリ常駐） | 診断（SQLite索引、遅延読込） |
|---|---|---|
| 常駐メモリ | Providerの起動後のピークRSSが67MB → 483MB（約416MB増、Phase 4-G の検証プロセス） | 診断索引を開いても増分はほぼなし（Phase 4-E・4-G）。軽量検索だけのプロセスで51MB（Phase 4-D） |
| 起動 | N03・usable形状の読込（時間は未計測） | 0.1ms（metaの照合だけ） |
| 索引のサイズ | 410MB（flood索引、東京都の3 ZIP。本工程で読取専用で確認） | 148MB（pending の構成だけ） |
| 1地点の応答 | `/api/v1/location` HTTP 中央値1.5ms | 参考解析API HTTP 中央値1.4ms・p95 10.7ms・最大17ms |
| 同時アクセス | ThreadingHTTPServer。索引の行読みはロックで直列化 | 接続2本、0.25秒待って `busy`。HTTP 32並列で答えの変化なし |
| コンテナ全体 | 約583MiB（通常のLocation API） | 参考解析APIを有効にしても577MiB |

### 9.2 複数ハザードを有効にしたとき

- **最大の懸念は正式検索の常駐メモリ**。現行の方式（usable 形状をすべてメモリに置き、STRtreeを作る）をハザードごとに繰り返すと、東京都だけでも頂点数に比例して増える（A49は頂点108万）。1GBのコンテナ上限（`mem_limit: 1g`）に収まるかは**未計測**。
- **候補**（いずれも計測してから決める。未検証の方式を採用しない）:
  - (a) 現行方式のまま、ハザードごとに別プロセス（コンテナ）。分離は強いが、Python・shapely・N03の常駐分（数十〜百MB）が重複する。
  - (b) 正式検索も診断索引と同じ「SQLite＋R-tree、地点ごとにWKBを読む」方式にする。常駐は小さいが、**正式判定の方式の変更**になるため、洪水には適用しない。新しいハザードで計測し、現行方式との全件一致を確認してから検討する。
  - (c) N03の対象地域の判定（A-12）を1回だけ読み込み、ハザード間で共有する（同じプロセス内のライブラリとして）。
- 初期案: **共通ライブラリ＋APIごとのデータ**、プロセスは現行どおり（Location API 1つ）。次のハザードの追加時に (a)・(b) を計測し、1GBを超える見込みならOWNER判断（U-4）。
- 大規模な更新: 索引の作り直しはオフライン（一時ファイル→置換）。実行中のプロセスは古い索引を開いたまま（起動時の照合済み）。新しい索引の使用には再起動が必要（現状）。

## 10. 設計レビューで回答する事項

| No | 質問 | 回答 |
|---|---|---|
| 1 | 今すぐ共通化できる処理 | 共通化済み: 理由コードのカタログ（A-13）、位置入力の検証（A-11）。切り出しが可能: 形状の有効性の分類（A-1・A-2）、局所輪郭法（A-3〜A-7、正本は1つ）、距離の近似（A-6）、診断の実行枠（A-10）、対象地域の判定（A-12）。ただし規則 D-7 により、**切り出すのは次のハザードが使う時点**とする |
| 2 | ハザード固有として残す処理 | 原典パーサーと区分表（B-1）、登録（B-2）、出典・利用条件・属性の提示（B-3）、状態の対応（B-4）、文言（B-5）、浸水深の扱い（B-6） |
| 3 | 共通化すると危険な処理 | 採用基準（R-1）、状態の意味（R-2）、修復（R-3）、精度プロファイルの既定化（R-5）、独立検証（R-6）、索引の統合（R-7）、Feature間の重なりの統合（R-10） |
| 4 | 境界判定・参考解析の再利用の粒度 | **構成Polygon 1つ × 地点1つ** の評価（関係・局所の読み・根拠）を単位とする。対象の選び方（正式な判定保留だけ）・分類（採用方針）・文言はその上の層。`diagnose(targets)` は「対象の受け渡しの約束」として共通にし、採用方針は引数で渡す |
| 5 | 索引の共有方法と所有権 | 形式（スキーマ・読み書きのコード）だけを共有し、ファイル・世代・設定はハザード（API）ごと・ソースごと。診断索引は正式索引の世代に従属し、組で切り替える |
| 6 | 依存関係の規則 | 第7章 D-1〜D-8 |
| 7 | 次のハザードに最小限必要な共通基盤 | (1) 形状の有効性の分類（A-1・A-2）、(2) 正式な関係の検索（使える形状の内外・境界接触、保留中の構成の外接矩形 → 判定保留）（A-9）、(3) 理由コードのカタログ（済）。参考解析（局所輪郭法・診断索引）は**不要**で、判定保留のまま返す |
| 8 | 最初の移行対象 | **津波（A40）を新しいハザードとして実装し、共通部品の最初の利用者にする**（第8章）。洪水は最後に移行する |
| 9 | 既存洪水APIを変更せずに進められるか | **できる**。共通部品は新設し、洪水は自分のコードを使い続ける。洪水と共通部品の一致は、洪水のコードを変えずに差分テスト（同じ入力で両方を呼ぶ）で確認する。洪水の切替（Step 4）は、回帰基準（第11章の移行計画）を満たしたときだけ、別のOWNER判断で行う |
| 10 | Codexによる独立検証の時期 | (1) 本レビューと契約案の確定前（設計監査）、(2) 共通部品の切り出し後（差分テストの妥当性）、(3) 次のハザードのProviderを有効にする前（パーサー・fail-closed）、(4) 洪水の切替の前（回帰の監査）、(5) 参考解析の正式採用・一般公開の検討の前。詳細は移行計画 第5章 |

## 11. 推奨構成

```
hererisk/common/polygon_reasons.py          （既存）理由コード・文言の仕組み
hererisk/common/polygon/                    （新設候補。次のハザードが使う時点で作る）
    validity.py      形状の有効性の分類（A-1・A-2）。修復しない
    relation.py      正式な関係の検索（A-9）。使える形状だけ。判定保留の外接矩形
    region.py        対象地域の判定（A-12、N03の許容幅）
    local_contour.py 局所輪郭法（A-3〜A-7の正本）。分類はしない
    diag_store.py    診断索引の形式（chunks・defects・R-tree・meta・derived_from の照合）
    runner.py        診断の実行枠（A-10: 接続・期限・件数・混雑）
hererisk/<hazard>/                          ハザードごと（flood は現状のまま）
    <format>.py      原典パーサー・区分表（B-1）
    registry.py      登録（B-2）
    index.py         正式索引の構築（共通の validity・relation を使う）
    adoption.py      採用方針（C-1、版付き。必要になったとき）
    reason_messages.py  文言（B-5）
hererisk/location/<hazard>_provider.py      状態の対応・提示（B-3・B-4）
```

- 1プロセスのLocation APIの中で、ハザードごとのProviderが独立に動く（現行の Orchestrator の方式）。1つのProviderの失敗は、そのセクションの `error` になる。
- 共通部品は新設するだけで、既存の洪水のファイルは移行計画のStep 4まで変更しない。

## 12. 未決定事項（OWNER判断）

| ID | 事項 |
|---|---|
| U-1 | 次のハザードを津波（A40）とするか |
| U-2 | 共通Engineの置き場所（`hererisk.common.polygon`）と、正本にする局所輪郭法の実装（SQLite上を推奨） |
| U-3 | 正式索引・診断索引を、Data Publish・Dataset Registryの世代としてどう管理するか（現在は対象外のローカル検証の成果物） |
| U-4 | 複数ハザードのメモリの方式（9.2節の (a)〜(c)）。計測の結果による |
| U-5 | 座標の精度プロファイル（整数・8桁）を、新しいハザードで採用するか（洪水は浮動小数のまま） |
| U-6 | API入力（WGS84）とJGD2011の扱い（ON-11） |
| U-7 | 共通の既定の採用方針を置くか（置く場合も、ハザードが明示的に選ぶ） |
| U-8 | A40・A49の原典の自己接触を、洪水と同じく判定保留とするか（Phase 2-C.6 の未決定事項） |
