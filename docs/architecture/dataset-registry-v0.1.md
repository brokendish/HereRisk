# Dataset Registry Design v0.1

- Status: Draft（初期ドラフトのOWNERレビュー承認済み。未決定事項は継続検討）
- Date: 2026-10-13
- Task ID: dataset-registry-design-v0.1
- 基準: [Project Charter v0.5](../project-charter.md)、[AI共通作業規約](../development/ai-development-policy.md)

## 1. 目的と確定範囲

Dataset Registryは、Hazard APIが利用する公開済みデータセットの「履歴書」であり、公開資格を持つデータだけを管理する正本である。Registry JSONは、取得元から取得方式・処理方法・公開データまでを追跡するためのメタデータを保持する。

本書は設計書であり、実際のRegistry JSON、JSON Schema、パイプライン、設定ファイルは作成しない。全国対応を前提に東京のデータで検証する方針を維持する。洪水のサンプルは設計説明用であり、標高を対象とするMVP 0の実装範囲を拡大しない。

OWNERが共有した既存フィールド一覧を初期ドラフトとして反映した。フィールドの型・必須区分と、詳細方式の確定度を区別する。追加承認された5フィールドを維持し、取得方式の分類等はPROVISIONAL（暫定）、詳細未決定事項はUNDECIDEDとする。全項目が最終FIX済みという意味ではない。
## 2. 基本原則と責務

| 担当・要素 | 責務 |
|---|---|
| 公開Registry JSON | 公開資格を満たした公開済みデータセットの正本。処理途中の状態・過去の処理履歴を蓄積しない |
| Data ManagerのPublish処理 | 公開資格を確認し、公開Registryを更新する唯一の処理 |
| Download / Normalize / Validate | 取得・正規化・検証を行う。公開Registryを変更しない |
| Hazard API | 公開Registryを読み取り専用で参照し、実データに基づき評価する。Registryを書き換えない |
| common / Dataset Selector | 明確な契約を通じて地域・対象範囲・災害種別等から選択する。判定処理や公開管理の責務を引き取らない |
| API固有conf / conf/common（将来） | パイプラインの処理定義を管理する。今回ディレクトリ・設定を作成しない |

公開失敗時は旧Registryと旧公開データを維持する。取得元、取得方式、処理方法、公開データの参照を区別し、互いを追跡可能にする。Coverageは都道府県をまたぐ収録範囲を許容する。

既存モジュールの責務と公開契約を意図せず変更しない。契約はバージョン管理と互換性を考慮する。意図的な変更には影響評価・回帰テスト・OWNER承認を必要とする。将来利用だけを理由に未使用の共通処理を実装しない。

## 3. JSONフィールド定義

### 3.1 区分と確定度

| 区分 | 意味 |
|---|---|
| 必須 | すべての公開データセットに必要（Registry全体の項目は各Registryに必要） |
| 条件付き必須 | 取得方式・データ形式・利用条件等に応じて必須 |
| 任意 | 利用可能な場合に記録する |
| 未決定 | 詳細設計で決定する |

以下のキー・型・区分は提供された既存設計案を保持した初期ドラフトである。PROVISIONALは暫定案、UNDECIDEDは未決定を示す。区分が必須であっても、採番・日時形式等の詳細まで確定したとは扱わない。

Dataset共通のパスは `datasets[]` 内を基点とする。Identityのid/name/hazardはその直下に配置し、独立したidentityオブジェクトは追加しない。

### 3.2 Registry全体

| フィールド | 型 | 区分 | 意味・確定度 |
|---|---|---|---|
| `schema_version` | `string` | 必須 | Registry契約の版。版の規則・移行方式はUNDECIDED。 |
| `prefecture_code` | `string` | 必須 | JSONの都道府県区分。実際の評価可能範囲とは区別する。 |
| `datasets` | `array` | 必須 | 公開資格を満たしたデータセットの配列。 |
| `registry_revision` | `string` | 未決定 | Registryの改訂識別。採用・更新規則はUNDECIDED。 |

### 3.3 Dataset共通・Identity

| フィールド | 型 | 区分 | 意味・確定度 |
|---|---|---|---|
| `id` | `string` | 必須 | データセット識別子。採番・一意性の範囲はUNDECIDED。 |
| `name` | `string` | 必須 | データセット名。 |
| `hazard` | `string` | 必須 | 対象災害種別。列挙値の詳細はUNDECIDED。 |
| `coverage` | `object` | 必須 | 評価可能範囲。 |
| `source` | `object` | 必須 | 取得元の情報。 |
| `acquisition` | `object` | 必須 | 取得方法。 |
| `pipeline` | `object` | 必須 | 使用した処理の識別情報。 |
| `validation` | `object` | 必須 | 公開対象の検証情報。 |
| `publication` | `object` | 必須 | 公開データ実体の情報。 |
| `attribution` | `object` | 条件付き必須 | 利用条件に応じた出典・ライセンス表記。 |

