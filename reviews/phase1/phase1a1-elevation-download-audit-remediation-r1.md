# Verification Summary

## Metadata

- Task ID: `phase1a1-elevation-download-audit-remediation-r1`
- Task: Phase 1-A.1 独立検証FAIL（F01〜F12）への限定修正
- Implementer: Claude（修正・回帰テスト）
- Reviewer: Claude（自己検証。独立検証ではない）
- Target Commit: 未コミット。基準main `d634cb0f7f55ecc17c4fd791bbb456ed199f235b`（対象実装 `264ff0a`、独立検証 `d634cb0`）。作業開始時にfetchし、HEADとorigin/mainの一致と作業ツリーがcleanであることを確認した
- Status: **自己テストPASS・Codex再検証待ち**（この自己テストは最終受入ではない）
- OWNER Approval: 未承認（commit・push未実施）

## Changes

| ID | 修正内容 | 主なテスト |
|---|---|---|
| F01 | 保存層の全I/O入口が、Pathではなく検証済みの論理位置 `Loc` だけを受け付ける。書込み可能領域と読込み可能領域を別の集合として定義し、操作ごとに再検証する。`dl/`・`rel/`・Registry・他APIへの経路はない | `test_every_operation_rejects_forbidden_locations`（13操作×9位置）、`test_plain_paths_grant_nothing`、`test_reads_limited_to_readable_areas` |
| F02 | データrootを一度だけディレクトリFDとして開き、各階層を `dir_fd` + `O_NOFOLLOW` + `O_DIRECTORY` で辿る。mkdir・open・linkat・unlink・rmdir・stat・lock・fsyncはすべてFD基点。非対応環境では全操作を拒否する。FixtureTransportもFD基点で開き、サイズはfstatから取る | `test_parent_swapped_to_symlink_during_operation`（親・祖父・API dirの3段）、`test_symlink_swap_before_operation_fails_safe`、`test_data_root_swap_after_open_has_no_effect`、`test_symlinked_final_component_not_followed`、`test_unsupported_platform_fails_safe` |
| F03 | 照合時に、固定設定（Source原文hash、実効設定ref・hash、source、URL、provider、pipeline、地域、usage）と実測（size・hash）から期待Recordを再構成し、完全一致を要求する。Recordから採るのは `acquired_at` だけで、実在する日時であることを検証する。タイルは計画集合内に限る。信頼モデルを文書化した | `test_forged_but_hash_consistent_record_is_rejected`（20種。Codexの再現手順を含む）、`test_forged_snapshot_is_rejected`、`test_swapped_artifacts_between_tiles_rejected` |
| F04 | 再実行時はrun単位で集合照合する。`records/commits` 全体を走査し、markerの参照先からrunへの帰属を判定する。marker・Record・原本の3集合の一致と、`work/download/<run>` が空であることを要求する。欠落分を再取得してSUCCESSにすることはしない | `test_orphan_marker_without_record_and_artifact`、`test_any_single_missing_evidence_blocks`（3種）、`test_extra_marker_pointing_into_run_blocks`、`test_unparseable_marker_blocks_resume` |
| F05 | Schemaは同一文書内の `#` 参照だけを許可し、`$id` を禁止する（静的検査）。加えて、取得を常に拒否するRegistryで検証する（二重防御）。CLIの `--config-root` は廃止し、Schemaの読込み先をリポジトリに固定した | `test_external_schema_reference_never_fetched`（5種、DNS/接続試行0）、`test_registry_alone_never_retrieves`、`test_external_schema_via_orchestrator_is_invalid_configuration` |
| F06 | 用途別の上限: 設定1 MiB、Record 64 KiB、marker 16 KiB、原本はポリシー値（1 MiB）。開いたFDのfstatで事前に判定し、読込み中も上限で打ち切る。原本hashはストリームで計算する | `test_oversized_committed_evidence_rejected`（64 MiB疎ファイル3種、実読込み1 MiB未満）、`test_oversized_configuration_rejected`、`test_oversized_authorization_rejected`、`test_reads_are_bounded` |
| F07 | IHDRのcompression/filter=0・interlace∈{0,1}、IHDR重複、IEND長0、未知の必須chunk、chunk型の文字、PLTEの位置と重複、IDATの連続、IEND後の余剰を検査する。画像展開はしない | `test_png_container_rules`（14種）、`test_png_container_valid_variants`（3種）、`test_bad_ihdr_methods_and_iend_rejected_end_to_end` |
| F08 | Source Definitionの読込み時と実効設定の保存前に、全文字列のURLを検査する（https限定、userinfo・query・fragment・明示port禁止）。違反時はスナップショットを一切作らない。値はログ・結果に出さない | `test_secret_url_rejected_before_any_snapshot`（4種）、`test_secret_in_other_source_of_definition_also_rejected` |
| F09 | argparseのエラーを固定文言に置き換え、終了コード2を維持した | `test_cli_syntax_errors_do_not_echo_values`（4種） |
| F10 | 確定物（原本・Record・marker）を読むときは、通常ファイル・実行ユーザー所有・リンク数1を要求する。`.part` の確定時も、リンク数1を確認してからlinkする。正当なlink+unlinkの途中状態（リンク数2）は確定物として扱わない | `test_external_hardlink_alias_blocks_resume`（3種）、`test_hardlink_alias_rejected_for_committed_reads`、`test_link_refuses_source_with_external_alias` |
| F11 | fixtureポリシーに `max_pending_acquisitions`（8）を追加した。データroot全体の未確定取得物が上限以上になると、新しいrunもBLOCKED / RECOVERY_REQUIREDとし、転送しない。自動削除はしない。手動の整理手順を文書化した | `test_pending_parts_are_capped_without_deletion` |
| F12 | 共通Orchestratorで、fixtureコンテキストのデータrootに明示的なマーカー（`init-fixture-root` で作成）を要求する。`/data` 配下と設定・Schema・fixture定義ツリー配下は拒否する（symlinkは解決して判定）。CLIに `init-fixture-root`（空ディレクトリのみ）を追加した | `test_orchestrator_requires_marked_fixture_root`、`test_orchestrator_rejects_root_inside_config_or_fixture_tree`、`test_orchestrator_rejects_production_data_root`、`test_symlinked_data_root_cannot_redirect_into_repo`、`test_cli_fixture_requires_initialised_root`、`test_cli_init_fixture_root_refusals` |

