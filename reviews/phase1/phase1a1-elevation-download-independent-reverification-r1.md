# Phase 1-A.1 独立再検証 Round 1

- Task ID: `phase1a1-elevation-download-independent-reverification-r1`
- 日付: 2026-10-17
- 対象コミット: `8ad69e9f793469f2cd6ba260bc24121ceaf9c65c`
- 実装修正: Claude / 独立再検証: Codex
- 開始時: 作業ツリーclean。指示された`git fetch origin main`後、HEAD・origin/main・指定コミット一致。
- **最終判定: FAIL**。前回の再現例は解消したが、root固定前の領域逸脱等が残る。**Phase 1-A.1の受入不可、Phase 1-Bへの進行不可**。修正後に再検証する。

## 1. 対象・実測結果

参照: [前回FAILレビュー](phase1a1-elevation-download-independent-verification.md)、[Claude修正レビュー](phase1a1-elevation-download-audit-remediation-r1.md)、[Download契約](../../docs/pipeline/elevation-download-contract-v0.1.md)、[使い方](../../docs/development/phase1a1-download-fixture-usage.md)。common、elevation/download、CLI、既存testsを確認した。

| 試験 | 実測結果 |
|---|---|
| 対象コミットの既存pytest全件 | **226 passed / 29.23秒**。Claude報告を流用せず再実行 |
| 前回独立試験の適合版 | **25 passed / 6.22秒** |
| Round 1追加境界試験 | **28件: 18 passed / 10 failed / 6.43秒** |
| 独立試験合計 | **53件: 43 passed / 10 failed**。既存226件と別集計 |
| 実SIGKILL・別プロセス排他 | 独立25件内の6＋1件PASS。既存226件にも別の6＋1件が含まれる |

環境: 既存`.venv`、Python 3.14.3 / macOS arm64、pytest 9.1.1、jsonschema 4.26.0。追加の依存インストールは行っていない。追加試験はGit対象外の作業報告領域、生成データはOS一時領域に限定した。旧証拠原本は保持し、複製を編集した。

外部接続・DNSを拒否するガードの下で検証。新しいSchema境界試験は接続・DNS試行0回。実GSI取得・本番データ操作なし。最新main確認のGit fetch以外の外部通信は行っていない。電源断、Linux/VPS、Docker、実syslog/journaldはNOT RUN。

## 2. F01〜F12クローズ状況

CLOSEDは単一ホスト・fixture限定の実装範囲に対する判定。本番運用の承認を意味しない。PARTIALは旧再現例を解消しているが、同じ安全性要求の境界に残存問題がある状態。

