# Flood Integration Contract v0.1（案）

- Task: Phase 2-B Flood Normalize / Integration Contract v0.1
- 状態: **契約案（OWNERレビュー待ち。正式採用されていない）**。本書は実装の承認ではない
- 作成: 2026-10-21（Claude）
- 前提: [Flood Normalize Contract v0.1（案）](flood-normalize-contract-v0.1.md)

区分: **［確定］** 既存の承認済み契約に由来、**［実測］** Phase 2-A.1〜A.4の実データ調査の事実、**［提案］** 本書の設計提案（未承認）、**［未決定］** OWNER判断が必要

根拠資料: [Phase 2-A.1](../../reviews/phase2/phase2a1-a31a-source-investigation.md)、[Phase 2-A.2](../../reviews/phase2/phase2a2-national-river-source-investigation.md)、[Phase 2-A.3](../../reviews/phase2/phase2a3-kanto-a31a-data-verification.md)、[Phase 2-A.4](../../reviews/phase2/phase2a4-n03-tokyo-coverage-verification.md)、[Dataset Registry設計](dataset-registry-v0.1.md)、[Data Publish設計](data-publish-v0.1.md)、[データソース定義設計](data-source-definition-v0.1.md)、[基本アーキテクチャ](basic-architecture-v0.1.md)

## 1. 目的・適用範囲

複数のSource Validate合格のNormalize成果物から、対象地域のFlood APIが使う**統合検索データ**（Integration成果物）を、入力を変更せずに再生成可能な形で作る。出典・ランク・重複関係を失わない。

| 項目 | 初期値 | 区分 |
|---|---|---|
| 入力 | A31a 東京都管理河川（2成果物、15成果品）、A31a 関東地方整備局（1成果物、想定最大規模48成果品）、N03 東京都2025年版 | ［提案］ |
| 対象地域 | 東京都本土（N03の行政区域コード13101〜13308と東京湾内の所属未定地3ポリゴン） | ［実測: Phase 2-A.4で定義］。地域の規則は設定で与え、東京都に固定しない［提案］ |
| シナリオ | 想定最大規模 | ［提案］ |
| 将来 | 埼玉県・神奈川県のA31a、他の地域 | ［未決定］ |

本書で扱わないこと: Flood APIの最終的な応答Schema、Data Publishの手順（既存契約）、Registryのフィールド変更（必要な場合は第9章の改訂案として別に提示する）。

## 2. 工程の契約

| 工程 | 責務 | 入力 | 出力 | 成功条件 | 失敗条件 | 証跡 | 再実行の単位 | 中断後の再開 |
|---|---|---|---|---|---|---|---|---|
| Integration | Manifestに固定した入力から、地域の選別・重複関係の保持・空間索引を含む統合成果物を作る | Integration Manifest（第3章）、各Normalize成果物、各Source Validate Record、N03のNormalize成果物 | `work/integrated/<run_id>/` の統合成果物、`records/integrations/<run_id>.json` | 全入力をManifestどおりに読み、出力を確定し、ハッシュを記録 | Manifestと入力の不一致、入力のSource Validateが合格でない、地域の判定で保留が出た、書込み失敗 | Integration Record（第7章） | 1つのManifest | 確定前の出力は不採用。同じManifestから新しい `run_id` で作り直す |
| Integrated Validate | 統合成果物を入力と照合して合否を決める | 統合成果物、Manifest、入力のNormalize成果物 | `records/integrated_validations/<run_id>.json` | 第8章の全項目に合格 | いずれかに不合格 | Integrated Validate Record | 1つの統合成果物 | 読取専用で、何度でも同じ結果 |
| Data Publish | 既存の契約どおり、検証済みの統合成果物を不変の公開実体にし、Registryを原子的に切り替える | Integrated Validate合格の統合成果物 | `rel/versions/…`、Registry | 既存契約［確定］ | 既存契約 | 既存のPublish記録 | 既存契約 | 既存契約（切替前の失敗では旧公開世代を維持） |

**Integration・Integrated Validateが失敗した場合、部分的に作った統合成果物は公開しない。既存の公開世代を保持する**（既存のData Publishの原則［確定］）。

