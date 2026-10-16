# Phase 1-A.1 Elevation Download Fixture MVP 独立検証

- Task ID: `phase1a1-elevation-download-independent-verification`
- 検証日: 2026-10-17
- 対象コミット: `264ff0a25be0e002b8174cf794adf4153abfe52b`
- 実装: Claude / 独立検証: Codex
- 作業開始時: clean。`git fetch origin main`後にHEAD・origin/main・指定コミット一致。
- 最終判定: **FAIL**。修正必須の領域分離・整合性・通信制限の不備があり、次工程への受入は不可。

## 実行結果と範囲

| 検証 | 実測結果 |
|---|---|
| 既存pytest | **117 passed**（記録した再実行10.89秒）。Claudeの自己申告ではなく実行して確認 |
| 独自の隔離pytest | **25件: 14 passed / 11 failed**（最終実行6.23秒）。安全動作を期待する回帰テストの失敗を含む。失敗数とFindings件数は1対1ではない |
| 実プロセスSIGKILL | 上記25件に含む6件すべてPASS。part中、完全受信後、原本確定後、Record後、marker後、結果返却前 |
| 別プロセス排他 | 上記に含む1件PASS。保持中はTARGET_BUSY、解放後SUCCESS |
| 実GSI・本番取得・Linux/VPS・電源断・syslog/journald | NOT RUN。対象外・未承認。実データは取得していない |

環境: macOS 27.0.1 arm64、Python 3.14.3、pytest 9.1.1、jsonschema 4.26.0。既存`.venv`を利用し、インストールや環境設定変更は行っていない。

一時fixtureと追加試験はGit対象外の作業報告領域・OS一時領域に置いた。ソケット接続・DNSを拒否するガードを設けた。F05の検証では通信**試行**をガードで遮断し、通信を許可していない。Git fetchだけはユーザー指示の最新main確認として実施した。既存テストのCLI子プロセスは親pytestのmonkeypatchを継承しないため、既存ガードだけで全子プロセスのネットワーク隔離を保証したとは扱わない。

独立検証したのはClaude実装の上記コミット。本検証者が先行契約案を作成した経緯はあるが、今回アプリケーション実装は担当・変更していない。設計そのものの第三者独立承認を意味しない。

## 修正必須Findings

### F01 HIGH — 保存操作でAPI・書込領域制限を迂回できる

該当: [storage.py](../../src/hererisk/common/storage.py) 95–114、149–158、170–197行。

`path()`だけがWRITABLE_AREASを検査する。実際に書く`write_new` / `open_exclusive` / `link_no_clobber`等は、渡されたPathのsymlink検査だけを行い、対象APIや許可サブ領域を再確認しない。`_reject_symlinks`の基点もAPI rootでなくdata_root。

再現: 隔離rootで `ApiDataArea(root, "elevation")` を作り、`root/flood/records/x` または `root/elevation/dl/current/x` の親だけ作成して `area.write_new(path, b"audit")`。どちらも拒否されず新規ファイルを作成した（独自2件FAIL）。既存ファイルの上書き・本番ファイル破壊を実施したという意味ではない。現行正常CLIは固定パスを使うが、保存層の内部APIとして契約上の権限境界を保証していない。

最小修正: 全I/O入口でAPI rootと許可領域を検証し、任意Pathを権限として信用しない。可能なら検証済み領域ハンドル経由に限定する。別API・dl・rel・Registryへの各操作を回帰試験に追加する。

### F02 HIGH — symlinkチェックと操作の間に領域外書込みが可能

該当: [storage.py](../../src/hererisk/common/storage.py) 109–153、192–209、226–228行。

再現: `open_exclusive`のsymlink検査直後、親ディレクトリを退避し、隔離領域外の試験ディレクトリへのsymlinkへ差替える。続くパスベースの`os.open`が外側にファイルを作成した。決定的な競合注入試験であり、自然発生競合の頻度は測定していない。前提は同じデータ親を変更できる別主体・処理の存在。

