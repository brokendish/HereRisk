# Verification Summary

## Metadata

- Task ID: `phase1a1-elevation-download-audit-remediation-r2`
- Task: 独立再検証Round 1の修正必須4件（R1-01〜R1-04）の限定修正
- Implementer: Claude（修正・回帰テスト）
- Reviewer: Claude（自己検証。独立検証ではない）
- Target Commit: 未コミット。基準main `61b2a2098652f32d647f3203804da3808f5c0e84`（対象実装 `8ad69e9`、再検証 `61b2a20`）。作業開始時にfetchし、HEADとorigin/mainの一致と作業ツリーがcleanであることを確認した
- Status: **自己テストPASS・Codex再検証待ち**（この自己テストは最終受入ではない）
- OWNER Approval: 未承認（commit・push未実施）

## Changes

### R1-01 HIGH — root固定前の競合

- ApiDataAreaは、データrootを生成時に一度だけ正規化する。そのうえで、最初の利用時に `/` から各階層を `O_NOFOLLOW | O_DIRECTORY` で辿って開き、FDを固定する（`pin`）。祖先・root自体のsymlinkは、固定時に `PERMISSION_DENIED` として拒否する。
- 固定時に、辿ったディレクトリの識別子（dev, inode）の連鎖を記録する。保護対象root（`/data`、設定・Schemaのルート、fixture定義ツリー）の判定は、固定済みの連鎖と正規化パスで行う（`root_within`）。パスの再resolveはしない。markerも同じFDから読む。
- Orchestratorは、pin → 保護対象判定 → marker確認の順に、同じFD上で判定する。従来のパスによる事前判定は、早期に失敗させるための補助として残す。
- 修正の過程で、旧来の字句的な判定だけではmacOSのfirmlink別名（`/System/Volumes/Data/...`。`realpath` で正規化されない）を通過できることを確認した。識別子での判定でこれを拒否する。`init-fixture-root` も同じ判定に変更した。
- markerは初期化の意図を示すだけで、認証情報としては扱わない（文書化）。FD固定後のディレクトリ移動という残余条件は、信頼境界とは別に文書化した。

### R1-02 MEDIUM — 未確定物上限の抜け

- `pending_acquisitions` は、未確定の取得を取得IDごとに1件として数える。対象は次のとおり。
  - 予約・part（`work/download`）
  - 原本のみ、Recordのみ、markerのみ
  - 一時ファイル
  - 識別できないエントリ（1件ずつ、保守的に計上）
- 確定済みと判定するのは、marker・Record・原本が揃い、partと一時ファイルが残っていない取得だけ。
- 枠の確認と予約（`work/download/<run>/<acq>` の作成）は、API共通の `work/locks/download-quota.lock`（blocking flock）の下で一体に行う。異なるsource_ref間でも上限8を超えない。
- 新しいrunでは、Orchestratorがスナップショットを保存する前に `reserve_capacity` を呼ぶ。上限に達していれば、スナップショット・予約・転送のいずれも行わない。2件目以降のタイルも、取得ごとに同じ方法で予約する。
- 同じrun_idの再開ではスナップショットを新規に保存しないため、事前予約はしない。既存の照合・RECOVERY_REQUIRED規則は維持した。自動削除はしない。

### R1-03 MEDIUM — PLTE長さ

PLTEについて次を検査する。既存の順序・CRC・重複検査は維持した。画像の展開・標高品質の判定はしない。

- 非空で3の倍数、最大768バイト（256エントリ）
- グレースケール（0, 4）では禁止
- インデックスカラー（3）では必須で、エントリ数は2^bit_depth以下
- RGB（2, 6）では任意

### R1-04 MEDIUM — FDリーク

- FD取得後の型検査を `_checked_dir` に集約した。FDの所有権は、成功時にだけ呼出元へ移す。失敗時は必ず閉じたうえで、OSErrorを保存層の共通エラーに分類する。
- 同じパターンの箇所も点検・修正した。
  - root固定の連鎖walk
  - `NewFile` の `fdopen` 失敗時（ファイルFDと親FDの両方を閉じる）
  - 各fstat・fsync・flockのOSError分類
  - marker読込み
  - FixtureTransportのfstat・fdopen

## Verification

