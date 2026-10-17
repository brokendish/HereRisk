# Verification Summary

## Metadata

- Task ID: `phase1d1-gsi-dem10b-acquisition-poc`
- Task: Phase 1-D.1 実GSI DEM10B取得PoC（管理者の明示操作による1タイル取得と保存済み実体の検査）
- Implementer: Claude（実装・自己テスト・commit・push）
- Reviewer: Claude（自己検証。Codexは今回使用しない指示）
- Target Commit: 本レビューと同じコミット（基準main `7c34b237aca94f308247e3b265fa65145f8910b4`。作業開始時にfetchし、HEADとorigin/mainの一致と作業ツリーがcleanであることを確認した）
- Status: **自己テストPASS**（通信なしのテストのみ。実GSIへのアクセスはClaudeは行っていない）
- OWNER Approval: Git運用ルールに基づきcommit・push。実際の1タイル取得は、コードレビュー後にOWNERが実施する

## Changes

| ファイル | 内容 |
|---|---|
| `src/hererisk/elevation/gsi_poc/http_fetch.py`（新規） | **リポジトリ内で唯一のネットワークコード**。HTTPS GETを1回、標準ライブラリの `http.client` で行う |
| `src/hererisk/elevation/gsi_poc/poc.py`（新規） | `plan_fetch`（`locate_pixel` と本番Source Definitionから計画を作る）、`run_fetch_poc`（専用ディレクトリへの保存・検査・証跡） |
| `src/hererisk/elevation/gsi_poc/__init__.py`（新規） | パイプライン外であることを明記 |
| `src/hererisk/cli.py` | `gsi-fetch-poc` サブコマンドを追加。PoCモジュールは、このコマンドの実行時にだけ読み込む |
| `tests/contract/test_gsi_fetch_poc.py`（新規、64件） | 偽のHTTP接続による契約テスト |
| `tests/contract/test_download_rerun_isolation.py` | ネットワークimport禁止の試験を**限定的に緩和**した（下記） |
| `docs/development/phase1a1-download-fixture-usage.md` | 第3.3節「実GSI DEM10B 1タイル取得PoC」（実行手順） |

本番Source Definition（`sources.json`）、Schema、保存層、Orchestrator、Download・Normalize・Validate・Lookup、fixtureは変更していない。依存の追加もない。

### ネットワーク禁止試験の変更

既存の試験は `src/` 全体での `socket`・`http`・`urllib.request` 等のimportを禁止していた。今回の要件を満たすため、例外を `gsi_poc/http_fetch.py` の**1ファイルだけ**にした。同時に、パイプラインのモジュール（common、download、normalize、validate、lookup）が `gsi_poc` をimportしないことを、新たに検査に加えた。パイプラインやCLIを読み込んでも、`http.client`・`gsi_poc` が読み込まれないことは、別プロセスで確認している。

## 仕様

```bash
hererisk-pipeline gsi-fetch-poc --lat <lat> --lon <lon> --zoom 14 --output-dir <dedicated_poc_dir> [--allow-network]
```

### 計画

- タイルは `locate_pixel` で求める（固定のタイル番号は持たない）。
- URLテンプレート・zoom・提供者・利用条件は、本番Source Definitionの `gsi-dem10b-candidate` から読取専用で得る。
- テンプレートは `^https://cyberjapandata.gsi.go.jp/xyz/dem_png/{z}/{x}/{y}.png$` と完全一致しなければならず、展開後のURLもhost・scheme・port・query・fragmentを再検査する。zoomはsourceのzoom（14）でなければならない。
- 任意のURLは受け付けない。
- 証跡には `approval_ref: null` をそのまま記録し、未承認であることを明示する。

### 通信（`--allow-network` があり、値が `True` の場合だけ）

- 1回の実行で1タイル・1リクエスト。自動再試行・並列取得・定期取得はない。
- HTTPS・443・許可した1ホストのみ。`ssl.create_default_context()` で証明書とホスト名を検証する。環境変数のプロキシは使わない。
- 接続後、送信前に、接続先が公開アドレス（`is_global`）であることを確認する。loopback・private・link-local・文書用アドレスには要求を送らない。
- リダイレクトは追跡しない。200以外はすべて失敗（3xxはREDIRECT_REJECTED、404・403・429・5xx・その他）。
- Content-Typeは `image/png` のみ。Content-Encodingは、なしかidentityのみ。Content-Lengthが宣言されていれば、上限と受信量の一致を確認する。
- タイムアウトは接続5秒・読込10秒・全体30秒。本文は1 MiBを上限としてストリーミングで受信する。
- 失敗は既存のエラーコードで返す（TIMEOUT・TLS_FAILED・TRANSFER_INTERRUPTED・SIZE_INVALID等）。欠損扱いにはしない。

### 保存と検査

1. 出力先の条件:
   - 実在するディレクトリ（symlinkは不可）であること。
   - `/data`・リポジトリ・fixtureのデータrootでないこと。判定はrootを固定したうえで、識別子でも行う。
   - 空であるか、PoCマーカーがあること。