最小修正: 信頼できるディレクトリFDを固定し、各階層をsymlinkを辿らず開く。mkdir/open/link/unlink/fsyncも相対FDと所有・種別検査で一貫させる。末端だけのO_NOFOLLOWでは親差替えを防げない。データroot自体の差替えとFixtureTransportのstat/open間も同じ観点で確認する。

### F03 HIGH — Recordの意味的な不整合を照合せずSUCCESS

該当: [download.py](../../src/hererisk/elevation/download/download.py) 324–336、340–390行、[record.py](../../src/hererisk/elevation/download/record.py) 52–80行。

再現: 正常取得Recordのrequested_urlを対象外URL、source_definition.raw_sha256をゼロhash、snapshot_refを存在しない参照、acquired_atを`2026-99-99T99:99:99Z`へ変更する。marker.record_sha256だけを新Recordに合わせて再計算し、同一runを再実行するとSUCCESS。原本のhash一致だけで、記録の事実・設定との対応を保証していない。単なるRecordのみの改変は検出する（対照試験PASS）。markerも書換可能な前提であり、任意改竄をhashだけで認証できると要求するものではない。

最小修正: 固定設定とsource原文の実体hash、snapshot_ref、選択タイル集合、URL、provider、pipeline、地域等を相互照合する。日時は形式だけでなく有効な日時として検証する。保管権限と改竄検出の信頼モデルも明文化する。

### F04 HIGH — 残存markerが再開時の検査対象から漏れる

該当: [download.py](../../src/hererisk/elevation/download/download.py) 302–313行。

再現: 2タイル正常取得後、1件のRecordと原本ディレクトリを隔離fixture内で削除し、markerは残す。同一runの再実行で旧markerの不整合を検出せず、欠けたタイルを新IDで再取得してSUCCESS。workとrecords/acquisitionsからだけIDを列挙し、records/commits側からの逆照合がない。

最小修正: runに所属する確定markerも列挙できる不変索引または厳格な参照解析を用い、片方向だけでなく集合の一致を確認する。原本・Record欠損時はRECOVERY_REQUIRED、勝手な再取得で旧確定状態を覆い隠さない。

### F05 HIGH — 差替えSchemaの外部参照からネットワークを試行する

該当: [config.py](../../src/hererisk/common/config.py) 92–96、173–185行、[cli.py](../../src/hererisk/cli.py) 55–56、66–70行。

再現: 隔離Schema rootに `{"$ref":"https://audit.invalid/never-fetch"}` を配置し、ConfigurationManagerでfixture定義を読み込む。jsonschema側から通信試行があり、独立試験のガードで遮断された。FixtureTransport自体にはネットワーク実装がないが、それだけでは全実行経路の外部通信禁止を満たさない。CLIの`--config-root`もSchema選択に到達する。

最小修正: JSON Schema参照解決をローカル許可集合に限定し、未登録URIの取得を必ず拒否する。Schema rootを信頼済みの定義に結び付ける。リモート参照を含むSchemaでDNS/接続試行0を試験する。

### F06 MEDIUM — 再検証の読込みにサイズ上限がない

該当: [storage.py](../../src/hererisk/common/storage.py) 211–215行、[download.py](../../src/hererisk/elevation/download/download.py) 354、366、374–381行。

新規転送時の1MiB制限は確認できた。一方、確定後の原本を8MiBの疎ファイルに差替えた再実行では、全体を`read_bytes`してから不整合を検出する。Record・marker・設定読込みにも上限がなく、より巨大な保存物でメモリ圧迫が可能。OOMそのものは起こしていない。

最小修正: 通常ファイルのサイズ上限を読込み前・中に検査し、原本hashは上限付きストリームで算出する。Record/marker/設定にも用途別上限を設ける。statとread間の差替えもFD固定で防ぐ。

### F07 MEDIUM — 不正なPNGコンテナを取得成功にする

該当: [png.py](../../src/hererisk/elevation/download/png.py) 42–50行。

