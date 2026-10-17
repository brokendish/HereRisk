# HereRisk — Data Publish Design v0.1

**Document:** `docs/architecture/data-publish-v0.1.md`  
**Status:** Draft / OWNERレビュー対象（標高APIへの適用として改訂P6・P7を2026-10-17にOWNERが正式採用。末尾を参照）  
**Task ID:** `data-publish-design-v0.1`

**関連文書**
- `docs/project-charter.md` — v0.5
- `docs/architecture/dataset-registry-v0.1.md`
- `docs/development/ai-development-policy.md`

---

## 1. 目的

Data Publishは、検証済みデータをHazard APIが利用可能な状態として公開確定するための独立した処理である。

単なるファイルコピーではなく、Dataset Registryへの登録を通じて、データセットへAPI利用資格を与えることを目的とする。

本設計は全国対応を前提とする。初期実装・実データ検証は東京都から開始する。

## 2. 基本原則

1. 公開確定点はRegistryの原子的な切り替えとする。
2. Publish前に公開データの資格と整合性を確認する。
3. 新データは既存データを上書きしない。
4. 公開確定前の失敗では旧Registryと旧データを維持する。
5. 同時Publishによる更新消失を防止する。
6. Hazard APIに更新途中のデータを見せない。
7. 公開データは世代管理により復旧可能性を確保する。
8. Publish、Generation、Restoreの責務を分離する。

上記を設計原則として採用する。具体的なファイル配置・排他実装・公開世代の識別方式は、後続の詳細設計で決定する。

## 3. モジュールの責務

| モジュール | 責務 |
|---|---|
| Data Manager / Orchestrator | 処理の起動、順序制御、終了状態の判定 |
| Download | データ取得 |
| Normalize | 取得データの正規化 |
| Validate | データの品質・整合性検証 |
| Data Publish | 公開資格確認、公開実体の確定、Registryの原子的切り替え |
| Generation Manager | 過去世代のアーカイブ、圧縮、保持数管理、整理 |
| Restore Manager | 過去世代の展開、整合性検証、復元候補の準備 |
| Dataset Registry | 現在公開中のデータセット情報の正本 |
| Hazard API | 現行Registryおよび参照データの読み取り |

モジュールは他モジュールの責務を代行しない。

Generation ManagerとRestore ManagerはRegistryを直接書き換えない。

Restoreによって準備された候補を公開する場合も、Data Publishを経由する。

## 4. Pipeline Execution Contract

### 4.1 共通実行原則

次の8原則を適用する。

1. 各モジュールは明確な終了ステータスを返す。
2. 正常終了した場合のみ、Orchestratorが次の処理を実行する。
3. 異常終了時は後続処理を停止し、エラー情報を返す。
4. 各モジュールは統一された形式の構造化ログを出力する。
5. ログはsyslog系基盤へ集約可能とする。
6. 実行結果とログを共通の `run_id` で関連付ける。
7. 各モジュールは後続モジュールを直接呼び出さない。
8. Publish後の世代管理失敗は、公開済み状態と区別して報告する。

### 4.2 終了ステータス

基本契約は以下とする。

- 正常終了：SUCCESS
- 異常終了：FAILED
- 実行不能：BLOCKED等の理由を識別可能とする

Linuxコマンドとして実行する場合、終了コード `0` を正常終了、それ以外を異常終了とする。

具体的な非ゼロ終了コードの割り当てはPROVISIONALとする。

実行結果には少なくとも次の情報を持たせる。

- `run_id`
- `module`
- `status`
- `error_code`（異常時）
- `message`（必要時）

詳細なJSON形式は共通実行契約の詳細設計で決定する。

ログは実行結果の代用とせず、実行結果を処理制御の正本とする。

### 4.3 構造化ログ

基本ログレベルは以下とする。

| Level | 用途 |
|---|---|
| INFO | 正常開始・正常終了・処理結果 |
| WARNING | 継続可能な問題・注意事項 |
| ERROR | 処理失敗・継続不能な異常 |

基本ログフィールド案：

- timestamp
- level
- service
- module
- run_id
- dataset_id
- pipeline_id
- pipeline_version
- error_code
- message

