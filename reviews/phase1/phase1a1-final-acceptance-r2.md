# Phase 1-A.1 Round 2 最終受入検証

- Task ID: `phase1a1-final-acceptance-r2`
- 対象コミット: `e622d04cf1aee3b1170eeac61ab8a51964a010fa`
- 日付: 2026-10-17 / 修正担当: Claude / 独立検証: Codex
- **判定: PASS WITH FINDINGS。Phase 1-A.1 Fixture Download MVPは受入可能。Phase 1-Bへ進行可能。**

## 1. 検証範囲・実測結果

開始時clean。指示されたfetch後にHEAD・origin/main・対象コミット一致。[前回レビュー](phase1a1-elevation-download-independent-reverification-r1.md)、[修正レポート](phase1a1-elevation-download-audit-remediation-r2.md)、[契約](../../docs/pipeline/elevation-download-contract-v0.1.md)を参照し、R1-01〜04と対象差分の回帰に限定した。

| 実行 | 結果 |
|---|---|
| 既存pytest全件 | **261 passed / 44.44秒** |
| 前回Codex独立試験（無改変） | **53 passed / 13.41秒**。証拠hash一致も確認 |
| 今回の限定追加試験・最終実行 | **8 passed / 1.69秒**。混在未確定状態、2 sourceの予約競合、有効PLTE、実macOS firmlink、TransportのFD解放 |
| 実SIGKILL・別プロセス排他 | 既存・独立試験に含まれる6停止点＋1件がそれぞれPASS |

Python 3.14.3 / macOS arm64の既存venvを利用。実機firmlink試験はskipせず実行した。本番DownloadのBLOCKED、正常経路のRegistry・dl/rel不変を既存回帰で確認。外部接続・DNSガード下で実施し、実GSI通信なし。Git fetch以外の外部通信、VPS操作、Docker変更、Publish実装は行っていない。

追加試験初回は7件中6 PASS・1 FAILだった。quotaロック初回作成の競合で想定したRECOVERY_REQUIREDではなくSTORAGE_INTEGRITY_FAILEDとなるためで、下記R2-F01として残す。最終8件は初回作成と作成済みを分け、前者でこの安全側停止を許容しつつ、予約8件以下・転送1要求のみ・失敗側snapshotなしを検証した。前回53件の期待値は変更していない。

## 2. 修正必須4件の結論

| 指摘 | 状態 | 確認根拠 |
|---|---|---|
| R1-01 root固定 | **CLOSED** | pin後に同一FD/識別子連鎖で保護領域とmarkerを判定。fixtureツリーへの誘導、pin前祖先symlinkを拒否。macOS firmlink別名も実行・初期化とも拒否。pin後は置換先に追従しない |
| R1-02 未確定物上限 | **CLOSED** | part・原本のみ・Recordのみ・markerのみ/一時物等を重複なく計数。上限後はsnapshot/候補を増やさない。API共通quotaロック内で確認と予約を行い、複数sourceの並行処理でも上限8を超えない |
| R1-03 PNG | **CLOSED** | PLTE長0/1/4/771を拒否。有効なRGBの3/6/765/768byteを受入。画像展開・標高品質判定は追加していない |
| R1-04 FDリーク | **CLOSED** | open後fstat等の失敗でFD解放。旧独立試験、反復EIO試験、Transportのfdopen失敗を確認。fstat EIOは保存エラーに分類され、正常系も維持 |

今回の実行環境・信頼境界で、変更差分に関連する新たなCRITICAL/HIGH問題、領域逸脱、データ破壊、取得記録の不正SUCCESS、秘密漏えいは確認していない。

## 3. Findings・運用前提・対応期限

**R2-F01 LOW / 後続対応: quotaロック初回同時作成時の安全側停止。**

該当: [storage.py](../../src/hererisk/common/storage.py) 648–651行、[download.py](../../src/hererisk/elevation/download/download.py) 149行。

最小再現: 初期化済み一時rootに未確定7件を配置し、quotaロック未作成のまま東京/大阪sourceを同時開始する。macOS上で、一方のquota lock `os.open`がENOENTとなりSTORAGE_INTEGRITY_FAILEDを返すケースを観測した（診断時にも再現、発生率は未測定）。もう一方は予約を取得でき、上限超過なし。失敗側はsnapshot/転送前に停止する。作成済みquotaロックでの競合は期待どおりRECOVERY_REQUIRED。

領域・記録の安全性を破壊する失敗ではないため、fixture MVPのブロッカーにはしない。管理ユーザーは失敗を成功扱いせず、状態確認後に再要求する。**Phase 1-Bの並行実行運用を常用する前**に、ロック初期化の直列化または限定的な再試行を検討し、原因と回帰試験を確定する。根拠なく検査やNOFOLLOWを緩めない。

| 残課題・前提 | 対応工程・期限 |
|---|---|
| 単一ホスト、専用の使い捨てfixture root。work/recordsと親領域は管理ユーザーのみ書込可。固定済みinode自体の移動・全証拠の同一管理者による書換えは防御境界外 | **今から適用**。権限の異なる主体を追加する前に信頼境界を再設計 |
| 空予約・未確定物は保守的に残す。上限時は自動削除せず、プロセス停止・証拠保全後に手動整理。全marker走査、他run破損時のresume停止、blocking quota待ち時間 | fixtureでは既存手順で運用。**長期・大量データ運用開始前**にPhase 1-B以降で容量・索引・復旧方針を決定 |
| 設定親symlinkの信頼、実OS/Volumeの永続性・UID/GID、Linux/VPS、電源断、syslog/journald | 今回未検証。**本番・実データ運用開始前**に詳細設計・実機検証 |

## 4. 受入・成果物

R1-01〜04はすべてCLOSED。上記前提と後続課題を記録したうえで、**Phase 1-A.1のfixture限定受入とPhase 1-Bへの進行を可**とする。実GSI取得、本番公開、未承認の取得条件を許可する判定ではない。

公開変更は本レビューのみ。非公開報告は `workspace/reports/codex/phase1a1-final-acceptance-r2-report.md`、実行証拠は `workspace/reports/codex/phase1a1-r2-evidence/`。コード・本番設定・既存テスト・過去独立証拠は変更していない。Git差分、リンク、秘密情報と非公開ファイルの除外を確認。commit/pushは未実施。
