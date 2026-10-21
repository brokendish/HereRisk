# Flood Normalize Contract v0.1（案）

- Task: Phase 2-B Flood Normalize / Integration Contract v0.1
- 状態: **契約案（OWNERレビュー待ち。正式採用されていない）**。本書は実装の承認ではない
- 作成: 2026-10-21（Claude）
- 対象: 災害種別 `flood`、国土数値情報 A31a（2025年度・想定最大規模）、補助データ N03（行政区域、東京都2025年版）
- 関連: [Flood Integration Contract v0.1（案）](flood-integration-contract-v0.1.md)

区分: **［確定］** 既存の承認済み契約（FIXED等）に由来する事項、**［実測］** Phase 2-A.1〜A.4の実データ調査で測定した事実、**［提案］** 本書の設計提案（未承認）、**［未決定］** OWNER判断が必要な事項

根拠資料: [Phase 2-A.1](../../reviews/phase2/phase2a1-a31a-source-investigation.md)、[Phase 2-A.2](../../reviews/phase2/phase2a2-national-river-source-investigation.md)、[Phase 2-A.3](../../reviews/phase2/phase2a3-kanto-a31a-data-verification.md)、[Phase 2-A.4](../../reviews/phase2/phase2a4-n03-tokyo-coverage-verification.md)、[Dataset Registry設計](dataset-registry-v0.1.md)、[Data Publish設計](data-publish-v0.1.md)、[データソース定義設計](data-source-definition-v0.1.md)、[基本アーキテクチャ](basic-architecture-v0.1.md)

## 1. 目的・適用範囲

### 1.1 目的

A31a・N03の原典（公式配布ZIP）を、データソースごとに独立した**不変のNormalize成果物**へ変換し、後続のIntegrationが出典・ランク・形状を失わずに使える形にする。

### 1.2 適用範囲

| 項目 | 初期値 | 区分 |
|---|---|---|
| 災害種別 | `flood` | ［提案］ |
| データ | A31a 2025年度、想定最大規模（ZIP内フォルダ `20_想定最大規模`） | ［提案］ |
| データソース（原典ZIP） | `A31a-25_13_10_GEOJSON.zip`、`A31a-25_13_20_GEOJSON.zip`（東京都管理河川）、`A31a-25_83_10_GEOJSON.zip`（関東地方整備局） | ［実測: Phase 2-A.1・A.3で取得・検証済み］ |
| 補助データ | `N03-20250101_13_GML.zip`（行政区域） | ［実測: Phase 2-A.4］ |
| 将来の追加 | 埼玉県・神奈川県のA31a（未取得・未検証） | ［未決定］ |

全国対応の設計とし、東京都・関東地方整備局に固有の処理をコードに埋め込まない。データソースの一覧・対象成果品・地域の規則は、Source Definition（`api/flood/conf/`）の版管理された定義で与える［提案］。

### 1.3 本書で扱わないこと

Integration（統合・地域選別・空間索引）、Flood APIの応答Schema、Data Publish、Registryの変更。

## 2. パイプライン全体と本書の範囲

```text
Download ──► Normalize ──► Source Validate ──► Integration ──► Integrated Validate ──► Data Publish
 (ZIP取得)    (本書)        (本書)              (統合契約)       (統合契約)              (既存契約)
```

各工程は既存のPipeline Execution Contractに従う［確定］: 明確な終了ステータス（SUCCESS / FAILED / BLOCKED）、正常終了の場合だけOrchestratorが次工程を実行、各モジュールは後続を直接呼ばない、結果とログを `run_id` で関連付ける、ログは結果の代用にしない。既存の共通Orchestrator・Data Publish・Registryの責務は変更しない。

### 2.1 工程ごとの契約（本書の範囲）