| ID | 状態 | 独立確認・残課題 |
|---|---|---|
| F01 保存層の領域制限 | **CLOSED** | 全公開I/O入口にLoc・領域再検査あり。既存の13操作×禁止位置の試験を再実行し、独自にも他API・dl・rel・Registry・絶対パス・traversalのread/write/hash/open拒否を確認。Path拒否だけで合格にはしていない |
| F02 symlink/競合 | **PARTIAL** | 固定済みFD以下の親差替えは追従しない。初回root FD取得前の親差替えは別rootへ書込む。R1-01参照 |
| F03 Record意味照合 | **CLOSED** | source原文hash、実効ref/hash、provider、URL、pipeline、地域・タイル・usageを固定計画から再構成して照合。有効な日時を検査。旧複合偽造試験と既存20変異等が拒否される。保存snapshot不一致も拒否 |
| F04 marker集合 | **CLOSED** | Record/原本/markerの単独欠落・孤立markerを拒否。他runの正常markerは混入しない。他runの解析不能markerは安全側に全resumeをBLOCKED。走査負荷は後続課題 |
| F05 外部Schema | **CLOSED** | `$ref` / `$dynamicRef`の外部参照、入れ子の`$id`、file URI、相対/authority参照を拒否。取得拒否Registryも確認。CLIのSchema root変更引数は廃止。通信試行0 |
| F06 サイズ上限 | **CLOSED** | 設定・Record・markerの上限、原本のfstat事前検査＋ストリームhashを確認。8MiB独立試験は原本read前に拒否。既存64MiB疎ファイル試験もPASS。総件数/総容量はF11と別 |
| F07 PNGコンテナ | **PARTIAL** | 旧IHDR方式値/IEND長等は拒否。新しいPLTE分岐に長さ検査がなく、不正なパレットもSUCCESS。R1-03参照 |
| F08 保存前の秘密URL拒否 | **CLOSED** | 全Source/実効設定のURLを保存前に検査。旧canary query試験、他sourceのuserinfo/query/fragment等を拒否。任意の自由文を秘密と識別する機能とは区別 |
| F09 CLI値反射 | **CLOSED** | argparse固定文言化。旧未知引数canaryと既存構文エラー試験で値をstderrへ出さない |
| F10 hardlink alias | **CLOSED** | 確定物の通常ファイル・所有者・nlink=1、link前のnlink確認あり。旧alias試験と既存3証跡alias試験は拒否。link+unlink途中のnlink=2も確定物として消費しない |
| F11 未確定物蓄積 | **PARTIAL** | part段階の上限停止は実装。原本確定後の失敗は数えず、上限BLOCKEDでもsnapshotを追加。R1-02参照 |
| F12 fixture root隔離 | **PARTIAL** | 共通Orchestratorでmarker、保護パスを確認。未初期化・静的symlink・不正/hardlink markerは拒否。本番定義もBLOCKED。ただし検査とFD固定が別時点でR1-01の迂回が可能 |

8件CLOSED、4件PARTIAL、完全未対応のOPENは0件。ただしPARTIALには修正必須事項が含まれるためPASSとはしない。

## 3. 前回25件の再利用

前回の `workspace/reports/codex/phase1a1-audit-evidence/` は変更していない。適合版を `workspace/reports/codex/phase1a1-r1-evidence/` に作成した。

- Harnessで`init_fixture_data_root`を呼ぶ。
- 親symlink競合は廃止された`_reject_symlinks`ではなく、FD取得後・末端`os.open`直前に差替える。
- link/unlink失敗注入をLocと`dir_fd`に対応させる。原本byte保持という期待値は維持。
- 大きい確定原本の試験は旧`read_bytes`シグネチャに依存せず、対象inodeへの`os.read`が発生しないことを確認。
- Pathを権限として渡せないことはそのまま確認し、Locの禁止領域は別の追加試験でも検査。

Claude報告の22/25について、旧内部API非互換を実装不具合として数えず、同じ安全性要求を新方式で再評価した結果は**25/25 PASS**。期待値を緩めていない。SIGKILL workerは旧試験の処理を使い、6停止点すべて実子プロセスをSIGKILL（returncode=-9）で停止した。例外注入を実停止として報告していない。

## 4. 新規・残存Findings

### R1-01 HIGH / 修正必須 — root検査から初回FD取得までの競合

関連: F02 / F12。

該当: [orchestrator.py](../../src/hererisk/common/orchestrator.py) 135–147行、[storage.py](../../src/hererisk/common/storage.py) 198–212行。

`_check_data_root`がパスを検査した後に、ApiDataAreaが再度resolveし、その後初めてrootをopenする。`O_NOFOLLOW`はこのroot openの最終要素だけに適用され、祖先の差替えには追従する。FD固定後の防御だけではこの窓を閉じられない。

隔離再現A:

1. 正常な初期化済みdata rootと、別のfixture定義ツリーを用意する。
2. fixture定義ツリーに既知内容のfixture root markerを配置する（故意の配置誤りを模擬）。
3. `_check_data_root`が正常終了した直後、元data rootを退避し、fixture定義ツリーへのsymlinkに差替える。
4. 通常Orchestrator処理を継続すると、保護対象のfixture定義ツリー内へ`elevation/work`・`records`を書き、SUCCESSを返す。