| Check | Result |
|---|---|
| 全pytest | **PASS: 261 passed**（約41秒、連続4回同一）。内訳: 単体90、契約in-process 155、CLIプロセス9、実プロセス7 |
| 既存226件 | 維持。期待値の変更なし |
| R2回帰テスト（`tests/contract/test_audit_regressions_r2.py`） | 35件PASS。内訳は下表 |
| 実SIGKILL 6停止点・別プロセス排他 | PASS（`tests/contract/test_process_kill.py`、7件） |
| Codex R1独立証拠（非公開、**無改変**で実行） | **53/53 PASS**（`test_previous_adapted.py` 25件、`test_r1_boundaries.py` 28件。前回は43/53） |
| 変異確認 | PASS: R2の防御8点を1つずつ無効化し、すべて検出（root連鎖walk、識別子判定、固定後の保護判定、確定済みの定義、スナップショット前の予約、quotaロック、PLTE長、fstat失敗時のclose）。識別子判定とquotaロックは、最初の試験では検出できなかったため、firmlink試験とbarrier注入試験を追加して検出を確認した |
| 本番取得 | BLOCKED / APPROVAL_REQUIRED を維持 |
| 外部通信 | 0回 |
| dl / rel / Registry | 変更なし |
| 実機（Linux/VPS、電源断、Docker、syslog/journald） | NOT RUN |

| 項目 | 主なテスト（すべてPASS） |
|---|---|
| R1-01 | 字句検査直後のrootのsymlink差替え、area生成後・pin前の差替え（PERMISSION_DENIED）、初回I/O前の祖先差替え、1〜3段の祖先symlink、Schemaツリーへの誘導、識別子判定、firmlink別名（Orchestrator・init）、pin後の差替え（固定inodeにだけ書く）、markerを固定FDから読むこと、`/data` |
| R1-02 | Record書込み失敗×8回の後の3回反復（書込み0）、marker失敗×8回の後の3回反復、part中断×8回の後の3回反復、異なるsource_refの同時実行、確認と予約の原子性（barrier注入）、確定済み12件を計上しないこと、6状態の重複なし計上、上限到達時の同run再開 |
| R1-03 | PLTE長0/1/4/771をPNG_INVALID（end-to-end）、長3/768のRGBはSUCCESS、単体の色形式規則 |
| R1-04 | `_opendir` のfstat EIO×20回、pin時のfstat失敗×10回、非ディレクトリ判定×10回、`fdopen` 失敗×10回、Transportのfstat失敗×10回、正常系・拒否系の反復でFD数が不変、EIOがSTORAGE_INTEGRITY_FAILEDに分類されること |

## Findings

1. **契約差分（追加なし）**: CLI引数・fixture承認形式は変更していない。`work/locks/download-quota.lock` を追加した（排他用で、`work/locks` 配下）。DownloadModuleの内部プロトコルに `reserve_capacity` と、`execute` の `reserved_acquisition_id` 引数を追加した。
2. **予約の副作用**: 予約後に転送が404等で失敗した場合も、空の予約ディレクトリが未確定物として1件残る（保守的。手動整理の対象）。
3. **quotaロックの性質**: blocking flockのため、枠を確認している間（短時間）は他のrunが待つ。単一ホスト前提。
4. **プラットフォーム判定**: `os.open` 等を差し替える環境（計測ツール等）では、`_platform_supported` が安全側に全I/Oを拒否する（テストで確認）。

## Limitations / 残余リスク

- FD固定後のディレクトリ自体の移動は防がない。I/Oは固定したinodeで続き、差し替え先へは追従しない。管理ユーザーだけが書き込める前提とし、fixture限定で許容する。
- 他runの解析不能なmarkerによる全resume停止、全markerの走査コスト、設定ツリーの親symlinkの許容は、前回から変更していない（後続判断）。
- 自動回復、電源断の永続性、Linux/VPS、Docker Volume、本番の権限・所有者設計は未実施・未決定。

## Conclusion

R1-01〜R1-04は修正済み。自己テストは全261件PASSで、Codex R1独立証拠も無改変で53/53 PASS。ただし**最終受入ではない**。

Codex再検証への引渡し事項:

1. R1-01: root固定の各タイミング（字句検査後、area生成後・pin前、pin後）での差替えと、firmlink別名を独立に再現・確認する。
2. R1-02: 未確定状態ごとの計上と、並行source間での上限を確認する。Linux等、別環境でのflockの挙動も確認する。
3. R1-03・R1-04: 独立に確認する。
4. Findings 1〜4の採否をOWNERが判断する。