| 工程 | 責務 | 入力 | 出力 | 成功条件 | 失敗条件 | 証跡 | 再実行の単位 | 中断後の再開 |
|---|---|---|---|---|---|---|---|---|
| Download | 公式ZIPの取得と完全性の確認 | Source Definitionの取得設定（URL・期待するファイル名） | `dl/` 配下のZIP、Acquisition Record | HTTP 200、Content-Lengthと実サイズの一致、SHA-256の記録、ZIP中央ディレクトリとCRCの検査、エントリのパス安全性（第6.1節）に合格 | 通信失敗、サイズ不一致、CRC不正、不審なエントリ（絶対パス・`..`・symlink・異常な圧縮率・想定外の巨大エントリ） | Acquisition Record（URL、HTTPヘッダー、サイズ、SHA-256、取得日時、設定スナップショット） | 1つの原典ZIP | 部分ファイルは確定させない。再開は新しい取得として完全性を最初から確認する |
| Normalize | 原典ZIPの対象メンバーを、規定の正規化表現に変換する | Download成功のZIP（Acquisition Recordで照合） | `work/` 配下のNormalize成果物（第4章）、`records/normalizations/` の証跡 | 対象メンバーをすべて変換し、出力のハッシュを記録 | 第5章の拒否条件に該当、入力ZIPのハッシュ不一致、出力の書込み失敗 | Normalize Record（第7章） | 1つの原典ZIP（＝1つのNormalize成果物） | 確定前の出力は不採用。同じ入力から新しい `run_id` で作り直す |
| Source Validate | Normalize成果物を原典と照合して合否を決める | Normalize成果物と、その原典ZIP | `records/source_validations/` の証跡 | 第8章の全項目に合格 | いずれかの項目に不合格 | Source Validate Record | 1つのNormalize成果物 | 何度でも同じ結果になる（読取専用） |

Integration以降は[Integration契約](flood-integration-contract-v0.1.md)。

### 2.2 既存のDownload実装との関係［実測・提案］

既存のDownload（Phase 1-A〜1-I）は標高PNG（1タイル）専用であり、ZIPの取得・検査を持たない［実測］。flood用には、同じ共通Orchestrator・保存層・Acquisition Recordの契約に従う、ZIP用のDownloadモジュールを `api/flood` 側に追加する必要がある［提案］。Phase 2-A.1〜A.4の調査で行ったZIPの検査（CRC、パス安全性、Windows形式の区切り、圧縮率）は、このDownloadの成功条件にする。

## 3. データソースの独立性

| 原則 | 内容 | 区分 |
|---|---|---|
| 1原典ZIP = 1 Normalize成果物 | 東京都管理河川は2つのZIP（`_10`・`_20`）なので、2つのNormalize成果物になる。関東地方整備局は1つ。N03は独立した補助のNormalize成果物 | ［提案］ |
| 相互に依存しない | あるデータソースのNormalizeは、他のデータソースの成果物を読まない。N03もA31aのNormalizeには使わない（地域の選別はIntegrationで行う） | ［提案］ |
| 不変 | 確定したNormalize成果物は変更しない。新版は新しい `run_id` の別成果物として作る。古い成果物は、参照する統合・公開世代がある間は削除しない | ［提案］（既存の上書き禁止・旧実体保護の原則に従う［確定］） |
| 対象メンバー | 原典ZIPの想定最大規模フォルダの**全成果品**を変換することを第一候補とする（関東地方整備局は48成果品） | ［提案］。理由: 東京都本土との交差は48成果品のうち11成果品でしか厳密に検証していない［実測］。調査結果で事前に絞ると、未検証の37成果品を「関係しない」と扱うことになる。地域の選別は、Integrationで全成果品に対して同じ方法で行う |
| 代替案 | Source Definitionで対象成果品を列挙し、それだけを変換する | ［未決定］。容量は小さくなるが、未検証の成果品を除外する根拠の記録が必要 |

## 4. Normalize成果物の論理構造

### 4.1 配置［提案］

既存のAPI別データ領域（`/data/<api>/` の `dl/`・`work/`・`rel/versions/`・`records/`）［確定］に従い、標高の配置（`work/normalized/<run_id>/…`、`records/normalizations/<run_id>.json`）と揃える。

```text
/data/flood/
  dl/current/<source_ref>/<原典ZIP名>                   Download（原典ZIP。変更しない）
  work/normalized/<run_id>/
    manifest.json                                       成果物の目録（第4.2節）
    members/<product_id>.ndjson                         成果品ごとの正規化レコード（1行1レコード）
  records/acquisitions/<run_id>/…                       Acquisition Record（既存契約の形式）
  records/normalizations/<run_id>.json                  Normalize Record（確定点）
  records/source_validations/<run_id>.json              Source Validate Record（確定点）
```

