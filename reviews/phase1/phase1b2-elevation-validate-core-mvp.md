# Verification Summary

## Metadata

- Task ID: `phase1b2-elevation-validate-core-mvp`
- Task: Phase 1-B.2 Validate Core MVP（Normalize候補のメモリ上の形式・値・欠損検査と統計）
- Implementer: Claude（実装・単体テスト）
- Reviewer: Claude（自己検証。独立検証ではない）
- Target Commit: 未コミット。基準main `e1b6eb5ca60de52e194a5369582814a731b1b46d`。作業開始時にfetchし、HEADとorigin/mainの一致と作業ツリーがcleanであることを確認した
- Status: **自己テストPASS・独立検証待ち**（この自己テストは最終受入ではない）
- OWNER Approval: 未承認（commit・push未実施）

## Changes

| 区分 | 内容 |
|---|---|
| 新規 | `src/hererisk/elevation/validate/core.py`（約130行）: `validate_candidate(candidate, *, expected_tile=None) -> ValidationResult`、`CandidateRejected` |
| 新規 | `tests/unit/test_validate_core.py`（73件） |

変更していないもの: Normalize Core（B1-F01は指示どおり未修正）、Download、Orchestrator、Configuration Manager、保存層・認可、CLI、Record、依存関係、文書。ファイルの保存・読込み、証跡、Publish・Registry、通信は実装していない。

### 検査内容

1. **キー**: `format`・`tile`・`width`・`height`・`values_cm` がちょうど揃っていること（欠落・未知キーは拒否）。
2. **format**: `hererisk-elevation-cm-json-v0.1` と完全一致すること（定数はNormalizeの `FORMAT` を再利用）。
3. **tile**: z/x/yのみからなる整数（boolは不可）で、0≤z≤30、0≤x,y<2^z。Normalizeと同じタイル検査関数を再利用する（変換処理は呼ばない）。任意引数 `expected_tile` を渡すと、固定計画のタイルとの完全一致も求める。
4. **寸法**: width・heightがともに整数の256であること（256.0やTrueは不可）。
5. **values_cm**: list型で、要素数がちょうど65536であること。
6. **各要素**: `type(v) is int` または `None` であること。bool、float（NaN・Infを含む）、文字列、bytes、入れ子、intのサブクラスは拒否する。暗黙の型変換はしない。
7. **値域**: −8388607〜8388607 の範囲内であること。
8. **統計**: 型・値域の検査と同じ1回の走査で、valid_count・nodata_count・min_cm・max_cm を計算する。Noneだけを欠損とし、0と負値は正常値として数える。

### 結果と拒否

- 合格時は、不変の `ValidationResult(profile, tile, valid_count, nodata_count, min_cm, max_cm)` を返す。`stats()` は推奨どおりの4キーのdictを返す。
- 全欠損でも合格とする。このときmin・maxはnullで、`warning == "ALL_NODATA"` になる。ログ基盤は追加していない。
- 不合格時は `CandidateRejected` を送出する。既存の `PipelineError` を継承し、`error_code` は既存の **INVALID_INPUT**、`check` に失敗した検査名（keys / format / tile / dimensions / values）を持つ。契約案の `VALIDATION_FAILED` は共通エラー表への追加が必要なため、今回は追加していない（指示どおり）。
- 入力は読むだけで、修正・補完・並べ替えはしない。PNGの復号もNormalizeの呼出しもしない。

## Verification

| Check | Result |
|---|---|
| Validate単体（73件） | PASS |
| 全pytest | **PASS: 393 passed**（既存320 + 新規73） |
| 変異確認 | 6点中5点を検出（型の暗黙変換、値域検査の削除、0を欠損扱い、配列の過剰を許容、expected_tileの無視）。残る1点（min/max更新の `elif` を `if` に変更）は挙動が同じになる等価変異のため、試験の不足ではない |
| 共通基盤・Normalizeへの変更 | なし |

試験の内訳:

| 区分 | 内容 |
|---|---|
| Normalize出力 | `fixture_builder` のPNGを実際にNormalizeした出力を受け入れること。欠損663件（手計算の固定値）と一致 |
| 計数・統計 | 正値・0・負値・欠損の混在、欠損がmin/maxに影響しないこと、1値のみの場合、減少→増加する並び |
| 一様タイル | 全0、全負値、全最小値、全欠損（ALL_NODATA）。0を欠損扱いしないこと |
| 拒否（構造） | 配列長0・1・65535・65537、format・寸法・tile不正15種、キーの欠落・未知・非object、expected_tileとの不一致 |
| 拒否（値） | 値13種（True、False、1.0、0.0、NaN、Inf、"12"、b"1"、[1]、{}、8388608、−8388608、2^63）×位置3か所（先頭・中央・末尾）、intのサブクラス |
| 不変性 | 入力が変更されないこと（成功時・失敗時）、結果オブジェクトが不変であること、Normalize・PNG処理・I/Oへの依存がないこと（静的検査） |

## Findings

1. **エラーコード**: 不合格を INVALID_INPUT（終了コード2）で表している。契約案のVALIDATION_FAILED（終了コード11案）を採用する場合は、共通エラー表の変更をOWNERが承認したうえで、`CandidateRejected` の1か所を差し替える。
2. **内部関数の再利用**: タイル検査は `normalize.convert._check_tile`（private）を再利用し、規則を二重定義しないようにした。公開名にするかどうかは後続の判断事項。
3. **B1-F01**: `max_png_bytes` の型検査はNormalize側の後続課題として、今回は扱っていない。

## 未実装の後続機能

- 候補JSONの保存・読込みとhash照合
- 変換証跡・検証証跡（`records/normalizations`・`records/validations`）
- Download証拠との接続
- Orchestratorでの逐次呼出しと工程別認可
- VALIDATION_FAILEDの追加
- 実データでの品質判定（欠損率、地形の妥当範囲、近隣との整合）

## Conclusion

正常な候補を受け入れ、不正な候補を検査名付きで拒否し、欠損と0mを区別した統計を返すことを確認した（自己テスト393件PASS）。**最終受入ではない。**