## 3. Integration Manifest［提案］

Integrationの入力は、実行前に作るManifestで完全に固定する。Integration中に入力を変更したり、新しいNormalize成果物へ暗黙に差し替えたりしない。

```json
{
  "schema": "hererisk-flood-integration-manifest-v0.1",
  "manifest_id": "<Manifestの識別子>",
  "pipeline": {"id": "<未採番>", "version": "<未採番>"},
  "scenario": "maximum",
  "region": {
    "region_id": "<地域定義の識別子（例: 東京都本土）>",
    "rule_ref": "<地域定義（版管理された設定）の参照>",
    "rule_sha256": "<地域定義のSHA-256>",
    "boundary_input": {"normalize_run_id": "<N03のNormalize run_id>", "manifest_sha256": "<…>",
                       "source_validation_ref": "<…>", "source_zip_sha256": "<N03原典ZIPのSHA-256>"}
  },
  "inputs": [
    {"source_ref": "<取得設定ID>", "normalize_run_id": "<…>", "manifest_sha256": "<…>",
     "source_validation_ref": "records/source_validations/<run_id>.json",
     "source_validation_sha256": "<…>", "source_zip_sha256": "<…>",
     "products": "all"}
  ],
  "parameters": {"selection": "area_intersection", "geometry_unit": "nano_degree_integer"},
  "manifest_sha256": "<自身を除く正規化表現のSHA-256>"
}
```

- `inputs[].products` は、原則として `all`（Normalize成果物の全成果品）。成果品を除外する場合は、除外の理由と根拠をManifestに記録する［提案］。
- Manifestの作成は、OWNERまたは承認された設定に基づく。最新の成果物を自動で選ぶ処理は設けない［提案］。
- 値は例示であり、実在するIDではない。

## 4. 地域の選別［提案］

### 4.1 方式（第一候補）

**Normalize成果物では原典の形状を保持し、Integrationで対象地域と面積で交差するポリゴンを選ぶ。原則として行政境界でポリゴンを切断しない。**

| 判定結果 | 扱い |
|---|---|
| 面積を持つ内部交差あり | 統合成果物に含める（ポリゴン全体を、原典の形状のまま） |
| 交差なし | 含めない |
| 境界の線・点で接するだけ | 含めない（地域内に面積を持たない） |
| 判定保留（境界が一致する縮退などで決まらない） | **Integrationを失敗させる**（暗黙に含める・除外することはしない）［未決定: 扱いの最終決定］ |

- 判定はPhase 2-A.4と同じく、10⁻⁹度の整数による厳密な計算で行う（Bounding Boxや標本点で代用しない）［実測: 26成果品の全ポリゴンで「接するだけ」「保留」は0件］。
- 選別の結果（成果品ごとの選ばれたポリゴン数と、交差した区市町村の一覧）を統合成果物とIntegration Recordに残す。
- 「面積交差あり」は、ポリゴンの一部が地域内にあることを意味する。統合成果物には地域外の部分も含まれるが、APIは地域外の地点を地域外として扱う（第10章）。

**N03は行政区域であり、A31aの洪水の評価済み範囲を証明しない。** 選別は「どの原典ポリゴンを索引に入れるか」を決めるだけで、地域内で区域に該当しない地点の意味（区域外か、未整備か）は決めない。

### 4.2 切り取り方式との比較（Phase 2-A.4 第7.3節の要約）

| 観点 | 選別のみ（第一候補） | 行政境界で切り取る |
|---|---|---|
| 原典の形状 | 保持（ハッシュで照合可能） | 加工される（加工の表示が必要） |
| データ量 | 交差するポリゴンだけ（例: 利根川626,847中12,637［実測］） | さらに小さい |
| 境界付近 | 判定は原典の形状に対して行う | 切り口が新しい境界になり、境界上の扱いが二重になる |
| N03の改版 | 選別だけをやり直す | 形状の再生成が必要 |
| 出典 | そのまま | 切り取ったポリゴンへの付け直しが必要 |

### 4.3 検索用の派生ジオメトリ（性能対策）［未決定］