ログフィールドの必須性、日時形式、ログスキーマバージョンはPROVISIONAL。

ログには秘密情報、認証情報、不要な利用者位置情報を記録しない。

### 4.4 syslog / journald

Linux運用でsyslog系ログとして収集可能な構成とする。

Docker環境では、構造化ログを標準出力・標準エラーへ出力し、ホスト側のログ機構でjournaldへ収集する方式を基本候補とする。

受入条件：

- `journalctl` から対象モジュールのログを確認できる。
- `run_id` で同一処理のログを追跡できる。
- INFO / WARNING / ERRORの重要度を識別できる。
- 必要な場合、journaldのPRIORITYで重大度別の絞り込みができる。

ログドライバー、syslog priorityへの変換方式、ログ保持期間は後続設計で決定する。

## 5. Data Publish Input / Output

### 5.1 Input案

| 項目 | 区分 | 内容 |
|---|---|---|
| dataset_id | 必須 | 対象データセット |
| candidate_id | 必須 | 検証済み公開候補 |
| run_id | 必須 | 処理追跡ID |
| expected_registry_revision | PROVISIONAL | 更新競合検出用 |
| requested_by | 内部管理 | 認可済み実行主体 |

取得URLや加工条件をPublishへ重複入力させず、検証済み候補の情報から取得する。

### 5.2 Output案

| 項目 | 区分 | 内容 |
|---|---|---|
| run_id | 必須 | 処理追跡ID |
| dataset_id | 必須 | 対象データセット |
| status | 必須 | 実行結果 |
| publication_version | 成功時必須 | 公開確定した版 |
| registry_revision | PROVISIONAL | 公開後のRegistry世代 |
| error_code | 失敗時必須 | 失敗理由 |
| message | 任意 | 補足説明 |

具体的なフィールド名称・型・戻り値の詳細は暫定とする。

## 6. 通常公開処理

基本フロー：

1. OrchestratorがPublishを要求する。
2. 検証済み候補と公開資格を確認する。Publishの認可には、公開条件（`license`、`attribution_url`）が必要である。欠ける場合はAPPROVAL_REQUIREDとし、公開領域に何も書かない（P7、2026-10-17 OWNER承認）。
3. 新データをバージョン付き不変領域へ準備する。
4. 実体・参照先・メタデータの整合性を確認する。
5. 必要な復旧用世代が失われないことを確認する。
6. 新Registryを作成し、スキーマと参照整合性を検証する。
7. 更新競合・排他条件を確認する。
8. Registryを原子的に切り替えて公開確定する。
9. 結果をOrchestratorへ返す。
10. 公開状態を保護したまま、Generation Managerによる圧縮・整理を別処理として実行する。

新Registryの切り替えが完了するまでは、旧Registryが正本である。

切り替えが成功した後は、新Registryが正本となる。

切り替え後に応答が失われた場合は、実際の公開状態を確認して結果を判定し、無条件に再実行しない。

## 7. 世代管理

### 7.1 基本方式

Linuxのlogrotateに近い方式を採用する。

- 原則3世代を保持する。
- 現行1世代は展開済みでAPI参照可能とする。
- 過去2世代は圧縮アーカイブで保持する。
- 保持世代数の共通定義は `conf/common/`、API固有定義は `api/<api>/conf/` に配置し、共通Configuration Managerで解決する。項目別上書き可否は別途定義し、他APIへ波及させない。
- 世代管理はデータセット単位を基本とする。

圧縮方式の初期候補は `tar.gz` またはZIPとし、形式はPROVISIONALとする。

圧縮率・処理時間はデータ形式に依存するため、実データで検証する。

### 7.2 Generation Manager

Generation Managerの責務：

- 過去世代の保管
- データ本体と対応メタデータのアーカイブ
- 圧縮
- アーカイブの整合性確認
- 保持世代数の管理
- 不要世代の整理

以下は責務に含めない。

- 公開Registryの更新
- データの復元・展開
- 公開確定
- Hazard APIの判定

過去世代には、その世代のデータ本体と対応するRegistryメタデータを保持する。

圧縮処理はAPIが参照するデータを破壊しない方法で実施する。

### 7.3 世代削除

