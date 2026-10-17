# Verification Summary

## Metadata

- Task ID: `phase1c2-elevation-validated-candidate-reader`
- Task: Phase 1-C.2 Validated Candidate Reader MVP（検証済みfixture候補の読取と地点標高の取得）
- Implementer: Claude（実装・自己テスト）
- Reviewer: Claude（自己検証。Codex検証は今回実施しない指示）
- Target Commit: 未コミット。基準main `7e91136196b9f14ea0dcdfcf5241020981b0a6cb`。作業開始時にfetchし、HEADとorigin/mainの一致と作業ツリーがcleanであることを確認した
- Status: **自己テストPASS**（ChatGPTのGitHub差分レビュー待ち。この自己テストは最終受入ではない）
- OWNER Approval: 未承認（commit・push未実施）

## Changes

| ファイル | 内容 |
|---|---|
| `src/hererisk/elevation/lookup/reader.py`（新規、195行） | `read_point_elevation`、`PointElevation`、`ReadRejected` |
| `tests/contract/test_elevation_reader.py`（新規、340行、37件） | 実パイプラインの成果物を読む契約テスト |

`lookup/core.py`、Normalize・Validateのコアとstage、保存層、Orchestrator、認可、設定は変更していない。新しい依存・エラーコード・保存領域は追加していない。

## インターフェース

```python
read_point_elevation(area: ApiDataArea, run_id: str, latitude, longitude, zoom: int) -> PointElevation
```

- `area`: 呼出元が渡す、そのAPI用のデータ領域。fixtureのデータrootであること（マーカー）が必須。
- `zoom`: 呼出元が明示的に指定する。Z14を固定していない。
- 結果 `PointElevation`: run_id、acquisition_id（候補の識別子）、candidate_sha256、z・tile_x・tile_y、pixel_x・pixel_y、`elevation_cm`（intまたはNone）、`nodata`（`elevation_cm is None`）。`to_dict()` も用意した。

## 読取手順（すべて読取専用）

1. `run_id` のUUID形式を確認し、`locate_pixel` でタイル・画素を求める。
2. fixtureのデータrootであることを確認する。
3. **Validate証跡**を上限付きで読み、厳密に解析し、Schemaで検査する。status=SUCCESS、error_code=null、7項目のchecksがすべてpassed、同じrun_idであること。
4. **Normalize証跡**のSHA-256が、Validate証跡に記録された `normalize_record_sha256` と一致すること。あわせて、SUCCESS、同じrun、Validate証跡と同じsource・実効設定・outputs、inputs・outputs・tilesの各ID列が同じ順序であることを確認する。
5. **タイルから取得IDを引く**: Normalize証跡の固定inputsの `tile` だけで決める（ディレクトリ名からの推測や候補の総当たりはしない）。該当がなければ TILE_NOT_IN_RUN、重複は不整合とする。
6. **その候補1件だけ**を保存層から上限付き（1 MiB）で読み、size・hashをNormalize証跡と照合する。
7. 厳密なJSON解析を行い、`validate_candidate(candidate, expected_tile=<計画の整数タイル>)` で検査する。得られた統計（valid・nodata・min・max・warning）が、Validate証跡の記録と一致すること。
8. `lookup_elevation` で格納値をそのまま取り出す。

証跡の信頼の連鎖は、Validate証跡 → Normalize証跡のhash → 候補のhash。SUCCESSと記録されているだけでは信用せず、各段を再照合する。PNG原本やDownload証拠は読まない。

## エラー・欠損の区別

`ReadRejected` は既存の `PipelineError` を継承し、`reason` を持つ。既存のエラーコードを再利用し、新しいコードは追加していない。