- `source_ref` はSource Definitionの取得設定ID（例: `ksj-a31a-2025-13-10`、`ksj-a31a-2025-83-10`、`ksj-n03-2025-13`。名称は［未決定］）。
- 保存層の書込み許可領域に `work/normalized`・`records/normalizations`・`records/source_validations` を追加する必要がある（標高と同様、明示的な最小追加）［提案］。

### 4.2 manifest.json（目録）［提案］

```json
{
  "schema": "hererisk-flood-normalized-manifest-v0.1",
  "run_id": "<Normalizeのrun_id>",
  "source_ref": "<Source Definitionの取得設定ID>",
  "source": {
    "acquisition_run_id": "<Downloadのrun_id>",
    "zip_name": "A31a-25_83_10_GEOJSON.zip",
    "zip_sha256": "<原典ZIPのSHA-256>",
    "dataset": "A31a", "reference_year": "2025", "scenario": "maximum",
    "scenario_folder": "20_想定最大規模"
  },
  "pipeline": {"id": "<未採番>", "version": "<未採番>"},
  "configuration": {"ref": "records/configurations/<run_id>/effective.json", "sha256": "<設定スナップショットのSHA-256>"},
  "crs": "EPSG:6668",
  "coordinate_unit": "nano_degree_integer",
  "members": [
    {"product_id": "A31a-20-25_83_8303040001_10",
     "zip_member": "20_想定最大規模\\A31a-20-25_83_8303040001_10.geojson",
     "member_size": 0, "member_crc32": "<ZIP中央ディレクトリの値>", "member_sha256": "<展開バイト列のSHA-256>",
     "output": "members/A31a-20-25_83_8303040001_10.ndjson", "output_sha256": "<出力のSHA-256>",
     "features": 0, "polygons": 0, "interior_rings": 0, "vertices": 0,
     "rank_counts": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0, "6": 0},
     "source_rank_type": "integer"}
  ]
}
```

値はすべて例示であり、実在する処理ID・公開版・承認証跡ではない。

### 4.3 正規化レコード（`members/<product_id>.ndjson` の1行）［提案］

1つの原典Feature＝1レコード。原典の順序を保つ。

```json
{"product_id": "A31a-20-25_83_8303040001_10", "feature_index": 0,
 "river_code": "8303040001", "river_name_in_source": "荒川",
 "manager_code": "83", "manager_name": "関東地方整備局",
 "rank": 1, "source_rank_literal": "1",
 "geometry": {"type": "Polygon", "coordinates": [[[139234567000, 35641250000], ["…"]]]},
 "source_geometry_sha256": "<原典Featureのgeometryの正規化JSON表現のSHA-256>"}
```

| 項目 | 型・規則 | 区分 |
|---|---|---|
| `product_id` | 原典GeoJSONのファイル名の幹（`name` メンバーと一致すること） | ［提案］ |
| `feature_index` | 0始まりの整数。原典ファイル内の出現順 | ［提案］ |
| `river_code` | 原典 `A31a_201`（文字列のまま） | ［実測: 全件に存在］ |
| `river_name_in_source` | 原典 `A31a_202`。**成果品の代表河川名であり、個別ポリゴンの原因河川ではない**（統合成果品・同一形状の重複がある） | ［実測］ |
| `manager_code`・`manager_name` | 原典 `A31a_203`・`A31a_204`（文字列） | ［実測］ |
| `rank` | 整数 1〜6 | ［提案］ |
| `source_rank_literal` | 原典の値の文字列表現（`"1"`）。原典の型は目録の `source_rank_type`（`integer`/`string`）に成果品単位で記録する | ［実測: 東京都は文字列、関東地方整備局は整数］ |
| `geometry` | `Polygon` / `MultiPolygon` のまま。各リングの頂点の順序・向き・穴を保持。座標は10⁻⁹度単位の整数（第6.3節） | ［提案］ |
| `source_geometry_sha256` | 原典geometryの正規化表現のハッシュ。同一形状の追跡と原典との照合に使う | ［提案］ |

- 浸水深ランクの区分境界（以上・未満）は**原典で未規定**であり、Normalizeは区分の数値を付け加えない（`depth_min_m` 等は持たない）［実測: 製品仕様書］。
- 原典にないキーを付け加えない。原典の追加キー（例: ルートの `xy_coordinate_resolution`）は目録に記録する。