再現: 合成PNGのIHDRのcompression/filter/interlaceを99に変更し、IENDへ3byteを付与して各CRCを再計算。取得はPNG_INVALIDにならずSUCCESS。標高値品質検証の不足ではなく、転送検査で宣言したPNGコンテナ妥当性の不足。

最小修正: IHDR方式値、IEND長、IHDR重複・必須chunk順序等のコンテナ規則を検証する。無制限の画像展開を追加せず、デコードと標高品質の後段責務を区別する。

### F08 MEDIUM — 秘密付きURLを拒否する前に設定スナップショットへ保存

該当: [orchestrator.py](../../src/hererisk/common/orchestrator.py) 141–145、273–275行、[download.py](../../src/hererisk/elevation/download/download.py) 88–94行。

再現: fixtureのofficial_page_urlへ`?token=AUDIT_CANARY`を付け、fixture承認hashを更新。取得は後でRecordのSchema検査に失敗するが、source.json/effective.jsonへcanaryが保存済み。実際の秘密は使用していない。取得URL以外のURLやSource全体を保存前に検査していない。

最小修正: スナップショット書込み前に全保存対象URL・情報の秘密禁止規則を検証する。拒否対象を原文ごと記録しない。原文hash・不変記録の契約を保つため、保存後に黙って編集する修正は避ける。

### F09 MEDIUM — CLI構文エラーが任意引数をstderrへ反映

該当: [cli.py](../../src/hererisk/cli.py) 36–40行。

再現: 必須引数を揃えて未知引数 `--secret=AUDIT_CANARY` を付けると、argparseのmessageをそのまま出力しcanaryがstderrに残る。通常のModuleResult/構造化ログは固定文言だが、構文エラー経路は別。

最小修正: 解析エラーも安全な固定文言・分類へ変換し、未知引数の値や内部パスを表示しない。構文エラーにJSON結果を要求するかは契約上の整理事項だが、値の反射は除去する。

## 修正推奨・限定事項

| ID / 重大度 | 内容・根拠 | 対応 |
|---|---|---|
| F10 MEDIUM | storage.py 109–114 / download.py 374: 確定原本に外部hardlinkを作っても再実行SUCCESS。外部alias経由で後から同じinodeを変更できる。専用試験は「拒否すべき」の強化期待に対してFAIL | hardlinkを一律拒否する契約は未確定。確定物のnlink・所有者と読取寿命の規則を決める。link+unlink途中の正当な二重リンクと区別する。fixture単独の追加防御として修正推奨 |
| F11 MEDIUM | download.py 147–183: 途中失敗を新runで3回繰り返すと.partが3件残る。取得ごとの上限はあるが総容量・run数・保持期限の上限なし | 所有run終了・参照なしを確認する隔離/整理と容量枠を実装するか、使い捨てroot運用を明示。自動削除で未確認データを破壊しない |
| F12 MEDIUM | cli.py 93–96: /dataと「指定されたconfig-root」だけを除外。config-rootの差替え、別物理本番root、Orchestrator直呼びに対する共通fixture root制限なし | fixture用の明示的な専用rootを共通入口で検証する。コード上の制約不足であり、実リポジトリ/本番rootへの書込み試験は行っていない。既存ファイル置換はno-clobberで防ぐが、任意rootへの追加を隔離と同一視しない |

## 異常終了・保存監査の補足