| 状態 | reason | error_code |
|---|---|---|
| 座標・zoomの不正 | INVALID_COORDINATES | INVALID_INPUT |
| run_idの形式不正 | INVALID_RUN | INVALID_INPUT |
| fixtureのデータrootでない | NOT_FIXTURE | APPROVAL_REQUIRED |
| Validate証跡がない、またはSUCCESSでない | NOT_VALIDATED | INVALID_INPUT |
| **タイルがそのrunに含まれない** | TILE_NOT_IN_RUN | TARGET_UNCONFIGURED |
| 証跡の破損・不整合（hash、参照、統計） | EVIDENCE_INCONSISTENT | RECOVERY_REQUIRED |
| 候補の欠落・hash不一致 | CANDIDATE_CORRUPTED | STORAGE_INTEGRITY_FAILED |
| hashは整合するが候補が不正（JSON・形式） | CANDIDATE_INVALID | VALIDATION_FAILED |
| **有効な候補の画素値がnull** | （エラーではない） | 正常な結果。`elevation_cm=None`、`nodata=True` |

タイルが存在しない場合はエラー、欠損画素は正常な結果として返すため、両者は混同しない。

## Verification

| Check | Result |
|---|---|
| Reader契約テスト（37件） | PASS |
| 全pytest | **PASS: 670 passed**（既存633 + 新規37、約94秒） |
| 変異確認 | 9点すべて検出（Validate証跡のstatus単独・error_code単独、Normalize証跡のhash、候補のhash、Validate Coreの省略、統計の照合、未存在タイルを別タイルで代用、fixtureマーカー、outputsの一致）。最初はstatus条件が単独では試験されていなかったため、条件ごとの試験を3件追加した |

テスト項目との対応:

| 内容 | 主なテスト |
|---|---|
| 実パイプラインの成果物を読む | すべての試験で、Orchestratorの `run_fixture_pipeline` による実成果物を使う |
| 1タイル・2タイルで正しいcm値 | 大阪1タイル5画素、東京2タイル×3画素。期待値はfixture PNGの生成規則による。取得ID・hash・`to_dict` の形も確認 |
| 0・負値・nullの区別 | 画素に0、−120、欠損、1234を配置したPNGを、パイプライン経由で処理して読む（型まで確認） |
| zoomの明示 | 同じ地点のz13は、runに含まれないタイルになる |
| 該当タイルがない | TILE_NOT_IN_RUN（欠損とは別） |
| Validate SUCCESS証跡がない | runが存在しない、Validateが未実行、FAILED、条件ごと（status・error_code・check） |
| hash不一致 | 候補の改変・欠落、Normalize証跡のバイト列の変化 |
| 不正JSON | NaN、途中で切れたJSON、重複キー、形式違反。いずれも全hashを整合させた偽造 |
| 値の偽造 | 全hashを整合させて値だけを変えた場合も、統計の照合で検出 |
| 証跡の不整合 | Normalize参照、outputs、tiles、source hash、Validate証跡の破損 |
| 保存データを変更しない | 読取の前後でファイルのhashが不変。読む候補は該当の1件だけで、PNG原本は読まない |

## 設計上の制約

1. **fixtureのみ**: マーカーとSchema（`execution_context=fixture`）の両方で限定している。将来の本番データの読取権限・経路は、この前提から推定しない。
2. **信頼の起点**: Validate証跡そのものはhashで固定されていない。管理領域に書き込める主体なら、整合した一式を偽造できる（既存の信頼境界と同じ）。
3. **呼出しごとの再検査**: 呼び出すたびに、2つの証跡と候補1件（約350 KB）を読み、Validate Coreを実行する。キャッシュはしない。
4. **範囲外**: Download証拠・設定スナップショットの再照合は、パイプライン側の責務として行わない。
5. Publish・Registry・Coverage・Web APIは扱わない。タイルの有無は、指定runの証跡の範囲でだけ判定する。

## Conclusion

検証済みのfixture候補から、指定地点の格納標高を読取専用で取得できる。タイルの未存在と欠損画素を区別し、証跡の連鎖が崩れている場合は成功させない（自己テスト670件PASS）。**最終受入ではない。**