巨大なポリゴン（荒川の1リング130,885頂点［実測］）は、点の内外判定が遅くなる（Pythonの単純な実装で1回あたり数〜十数ms［実測］）。対策として、検索用の**派生ジオメトリ**（例: 格子での分割、辺の格子索引）を別に生成する方式を、小規模な性能測定の後で比較する。派生ジオメトリを使う場合も、原典のポリゴン（`product_id`・`feature_index`・形状のハッシュ）と必ず関連付け、判定結果は原典のポリゴンに対する結果と一致しなければならない（第8章 IV-9）。

## 5. 重複の保持［提案］

前提となる事実［実測］:

- 異なる成果品の浸水区域が重なる。東京都本土の標本（7,121点）で、区域に該当した1,942点のうち858点が複数の成果品に該当し、595点はランクが異なる。最大6成果品。
- 東京都本土と面積交差するポリゴンのうち、17,331の形状が複数の成果品に同一の形で含まれる（大部分は多摩川・大栗川・浅川の間）。同一形状で成果品によりランクが異なるものが223ある。
- 同一成果品の内部では、重なりは見つかっていない（標本調査）。

契約原則:

1. **原典の各区域の情報（Feature単位）を失わない。** 統合成果物には、選ばれた原典Featureのすべてを、`product_id`・`feature_index`・管理者・河川コード・代表河川名・ランクとともに保持する。
2. **形状だけを根拠とした無条件の重複排除は禁止する。** 同一形状でもランク・出典が異なる。
3. 同一形状を内部で1つの形状として共有する最適化は認める。ただし、その形状に関連する全原典レコードを追跡できること。
4. 代表ランク（例: 最大ランク）は、統合成果物には格納しない（APIで全区域から計算できる）［提案］。**最大ランク方式は候補であり、管理者間の優先関係が原典で確認できていないため、OWNER承認待ち**［未決定］。

## 6. 統合成果物と空間検索［提案］

### 6.1 形式

第一候補: **SQLite**（標準ライブラリの `sqlite3`、RTreeモジュール）［実測: Macと既存APIのベースイメージで利用可能］。公開時は読取専用で開く。

### 6.2 論理構造

```text
zone_record       原典Feature 1件 = 1行（全件保持）
  record_id (PK), source_ref, normalize_run_id, product_id, feature_index,
  river_code, river_name_in_source, manager_code, manager_name, rank,
  source_geometry_sha256, geometry_id (FK)

geometry          形状（同一形状は1行に共有可）
  geometry_id (PK), geometry_sha256 (UNIQUE), type, n_polygons, n_rings, n_vertices,
  min_x, min_y, max_x, max_y, coords (BLOB: 整数座標。符号化方式は未決定)

geometry_rtree    RTree（geometry_id, min_x, max_x, min_y, max_y）
                  ※ 外接矩形だけを持つ候補抽出用

search_piece      （派生。第4.3節で採用した場合のみ）
  piece_id, geometry_id (FK), 範囲, 派生形状（原典形状と関連付け）

region_selection  成果品×区市町村ごとの選別結果（件数・判定方式）
metadata          Manifestの内容とSHA-256、処理版、入力のハッシュ、作成日時
```

### 6.3 責務の分離

| 段階 | 内容 |
|---|---|
| 候補抽出 | RTreeで、地点を含む外接矩形の形状を列挙する（**RTreeだけで判定は完了しない**） |
| 厳密な判定 | 候補の形状について、整数座標で点の内外を判定する（外周の内部かつすべての穴の外部。MultiPolygonは構成ポリゴンごと） |
| 境界上 | 地点が外周・穴の辺の上にある場合は「境界上（判定保留）」とし、内部・外部のどちらにも分類しない。原典は境界上の扱いを規定していない［実測］ |
| 結果 | 判定が「内部」の形状に関連する全 `zone_record` を返す。境界上の形状は別のリストとして返す |

### 6.4 測定と障害