### 3.4 Coverage

| フィールド | 型 | 区分 | 意味・確定度 |
|---|---|---|---|
| `coverage.ref` | `string` | 条件付き必須 | 評価可能範囲への参照。適用条件・参照形式はUNDECIDED。 |
| `coverage.bbox` | `number[4]` | 任意 | 外接矩形。座標順序・地理判定への利用方法はUNDECIDED。 |
| `coverage.prefectures` | `string[]` | 任意 | 関係する都道府県。境界を越える収録を許容する。 |
| `coverage.crs` | `string` | 条件付き必須 | 座標参照系。必要条件・表記方式はUNDECIDED。 |
| `coverage.mode` | `string` | 未決定 | 範囲表現の方式。UNDECIDED。 |

### 3.5 Source

| フィールド | 型 | 区分 | 意味・確定度 |
|---|---|---|---|
| `source.provider` | `string` | 必須 | 取得元の提供主体。 |
| `source.page_url` | `string` | 任意 | 提供元の案内ページ。実取得URLとは区別する。 |
| `source.format` | `string` | 必須 | 元データ形式。 |
| `source.retrieved_at` | `string` | 条件付き必須 | 取得時点。方式別適用条件・日時形式はUNDECIDED。 |
| `source.original_version` | `string` | 任意 | 元データのバージョン。 |
| `source.filename` | `string` | 条件付き必須 | 取得元ファイル名。ファイル取得のないAPI・内部生成方式では必須としない。複数ファイル表現はUNDECIDED。 |

### 3.6 Acquisition

| フィールド | 型 | 区分 | 意味・確定度 |
|---|---|---|---|
| `acquisition.method` | `string` | 必須 | 取得方式。http / api / manual / generatedの分類詳細はPROVISIONAL。 |
| `acquisition.url` | `string` | 条件付き必須 | 取得に使用するURL。方式ごとの適用条件はPROVISIONAL。 |
| `acquisition.generator` | `string` | 条件付き必須 | 生成元の識別。生成方式での詳細とpipelineとの境界はUNDECIDED。処理識別を二重管理しない。 |
| `acquisition.input_dataset_ids` | `string[]` | 条件付き必須 | 入力データセットの参照。適用条件・版の解決方法はUNDECIDED。 |
| `acquisition.parameters` | `object` | 任意 | 取得条件。方式別の項目はUNDECIDED。秘密情報を格納しない。 |

### 3.7 Pipeline

| フィールド | 型 | 区分 | 意味・確定度 |
|---|---|---|---|
| `pipeline.id` | `string` | 必須 | 処理を一意に識別するID。使用した処理版はversionと組み合わせて識別する。 |
| `pipeline.name` | `string` | 必須 | 人間向けの処理名。検索キーや処理識別に使わない。 |
| `pipeline.version` | `string` | 必須 | 実際に使用した処理定義のバージョン。表記規則はUNDECIDED。 |

### 3.8 Validation

| フィールド | 型 | 区分 | 意味・確定度 |
|---|---|---|---|
| `validation.status` | `string` | 必須 | 公開Registryではpassed。pending、failed等を登録しない。 |
| `validation.profile` | `string` | 必須 | 使用した検証基準の識別。詳細形式はUNDECIDED。 |
| `validation.validated_at` | `string` | 必須 | 検証時点。日時形式はUNDECIDED。 |

### 3.9 Publication

| フィールド | 型 | 区分 | 意味・確定度 |
|---|---|---|---|
| `publication.version` | `string` | 必須 | 公開データの版。pipeline.versionやschema_versionとは別概念。 |
| `publication.path` | `string` | 必須 | 内部公開データ実体の参照先。原則バージョン付きの不変実体を参照する。基点・解決方法はUNDECIDED。 |
| `publication.format` | `string` | 必須 | 公開データ形式。 |
| `publication.published_at` | `string` | 必須 | 公開時点。日時形式はUNDECIDED。 |
| `publication.filename` | `string` | 必須 | 内部公開ファイル名。取得元ファイル名とは別に保持する。 |
| `publication.checksum` | `string` | 未決定 | 必須性・方式・検査時機はUNDECIDED。 |

### 3.10 Attribution