### 4.4 N03（補助データ）［提案］

| 項目 | 規則 |
|---|---|
| 入力 | `N03-20250101_13_GML.zip` の **GML**（正本）。同梱のGeoJSON・Shapefileは使わない（GeoJSONは外周の向きが逆で、座標の桁数が異なる［実測］） |
| 安全な解析 | DOCTYPE・ENTITYの宣言を含むXMLは拒否する。外部エンティティを解決しない |
| 座標軸 | GMLの `posList` は（緯度, 経度）［実測］。正規化レコードは（経度, 緯度）の10⁻⁹度整数 |
| レコード | `administrative_area_code`、`municipality_name`、`district_name`（存在する場合）、`surface_id`、`geometry`（外周1・穴0以上） |
| 地域の区分 | **本土・島しょ部などの区分はNormalizeでは行わない**。区分の規則（例: 東京都本土＝行政区域コード13101〜13308と東京湾内の所属未定地）は、Integrationの地域定義（版管理された設定）で与える。公式属性には本土・島しょ部の区別がない［実測］ |
| 注意 | N03は行政区域を表すだけであり、A31aの洪水の評価済み範囲を表さない |

## 5. 拒否・隔離・許容の条件

**自動修復して成功扱いにすることは禁止する。**

| 条件 | v0.1の扱い［提案］ |
|---|---|
| ZIPの完全性（CRC、サイズ、ハッシュ）の不一致 | 拒否（Downloadで停止） |
| 不審なエントリ（絶対パス・`..`・ドライブ文字・NUL・symlink・異常な圧縮率） | 拒否（展開しない） |
| GeoJSONのルートが `FeatureCollection` でない、`crs` が EPSG:6668 でない | 拒否 |
| 必須属性（`A31a_201`〜`A31a_205`）の欠落・null・空 | 拒否 |
| ランクが整数1〜6（または文字列"1"〜"6"）以外 | 拒否 |
| geometryがnull・空、`Polygon`/`MultiPolygon` 以外 | 拒否 |
| 非有限値、2次元以外の座標 | 拒否 |
| 閉じていないリング、4点未満のリング | 拒否 |
| 小数10桁以上の座標（整数化で不可逆になる） | 拒否（第6.3節） |
| 連続する重複頂点 | 許容（件数を記録。変更しない）［未決定: 拒否にするか］ |
| 自己交差・位相の不正 | **［未決定］**（第6.2節） |
| 想定外の追加属性 | 許容（目録に記録） |

**隔離**（不正なFeatureを除外して残りを成功とする）は、v0.1では採用しない［提案］。採用する場合は、除外するFeatureを特定する検証プロファイルと、除外の証跡、OWNERの承認を必要とする［未決定］。

Phase 2-A.1・A.3の実データでは、上記の拒否条件に該当するFeatureは0件であった［実測］（自己交差は未検査）。

## 6. ジオメトリ

### 6.1 ZIPメンバーの扱い［提案］

- ZIP内のパス区切りはWindows形式（バックスラッシュ）である［実測: 全エントリ］。区切りとして解釈し、各要素を検査する。
- メンバーは調査時と同様に、1行1Featureの書式を前提にストリーミングで読む［実測: 最大626MBのファイルでピークRSS約230MB］。書式が想定と異なる場合は拒否する（全体を一度にメモリへ読み込む方式に切り替えない）。

### 6.2 自己交差・位相の検出方針［未決定］

| 案 | 内容 | 影響 |
|---|---|---|
| A | Source Validateで全リングの自己交差を整数演算で検査し、検出したら不合格 | 正確。頂点が約4,180万［実測］あり、走査線法等の実装と処理時間の見積りが必要 |
| B | 検査して件数を報告するが、合否には使わない | 不正な形状がIntegrationへ進む可能性 |
| C | v0.1では検査しない（未検査と明記） | 偶奇規則の内外判定が原典の意図と異なりうる |

推奨: **A**（ただし処理時間を小規模に測定してから確定）。自動修復はいずれの案でも行わない。

### 6.3 座標の表現［提案］