- 測定項目: 統合成果物のサイズ（ディスク）、APIプロセスのメモリ、1地点の検索時間（RTreeの候補数、巨大ポリゴンの判定時間）、生成時間。代表的な地点（東京駅など）と、巨大ポリゴンの内部の地点、境界付近の地点で測る。
- 見積り: 座標を64ビット整数で保持すると、東京都本土と交差するポリゴンだけでも数百MB規模になる可能性がある［推定］。符号化方式（差分符号化等）は測定後に決める［未決定］。
- **形式・分割方式を確定する前に、小規模な性能検証を次工程で行うことを推奨する**［提案］。
- SQLiteの破損・読込失敗: 公開前のIntegrated Validateで `PRAGMA integrity_check` 等を行う。API起動時の検証に失敗した場合は起動しない（標高APIと同じ方針［確定: 標高APIの実装方針］）。稼働中の読込失敗は、該当なしとして扱わず、取得失敗としてAPIが報告する。

## 7. 来歴と再生成性［提案］

### 7.1 Integration Record

| 項目 | 内容 |
|---|---|
| `run_id`・`module`・`status` | 既存の実行結果の契約［確定］ |
| `manifest_ref`・`manifest_sha256` | 第3章 |
| `inputs[]` | 各入力のNormalize run_id・目録のSHA-256・Source Validate Recordの参照とSHA-256（Manifestと一致を確認した値） |
| `pipeline`・`configuration` | 処理版と設定スナップショット |
| `output` | 統合成果物の参照、ファイルのSHA-256、論理ハッシュ（第7.2節） |
| `selection_summary` | 成果品ごとの選択数・除外数、区市町村ごとの件数 |
| `started_at`・`completed_at` | UTC |

### 7.2 再生成性

**同じManifest（入力・処理版・設定・N03版）から、論理的に等価な統合成果物を再生成できることを必須とする。**

| 区別 | 定義 | v0.1の要件 |
|---|---|---|
| 論理的に等価 | 全テーブルの内容を、主キーで整列した正規化表現にしたときのハッシュ（論理ハッシュ）が一致 | **必須** |
| バイト単位で一致 | SQLiteファイルのSHA-256が一致 | 必須にしない。SQLiteのページ構成・挿入順・内部の空き領域で変わりうる。決定的な挿入順と `VACUUM INTO` 等で一致するかを、次工程で検証する［未決定］ |

来歴の連鎖: 原典ZIP（SHA-256）→ Acquisition Record → Normalize成果物（目録・出力のSHA-256）→ Source Validate Record → Integration Manifest → Integration Record（論理ハッシュ・ファイルハッシュ）→ Integrated Validate Record → Publish記録 → 公開Registry。

## 8. Integrated Validate［提案］

| No | 項目 | 方法 |
|---|---|---|
| IV-1 | Manifestとの一致 | 統合成果物の `metadata` のManifest・入力ハッシュ・処理版が、Integration Record・Manifestと一致 |
| IV-2 | 入力の合格 | すべての入力のSource Validate Recordが合格 |
| IV-3 | 成果品の過不足 | 入力の全成果品について、選別の結果（選択0件を含む）が記録されている |
| IV-4 | 地域の選別 | 選択されたポリゴンがすべて「面積交差あり」であることを、厳密な判定で独立に再計算して確認。選択されなかったポリゴンも再計算で「交差なし」または「接するだけ」 |
| IV-5 | 原典情報の保持 | 選択された原典Featureの件数・属性・ランクが、入力のNormalize成果物と一致（全件） |
| IV-6 | 重複関係の保持 | 同一形状を共有する `zone_record` の数・ランクの組合せが、入力から再計算した値と一致 |
| IV-7 | 索引の参照整合 | RTreeの全行が `geometry` を参照し、外接矩形が形状から再計算した値と一致。孤立した行がない |
| IV-8 | 代表地点の判定 | 固定の検証地点（例: 東京駅）で、期待する区域の一覧が返る。期待値には、原典ZIPのSHA-256・対象成果品・処理版を結び付ける（例: Phase 2-A.4の版では、東京駅は荒川（国）ランク1と隅田川の成果品（都）ランク1［実測］） |
| IV-9 | 特殊な形状 | 合成データで、穴の内部（区域外）・穴の境界上（判定保留）・外周の境界上（判定保留）・MultiPolygon・巨大ポリゴンの判定を確認。派生ジオメトリを使う場合は、原典形状での判定と一致 |
| IV-10 | 再生成 | 同じManifestから再生成した成果物の論理ハッシュが一致 |
| IV-11 | DBの完全性 | `PRAGMA integrity_check` が ok、読取専用で開ける |
| IV-12 | API互換 | APIの読取モジュールで開き、IV-8の地点を判定できる |

