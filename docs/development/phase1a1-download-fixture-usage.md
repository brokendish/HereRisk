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
| pytest (>=8) | テスト | 開発時のみ |

その他は標準ライブラリのみ。jsonschemaの `uri` フォーマット検査は任意パッケージ未導入のため実質無効で、HTTPSのパターン検査で代替している。

以降のCLI例は、editable installの `.pth` に依存しない `PYTHONPATH=src` 形式で記載する。macOSで `~/Documents` 等の同期対象に `.venv` を置くと、`.venv` 内のファイルに `hidden` フラグが付くことがある。Python 3.13以降は隠し `.pth` を読み込まないため、`hererisk-pipeline` コマンドや `import hererisk` が失敗する（`python -v` で `Skipping hidden .pth file` と表示される）。この場合も下記の形式なら動作する。

## 3. Fixture CLIの実行

データルートは必ず一時ディレクトリを指定する。fixture実行では `/data` 配下とリポジトリ配下を拒否する（終了コード2）。

```sh
DATA_ROOT="$(mktemp -d)"
PYTHONPATH=src .venv/bin/python -m hererisk.cli download \
  --api elevation --region 13 --source fixture-dem-png-tokyo \
  --fixture tests/fixtures/elevation-fixture \
  --data-root "$DATA_ROOT"
echo "exit=$?"
```

- stdout: 結果JSON 1行（`run_id`、`module`、`status`、`artifacts`、`error_code`、`message`）
- stderr: 構造化ログ（JSON Lines）。`2>/dev/null` で結果だけを得られる
- `--config-root` はSchemaを読むリポジトリルート（既定: カレントディレクトリ）
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

整合確認（marker・Record・原本の照合。テストで使う関数と同じ）:

```sh
PYTHONPATH=src .venv/bin/python - "$DATA_ROOT" <run_id> <acq_id> <<'EOF'
import sys
from hererisk.common.storage import ApiDataArea
from hererisk.elevation.download.download import verify_commit
print(verify_commit(ApiDataArea(sys.argv[1], "elevation"), sys.argv[2], sys.argv[3]))
EOF
```

`shasum -a 256 .../original.png` の値は、Recordの `sha256`、markerの `artifact_sha256`、結果JSONの `sha256` と一致する。

## 5. テスト

```sh
.venv/bin/python -m pytest            # 全件
.venv/bin/python -m pytest tests/unit # 単体のみ
```

テストは一時ディレクトリだけに書き込み、ソケット接続・名前解決をautouseで禁止している。障害注入（容量不足・権限・hash不一致・Record/marker失敗・強制停止相当）は保存層とTransportの差替えで行う。

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
- fixture用の上限値（1タイル1MiB、1要求16タイル）はfixture承認ファイル内のポリシーであり、本番のコード既定値ではない。

## 7. 中断・再実行の扱い

| 状況 | 動作 |
|---|---|
| 新しいrunで再実行 | 新しいrun_id・acquisition_idで取得。既存の成果物・Recordは変更しない |
| 同じrun_id・同じ設定（全件確定済み） | 確定物を照合して同じartifactsを返す。転送0回 |
| 同じrun_id・同じ設定（一部確定済み） | 確定済みは再利用し、未取得タイルだけ取得 |
| 同じrun_id・異なる設定 | FAILED / INVALID_INPUT。何も書き込まない |
| 同じrun_idに未確定物（.part、markerなしの原本・Record）や照合不一致 | BLOCKED / RECOVERY_REQUIRED。削除・上書きしない |
| 同じsourceを同時実行 | 後発はBLOCKED / TARGET_BUSY（flock。プロセス終了で解放） |

**自動回復処理は未実装。** RECOVERY_REQUIREDとなった未確定物は、管理者が調査したうえで新しいrunで再取得する。契約第6節の回復案（排他・実行者不在の確認 → 原本・Record・設定が完全なら照合して確定を完了 → 証拠不足なら隔離して新run）は今後の実装対象。
