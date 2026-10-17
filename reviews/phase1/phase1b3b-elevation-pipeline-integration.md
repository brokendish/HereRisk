# Verification Summary

## Metadata

- Task ID: `phase1b3b-elevation-pipeline-integration`
- Task: Phase 1-B.3-B パイプライン統合（Download → Normalize → Validate → 検証証跡、fixture限定）
- Implementer: Claude（実装・自己テスト）
- Reviewer: Claude（自己検証。独立検証ではない）
- Target Commit: 未コミット。基準main `47a6c3090518a418ce611762aabdd4e65603ac83`。作業開始時にfetchし、HEADとorigin/mainの一致と作業ツリーがcleanであることを確認した
- Status: **自己テストPASS・独立検証待ち**（この自己テストは最終受入ではない）
- OWNER Approval: 未承認（commit・push未実施）

## Changes

| ファイル | 内容 |
|---|---|
| `src/hererisk/elevation/validate/stage.py`（新規、約340行） | `ValidateStage.run(plan, normalize_result, area, logger, *, authorization)` |
| `src/hererisk/common/orchestrator.py` | `run_fixture_pipeline` を追加し、`PipelineStage` プロトコルと `stages` 引数を新設。Downloadの処理を内部の `_execute` に集約し、`run_download` の挙動は維持 |
| `src/hererisk/common/authorization.py` | operationを download/normalize/validate の列挙にした。工程ごとの承認ファイル（同じディレクトリの `<operation>.json`）を読む。安全ポリシーはdownload用の承認だけが持つ |
| `src/hererisk/common/result.py` | `VALIDATION_FAILED`（FAILED、終了コード11）と固定文言を追加 |
| `src/hererisk/common/storage.py` | 固定領域 `records/validations` を追加 |
| `src/hererisk/elevation/normalize/stage.py` | 工程自身の承認（normalize）を必須引数にした。API・source・地域が固定計画と一致することを確認し、証跡の `authorization_ref` に記録する。変換・保存の処理は変更なし |
| テスト | `tests/contract/test_pipeline_integration.py`（新規、41件）。あわせて `conftest.py`（`stages` 引数）、`fixture_builder.py`（工程別の承認ファイル）、`test_normalize_stage.py`（承認を渡す）、`test_download_blocked_invalid.py`（承認ファイル名の変更に追従。期待値は不変）を更新した |
| fixture | `authorization/normalize.json`・`validate.json` を追加（`download.json` は不変） |
| 文書 | 使い方文書のfixture分離の節に2項目を追加 |

変更していないもの: Download・Normalize・Validateの各コア、候補データ、Configuration Manager、CLI、Record、設定、依存、Generation・Restore・Publish・Registry。

### Orchestrator（`run_fixture_pipeline`）

1. 既存のDownload前処理（設定、対象、Download承認、データroot、snapshotの可否）に続けて、**後段の全工程を、それぞれの工程の承認で事前に確認する**。fixture以外の承認、承認のない工程、`operation` が一致しない承認は、BLOCKED / APPROVAL_REQUIRED となり、その時点で何も書き込まない（結果のmoduleは止まった工程の名前）。
2. source単位のロックを**一度だけ**取得し、その中でDownloadの実行に続けて、直前の工程がSUCCESSの場合だけ次の工程の `run` を呼ぶ。工程同士が互いを起動することはない。
3. 戻り値は、実行した工程の `ModuleResult` を順に並べたタプル。全工程がSUCCESSのときだけパイプラインとして成功となる。工程内の予期しない例外は、その工程のINTERNAL_ERRORに変換する。

### Validate stage

1. **前提検査**（失敗時はファイルを書かない）
   - validate用の承認であること
   - Normalize結果が同じrunのSUCCESSであること
   - snapshotが固定計画と一致すること（1-B.3-Aの照合を再利用）
   - Download証拠（`reconcile_run`）のタイル集合が計画と完全に一致すること
   - Normalize証跡がこの計画のSUCCESSで、そのinputsがDownload証拠と一致し、outputsとNormalize結果のartifactsが一致すること
   - そのrunのValidate証跡がないこと（健全なSUCCESS証跡があれば、再照合したうえで再利用する）
2. **タイルごとの検査**（計画の順）
   - 候補を上限付きで読み、size・hashをNormalize証跡と照合する。不一致は STORAGE_INTEGRITY_FAILED。
   - 厳密なJSON解析（NaN・重複キーを拒否）を行い、`validate_candidate(candidate, expected_tile=計画の整数タイル)` を呼ぶ。
   - JSON解析の失敗とプロファイル違反は **VALIDATION_FAILED**。Validate Coreは従来どおりINVALID_INPUTを返し、それを統合の境界で変換する。
   - valid_count・nodata_count・min_cm・max_cm・warning（`ALL_NODATA`）を記録する。
3. **確定**: `records/validations/<run>.json` を上書き禁止で保存し、読み直して照合する。証跡のvalidationには、`normalize_record_ref` とそのhash、checks（契約5節の7項目。passed / failed / not_run）、tilesを入れる。全欠損のタイルは、SUCCESSのままWARNINGログを出す。
4. **失敗時**: 同じ証跡ファイルにFAILEDとして記録し、以後の再実行はRECOVERY_REQUIREDにする。再利用時は、候補のhashと統計を再計算して照合する（保存済みの統計だけを信用しない）。

### エラー分類

