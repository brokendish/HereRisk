# Verification Summary

## Metadata

- Task ID: `phase1b3a-elevation-normalize-evidence-storage`
- Task: Phase 1-B.3-A 証拠接続・Normalize候補保存（確定済みPNG → Normalize → 候補保存 → Normalize証跡）
- Implementer: Claude（実装・単体・限定統合テスト）
- Reviewer: Claude（自己検証。独立検証ではない）
- Target Commit: 未コミット。基準main `287e24e7f7df315d038fc16882586abfbb2b006d`。作業開始時にfetchし、HEADとorigin/mainの一致と作業ツリーがcleanであることを確認した
- Status: **自己テストPASS・独立検証待ち**（この自己テストは最終受入ではない）
- OWNER Approval: 未承認（commit・push未実施）

## Changes

| ファイル | 内容 |
|---|---|
| `src/hererisk/elevation/normalize/stage.py`（新規、約330行） | `NormalizeStage.run(plan, download_result, area, logger) -> ModuleResult` |
| `src/hererisk/common/storage.py`（+11行） | 固定領域 `work/normalized` と `records/normalizations` を `NORMALIZE_AREAS` として追加。既存の集合を `DOWNLOAD_AREAS` と命名し、`WRITABLE_AREAS` はその和集合。読込み可能領域にも同じ2領域を追加 |
| `src/hererisk/common/orchestrator.py`（2行） | Downloadの領域準備を `DOWNLOAD_AREAS` に限定した（新しい領域をDownload時に作らない。実行順序は不変） |
| `tests/contract/test_normalize_stage.py`（新規、40件） | — |

変更していないもの: Download・Normalize・Validateの各コア（`normalize_tile` はそのまま呼ぶ）、Configuration Manager、認可、CLI、Record、設定、依存。Validate・Orchestratorでの逐次実行・Publish・Registryは実装していない。

### 処理

1. **前提検査**（失敗時はファイルを一切作らない）
   - Download結果が module=download、SUCCESS、同じrun_idであること。違反はINVALID_INPUT。
   - fixtureコンテキストであること。本番はBLOCKED / APPROVAL_REQUIRED。
   - ポリシー `max_tile_bytes` が正の整数（boolは不可）であること。違反はINVALID_CONFIGURATION。B1-F01への接続境界での対策。
   - `records/configurations/<run>/source.json` の内容と `effective.json` のhashが、固定計画と一致すること。最新の設定は読み直さない。違反はRECOVERY_REQUIRED。
   - 既存の `reconcile_run` でmarker・Record・原本を固定計画と照合し、その結果のタイル集合が計画のタイル集合と完全に一致すること。部分成功・欠落・余分な取得物・未確定物は拒否する。さらに、Download結果のartifactsが照合結果と一致すること。違反はRECOVERY_REQUIRED。
   - そのrunのNormalize出力がまだないこと。健全なSUCCESS証跡がある場合は、再照合したうえで同じ結果を返す。証跡のない候補や一時ファイルが残っている場合はRECOVERY_REQUIRED。
2. **タイルごとの変換**（計画の順に1枚ずつ）
   - 原本を上限付きで1回だけ読み、**そのbytes**が照合済みのsize・SHA-256と一致することを確認したうえで `normalize_tile` に渡す。
   - 結果をcompactなUTF-8 JSONにする（契約どおりのキー順、1 MiB上限）。
   - `work/normalized/<run>/<acq>.json` へ上書き禁止で保存し、読み直してhashを照合する。配列はタイルごとに解放する。
3. **確定**: すべての候補を保存した後に、`records/normalizations/<run>.json`（SUCCESS）を上書き禁止で保存し、読み直して照合する。
4. **失敗時**: 手順2・3での失敗は、同じ証跡ファイルに status=FAILED、error_code、完了済みの候補として記録する。以後の再実行はRECOVERY_REQUIREDになる。自動削除・自動修復・再生成はしない。
5. **結果**
   - SUCCESS時は既存の `ModuleResult` を使い、module=normalize、message は工程用の固定文言 "Normalization committed" とする。
   - artifactsは既存の `Artifact` の形で、artifact_id＝acquisition_id、record_ref＝Normalize証跡、sha256・size_bytes は候補JSONのもの。
   - FAILED・BLOCKED時のartifactsは空。

