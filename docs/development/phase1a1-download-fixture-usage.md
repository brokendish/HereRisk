# Phase 1-A.1 Elevation Download Fixture MVP 使い方

Task ID: `phase1a1-elevation-download-fixture-mvp` / 対象: 開発・テスト専用

本書は、外部通信を行わないfixture専用のDownload実装の動かし方と確認方法をまとめる。本番取得の手順書ではない。本番Source Definitionは未承認のため、本番コンテキストでは必ずBLOCKEDになる。

契約: [Download / Acquisition Record実装契約案 v0.1](../pipeline/elevation-download-contract-v0.1.md)

## 1. 構成

```text
src/hererisk/
  cli.py                        開発用CLI（構成ルート。Orchestratorだけを呼ぶ）
  common/
    config.py                   Configuration Manager（識別子解決・厳格JSON・Schema・不変スナップショット）
    authorization.py            実行認可（production: 常にBLOCKED / fixture: fixture専用承認）
    orchestrator.py             run_id・対象検証・認可・排他・設定スナップショット保存・Download起動
    storage.py                  API別領域への閉じ込め・fsync・上書き禁止の確定
    logging.py                  構造化ログ（sink差替え可能。既定はstderr）
    result.py                   SUCCESS / FAILED / BLOCKED、error_code、終了コード
  elevation/download/
    download.py                 Downloadコア（.part → 検証 → 確定 → Record → marker）
    transport.py                Transportインターフェース、FixtureTransport
    png.py                      PNGコンテナ検査
    record.py                   Acquisition Record・commit markerのSchema
tests/
  fixture_builder.py            fixture木の生成（コミット済みfixtureとテスト用一時fixtureの共通元）
  fixtures/elevation-fixture/   CLI用fixture（sources.json、承認、合成PNG）
  unit/  contract/              単体テスト・契約テスト
```

`common` は `elevation` を参照しない（テストで検査）。HTTP Transport、Normalize / Validate / Publish、Generation / Restore、Data Managerは実装していない。

## 2. セットアップ

Python 3.11以上（確認環境は3.14.3 / macOS）。

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

| 依存 | 用途 | 区分 |
|---|---|---|
| jsonschema (>=4.23,<5) | Source Definition・Record・markerのJSON Schema検証 | 実行時 |
| pypng (==0.20220715.0) | Normalize（Phase 1-B.1）のPNG画素復号。純Python・依存なし | 実行時 |
| pytest (>=8) | テスト | 開発時のみ |

その他は標準ライブラリのみ。jsonschemaの `uri` フォーマット検査は任意パッケージ未導入のため実質無効で、HTTPSのパターン検査で代替している。

以降のCLI例は、editable installの `.pth` に依存しない `PYTHONPATH=src` 形式で記載する。macOSで `~/Documents` 等の同期対象に `.venv` を置くと、`.venv` 内のファイルに `hidden` フラグが付くことがある。Python 3.13以降は隠し `.pth` を読み込まないため、`hererisk-pipeline` コマンドや `import hererisk` が失敗する（`python -v` で `Skipping hidden .pth file` と表示される）。この場合も下記の形式なら動作する。

## 3. Fixture CLIの実行

fixture実行のデータルートは、空の一時ディレクトリを `init-fixture-root` で明示的に初期化したものに限る。初期化するとマーカーファイル `.hererisk-fixture-data-root` が作成される。共通Orchestratorは、fixtureコンテキストで次のデータルートを拒否する（`INVALID_INPUT`、終了コード2、何も書き込まない）。

- マーカーがない
- `/data` 配下
- 設定・Schemaのルート（リポジトリ）やfixture定義ツリーの配下

判定は、固定（pin）したデータrootのディレクトリ自体に対して行う。パス名だけでは判定しない。手順は次のとおり。

