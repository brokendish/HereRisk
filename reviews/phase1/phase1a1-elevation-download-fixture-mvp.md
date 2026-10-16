# Verification Summary

## Metadata

- Task ID: `phase1a1-elevation-download-fixture-mvp`
- Task: Phase 1-A.1 Elevation Download Fixture MVP（外部通信なしのDownload・Acquisition Record最小実装）
- Implementer: Claude（実装・単体テスト）
- Reviewer: Claude（自己検証。独立検証ではない）
- Target Commit: 未コミット（基準main `03fd7ff5a839099e9ab8b8bdbd030d405a3b9b2c`。作業開始時にfetchし、HEADとorigin/mainの一致を確認）
- Status: **PASS WITH FINDINGS**（fixture・ローカル単体/契約テストの範囲）
- OWNER Approval: 未承認（commit・push未実施）

## Changes

| 区分 | 内容 |
|---|---|
| 共通 | `src/hererisk/common/`: Configuration Manager、実行認可（production / fixture分離）、Orchestrator（download操作のみ）、API別領域の保存層、構造化ログ、結果・終了コード |
| 標高 | `src/hererisk/elevation/download/`: Downloadコア、Transportインターフェース + FixtureTransport、PNGコンテナ検査、Record・marker Schema |
| CLI | `src/hererisk/cli.py`: 開発・テスト専用。Orchestratorだけを呼ぶ |
| テスト | `tests/unit/`、`tests/contract/`、`tests/conftest.py`、`tests/fixture_builder.py`、`tests/fixtures/elevation-fixture/`（合成PNG。実データではない） |
| 設定 | `pyproject.toml`（依存: jsonschema、開発時pytest）、`.gitignore` に `*.egg-info/` 追加、不要になった `src/.gitkeep`・`tests/.gitkeep` を削除 |
| 文書 | [使い方](../../docs/development/phase1a1-download-fixture-usage.md)、本サマリー、READMEリンク |

変更していないもの: `api/elevation/conf/sources.json`・Schema、既存設計書・契約、Docker、conf/env、`dl/`・`rel/`・Registry。

## Verification

| Check | Result |
|---|---|
| 単体テスト（`tests/unit`、47件） | PASS: 厳格JSON（重複キー・構文・NaN・BOM）、Schema違反、47都道府県、参照整合、識別子許可、不変スナップショット、no-clobber書込み、領域外・symlink拒否、fsync呼出し、排他、PNG検査、終了コード対応、ログ項目 |
| 契約テスト（`tests/contract`、in-process 64件） | PASS: 正常取得、size/SHA-256/Record/marker/設定スナップショットの対応、run_id引継ぎ、東京以外（27・01）の同一経路、本番定義のBLOCKED、fixture承認の本番流用拒否、未設定地域、不正設定時の転送0回、障害注入（欠損・途中失敗・長さ不一致・MIME・redirect・PNG破損・空/上限超過・権限・容量不足・再読hash不一致・Record失敗・marker失敗）、強制停止相当（3停止点）、同一/異なる設定での再実行、同時実行、領域分離、後続工程・ネットワークコードの不在 |
| CLIプロセステスト（6件） | PASS: stdoutは結果JSON 1行・stderrはログ、終了コード0/2/3、本番BLOCKED、`/data`・リポジトリ配下のデータルート拒否 |
| 安定性 | PASS: 全117件を連続5回実行し全PASS |
| 変異確認 | PASS: marker失敗の握り潰し、上書きrename、再読照合の無効化、排他の無効化、未確定物の無視の5変異をそれぞれテストが検出 |
| ネットワーク | PASS: テスト中はソケット接続・名前解決を禁止。HTTP実装・socket/subprocess importなし（AST検査） |
| Security / 秘密情報 | PASS: 新規ファイルに秘密・内部IP・個人情報なし。結果JSON・ログに例外文・URL・パスを出さないことをテスト |
| 実機テスト | NOT RUN: 実プロセスのSIGKILL、電源断時の永続性、Linux/VPS、Docker Volume、OS権限設計、syslog/journald |
| 実GSI統合試験 | NOT RUN: 対象外（未承認。外部通信禁止） |

## Findings

1. **自動回復は未実装。** 未確定物・照合不一致は `BLOCKED / RECOVERY_REQUIRED` で停止し、削除・上書きしない。契約第6節の回復処理（照合による確定完了・隔離）は後続作業。
2. 確定名への移動は `rename` ではなく `link` + `unlink` で実施した。POSIXの `rename` は既存ファイルを置換するため、上書き禁止を原子的に保証する目的。同一ファイルシステムは `st_dev` で事前確認し、別FSは `STORAGE_INTEGRITY_FAILED`。
3. fsyncはファイルと親ディレクトリに実施（macOSは `F_FULLFSYNC`）。呼出しはテストで確認したが、電源断に対する実効性は未検証。
4. 契約に明記のない判断: fixture欠損は `HTTP_404` 相当、同一run_idで設定が異なる再実行は `FAILED / INVALID_INPUT`、pipeline版不一致は `BLOCKED / APPROVAL_REQUIRED`、未知source_refは `INVALID_INPUT`・地域に紐付かないsourceは `TARGET_UNCONFIGURED`。
5. 排他ファイル用に契約の論理構成にない `work/locks/` を追加した。
6. 現行Schemaは `approval_ref` が非nullなら `tiles` 非空を要求するため、`tiles=null` は実際には `APPROVAL_REQUIRED` で止まる（Download側の `TARGET_UNCONFIGURED` 判定は防御的に残す）。
7. CLIはfixture・データルート・Schemaルート・再実行run_idの引数を受け取る。契約4.1の「CLIからはapi/region/sourceのみ」に対し、開発・テスト用の追加である。
8. 他runの未確定物は新しいrunを止めない（markerがない限り消費されない）。同一run_idの再実行時のみ `RECOVERY_REQUIRED`。
9. jsonschemaの `uri` フォーマット検査は任意依存がないため無効。HTTPSパターンで代替。
10. macOSで `.venv` 内に `hidden` フラグが付くと、Python 3.14がeditable installの `.pth` を読み込まない。使い方では `PYTHONPATH=src` 形式を記載した。

## Limitations

- HTTP Transport、通信ポリシー（timeout・間隔・TLS・DNS検査）、Normalize/Validate/Publish、Generation/Restore、Data Manager、永続運用オーバーライド、Record訂正記録は実装していない。
- 強制停止は `BaseException` の注入による模擬であり、実プロセス停止ではない。
- fixtureの上限値（1MiB、16タイル）はfixture承認内の値で、本番値として承認されたものではない。
- 新規ディレクトリ（`src/hererisk/`、`tests/unit/`、`tests/contract/`、`tests/fixtures/`）と `pyproject.toml` の配置は、OWNERの確認が必要。

## Conclusion

PASS WITH FINDINGS（fixture・ローカル単体/契約テストの範囲）。Fixture Downloadの正常終了、Record・原本・markerの照合、指定異常系の安全な失敗、本番取得のBLOCKED、API別領域の分離をテストで確認した。自動回復・実機・実GSI通信は未実施。OWNER確認事項: Findings 2・4・5・7・8の採否、新規ディレクトリ配置、回復処理の実装時期。