2. 同名のPNGまたは証跡が既にある場合は、通信する前に拒否する（上書き禁止）。
3. 一時ファイルへストリーミングで書き込み、fsyncする。読み直して、size・SHA-256を照合する。
4. `normalize_tile`（Downloadのコンテナ検査と、上限付きの厳密な復号）と `validate_candidate`（統計）で検査する。
5. 合格した場合だけ、link（上書き不可）でPNGを最終名にし、その後で証跡JSONを書く。
6. 失敗時は、その実行の一時ファイルだけを削除する。
7. 証跡の内容:
   - 取得情報: URL、タイル、`requested_at`・`acquired_at`、HTTPステータス、Content-Type・Length、size、SHA-256
   - 検査結果と統計
   - Source Definitionの参照（版・原文hash・`approval_ref`・`vertical_reference`）
   - 出典、利用条件の確認先
   - `unconfirmed`（鉛直基準・測量時期・改定の反映状況・再配布条件）
   - `poc_only: true` と、公開・再配布・パイプライン投入を禁止する注意書き

### CLIの出力

stdoutにJSONを1行だけ出す。キーは `status`・`error_code`・`message`・`mode`（plan / fetch）・`network_used`・`url`・`tile`・`files`・`evidence`。座標・パス・例外文は出さない。終了コードは既存のエラー表どおり。

## Verification

| Check | Result |
|---|---|
| PoC契約テスト（64件、通信なし） | PASS |
| 全pytest | **PASS: 758 passed**（既存694 + 新規64、約111秒）。fixtureパイプライン・標高参照CLIの回帰を含む |
| 変異確認 | 11点を検出（hostの許可、公開アドレス検査、200以外の拒否、Content-Type、受信量の上限、長さの一致、フラグはTrueのみ、上書きの事前拒否、fixture rootの拒否、空でないディレクトリの拒否、テンプレートの許可）。明示的な `check_png` 呼出しを外しても検出されなかったが、これは `normalize_tile` 内で同じ検査をしているための等価変異と判断し、重複していた呼出しを削除した。fixture rootの拒否は、最初は空でないディレクトリの拒否に隠れていたため、試験を追加した |
| 実GSIへの通信 | **NOT RUN**（指示どおり。Claudeは実行していない） |

テスト項目との対応:

| 内容 | 主なテスト |
|---|---|
| URLの公式ホスト・パス制限 | 公式URLの生成、改ざんされたテンプレート3種（別ホスト、別レイヤー、似せたホスト）、HTTP層での別ホストの拒否、TLS検証の既定値 |
| タイル座標の算出 | 東京駅のz14タイル14552/6451、東隣の14553/6451、zoom≠14・不正座標の拒否 |
| フラグなしでは通信0回 | 計画のみ（書込みもなし）。フラグの値は `True` だけを受け付ける。CLIを別プロセスで実行しても、通信の試行は0 |
| 成功時の保存・hash照合 | 保存したバイト列が受信内容と一致、SHA-256・size・統計（欠損663）、要求ヘッダー、一時ファイルが残らないこと |
| 404・403・500・タイムアウト・リダイレクト | 21種（429、204、302、html、gzip、各種タイムアウト、TLS、接続拒否、受信途中の切断、長さの不一致、不正な長さ、空の本文、loopback・private・link-local・TEST-NET・IPv6 loopback）。いずれも何も保存せず、再試行しない |
| サイズ超過・途中切断・PNG破損 | 宣言長の超過（読込前に拒否）、受信量の超過、全体の期限、CRC・末尾の余剰・復号不能・PNGでないもの |
| 上書きの拒否 | 既存のPNG・証跡がある場合、通信の前に拒否し、既存の内容も不変 |
| 出力先の境界・symlink | 存在しない、ファイル、空でない、fixture root（PoCマーカーがあっても）、symlink、不正なマーカー、保護対象の配下、`/data`、リポジトリ |
| 取得メタデータの正確性 | 時刻（注入した時計）、Content-Lengthがない場合はnull、Source Definitionの参照 |
| 分離 | パイプラインやCLIを読み込んでもネットワークコードが読み込まれないこと。import禁止の試験 |

## Findings・未解決事項

1. **OWNERによる実取得が未実施**: 実配信のContent-Type、圧縮、サイズ、応答時間が想定どおりかは未確認。合わない場合は、検査を緩めずに設計を見直す。
2. **利用条件**: ローカル保存・加工・再配布の条件は未審査。PoCのファイルは公開・再配布しない。リクエスト間隔や取得規模は、運用設計で別途決める。
3. **鉛直基準・測量時期・改定の反映状況**: 未確認（証跡の `unconfirmed` に記録）。
4. **保存層の内部関数の再利用**: `_open_dir_chain`・`_chain_within`（private）を再利用し、独自のパス検査は作らなかった。公開名にするかは後続の判断事項。
5. **DNS解決後の公開アドレス検査**: 接続した相手のアドレスで判定する。プロキシ・NAT64等の特殊な環境は想定していない。

## 次工程（Phase 1-D.2）への引渡し

- PoCのPNGを、fixture承認済みや本番承認済みと偽ってパイプラインへ投入しない。
- 実PNGを Download → Normalize → Validate の証跡モデルへどう接続するか（本番承認・Source Definitionの確定・取得証跡）を設計する。

## Conclusion

管理者が明示したときだけ1タイルを安全に取得・検査・保存できるPoCを、ネットワークコードを1ファイルに隔離して実装した（自己テスト758件PASS、実通信なし）。**最終受入・本番承認ではない。**