証跡の項目（契約6.2）は、schema_version、module、run_id、api_id、execution_context、authorization_ref、pipeline（`elevation-normalize`／`fixture-0.1`）、profile、source_raw_sha256、effective_configuration、status、error_code、completed_at、inputs（acquisition_id、Record参照とそのhash、原本のhash・size、tile）、outputs（acquisition_id、candidate_ref、hash、size）、validation（null）。未知キーはJSON Schemaで拒否する。

## Verification

| Check | Result |
|---|---|
| Normalize stage（40件） | PASS |
| 全pytest | **PASS: 433 passed**（既存393 + 新規40） |
| Codex R1独立証拠（Download境界、無改変） | 53/53 PASS（保存層の変更による回帰なし） |
| 変異確認 | 11点すべて検出（タイル集合の一致、結果と証拠の一致、snapshot照合、B1-F01境界、同一bytesの照合、未確定候補の拒否、再利用時の証跡一致・候補hash・候補集合、失敗証跡の記録、fixture限定）。最初の試験では3点を検出できなかったため、試験を3件追加して検出を確認した |

受入条件との対応:

| # | 条件 | 主なテスト |
|---|---|---|
| 1 | 1タイルの変換・保存 | `test_one_tile_normalized_and_recorded`（候補は `normalize_tile` の出力と一致、compact、Validate Coreで合格、証跡の全項目） |
| 2 | 2タイルの対応 | `test_two_tiles_keep_correspondence` |
| 3 | 原本・Recordのhashが不変 | 成功・失敗の各試験で、Downloadの証拠一式のhashが変わらないこと |
| 4 | 候補を読み直してhash確認 | 保存直後と再利用時の両方で照合（改変・欠落・余分を拒否） |
| 5 | Record・markerの不正時に候補を作らない | provider・tileの偽造、Record破損、marker欠落、PNG改変、snapshot不一致、最新設定での代用、Download結果の不正4種、部分成功、整合する部分集合 |
| 6 | 2枚目で失敗してもSUCCESSにしない | `test_second_tile_failure_is_not_success`（コンテナとしては正常だがフィルター不正のPNG。FAILED/PNG_INVALID、artifactsは空、失敗証跡、再実行はBLOCKED） |
| 7 | 未確定候補を上書きしない | 証跡のない候補、証跡の書込み失敗後の再実行 |
| 8 | dl・rel・Registryへの書込みなし | `test_only_normalize_areas_written` |
| 9 | 既存pytestがすべてPASS | 433 passed |

## Findings

1. **工程別認可は未実装**: 証跡の `authorization_ref` には、そのrunの（Download用の）fixture認可を記録している。本番コンテキストはBLOCKED。Normalize専用の認可は1-B.3-Bで扱う。
2. **領域の権限**: 保存層には工程別の許可集合がないため、新しい2領域は保存層の全利用者から書込み可能。Downloadが実際に新しい領域へ書くことはない（領域準備をDownload用の集合に限定した）。工程別に限定するかは後続の判断。
3. **排他は呼出元の責任**: このステージは自分でロックを取らない。1-B.3-Bで、Orchestratorがsource単位のロックを保持して直列に呼ぶ前提。
4. **候補の大きさ**: 65536要素の最大値の表現でも1 MiB以内に収まる。上限の超過はSIZE_INVALIDとして扱う（実際には到達しない）。

## Limitations

- 実プロセスのSIGKILL試験は今回行っていない。例外による中断と、証跡なしの候補の拒否は確認した。
- 単一ホスト・専用fixture root・直列実行が前提。

## 1-B.3-Bへの接続条件

1. Orchestratorは、DownloadのSUCCESS直後に、**同じ** `DownloadPlan` と `ModuleResult` を渡して、source単位のロックを保持したまま `NormalizeStage.run` を呼ぶ。Normalizeは自分でロックを取らない。
2. Normalize用の工程別fixture認可を追加し、証跡の `authorization_ref` をそれに置き換える。
3. Validateは、Normalize証跡の参照と候補のhashを入力とする。候補を読み直すときは上限付きで行い、hashを照合する。`expected_tile` には検証済みの固定計画の整数タイルだけを渡す（B2-F01）。
4. 実プロセスのSIGKILLを含む中断回帰試験を行う。

## Conclusion

受入済みDownloadの確定成果物から候補と変換証跡を確定し、不正・不完全・未確定の入力では候補を作らず、上書きもしないことを確認した（自己テスト433件PASS）。**最終受入ではない。**