- 原典の座標は小数9桁以下である［実測: 関東地方整備局は `xy_coordinate_resolution` 1e-09、東京都も最大9桁］。10⁻⁹度単位の整数に変換すると**原典の数値を失わない**（逆変換で原典の10進表記を復元できる）。
- 変換は、JSONの数値を浮動小数としてではなく**10進の文字列**として読み、整数へ変換する。小数10桁以上の値は拒否する（丸めない）。
- 範囲: 経度・緯度とも符号付き64ビット整数に収まる。
- **整数化による形状の変化は、上記の条件下では発生しない**。より粗い単位（例: 10⁻⁷度）への丸めは不可逆であり、v0.1のNormalizeでは採用しない（Integrationの派生データで採用する場合は、そちらで評価する）。

### 6.4 座標系［未決定］

原典はJGD2011（EPSG:6668）である［実測］。API入力（WGS84）との扱いは、標高APIと同じ論点である。Normalizeは座標を変換せず、`crs` を記録する。API側で同一とみなすか、変換するかはFlood API契約で決める。位置正確度（A31aは標準偏差50m、N03は25m［実測: メタデータ］）に比べて差は小さいと考えられる［推定］が、同一であるとは主張しない。

## 7. Normalize Record（証跡）［提案］

| 項目 | 内容 |
|---|---|
| `record_schema_version` | 証跡の契約版 |
| `run_id`・`module`・`status` | 既存の実行結果の契約［確定］ |
| `source_ref`・`acquisition_run_id` | 入力の識別 |
| `input.zip_sha256` | Acquisition Recordの値と一致していることを確認した原典ZIPのハッシュ |
| `configuration` | 設定スナップショットの参照とSHA-256（実行開始時に固定）［確定: 開始時設定の固定］ |
| `pipeline` | 処理ID・版（未採番） |
| `manifest_ref`・`manifest_sha256` | 第4.2節の目録 |
| `outputs[]` | 成果品ごとの出力の参照・SHA-256・件数 |
| `warnings[]` | 許容した事項（連続する重複頂点の件数など） |
| `started_at`・`completed_at` | UTC |

Normalize Recordの確定（上書き禁止の新規作成）を、Normalize全体の成功の確定点とする。

## 8. Source Validate［提案］

### 8.1 検証項目

| No | 項目 | 方法 |
|---|---|---|
| V-1 | 入力の一致 | 原典ZIP・メンバーのSHA-256が目録と一致 |
| V-2 | 件数 | 成果品ごとに、原典のFeature数＝出力のレコード数 |
| V-3 | ランク分布 | 成果品ごとに、原典のランク別件数＝出力のランク別件数 |
| V-4 | 属性 | 欠損・null・空の件数が0。`river_code` 等が原典と一致（全件照合） |
| V-5 | geometry型 | Polygon / MultiPolygon の件数が原典と一致 |
| V-6 | 形状の構造 | ポリゴン数・穴の数・頂点数が原典と一致 |
| V-7 | 座標の可逆性 | 出力の整数座標を10進表記に戻した値が、原典の数値と一致（全頂点） |
| V-8 | 形状の妥当性 | 閉合・4点以上・有限値。自己交差は第6.2節の決定に従う |
| V-9 | 出力のハッシュ | 各出力ファイルのSHA-256が目録・Normalize Recordと一致 |
| V-10 | 目録の完全性 | 想定最大規模フォルダの全メンバーが目録にある（またはSource Definitionの列挙と一致） |

### 8.2 結果と報告

- Source Validate Record: 各項目の合否、件数、不合格の場合は最初のN件の位置（成果品ID・`feature_index`）。座標の値そのものは記録しない（位置情報の記録を最小にする）。
- 1項目でも不合格ならFAILED。Integrationの入力にできない。
- 合格したNormalize成果物とSource Validate Recordの組を、Integrationが入力として参照する。

## 9. 来歴と再生成性［提案］

- 来歴: Acquisition Record（原典ZIPのSHA-256）→ Normalize Record（処理版・設定・出力のSHA-256）→ Source Validate Record。
- 再生成性: 同じ原典ZIP・処理版・設定からは、**バイト単位で同一の出力**を生成することを要件とする（NDJSONの各行は、キー順・区切り・数値表記を固定した正規化JSONとし、原典の順序で出力する）。
- 再生成の確認: 同じ入力で2回実行し、出力のSHA-256が一致することをテストする（第11章）。

