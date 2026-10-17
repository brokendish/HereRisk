# Verification Summary

## Metadata

- Task ID: `phase1b4-elevation-fixture-pipeline-cli`
- Task: Phase 1-B.4 Fixture Pipeline CLI MVP（既存CLIからDownload → Normalize → Validateを実行）
- Implementer: Claude（実装・自己テスト）
- Reviewer: Claude（自己検証。独立検証ではない）
- Target Commit: 未コミット。基準main `666ef8020787a0ccbb37858d1e9b9d2fc5dfcfd7`。作業開始時にfetchし、HEADとorigin/mainの一致と作業ツリーがcleanであることを確認した
- Status: **自己テストPASS・独立検証待ち**（この自己テストは最終受入ではない）
- OWNER Approval: 未承認（commit・push未実施）

## Changes

| ファイル | 内容 |
|---|---|
| `src/hererisk/cli.py` | `pipeline` サブコマンドを追加（`--fixture` 必須）。fixtureコンテキストの場合だけ、Orchestratorに `NormalizeStage`・`ValidateStage` を登録する。`run_fixture_pipeline` の結果をまとめる `pipeline_summary` を追加 |
| `tests/contract/test_cli_pipeline.py`（新規、12件） | CLI統合テスト（子プロセス、ソケット・DNSガード付き） |
| `docs/development/phase1a1-download-fixture-usage.md` | 第3.1節「fixtureパイプライン」を追加。終了コード表にVALIDATION_FAILEDを追加。「CLIは未追加」の記述を更新 |

変更していないもの: 処理コア（Download・Normalize・Validate・各stage）、Orchestrator、保存層、認可、設定、fixture、依存。`download` と `init-fixture-root` の挙動。

### CLIの契約

```sh
hererisk-pipeline pipeline --api elevation --region 13 --source fixture-dem-png-tokyo \
  --fixture <fixture-tree> --data-root <initialised fixture root> [--resume-run-id <run_id>]
```

- **stdout**: JSONを1行だけ出す。`{"run_id", "status", "error_code", "results": [ModuleResult.to_dict(), ...]}`。`results` は実行した工程の結果を順に並べたもの。ログはstderrに出し、stdoutと混ぜない。
- **成功判定**: 工程が download・normalize・validate の順にちょうど揃い、すべてSUCCESSの場合だけ `status=SUCCESS`・終了コード0。
- **成功以外**: `status`・`error_code`・終了コードは、止まった工程の結果をそのまま使う（既存のModuleResult・終了コード表の契約どおり）。失敗結果がないまま完了しなかった場合は、INTERNAL_ERROR（14）とし、成功とは報告しない。
- **本番の入口なし**: `--fixture` を省略すると構文エラー（固定文言、終了コード2）。引数エラーで値を表示しないことは既存契約のまま。

## Verification

| Check | Result |
|---|---|
| CLI統合テスト（12件） | PASS |
| 全pytest | **PASS: 486 passed**（既存474 + 新規12、約82秒） |
| 変異確認 | 4点すべて検出（工程の揃い・順序の要求、`--fixture` 必須、終了コードの反映、コマンドの振り分け） |
| 手動実行 | 初期化 → `pipeline` で3工程SUCCESS、終了コード0 |

検証項目との対応:

| # | 内容 | 主なテスト |
|---|---|---|
| 1 | 1タイル・2タイルで3工程SUCCESS | `test_one_tile_pipeline_success`、`test_two_tiles_pipeline_success`（ID・hashが工程間で対応し、検証証跡を確認） |
| 2 | run_idと工程別の結果を確認できる | stdoutが1行で、全工程のrun_idが一致し、各結果がModuleResultのキーを持つこと。stderrのログが同じrun_idであること。再実行で同じ結果になること |
| 3 | 未認可・不正入力・途中失敗で成功終了しない | validate承認の欠落（3、書込みなし）、Normalize失敗（11）、Download失敗（10）、不正地域（2）、対象外地域（3）、fixture定義にないsource（2）、未初期化root・`/data`・リポジトリ配下（2）、`--fixture` 省略・未知引数（2、固定文言）、工程不足・順序違い（集約規則の単体テスト、14） |
| 4 | 既存CLIの回帰・全pytest | 既存の `test_cli.py` 9件と `download` コマンドの挙動確認を含む、486件すべてPASS |
| 5 | 管理対象外へ書き込まない | 作成されたファイルが管理領域（work/download・acquisitions・locks・normalized、records/）に限られること。`dl`・`rel`・リポジトリ・fixtureツリーが不変であること |

## Findings

1. **`download` コマンドへの影響**: fixtureの場合、`download` でも後段のstageがOrchestratorに登録される。ただし `run_download` はstageを実行しない（テストで確認）。
2. **`results` の内容**: 止まった工程までの結果だけが入る。実行されなかった工程の結果（not_run）は含めない。

## Limitations

- CLIの実行は単一ホスト・専用fixture rootでの直列運用が前提。Linux/VPS・journaldでは未検証。
- 処理コアの既存Findings（工程別の保存制限、VALIDATION_FAILEDの終了コード区分など）は、1-B.3-Bから変わっていない。

## Conclusion

既存CLIからfixtureパイプラインを実行でき、全3工程がSUCCESSの場合だけ成功で終了することを確認した（自己テスト486件PASS）。**最終受入ではない。**