隔離再現B: `ApiDataArea(base/data, "elevation")`生成後・初回I/O前に、baseを退避して別rootへのsymlinkにする。`write_new(Loc(("work","download","x")), ...)`が別rootへ作成する。いずれも実リポジトリ・`/data`を対象にしていない。

前提: rootまたは祖先を差替えられる主体/処理が存在すること。決定的な競合注入で再現し、自然発生頻度は測定していない。markerは初期化意図の表示であり、偽造不能な認証情報ではない。marker単独を認可根拠にしてはいけない。

最小修正: rootを先に安全にFD固定し、その同一実体について保護対象・marker・I/Oの判定を一貫させる。検査後の再resolveをなくすだけでなく、初回openに至る祖先差替えも検出/拒否する。禁止rootへの差替え・親symlink・FD固定前後を回帰試験へ追加する。

### R1-02 MEDIUM / 修正必須 — 未確定物上限の対象と判定順序が不十分

関連: F11。

該当: [download.py](../../src/hererisk/elevation/download/download.py) 142–147、218–233、422–438行、[orchestrator.py](../../src/hererisk/common/orchestrator.py) 181–185行。

再現1: Record書込み、またはmarker書込みの直前にSTORAGE_FULLを注入し、新runで9回実行する。両ケースとも9回すべてRECORD_COMMIT_FAILEDとなり、上限8でも9件の未確定原本が残る。実測は各ケース「original.png 9件、part 0件、snapshot 9件」。原本確定後にdownloadディレクトリを消しているため、`check_pending_limit`の`work/download`だけの集計から漏れる。

再現2: 転送途中失敗で8件のpartを残す。次の要求はRECOVERY_REQUIREDになるが、その前にsource.json/effective.jsonを新規保存する。BLOCKED要求を繰り返してもメタデータを増やせる。未確定物を消さない方針自体は安全だが、上限が総蓄積を抑止していない。

最小修正: part・確定原本のみ・Recordのみ・marker未確定等を取得IDで重複なく計数し、転送とsnapshot保存前に枠を確認/予約する。共有rootの枠はsource別ロックだけに依存させず、並行sourceにも一貫させる。自動削除で不整合物を隠さない。使い捨てrootの手動整理は保持方針として有用だが、実装済み上限の漏れの代替にはしない。

### R1-03 MEDIUM / 修正必須 — PLTE長さ不正のPNGもSUCCESS

関連: F07。

該当: [png.py](../../src/hererisk/elevation/download/png.py) 63–65行。

再現: 正常なRGB合成PNGのIHDR直後に、CRCを正しく算出したPLTEを挿入する。payloadを0、1、4、771byteとした4件すべて、DownloadがSUCCESSとなった。RGBパレットは3byte単位で1～256エントリ、すなわち3～768byteかつ3の倍数が必要。位置・重複だけ検査して長さを見ていない。

最小修正: PLTEの非空・3の倍数・最大エントリ数と色形式に応じた条件を検査する。これに画像展開や標高品質検証は不要。今回のFAILは標高品質の後段未実装を理由としたものではない。

### R1-04 MEDIUM / 修正必須 — `_opendir`のfstat例外でFDリーク

該当: [storage.py](../../src/hererisk/common/storage.py) 258–267行。

再現: root FDを固定してから、子ディレクトリopen直後の`os.fstat(fd)`へEIOを注入する。呼出しは異常終了するが、area.close後も該当FDは有効。試験内で検出後にcloseし、リークを持ち越していない。正常・通常拒否の10反復ではFD数増加なしを別途確認した。

`fstat`が例外になると、型不正時のcloseにも、呼出元がFDを受け取ってcloseする経路にも到達しない。Orchestratorでは生OSErrorが汎用INTERNAL_ERRORへ分類される経路でもある。