| 状態 | 分類 |
|---|---|
| 入力契約違反（前段の結果がSUCCESSでない等） | INVALID_INPUT |
| 承認なし・本番 | APPROVAL_REQUIRED |
| 証跡の欠落・不整合・未確定 | RECOVERY_REQUIRED |
| 候補bytesの破損 | STORAGE_INTEGRITY_FAILED |
| 品質（プロファイル）検査の不合格 | VALIDATION_FAILED |

### 権限境界

- 保存層の許可領域はコード上の許可集合で、追加は `records/validations` の1つだけ。
- 作成されるファイルは0640、ディレクトリは0750（umaskに依存）。グループ・その他に書込み権限がないことをテストで確認した。
- 公開APIのプロセスは存在せず、管理領域への書込み経路もない。fixture rootは専用ディレクトリで、管理ユーザーだけが書き込める前提は変わらない。

## Verification

| Check | Result |
|---|---|
| 統合テスト（41件） | PASS（2回連続） |
| 全pytest | **PASS: 474 passed**（既存433 + 新規41、約74秒） |
| Codex R1独立証拠（Download境界、無改変） | 53/53 PASS（Orchestrator変更による回帰なし） |
| 変異確認 | 11点すべて検出（SUCCESSによる進行判定、工程別承認、承認のoperation一致、工程側のoperation検査、Normalize結果と証跡の一致、候補hash、VALIDATION_FAILEDへの変換、再利用時の統計の再照合、expected_tileの受渡し、失敗証跡、Validate側のsnapshot照合）。最後の1点は最初の試験では検出できなかったため、試験を1件追加した |

必須テストとの対応:

| # | 内容 | 主なテスト |
|---|---|---|
| 1 | 1タイルでSUCCESS | `test_single_tile_pipeline_success` |
| 2 | 2タイルでID・位置・hashが対応 | `test_two_tiles_keep_ids_positions_and_hashes` |
| 3 | Download失敗時は後続を呼ばない | `test_download_failure_stops_pipeline` |
| 4 | Normalize失敗時はValidateを呼ばない | `test_normalize_failure_stops_before_validate` |
| 5 | 不正候補・hash不一致・証跡欠落はSUCCESSにしない | hashが整合する不正候補6種とNaN（VALIDATION_FAILED）、bytes改変（STORAGE_INTEGRITY_FAILED）、Normalize証跡・marker・候補の欠落、Normalize結果の不正3種、snapshotの変更 |
| 6 | 全欠損でもSUCCESS、WARNINGと統計を記録 | `test_all_nodata_tile_passes_with_warning` |
| 7 | 中断・再実行で未確定証跡を上書きしない | FAILED証跡の後の再実行はBLOCKEDでファイル不変。証跡書込み失敗後の再実行。編集された証跡の再利用拒否。成功後の再実行は完全再利用（転送0回、ファイル不変） |
| 8 | 実SIGKILL | 候補保存後（Normalizeが停止）、Normalize証跡後（再開してSUCCESS）、Validate証跡後（再利用してファイル不変）、結果返却前（再利用してファイル不変） |
| 9 | 本番・未認可を拒否 | 本番、normalize・validateの承認欠落、download承認の流用、他sourceや他定義hashに束縛された承認、工程に別operationの承認を渡す場合。いずれも書込み0件 |
| 10 | 原本・Record・設定・dl・rel・Registryを変更しない | `test_evidence_and_protected_areas_unchanged` |
| 11 | 既存pytestがすべてPASS | 474 passed |

その他: source単位のロックが全工程で保持され、二重に取得されないこと（`test_source_lock_held_once_across_all_stages`）。ステージを登録しても `run_download` の挙動が変わらないこと。B2-F01の境界（expected_tileが計画由来の厳密な整数であること）。

## Findings

1. **CLI未追加**: パイプラインはOrchestratorのAPIからだけ呼べる。管理入口（CLI）への追加は後続の判断事項。
2. **工程別の書込み制限なし**: 保存層には工程ごとの許可集合がない（1-B.3-Aから継続）。
3. **Normalize stageの引数変更**: `authorization` を必須引数にした（1-B.3-Aの直接呼出しとは互換性がない）。
4. **Validate証跡の `inputs`**: 空配列とし、Download入力はNormalize証跡を経由して参照する。
5. **VALIDATION_FAILED**: 終了コード11（PNG_INVALIDなど「表現不正」と同じ区分）とした。区分の最終的な採否はOWNERの確認事項。

## Limitations

- 単一ホスト・専用fixture root・直列実行が前提。電源断、Linux/VPS、syslog/journaldは未検証。
- R2-F01（quotaロックの初回競合）など、既存の後続課題は変わらない。

## 独立検証への引渡し事項

1. 工程別の承認が、事前確認・承認ファイルの分離・operationの一致によって、download承認の流用や他source・他定義への流用を防いでいることを確認する。
2. 3工程の実SIGKILL再開と、ロックを一度だけ保持していることを確認する。
3. INVALID_INPUT・RECOVERY_REQUIRED・STORAGE_INTEGRITY_FAILED・VALIDATION_FAILEDの分類が混同されていないことを確認する。
4. Findings 1〜5の採否をOWNERが判断する。

## Conclusion

3工程をOrchestratorから順に実行して、検証済みの候補と検証証跡を残せることを確認した。失敗・中断・未認可の場合はSUCCESSにせず、何も上書きしない（自己テスト474件PASS）。**最終受入ではない。**