| フィールド | 型 | 区分 | 意味・確定度 |
|---|---|---|---|
| `attribution.text` | `string` | 条件付き必須 | 利用条件が要求する出典表記。 |
| `attribution.license` | `string` | 条件付き必須 | 利用条件・ライセンス。詳細表現はUNDECIDED。 |
| `attribution.url` | `string` | 任意 | 出典・利用条件に関する参照URL。 |

### 3.11 Transformation旧案と処理識別の集約

| 旧案フィールド | 型 | 旧案の区分 | 今回の扱い |
|---|---|---|---|
| `transformation.processor` | `string` | 条件付き必須 | 独立領域の必要性はUNDECIDED。pipeline.idと重複して必須にしない |
| `transformation.version` | `string` | 条件付き必須 | 独立領域の必要性はUNDECIDED。処理版はpipeline.versionへ集約 |
| `transformation.parameters` | `object` | 任意 | 独立領域とパラメータの保持方式はUNDECIDED |

旧案は検討経緯として保持し、現在の必須フィールドへ追加しない。原則として処理識別を `pipeline.id` と `pipeline.version` に集約する。pipeline.nameは表示用とする。

Registryには実行コード、コマンド、処理手順の定義を埋め込まない。将来の `api/<api>/conf/` または `conf/common/` が責務に応じて実行定義を管理し、Registryはどの処理を使ったかを記録する。定義の詳細形式はUNDECIDED。取得パラメータは取得条件の記録であり、実行定義の複製にしない。

出典表記や利用条件を確認できないデータに無条件で公開資格を与えない。attributionが条件付き必須であることは、この確認の省略を認めない。

## 4. 取得方式と拡張

| 初期候補 | 用途の説明（詳細契約は未決定） |
|---|---|
| `http` | 配布ファイル等をHTTP経由で取得 |
| `api` | 提供元API経由で取得。httpとの分類境界・取得条件の表現は後続で定義 |
| `manual` | 人が入手したデータを受け渡す。取得元・条件の追跡を省略しない |
| `generated` | 別の入力から生成。入力の由来と生成処理を追跡可能にする |

候補をすべて先行実装することは要求しない。方式固有の入力・認証方法・再取得条件は必要になった時点で契約を拡張する。認証情報や秘密を含むURLはRegistryへ格納しない。

## 5. 公開資格と失敗時の契約

Publish前に、少なくとも以下を確認する。

1. 合意済み契約の必須項目・条件付き必須項目が満たされている。
2. 公開データ実体が存在し、参照可能である。
3. 対象データが品質検証を通過し、検証対象と公開実体が対応している。
4. 出典・利用条件・再配布条件を確認し、必要な表示を用意している。
5. 識別子、取得元、パイプラインのID・バージョン、公開参照先、Coverageの参照整合性が確認できる。

Validate完了だけでは公開Registryを変更しない。Data ManagerのPublish処理が正常完了したときに公開Registryの更新を確定する。実体とRegistryの切替えの途中状態を読者へ見せず、失敗時には旧Registryと旧公開データを参照可能なまま維持する。旧実体を先に上書き・削除する方式ではこの条件を満たせない。

切替えの原子性、同時Publishの排他、複数の都道府県JSON間の整合性、旧実体の保持期間・回収方法は後続の設計事項である。特定のファイル操作やストレージ方式を本書で固定しない。

Registry登録後に実体の欠損・破損・参照不整合が判明した場合、Hazard APIは正常な評価結果や危険区域外へ変換しない。Charterの取得失敗・判定不能等として不明を明示する。具体的な応答フィールド・HTTPコード・エラー分類はAPI契約で決める。Registry自体が読めない場合も、空の正常結果として扱わない。

## 6. 地域・Coverage・選択

都道府県別JSONを基本とするが、ファイルの分割単位は評価可能範囲の保証ではない。都県境をまたぐデータ、行政区域の一部だけを評価するデータを許容する。共通の地域解決・データセット選択処理を用い、東京専用の処理を複製しない。

同じ地点を評価できる複数データセットが存在してよい。Coverageの詳細表現、都道府県JSON間の参照・重複保持、重複候補の優先順位・統合・競合時の扱いは未決定である。単純な先着順や「該当なし」を優先する規則を仮定しない。

データ未整備・範囲外と、評価可能なデータに基づくハザード区域外を区別する。ポリゴンが存在しないことだけを評価可能性の根拠にしない。評価不能な地点を安全と扱わず、非該当も安全を保証しない。

## 7. 追跡・再構築

Registryから取得元・取得方式・実際に使用した `pipeline.id` と `pipeline.version` を追跡できることを要件とする。処理定義の更新に合わせて、既に公開したデータのRegistryに記録した処理バージョンを書き換えない。新しい処理による生成・検証・公開は別の公開更新として扱う。