世代削除は次の条件を満たす場合に限る。

- 現行Registryから参照されていない。
- 実行中のAPIが使用していない、または安全な参照終了を保証できる。
- 保持数と復旧要件を満たしている。
- 保管済みアーカイブの整合性が確認されている。

参照中のデータを削除してはならない。

参照終了の判定・安全な回収方式はUNDECIDEDとする。

## 8. Restore Manager

Restore Managerは以下を担当する。

1. 指定された世代アーカイブの選択
2. アーカイブの展開
3. データ本体とメタデータの整合性確認
4. 公開候補として利用可能な状態への準備
5. 復元結果の返却

Restore Managerは公開Registryを変更しない。

ロールバック時は、Restore Managerが準備した候補をData Publishが再検証し、公開する。

旧世代のパイプラインID、バージョン、出典、Coverage、検証情報を対応させ、旧データと新メタデータの混在を防ぐ。

復元に必要なディスク空き容量が不足する場合は、事前にエラーとして扱う。

アーカイブから展開できたことだけでは、公開成功とはしない。

## 9. 異常時の扱い

| 状況 | 必須動作 |
|---|---|
| Download失敗 | Normalize以降を実行しない |
| Normalize失敗 | Validate以降を実行しない |
| Validate失敗 | Publishしない |
| Publish前の確認失敗 | 旧Registryを維持 |
| 新データ配置失敗 | 旧Registryを維持 |
| Registry作成失敗 | 旧Registryを維持 |
| 更新競合 | 上書きせず異常終了 |
| 切替え後の応答不明 | 現在のRegistryを照会して確定状態を判断 |
| 公開後のデータ異常 | 健全な旧世代への復元・再公開を検討 |
| Publish後の圧縮失敗 | 公開成功と世代管理異常を区別して報告 |
| Restore失敗 | 公開Registryを変更しない |

Registry自体や参照データが破損した場合、Hazard APIは正常結果や「危険区域外」として処理しない。

自動ロールバックの発動条件はUNDECIDEDとする。

## 10. 同時Publish・地域境界

同一Registryに対する同時Publishで更新の消失を発生させない。

排他制御と更新世代の照合を必要とする。

同じデータセットが東京都と神奈川県など複数都道府県のRegistryに関係する場合、片方だけが更新された不整合状態をAPIへ見せないことを要求する。

複数Registryにまたがる原子的切り替えの具体方式はUNDECIDEDとする。

都道府県単位のRegistry管理と、データセット単位の公開・世代管理は別の概念として扱う。

## 11. セキュリティ・運用

- 管理操作には認証・認可を必要とする。
- Publish・世代管理・Restoreは権限を分離する。
- 一般向けHazard APIには公開Registryの更新権限を与えない。
- 公開データを原則不変とする。
- アーカイブの内容と参照先を検証する。
- Restore時はパストラバーサルや不正なシンボリックリンク等を防止する。
- ログ・Registry・公開サマリーに秘密情報を格納しない。
- 空き容量不足、ディスクI/Oエラー、アーカイブ破損を異常として扱う。
- 本番操作にはOWNERの承認を必要とする。

## 12. テスト・受入条件

以下を段階的に検証する。

1. 正常な候補のみ公開できる。
2. 途中失敗で旧Registryを維持する。
3. 新世代公開中も旧データを破壊しない。
4. 同時Publishによる更新消失がない。
5. 指定世代の圧縮・保持ができる。
6. 復元候補の展開・検証ができる。
7. 復元データの公開はPublishを経由する。
8. 異常時に後続モジュールが実行されない。
9. 終了結果とログがrun_idで追跡できる。
10. journalctlでログを確認できる。
11. 公開後の世代管理失敗を公開失敗と誤認しない。
12. 変更時に既存の責務・契約を壊さない。

本書作成段階では、実装・実行テストの成功を宣言しない。

## 13. 未決定事項