最小修正: open後の検査をtry/except/finallyで囲み、成功時にだけFD所有権を移譲する。保存層の例外分類へ統一し、Transportのopen/fstat/fdopenなど同型の資源取得経路も点検する。今回は電源断保証ではなく、コードで解決できる例外時資源解放の問題。

## 5. 追加重点項目と受入可能な制限

| 項目 | 独立評価 |
|---|---|
| 固定済みディレクトリそのものの移動 | FD取得済みのディレクトリを領域外へ移し、元パスを別symlinkへ変更する独自試験で、書込みは保持inodeに残り、置換先へ追従しなかった。これはClaudeが明示した管理ユーザー権限下の残余条件としてfixture限定で許容。**R1-01の「固定前に別実体を開く」問題とは区別** |
| Locとhardlink | 禁止位置・通常ファイル・所有者・nlink検査を確認。link+unlinkのEIOでは両名の原本を保全し、nlink=2を確定物として読まない。任意Pythonコード実行者をsandbox化するAPIではない |
| 全marker走査 | 全件をlist/sort/parseするため件数に比例して負荷・メモリが増える。他runの壊れたmarkerで全resume停止することを確認。少量fixtureでは安全側で受入可能。本番/長期運用前に索引・件数予算・帰属不能物の隔離を判断 |
| fixture marker | 未初期化、不正内容、hardlink aliasを拒否。内容が公開定数なので管理ユーザーの初期化意図を示すもので、独立した認証ではない。配置誤りをroot検査で防ぐ必要がある |
| 設定親階層symlink | 実際にfixture conf親をsymlink化してもSUCCESS。最終要素だけNOFOLLOWという文書化済み挙動。設定/Schemaの親は管理者が信頼する前提としてfixtureでは許容。本番設計で所有権・更新競合を明記する |
| URL以外の秘密・hash信頼モデル | 自由文中の秘密推定は実装範囲外。管理者が全証拠を書き換えられる場合の一式偽造をSHAだけで認証できないという説明は妥当。固定計画と矛盾した部分偽造を拒否することは確認済み |
| 新しい上限・CLI変更 | fixture承認のmax_pending_acquisitions、16MiB上限、init-fixture-root、config-root廃止はfixture専用。契約差分のOWNER承認は実装テストと別。正常fixture・別地域・本番BLOCKEDは回帰維持 |
| 時間/OS保証 | SIGKILL後再開・別プロセス排他はPASS。電源断永続性、Linux/VPS/Volume、syslog/journaldは未検証であり今回の修正必須事項と混同しない |

## 6. 成果物・再実行・結論

- 公開成果物: 本レビューのみ。
- 非公開報告: `workspace/reports/codex/phase1a1-elevation-download-independent-reverification-r1-report.md`
- 非公開証拠: `workspace/reports/codex/phase1a1-r1-evidence/`（適合試験、追加境界試験、SIGKILL worker、実行結果、hash一覧）。

```sh
.venv/bin/python -m pytest -q
PYTHONPATH=src:tests .venv/bin/python -m pytest -q workspace/reports/codex/phase1a1-r1-evidence/test_previous_adapted.py
PYTHONPATH=src:tests .venv/bin/python -m pytest -q workspace/reports/codex/phase1a1-r1-evidence/test_r1_boundaries.py --tb=short
```

追加境界試験の10 FAILはR1-01の2件、R1-02の3件、R1-03の4件、R1-04の1件。4 Findingsとしてまとめており、10種類の独立した重大問題という意味ではない。

**Phase 1-A.1は未受入、Phase 1-Bへの進行は保留。** R1-01〜R1-04を修正し、同じ安全性期待値で再検証する。コード・既存テスト・本番設定・Registryは変更していない。リンク・公開内容の秘密情報・Git差分と、非公開証拠がGit対象外であることを確認。commit/pushは未実施。