識別情報があることだけでは再構築を保証しない。旧処理バージョン、元データ、利用条件、必要な設定や依存環境を利用できるか確認する。旧バージョンが利用できない、元データが取得できない、再現条件が不明な場合は再構築可能と表示しない。新しい処理版で代替した結果を旧版による再構築と偽らない。

旧処理定義・入力・設定の保存方式と再構築可否の表示契約は未決定。Registryに過去の実行履歴を蓄積することで代替しない。

## 8. JSONサンプル

以下は東京都の洪水データセット1件を説明するための架空サンプルである。URL、ファイル名、ID、バージョン、出典、利用条件、検証結果はすべて架空であり、実データの公開資格・検証成功を示さない。URLへアクセスして取得・検証していない。

提供された初期ドラフトのRegistry全体・datasets配列・フィールド型を使用する。名前を持つ元ファイルをHTTPで取得し、出典表示が必要となる例を想定する。`validation.status` の `passed` も架空の値であり、実検証の成功を意味しない。Coverage参照、コード表記、パス、日時、検証profileは説明用であり、詳細方式の確定ではない。任意・未決定項目は網羅しない。正式なJSON Schemaへの適合を示すものではない。

```json
{
  "schema_version": "0.1",
  "prefecture_code": "13",
  "datasets": [
    {
      "id": "example-tokyo-flood",
      "name": "架空の東京都洪水データセット",
      "hazard": "flood",
      "coverage": {
        "ref": "example/coverage/tokyo-evaluation-area.geojson",
        "prefectures": [
          "13"
        ],
        "crs": "EPSG:4326"
      },
      "source": {
        "provider": "架空の提供主体",
        "page_url": "https://example.invalid/source",
        "format": "zip",
        "retrieved_at": "2026-10-01T00:00:00Z",
        "original_version": "example-source-v1",
        "filename": "example-tokyo-flood-source.zip"
      },
      "acquisition": {
        "method": "http",
        "url": "https://example.invalid/source/example-tokyo-flood-source.zip"
      },
      "pipeline": {
        "id": "example-flood-normalize",
        "name": "架空の洪水データ正規化処理",
        "version": "example-pipeline-v1"
      },
      "validation": {
        "status": "passed",
        "profile": "example-flood-profile-v1",
        "validated_at": "2026-10-02T00:00:00Z"
      },
      "publication": {
        "version": "example-publication-v1",
        "path": "example/published/example-publication-v1/example-tokyo-flood.geojson",
        "format": "geojson",
        "published_at": "2026-10-03T00:00:00Z",
        "filename": "example-tokyo-flood.geojson"
      },
      "attribution": {
        "text": "架空の出典表記",
        "license": "架空の利用条件。実データの利用許可ではない",
        "url": "https://example.invalid/terms"
      }
    }
  ]
}
```

## 9. OWNERレビューで確定する事項

- 初期ドラフトの詳細契約の承認。必須区分を保持したうえで型の制約・識別子・日時等の詳細を決定。
- source.filenameのファイル取得時の扱いを維持し、複数入力・複数公開ファイルの表現を決定。
- registry_revisionの採用、識別子・公開版・契約版の規則と互換性管理。
- Coverageの表現、都道府県別JSON間の参照と重複選択方式。
- 品質検証基準・証跡、checksumの必須性・方式、破損検知、API異常応答の詳細契約。
- Publishの整合性・排他・失敗復旧・旧データ保持を満たす方式。
- PROVISIONALな取得方式分類・追加パラメータ、Transformation領域の独立性、パイプライン定義の詳細形式、旧処理・入力・設定の再現条件と保持方式。

以上は未決定のまま管理し、実装着手前に必要な範囲をレビュー・承認する。

## API独立性との接続（2026-10-16契約改訂）

Source Definitionは各 `api/<api>/conf/sources.json` に配置し、共通Configuration Managerでスコープ付き解決を行う。公開Registryのフィールド・公開資格は変更しない。APIは原則自APIの公開データのみ読み取り、他APIの内部Registry・実体を直接参照しない。共通管理処理は認可されたAPI領域に限って処理する。

公開実体は論理領域 `/data/<api>/rel/versions/`、取得・処理証跡は `/data/<api>/records/` の責務に属する。Registryの物理配置は未決定。API識別・公開版・実体と証跡の対応をバックアップ・復元でも維持し、ディレクトリ名やSource Definitionから公開状態を決めない。Publishのみ更新、Generation/Restoreは直接更新しない原則を維持する。