## 10. 既存契約との整合

| 既存契約 | 本書の扱い | 矛盾・差異 |
|---|---|---|
| Pipeline Execution Contract（data-publish §4） | そのまま適用 | なし |
| API別データ領域（基本アーキテクチャ §6.4、FIXED） | `/data/flood/` の `dl`・`work`・`records` を使う | 保存層の書込み許可領域の追加が必要（標高と同様） |
| Acquisition Record（データソース定義 §7） | 1つの原典ZIP＝1取得実体として適用 | 既存の項目「tile」は標高用。ZIP用の項目（ZIP名・メンバー一覧）が必要［未決定: 契約の追加］ |
| Source Definition（データソース定義 §3） | `api/flood/conf/sources.json` に取得設定を置く | 既存のSchemaは標高（`xyz_png`）用。flood用のSchemaが必要［未決定］ |
| 開始時設定の固定（基本アーキテクチャ §6.2、FIXED） | 設定スナップショットをNormalize Recordに固定 | なし |
| Dataset Registry | Normalize成果物は公開Registryに登録しない | なし |

既存の文書は本書では改訂しない。

## 11. テストケース（設計のみ。実行していない）

| ID | 入力 | 期待 |
|---|---|---|
| N-01 | Phase 2-A.1の東京都ZIP（`_13_10`） | SUCCESS。成果品7件、Feature数・ランク分布が調査値と一致 |
| N-02 | Phase 2-A.3の関東地方整備局ZIP | SUCCESS。成果品48件（想定最大規模） |
| N-03 | 同じ入力で2回実行 | 出力のSHA-256が一致 |
| N-04 | ランクが文字列の原典と整数の原典 | どちらも `rank` は整数、`source_rank_literal` と目録の `source_rank_type` に原典の型 |
| N-05 | 小数10桁の座標を含む合成データ | FAILED（拒否） |
| N-06 | 閉じていないリング・3点のリング・null geometry・NaN | それぞれFAILED |
| N-07 | ランク0・7・null | FAILED |
| N-08 | パスに `..` を含むZIP・symlinkのエントリ・異常な圧縮率 | 展開せずにFAILED |
| N-09 | 1行1Featureでない書式 | FAILED（全体読込みへ切り替えない） |
| N-10 | 穴・MultiPolygonを含む合成データ | 構造を保持（V-5・V-6が一致） |
| N-11 | 出力ファイルを1バイト改変 | Source Validate V-9でFAILED |
| N-12 | 確定済みの成果物への再書込み | 拒否（上書き禁止） |
| N-13 | N03のGMLにDOCTYPEを加えた合成データ | FAILED（解析しない） |
| N-14 | N03 GMLの座標軸 | 正規化レコードが（経度, 緯度）で、既知の地点（例: 千代田区の範囲）と一致 |
| N-15 | 自己交差を含む合成ポリゴン | 第6.2節の決定に従う |

## 12. 未決定事項とOWNER判断事項

| No | 事項 | 選択肢・推奨 |
|---|---|---|
| ON-1 | Normalize成果物の単位 | 1原典ZIP＝1成果物（推奨） |
| ON-2 | 変換対象の成果品 | 想定最大規模の全成果品（推奨）／Source Definitionで列挙 |
| ON-3 | 正規化表現の形式 | NDJSON（成果品ごと、整数座標）（推奨）／GeoJSONのまま／SQLite |
| ON-4 | 座標の単位 | 10⁻⁹度の整数（可逆。推奨） |
| ON-5 | 自己交差の検査 | 案A（不合格）を推奨。処理時間の測定後に確定 |
| ON-6 | 連続する重複頂点 | 許容して記録（推奨）／拒否 |
| ON-7 | 隔離の採用 | v0.1では採用しない（推奨） |
| ON-8 | ZIP用のAcquisition Record・flood用Source DefinitionのSchema | 既存契約への追加案を別途作成する |
| ON-9 | `source_ref` の命名規則 | 未決定 |
| ON-10 | 処理ID・版の採番 | 未決定（実在のIDを本書では定めない） |
| ON-11 | JGD2011とWGS84の扱い | Flood API契約で決定 |

本書の採用は、Normalizeの実装・実データの処理・公開の承認ではない。