1. データrootを一度だけ正規化する。
2. `/` から各階層を `O_NOFOLLOW` で辿って開き、そのFDを固定する。途中にsymlinkが差し込まれていれば `PERMISSION_DENIED` で停止する。
3. 辿った各ディレクトリの識別子（dev, inode）と、正規化後のパスの両方で、保護対象rootの配下でないことを確認する。識別子での比較は、macOSの `/System/Volumes/Data/...` のように `realpath` で正規化されない別名にも有効である。
4. マーカーも、同じFDから読む。

マーカーは、管理者が「使い捨てfixture rootとして使う」という意図を記録するものであり、認証情報ではない。

`init-fixture-root` は、存在する空ディレクトリだけを受け付ける。リポジトリと `/data` の配下は、同じく識別子でも判定して拒否する。

```sh
DATA_ROOT="$(mktemp -d)"
PYTHONPATH=src .venv/bin/python -m hererisk.cli init-fixture-root --data-root "$DATA_ROOT"
PYTHONPATH=src .venv/bin/python -m hererisk.cli download \
  --api elevation --region 13 --source fixture-dem-png-tokyo \
  --fixture tests/fixtures/elevation-fixture \
  --data-root "$DATA_ROOT"
echo "exit=$?"
```

- stdout: 結果JSON 1行（`run_id`、`module`、`status`、`artifacts`、`error_code`、`message`）
- stderr: 構造化ログ（JSON Lines）。`2>/dev/null` で結果だけを得られる
- 設定・Schemaは、常にこのパッケージを含むリポジトリの `api/<api>/conf` から読む。読込み先を変更するCLI引数はない（r1で `--config-root` を廃止）
- 引数の構文エラーは、固定文言 `hererisk-pipeline: invalid arguments (see --help)` をstderrに出し、終了コード2とする。指定値やパスは表示しない
- 東京以外の例: `--region 27 --source fixture-dem-png-osaka`

同じrun_idで再実行（確定物を照合して再取得しない）:

```sh
PYTHONPATH=src .venv/bin/python -m hererisk.cli download --api elevation --region 13 \
  --source fixture-dem-png-tokyo --fixture tests/fixtures/elevation-fixture \
  --data-root "$DATA_ROOT" --resume-run-id <前回のrun_id>
```

本番コンテキスト（`--fixture` なし）はBLOCKEDになり、何も書き込まない:

```sh
PYTHONPATH=src .venv/bin/python -m hererisk.cli download --api elevation --region 13 \
  --source gsi-dem10b-candidate --data-root "$(mktemp -d)"
# {"error_code": "APPROVAL_REQUIRED", "status": "BLOCKED", ...}  exit=3
```

### 終了コード

| コード | 意味 |
|---|---|
| 0 | SUCCESS |
| 2 | INVALID_INPUT / INVALID_CONFIGURATION、CLI引数誤り |
| 3 | BLOCKED（TARGET_UNCONFIGURED / APPROVAL_REQUIRED / TARGET_BUSY / RECOVERY_REQUIRED） |
| 10 | 転送失敗（fixture欠損はHTTP_404相当、途中失敗はTRANSFER_INTERRUPTED、REDIRECT_REJECTED） |
| 11 | CONTENT_TYPE_INVALID / SIZE_INVALID / PNG_INVALID |
| 12 | STORAGE_FULL / PERMISSION_DENIED / HASH_FAILED / STORAGE_INTEGRITY_FAILED |
| 13 | RECORD_COMMIT_FAILED |
| 14 | INTERNAL_ERROR |

## 4. 保存結果の確認

```text
$DATA_ROOT/elevation/
  work/download/<run_id>/<acq_id>/original.part     受信中（成功時は残らない）
  work/acquisitions/<run_id>/<acq_id>/original.png  確定原本
  work/locks/download-<source_ref>.lock             (api, source_ref) 排他用
  records/configurations/<run_id>/source.json       Source Definition原文（バイト列そのまま）
  records/configurations/<run_id>/effective.json    実効設定（execution_context=fixture を含む）
  records/acquisitions/<run_id>/<acq_id>.json       Acquisition Record
  records/commits/<acq_id>.json                     commit marker
```

整合確認は、同じrun_idでの再実行（`--resume-run-id`）で行う。再実行時には、次をすべて照合して一致した場合だけ、同じartifactsを転送0回で返す。