不合格の場合はFAILED。公開しない。

## 9. Dataset Registry / Publishとの接続

### 9.1 原則［確定］

- 公開Registryは、公開資格を持つデータだけの正本である。取得中・Normalize済み・Integration失敗などの状態を記録しない（Dataset Registry §3.8: 公開Registryの `validation.status` は `passed` だけ）。
- 取得・正規化・検証・公開の状態は、それぞれの記録で確認する（データソース定義 §4）。
- Publishの要件は、Integrated Validateの合格に加え、**利用条件の確認とOWNERの公開承認**である。

### 9.2 既存Registryとの差異・課題

| 課題 | 内容 | 案 |
|---|---|---|
| R-1 `source.filename` が単一の文字列 | 統合成果物は複数の原典ZIP（東京都2、関東地方整備局1、N03 1）から作られる。Dataset Registry §3.5で「複数ファイル表現はUNDECIDED」 | (a) Registryには代表の出典だけを表示し、全来歴は非公開のLineage Manifest（Integration Manifest・Record）に保持する。(b) 複数の出典を表す項目を追加する契約改訂。**いずれもOWNER判断**［未決定］ |
| R-2 `acquisition.input_dataset_ids` | 定義は「入力データセットの参照」（条件付き必須）。Normalize成果物は公開データセットではない | 統合成果物を `acquisition.method = generated` とし、`input_dataset_ids` にManifestのIDを入れる案があるが、既存の意味（データセット）と一致しない。改訂案として別途検討［未決定］ |
| R-3 `pipeline.id`・`pipeline.version` | 単一の処理を想定。flood はNormalize・Integrationの2つの処理版がある | Integrationの処理版をRegistryに、Normalizeの処理版はLineage Manifestに保持する案［未決定］ |
| R-4 `coverage` | 標高のP2（XYZタイル）は使えない。floodの評価可能範囲は、行政区域による選別とA31aの区域の組合せで、「評価済み範囲」は不明 | `coverage` の形式（例: 地域定義の参照）をflood用に決める改訂案が必要［未決定］ |
| R-5 `attribution` | 原典はA31a（国土交通省）・N03（国土交通省）。利用規約は出典と**加工の表示**を求める［実測］ | 出典文言の確定はOWNER判断［未決定］ |
| R-6 公開単位 | 標高は1タイル＝1データセット。floodは統合成果物1つ＝1データセットが候補 | ［未決定］ |

**既存のRegistryのフィールドを、本書では増減・変更しない。** 必要な改訂は、独立した改訂案としてOWNER承認を得る。

### 9.3 既存Elevation APIへの影響

本書の内容は `api/flood` の領域に閉じる。標高のRegistry・公開実体・API・Schemaは変更しない［提案］。Registryの改訂（R-1〜R-4）を採用する場合は、標高のRegistryとの互換性（既存の必須項目・Schemaの検証）を改訂案の中で評価する。

### 9.4 公開の可否

**現在のA31a・N03は、利用条件の未解決事項がある（ZIP内メタデータの「国土情報利用約款を参照」とデータページの「CC_BY_4.0」の差異など［実測］）。実データの一般公開を許可済みとして扱わない。**

## 10. Flood APIとの境界

最終的な応答Schemaは別工程で決める。統合成果物は、APIが次を返せるようにする［提案］:

- 指定地点に該当する全区域（`zone_record` の一覧）
- 各区域の原典ランク
- 河川コード
- 成果品の代表河川名（原因河川ではない）
- 管理者（コード・名称）
- 成果品ID、データの出典、公開版
- 境界上の判定状態（判定保留の区域の一覧）
- 地点が対象地域（N03による）の内部か外部か