- Registryと複数都道府県JSONの原子的切り替え方式
- 排他制御・Registry改訂番号の具体契約
- Generation Managerのアーカイブ形式・命名規則
- 参照中の旧データを安全に回収する方法
- Publish前に必要な復旧世代を確保する具体方式
- データセットIDの全国一意性と重複参照方式
- 旧世代アーカイブの配置先
- アーカイブのチェックサム方式
- ロールバックの自動実行条件
- ロールバック時の公開バージョン付与規則
- 標準終了コードの詳細体系
- syslog / journaldの実装方式と保持期間
- 実行結果JSONの正式スキーマ
- Generation / Restoreの詳細Input / Output

これらは独断で確定せず、必要な実装工程より前に設計・レビューする。

---

**設計方針：一つのモジュールに一つの責務を持たせ、処理の接続には明確な契約を用いる。公開済みデータの整合性と復旧可能性を優先する。**

## API別領域への適用（2026-10-16契約改訂）

共通管理処理は対象API識別子と認可済み操作を受け、環境設定で解決した `/data/<api>/` 内だけを扱う。公開APIは原則自APIの公開Registryが指すrel/versionsの実体を読み取り、Download・Validate・Publishを起動する権限を持たない。配置詳細は[基本アーキテクチャ第6節](basic-architecture-v0.1.md)を参照。

rel/versionsに準備した実体もRegistry切り替えまでは未公開である。ディレクトリ名やリンクによる公開判定を行わず、原子的切り替え・資格確認・排他・旧参照保護を維持する。Registryの物理配置は未決定。

dl/currentとdl/archiveの元DL世代（原則非圧縮1＋圧縮2）と、本書の公開世代（原則現行1＋過去2）は別管理。元DLとrecordsの由来・設定版・処理証跡を追跡し、データセット単位を基本候補として安全に保持する。API全体の一括圧縮や両系列同時削除は要求しない。使用中の元DL・公開実体・復元に必要な証跡を削除しない。

Generationは保持・圧縮・整理、RestoreはAPI/データセット/世代と対応メタデータを検証して候補化する。DL復元のみでは公開状態は変わらず、公開再確定はPublishだけが行う。他APIへの展開・書込みを拒否する。API別バックアップの方式・DL世代管理の詳細・Docker権限実装は未決定。

## P6・P7 OWNER承認による改訂（2026-10-17）

- OWNER決定日: 2026-10-17。決定: 改訂P1〜P7をすべて正式採用。本書に関係するのはP6・P7である。詳細は[契約改訂案](../pipeline/elevation-contract-revision-p1-p7-v0.1.md)、決定記録は[2026-10-17 P1〜P7の採用](../decisions/2026-10-17-elevation-p1-p7.md)。
- **P6（標高APIでの切替方式）**: 第6節の手順8「Registryを原子的に切り替える」を、標高APIでは次の方式で満たす。本書の一般方式（「特定のファイル操作やストレージ方式を固定しない」）は変更しない。
  - 公開実体 `rel/versions/pub-<run_id>/<dataset_id>.json` と、Registry改訂 `rel/registry/<pref>/revisions/rev-<run_id>.json` は新規作成のみで、上書きしない。
  - 現行ポインタ `rel/registry/<pref>/current.json`（`registry_revision`、`registry_sha256`、`previous_revision`）だけを、同じディレクトリ内のrenameで原子的に置換する。これが公開点である。切替前の失敗では旧Registryが正本のままである。
  - 第10節の同時Publishは、都道府県ごとの公開ロックと、ロック下での現行ポインタの再確認で、更新の消失を防ぐ。
  - 旧改訂・旧実体は削除しない。第7節（世代管理）・第8節（Restore）は未実装・未変更である。
- **P7**: 第6節の手順2に、公開条件（`license`、`attribution_url`）の必須化を追記した。本番の実行では、承認記録の `attribution_text`（Source Definitionの出典文言と一致すること）と、`eligibility_status = approved` の公開資格も必要である（[本番認可設計](production-authorization-v0.1.md)）。
- 変えないもの: 複数Registryにまたがる原子的切替（第10節）と、Registryの物理配置の一般方式はUNDECIDEDのまま。上記の配置は標高APIについてだけ定める。
- **実GSIデータの本番取得・Publishは、引き続きBLOCKEDである**（公開資格が未成立。[GSI利用条件チェックリスト](../operations/gsi-dem10b-usage-checklist-v0.1.md)）。
