# Verification Summary

## Metadata

- Task ID: `phase1g-api-bearer-auth`（Phase 1-G API認証方式の変更）
- Task: 個人実験APIのアクセス制御を、SSHトンネル必須の方式から共通Bearer Token認証へ変更する（OWNER方針変更 2026-10-17）
- Implementer: Claude（実装・テスト・文書・commit・push）
- Reviewer: Claude（自己検証。Codexは使用しない指示）
- Target Commit: 本サマリーと同じコミット（基準main `10950c3d7ffe4c63d6e44b2fee9c0afaf68dc4d6`。開始時とcommit前にfetchし、HEADとorigin/mainの一致を確認した）
- Status: **自己テストPASS**
- OWNER Approval: OWNER方針変更に基づく実装。commit・pushはGit運用ルールに基づく。**実GSI取得・Publish・VPSへのデプロイ・外部からのアクセス経路の有効化は行っていない。トークンは作成していない（テストの一時ファイルのみ）**

## Changes

| ファイル | 内容 |
|---|---|
| `src/hererisk/common/api_auth.py`（新規） | `BearerAuth`（SHA-256ダイジェストのみ保持、定数時間の照合）、トークンファイルの検査・作成・ローテーション。API非依存（標準ライブラリのみ） |
| `src/hererisk/elevation/api/handler.py` | 任意の `auth`。設定時は最初に認証し、失敗は401 `unauthorized`（`WWW-Authenticate: Bearer`） |
| `src/hererisk/elevation/api/server.py` | `--auth-token-file`。`--private-experiment` では必須。リポジトリ内のファイルは拒否。重複した `Authorization` は無効。認証失敗では本文を読まない |
| `src/hererisk/cli.py` | `api-token-generate`（`--append`）、`api-token-retire` |
| `tests/contract/test_api_auth.py`（新規、38件）、`test_private_experiment.py` | 認証のテスト。既存のループバックのテストにトークンを追加 |
| 文書 | [個人実験Runbook](../../docs/operations/elevation-private-experiment-runbook-v0.1.md)（トークン、共通のcurl形式、Caddy、systemd の `LoadCredential`、ローテーション・失効、SSHトンネルは代替）、[個人実験の契約 4.1](../../docs/architecture/private-experiment-v0.1.md)、[GSI利用条件チェックリスト 5.2・5.4](../../docs/operations/gsi-dem10b-usage-checklist-v0.1.md)、標高API契約（末尾の節）、実装仕様（401の行） |

ProductionAuthorizer・承認ストア・Private/PublicのRegistry・Publishの資格・承認記録のSchemaは変更していない。

## Verification

| Check | Result |
|---|---|
| 全テスト | 993 passed（既存955 + 新規38） |
| 認証の成功 | 正しいトークンで200・12.34 m（handler・実ループバックHTTP）。ローテーション中は2つのトークンがどちらも有効で、retire後は古いトークンが401 |
| 401 | ヘッダーなし、空、`Bearer` のみ、空白の過不足、`Basic`、不一致、重複した `Authorization`（handler・HTTPの両方）、別のヘッダー名 → 401。パス違い・GETでも、404・405より先に401。401の時点で地点の選択・公開実体の読取りが呼ばれないことを確認した |
| 秘密情報の未設定 | `--private-experiment` でトークンファイルなし、0644・0640・0604、hardlink、symlink、空・短い・重複・3行・空白・非ASCII・大きすぎ、リポジトリ内（有効なファイルでも）→ 起動しない（exit 3） |
| 漏えい防止 | ログ・stdout・stderr・401の応答に、トークン・`Bearer`・`Authorization`・緯度経度・トークンファイルのパスが含まれない。`api-token-generate` はトークンを表示しない |
| 既存APIの回帰 | 認証を設定しない場合の挙動は従来どおり（fixture demo・既存のE2E・API契約テストはすべてPASS） |
| ミューテーション | 認証の判定11点を1つずつ無効化し、すべて検出（当初未検出の1点はテストを追加して解消） |
| 手動確認（Mac、通信なし） | fixtureでPublishまで実行し、`--fixture-demo --auth-token-file` で起動。`curl -H @auth-header` で success、ヘッダーなしで401。サーバーのログにトークン・座標なし |

## Limitations

- トークンは1つの共通の秘密である（利用者の識別・権限の区別はない）。漏えいした場合は、Runbook 第2.8節の失効の手順で作り直す。
- Caddy・systemd（`LoadCredential`、`%d`）の設定例は、文書として作成した。実機では検証していない。資格情報のファイルの所有者・権限が合わない場合の代替手順をRunbookに記載した。
- 外部からのHTTPSの経路を有効にするかどうかは、OWNERが判断する（本作業では有効にしていない）。
- 個人実験の利用条件は、引き続き未確認である（チェックリスト 第5章）。一般公開はBLOCKEDのままである。

## Conclusion

自己テストの範囲で、共通Bearer Token認証は、未認証のリクエストを標高の計算・公開実体の読取りより前に拒否し、秘密情報をログ・応答に出さない。Mac・VPSで同じcurl形式を使える。