その他:

- 実プロセスSIGKILL試験（6停止点）と別プロセス排他試験を自前で追加した（`tests/contract/test_process_kill.py`）。
- CLI子プロセス内にもソケットガードを設けた。
- 新規依存はない（`referencing` は既存jsonschemaの依存）。
- 本番 `sources.json`・Schema・47地域定義は変更していない。
- 契約文書は変更していない。fixture承認の形式にポリシー項目を1つ追加し、CLIの引数を変更した（下記Findings）。

## Verification

| Check | Result |
|---|---|
| 全pytest | **PASS: 226 passed**（約29秒、連続4回同一結果） |
| 内訳 | 単体90、契約（in-process）120、CLIプロセス9、実プロセス（SIGKILL・別プロセス排他）7 |
| 既存117件 | 維持。期待値は緩めていない。保存層API変更に伴い、Pathベースのフック・単体テストをLocベースへ書き換えた |
| 変異確認 | PASS: 指摘ごとの防御を1つずつ無効化した14変異をすべて検出（F05の静的検査とRegistryは個別に検出） |
| Codex独立試験（非公開証拠）の参照実行 | 証拠ファイルは無改変。F12のマーカー要件だけを加えた複製で **22/25 PASS**（SIGKILL 6点・別プロセス排他を含む）。残り3件は旧内部API（`_reject_symlinks`、Path引数、`read_bytes` の旧シグネチャ）に依存する試験手法の非互換で、同じ観点を本リポジトリの回帰テストで確認した |
| 本番取得 | PASS: 本番定義は引き続きBLOCKED / APPROVAL_REQUIRED（in-process・CLIとも）。データrootへの書込みなし |
| 外部通信 | PASS: テスト・CLI子プロセスとも接続・DNS試行0。HTTP Transportなし |
| Publish / Registry / dl / rel | PASS: 書込み経路なし（保存層の許可集合外）。正常系でもバイト不変 |
| 実機（Linux/VPS、電源断、syslog/journald、実Docker Volume） | NOT RUN |

## Findings

1. **CLI・使い方の変更**: `--config-root` を廃止し、fixture実行の前に `init-fixture-root` が必要になった。契約4.1との差異として、引き続きOWNERの承認対象。
2. **fixture承認形式**: ポリシーに `max_pending_acquisitions` を追加した。`max_tile_bytes` の上限を16 MiBとした。どちらもfixture専用で、本番値ではない。
3. **F04の走査範囲**: markerは契約どおり `records/commits/<acq>.json` のままとし、全markerを走査してrunへの帰属を判定する。解析不能なmarkerが1件でもあると、同じrun_idの再実行はすべてRECOVERY_REQUIRED（安全側）。markerが大量にある場合の走査コストと、run別索引の採否は後続の判断事項。
4. **F10の方針**: リンク数1・所有者一致はfixture MVPの最小防御。本番の所有者・権限・nlink方針は未決定。
5. **F02の残余リスク**: 保持中のディレクトリFDが指すディレクトリそのものを、第三者が領域外へ移動した場合、書込み先はその（元々自分の）ディレクトリになる。攻撃者が指定した場所へ追従することはない。データrootの書込み権限を管理ユーザーに限定する前提は変わらない。
6. **設定ファイル**: 最終要素は `O_NOFOLLOW` で開くが、リポジトリ内の親階層のsymlinkは許容している。設定・Schemaの読込み先は、CLIからは変更できない。
7. **F08の検査範囲**: URL形式の文字列だけを対象とする。URL以外の文字列に含まれる秘密は、Schemaの `additionalProperties: false` と項目定義で制限される範囲にとどまる。

## Limitations

- 自動回復（照合による確定の完了、隔離）は未実装。未確定物はRECOVERY_REQUIREDで停止する。
- 電源断時の永続性、Linux/VPS、実際の権限・UID設計、syslog/journaldは未検証。
- Codexの非公開証拠試験は、改変なしの原本では大半がF12のマーカー要件によりINVALID_INPUTとなる（意図した仕様変更）。再検証では、harnessで `init_fixture_data_root` を呼ぶ必要がある。

## Conclusion

F01〜F09は修正済み。F10〜F12は、fixture MVPの範囲で安全側の対策を実装した。自己テストは全226件PASSだが、**最終受入ではない**。

Codex再検証への引渡し事項:

1. 公開レポートの再現手順で、F01〜F12を独立に再確認する
2. 非公開証拠試験は、マーカー初期化を加えて再実行する
3. F02の競合試験は、新しい保存層（FD基点）に合わせた注入点で再設計する
4. Findings 1〜7の採否をOWNERが判断する
