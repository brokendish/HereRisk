# Verification Summary

## Metadata

- Task ID: `phase1c3-elevation-point-cli`
- Task: Phase 1-C.3 Point Elevation CLI MVP（Readerを管理CLIの `elevation` コマンドから利用）
- Implementer: Claude（実装・テスト・commit・push）
- Reviewer: Claude（自己検証。Codexは今回使用しない指示）
- Target Commit: 本レビューと同じコミット（基準main `3ee029c8d7ba4dc2883e96258920b512be9e9b3d`。作業開始時にfetchし、HEADとorigin/mainの一致と作業ツリーがcleanであることを確認した）
- Status: **自己テストPASS**（この自己テストは最終受入ではない）
- OWNER Approval: Git運用ルールに基づきcommit・push

## Changes

| ファイル | 内容 |
|---|---|
| `src/hererisk/cli.py` | `elevation` サブコマンド、`_read_elevation`、固定キーの結果文書 `_elevation_document` を追加 |
| `tests/contract/test_cli_elevation.py`（新規、24件） | 子プロセスでのCLI試験（ソケット・DNSガード付き） |
| `docs/development/phase1a1-download-fixture-usage.md` | 第3.2節「地点標高の読取」を追加 |

Reader、Point Lookup、Normalize、Validate、Orchestrator、保存層は変更していない。`download`・`pipeline`・`init-fixture-root` の挙動もそのまま。

## CLI仕様

```bash
hererisk-pipeline elevation --run-id <run_id> --lat <lat> --lon <lon> --zoom <z> --data-root <fixture_data_root>
```

- 5つの引数はすべて必須。欠けている場合は、既存の固定文言の構文エラー（終了コード2、stdoutは空）。
- `--lat`・`--lon`・`--zoom` は、argparseではなくコマンド側で解析する。数値でない、範囲外、NaN・Inf、整数でないzoom等は、固定構造のJSONで INVALID_INPUT / INVALID_COORDINATES を返す。
- 実処理は既存の `read_point_elevation` に任せる。
- stdoutにはJSONを1行だけ出す。キーは成功・失敗とも同じで、`status`、`error_code`、`reason`、`message`、`run_id`、`acquisition_id`、`candidate_sha256`、`tile`、`pixel`、`elevation_cm`、`nodata`。ログはstderr。
- 終了コード
  - 成功（欠損画素を含む）は0。
  - 失敗時は、既存エラー表（`ERROR_CODES`）の status と終了コードを使う。例: 座標・run不正・未検証は2、タイル未存在は3、候補破損は12。
- 漏えい防止
  - 入力した緯度経度・内部パス・例外文は、stdoutにもstderrにも出さない。
  - `run_id` は、UUID形式の場合だけ出力する。
  - 予期しない例外は INTERNAL_ERROR（14）にする。

## Verification

| Check | Result |
|---|---|
| CLI試験（24件） | PASS |
| 全pytest | **PASS: 694 passed**（既存670 + 新規24、約111秒） |
| 変異確認 | 4点すべて検出（run_idの出力制限、失敗時の終了コード、zoomの解析、緯度経度の解析） |

試験項目との対応:

| # | 内容 | 主なテスト |
|---|---|---|
| 1 | パイプラインの成果物をCLIから参照 | 成果物はCLIの `pipeline` コマンドで作成 |
| 2 | 1タイル・2タイルの標高 | 大阪1画素、東京2タイル×3画素。期待値はfixture PNGの生成規則による。タイルごとに取得IDが異なること |
| 3 | 0・負値・nullの区別 | 該当の値を画素に置いたPNGを、パイプライン経由で読む。nullでもSUCCESS・終了コード0 |
| 4 | タイル未存在と欠損を区別 | BLOCKED / TARGET_UNCONFIGURED / TILE_NOT_IN_RUN（3） |
| 5 | 不正な座標・run_id・未検証の候補 | 座標10種、run_id 3種（出力に残さない）、存在しないrun、FAILEDの検証証跡、候補の改変（12）、fixtureでないroot、存在しないroot（パスを出さない） |
| 6 | stdoutがJSON1行 | すべての試験で、1行であることとキー集合を確認 |
| 7 | 読取前後でデータrootが不変 | 成功・失敗の読取を混ぜても、ファイルのhashが不変 |
| 8 | 既存pytest全件PASS | 694 passed。既存CLIの `download` の確認も含む |

## Findings

1. **`message` の文言**: 既存エラー表の固定文言を再利用している。TARGET_UNCONFIGUREDの文言は「取得対象」を指すため、読取時の意味は `reason` で判断する。工程別の文言にするかは後続の判断事項。
2. **データrootの保護対象チェックなし**: 読取専用のため、`/data`・リポジトリ配下の拒否は行わない。fixtureマーカーは必須。

## Limitations

- 呼び出すたびに、証跡2件と候補1件を読んで再検証する（キャッシュなし）。
- fixtureのみが対象。本番の読取経路・Web APIは扱わない。

## Conclusion

管理CLIから、検証済みfixture runの地点標高を、読取専用・固定構造のJSONで取得できる（自己テスト694件PASS）。**最終受入ではない。**