- 実SIGKILLは`os.kill(os.getpid(), SIGKILL)`で子プロセスを停止し、returncode=-9を確認。part中・完全受信後・原本後・Record後はRECOVERY_REQUIRED、marker後は確定分再利用＋残り取得、全処理終了直後（CLI相当の結果返却前）は再利用SUCCESS。電源断の代用ではない。
- 既存のBaseException試験はfinally等が走る可能性があり、SIGKILLと区別する。
- link後のunlinkへEIOを注入した試験はPASS。例外を返し、両名の同一原本byteを保持した。親fsync・unlink失敗後は「操作は失敗したが最終名がある」状態があり、回復確認が必要。
- 通常の既存名置換拒否、静的symlink拒否、他API/Registry/currentを変更しない正常Orchestrator経路、同一run異設定拒否は既存・追加試験で確認。ただしF01/F02の境界迂回を相殺しない。
- Directoryはos.mkdirの既定modeとumaskに依存、ファイルは0640。親ディレクトリの所有権・書込許可、特別ファイル・hardlinkを含む信頼境界は未確立。
- ファイル/親fsyncの呼出しはコードと既存試験で確認。F_FULLFSYNC失敗時os.fsyncへのfallbackがあり、macOS実機の電源断永続性を保証したとはしない。
- 公開API/後続工程は実装されておらず、DownloadからNormalize/Validate/Publishの呼出しなし。共通Configuration Manager・Orchestratorを使用し、47地域と東京以外fixtureの同一経路は維持。
- 通常Recordの項目・null・SHA/size対応、fixtureのpipeline版とeffective.execution_contextの追跡は確認。F03はその再検証の不足である。
- 終了コードの基本対応は契約案どおり。ただし未知source等の分類差異、予期しない例外時にINTERNAL_ERRORとなる経路は区別して扱う。

## Claude自己検証Findingsの個別評価

| 自己検証事項 | 独立評価 |
|---|---|
| 自動回復未実装 | **受入可能（fixture限定）**。RECOVERY_REQUIREDで保護する方針自体は安全。ただしF04の未検出は修正必須 |
| renameではなくlink+unlink | **受入可能な設計案**。no-clobberの目的とunlink失敗時保全を確認。F01/F02の操作境界は修正必須、hardlink規則は修正推奨。方式のOWNER承認は別 |
| fsync実機保証未確認 | **受入可能（限定明記）**。SIGKILLで電源断保証はできない。本番前に実機検証 |
| 契約にないエラー分類 | **修正推奨**。未知sourceをINVALID_INPUTとする等は安全を破壊しないが契約案との差を合意する。fixture404相当、異設定run拒否、pipeline不一致BLOCKEDは妥当 |
| work/locks追加 | **受入可能**。work内の管理用排他で公開資格を変更しない。配置承認の記録を残す |
| CLI開発用追加引数 | **修正必須**。利便性は理解できるが、Schema選択の外部通信経路F05とroot境界F12を固定/検証する。契約の引数例との差を承認する |
| 他runの未確定物 | **修正推奨**。未確定物を消費しない点は妥当。総容量/整理のF11、同一runのF04は別問題 |
| URI format制限 | **修正必須（必要なURL検査について）**。実環境でuri checkerなしを確認。HTTPS prefixだけで秘密・完全なURI構文の検証にはならずF08が発生。ライブラリ追加だけでなく保存前検証が必要 |
| Python 3.14/macOS editable install | **受入可能（限定）**。既存venv + PYTHONPATHで再実行できた。clean install/.pth問題の原因・復旧手順は今回再現していない |

自己検証のtiles=null判定差は、Schema/承認不足を優先して停止する安全側の分類差として受入可能。fixture上限を本番承認へ転用していない点も確認した。

## 再現と再受入条件

公開レビューだけでも上記F01～F09の手順・該当行から再現可能。追加スクリプトと完全出力は非公開 `workspace/reports/codex/phase1a1-audit-evidence/` に保存した。リポジトリrootからの再実行例:

```sh
.venv/bin/python -m pytest -q
PYTHONPATH=src:tests .venv/bin/python -m pytest -q workspace/reports/codex/phase1a1-audit-evidence/test_independent.py --tb=short
```

追加試験は既存fixture生成・Harnessを使うが、安全性の期待値・改変・競合/停止注入は独自に記述した。初期試験の巨大PNGケースは対象外の大阪タイルを変更していたため、東京の取得対象へ修正して最終実行ではPASSを確認した。これを実装不具合として計上していない。

F01～F09を修正し、F12のfixture root境界を確定・制限したうえで再検証する。F10/F11の対策またはfixture限定の明示的受入を要する。既存117件PASSだけで次工程へ進めない。今回コード・テスト・設定・データ・Registryは変更せず、レビューとGit対象外の証拠だけを作成。commit/pushは未実施。