- run単位の集合: marker・Record・原本の各集合が一致し、`work/download/<run_id>` に未確定物がないこと
- 個別の確定物: 各marker・Record・原本のhash
- Recordの意味的整合: 固定設定から再構成したRecordと完全一致すること

一致しない場合は `BLOCKED / RECOVERY_REQUIRED` になる。`shasum -a 256 .../original.png` の値は、Recordの `sha256`、markerの `artifact_sha256`、結果JSONの `sha256` と一致する。

### 読込み上限

| 対象 | 上限 |
|---|---|
| 設定・Schema・fixture承認ファイル | 1 MiB |
| Acquisition Record | 64 KiB |
| commit marker | 16 KiB |
| 原本（受信中・確定後の再検証とも） | fixtureポリシー `max_tile_bytes`（1 MiB）。確定後はストリームでhashを計算する |

上限を超えるファイルは、全体を読み込まずに拒否する。設定は `INVALID_CONFIGURATION`、確定物は `RECOVERY_REQUIRED`。

### 信頼境界

SHA-256は、偶発的・部分的な破損を検出するためのもので、改竄者を認証しない。API領域の `work/` と `records/` に書き込める主体は、整合する一式を偽造できる。したがって、これらの領域はパイプライン管理ユーザーだけが書き込める権限で運用することを前提とする（本番の所有者・権限設計は未決定）。保存層は次のように動作する。

- 呼出元から任意のPathを受け取らない。API内の許可領域（`work/download`・`work/acquisitions`・`work/locks`・`records/configurations`・`records/acquisitions`・`records/commits`）だけを操作する。`dl/`・`rel/`・Registryは読み書きともできない
- データrootは、検査より前に `/` から `O_NOFOLLOW` で辿ってFDとして固定する。以後の検査とI/Oはすべてこの同じFDを基点に行い、パスを再resolveしない。固定前・固定後のどちらでも、rootや途中の階層をsymlinkに差し替えて領域外へ誘導することはできない（安全側に `PERMISSION_DENIED`）
- 残余条件（防止しない）: FDを保持したディレクトリそのものが、書込み権限を持つ主体によって別の場所へ移動されると、I/Oはその同じディレクトリで続く。差し替え先へ追従することはない。データ領域の書込み権限を管理ユーザーに限るという前提で許容する
- 開いたFDは、その後の検査（fstat等）が失敗した場合も必ず閉じる。OSErrorは保存層の共通エラーに分類する
- 確定物として読み込むファイルは、通常ファイルで、実行ユーザー所有、リンク数1であることを要求する。外部hardlinkの別名がある場合は `RECOVERY_REQUIRED`
- `dir_fd` / `O_NOFOLLOW` を使えない環境では、すべての操作を拒否する

## 5. テスト

```sh
.venv/bin/python -m pytest            # 全件
.venv/bin/python -m pytest tests/unit # 単体のみ
```

テストは一時ディレクトリ（`init-fixture-root` 済み）だけに書き込み、ソケット接続・名前解決をautouseで禁止している。CLI・強制停止の子プロセス内にも同じガードを入れている。障害注入（容量不足・権限・hash不一致・Record/marker失敗・symlink差替え競合）は、保存層とTransportの差替えで行う。強制停止は、子プロセスが自分にSIGKILLを送る実プロセス試験で行い、6停止点を確認している（`tests/contract/test_process_kill.py`）。独立検証の指摘（F01〜F12）に対応する回帰テストは `tests/contract/test_audit_regressions.py` と単体テストにある。

コミット済みfixtureを再生成する場合:

```sh
.venv/bin/python tests/fixture_builder.py
```

fixtureの承認はSource Definition原文のSHA-256に結び付いているため、fixtureの `sources.json` を手で変更すると承認が無効になりBLOCKEDになる。生成スクリプト経由で更新する。

## 6. Fixture と本番の分離