安全上の原則:

- **区域のポリゴンが見つからない地点を、洪水リスクなし・評価済みの区域外と判定しない。** A31aは評価済みの範囲を持たない［実測］。
- `outside_inundation_zone` は、評価済み範囲が分からない制約により、A31aだけでは成立しない［実測］。対象地域の内部で区域に該当しない地点は `unknown` に相当する扱い（名称・定義はAPI契約で決める）。
- 対象地域の外部（N03で判定）の地点は `not_covered` に相当する扱い。

## 11. テストケース（設計のみ。実行していない）

| ID | 入力・条件 | 期待 |
|---|---|---|
| I-01 | 合格した4つのNormalize成果物とN03でManifestを作成 | Integration SUCCESS、Integrated Validate SUCCESS |
| I-02 | Manifestのハッシュと異なる入力（入力の差し替え） | FAILED（入力を変更・自動選択しない） |
| I-03 | Source Validateが不合格の入力 | FAILED |
| I-04 | 地域の境界に接するだけの合成ポリゴン | 選択されない |
| I-05 | 境界が地域の境界と一致する縮退の合成ポリゴン | 判定保留 → FAILED |
| I-06 | 同一形状でランクが異なる2つの原典Feature | 両方の `zone_record` が残り、形状は共有されうる |
| I-07 | 東京駅（Phase 2-A.4の入力版） | 荒川（国）ランク1と隅田川の成果品（都）ランク1の2区域 |
| I-08 | 穴の内部の地点 | その区域に該当しない |
| I-09 | 外周・穴の辺の上の地点 | 判定保留として返る |
| I-10 | 荒川の巨大ポリゴンの内部の地点 | 該当。判定時間を記録 |
| I-11 | 同じManifestで2回生成 | 論理ハッシュが一致 |
| I-12 | 統合成果物の1行を改変 | Integrated Validate FAILED |
| I-13 | RTreeの行を削除 | IV-7でFAILED |
| I-14 | Integrationの途中で中断 | 部分的な出力は公開されず、既存の公開世代が残る |
| I-15 | 対象地域の外部の地点 | 地域外として返る（区域の判定と区別） |
| I-16 | 地域の内部で区域に該当しない地点 | 「区域外」とせず、該当なし（評価済み範囲は不明）として返る |
| I-17 | 関東地方整備局の残り37成果品 | 選別の結果（多くは0件の見込み［推定］）が記録される |

## 12. 未決定事項とOWNER判断事項

| No | 事項 | 選択肢・推奨 |
|---|---|---|
| OI-1 | 地域の選別方式 | 選別のみ・切り取らない（推奨） |
| OI-2 | 判定保留の扱い | Integrationを失敗させる（推奨） |
| OI-3 | 検索用の派生ジオメトリ | 小規模な性能測定の後に決定 |
| OI-4 | 統合成果物の形式 | SQLite＋RTree（推奨）。座標の符号化は測定後 |
| OI-5 | バイト単位の再現性 | v0.1では論理ハッシュの一致を必須、バイト一致は検証して判断 |
| OI-6 | 代表ランクの方式 | 最大ランク方式は候補。管理者間の優先関係の確認後に決定 |
| OI-7 | 同一形状の共有 | 内部共有は可（全原典レコードの追跡を条件） |
| OI-8 | Registryの複数出典（R-1〜R-4） | Lineage Manifestで保持する案／Registry改訂案。改訂する場合は別文書 |
| OI-9 | 公開単位（R-6） | 統合成果物1つ＝1データセットが候補 |
| OI-10 | 出典・加工の表示文言 | 未決定 |
| OI-11 | 利用条件の照会 | 国土情報提供サイト運営事務局への照会の要否 |
| OI-12 | 隣接県（埼玉県・神奈川県）の追加 | 取得の承認後、Normalize成果物を追加してManifestに含める |
| OI-13 | 地域定義の管理方法 | 版管理された設定（`api/flood/conf/`）に置く案。東京都本土の規則（コード範囲・東京湾の所属未定地）の承認 |

本書の採用は、Integrationの実装・統合成果物の生成・公開の承認ではない。