- fixture定義は `tests/fixtures/` のみに置き、本番 `api/elevation/conf/sources.json` は変更しない。Schemaは本番のものをそのまま使う。
- fixtureの承認ID・source_ref・ポリシーIDはすべて `fixture-` 接頭辞を必須とする。fixture承認は本番source（`gsi-dem10b-candidate` 等）を認可できない。
- fixture承認ファイルが本番の `api/` 配下にある場合は拒否する。
- 取得URLは予約TLDの `https://fixture.invalid/...` だけで、FixtureTransportは他のURLを受け付けない。
- 本番コンテキストには承認機構もネットワークTransportも存在しないため、常に `APPROVAL_REQUIRED` で止まる。
- fixture用の上限値（1タイル1MiB、1要求16タイル、未確定取得物8件）はfixture承認ファイル内のポリシーであり、本番のコード既定値ではない。
- Source Definition（全source）と実効設定は、保存前に次を検査する。URLはhttpsに限り、userinfo・query・fragment・明示portを含まないこと。違反は `INVALID_CONFIGURATION` とし、スナップショットを一切保存しない。拒否した値は、ログ・結果・Recordに転記しない。
- JSON Schemaは同一文書内の `#...` 参照だけを許可し、`$id` を禁止する。外部URIは取得しない（DNS・HTTPの試行0回）。

## 7. 中断・再実行の扱い

| 状況 | 動作 |
|---|---|
| 新しいrunで再実行 | 新しいrun_id・acquisition_idで取得。既存の成果物・Recordは変更しない |
| 同じrun_id・同じ設定（全件確定済み） | 確定物を照合して同じartifactsを返す。転送0回 |
| 同じrun_id・同じ設定（一部確定済み） | 確定済みは再利用し、未取得タイルだけ取得 |
| 同じrun_id・異なる設定 | FAILED / INVALID_INPUT。何も書き込まない |
| 同じrun_idに未確定物（.part、markerなしの原本・Record）や照合不一致 | BLOCKED / RECOVERY_REQUIRED。削除・上書きしない |
| 同じsourceを同時実行 | 後発はBLOCKED / TARGET_BUSY（flock。プロセス終了で解放） |
| 未確定取得物がデータroot全体でポリシー上限（fixtureは8件）以上 | 新しいrunはスナップショット保存前にBLOCKED / RECOVERY_REQUIRED（転送0回・書込み0件）。自動削除しない |
| 同じrun_idで、他のmarkerが破損・解析不能 | BLOCKED / RECOVERY_REQUIRED（帰属を判定できないため安全側に倒す） |

未確定取得物は、取得IDごとに1件として数える。含まれる状態は次のとおり。

- `.part` や予約だけの段階（`work/download`）
- 原本のみ、Recordのみ、markerのみ
- 書込み途中の一時ファイル

marker・Record・原本がすべて揃い、part・一時ファイルが残っていない取得だけが確定済みで、計上しない。枠の確認と予約（`work/download/<run>/<acq>` の作成）は、API共通のロック（`work/locks/download-quota.lock`）の下で一体に行う。このため、異なるsource_refを同時に実行しても上限を超えない。新しいrunは、最初の取得枠を予約してからスナップショットを保存する。

**自動回復処理は未実装。** RECOVERY_REQUIREDとなった未確定物は、管理者が調査したうえで新しいrunで再取得する。契約第6節の回復案（排他・実行者不在の確認 → 原本・Record・設定が完全なら照合して確定を完了 → 証拠不足なら隔離して新run）は今後の実装対象。

### fixtureデータrootの整理手順（手動）

fixtureのデータrootは使い捨てとする。未確定物が上限に達した場合や、RECOVERY_REQUIREDの調査が終わった場合は、次の手順で整理する。

1. 同じデータrootを使うプロセスが動いていないことを確認する。`work/locks/` のロックを取得できることが目安になる。
2. 必要なら、データroot全体を調査用に退避する。
3. データrootを削除し、新しい空ディレクトリで `init-fixture-root` からやり直す。

本番データrootでの隔離・整理・保持期限は未決定。この手順を本番に適用しない。
