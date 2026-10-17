# Verification Summary

## Metadata

- Task ID: `phase1i-fixture-vps-deploy`
- Task: Phase 1-I 標高APIのFixtureデータによるVPS受入の準備（独立したDocker Compose、KAGOYA VPS・Debian 13向け）
- Implementer: Claude（実装・Macでの実機検証・文書・commit・push）
- Reviewer: Claude（自己検証）
- Target Commit: 本サマリーと同じコミット（基準main `3282ea082c9b103b95efa7843340e43d1170acce`。開始時とcommit前にfetchし、HEADとorigin/mainの一致を確認した）
- Status: **Macでの実機検証PASS。VPSでの実機受入は未実施**（OWNERが[Runbook](../../docs/operations/elevation-fixture-vps-runbook-v0.1.md)で実行する）
- OWNER Approval: commit・pushはGit運用ルールに基づく。VPSへの接続・デプロイ、実GSIの取得・転送、Caddy・Firewallの変更、OnHighGround2の操作は行っていない

## Changes

| ファイル | 内容 |
|---|---|
| `deploy/fixture-vps/Dockerfile`（新規） | `python:3.14.3-slim-trixie`。依存は固定版（Macと同じ）。uid 10001で実行。ソース・設定・Fixtureだけを入れる |
| `deploy/fixture-vps/Dockerfile.dockerignore`（新規） | 許可リスト方式（`*` を除外し、必要なものだけ許可） |
| `deploy/fixture-vps/compose.yaml`（新規） | プロジェクト `hererisk-fixture`。`api`（`127.0.0.1:18080:8000`、Bearer Token必須、読取専用のVolume・root FS、`cap_drop: ALL`、`no-new-privileges`、256MiB、`restart: unless-stopped`）。`init`・`token`（プロファイル `init`、`network_mode: none`） |
| `deploy/fixture-vps/init-fixture.sh`（新規） | 明示的な1回限りの初期化。初期化済みなら何もしない（exit 0）。中身があるのにRegistryがない場合は拒否（exit 1）。削除・上書きをしない |
| `deploy/fixture-vps/requirements.txt`（新規） | 実行時の依存の固定版 |
| `src/hererisk/elevation/api/server.py` | `--container`: コンテナの中でだけ、Fixtureデモの非ループバックの待受けを許可する（`--auth-token-file` 必須）。privateモードは従来どおりループバックのみ |
| `tests/contract/test_fixture_vps_deploy.py`（新規、8件） | `--container` の規則と、配備ファイルの安全性の静的検査 |
| `docs/operations/elevation-fixture-vps-runbook-v0.1.md`（新規） | VPS Runbook（10章。貼付け用のコードにコメントなし） |

API契約・認証方式・データ構造・Fixtureの初期化の契約は変更していない（既存のCLI `init-fixture-root`・`pipeline --fixture --publish`・`api-token-generate` を使う）。

## Verification

### Macでの実機検証（Docker 29.7.2 / Compose v5.4.0、実施済み）

| 確認 | 結果 |
|---|---|
| Build | 成功（イメージ209MB）。イメージ内は `/app/src`・`/app/api/elevation/conf`・`/app/fixtures`・初期化スクリプトのみ。`.pyc` なし。uid 10001 |
| 秘密ファイルの作成 | `token` サービスで0600のファイルを作成（トークンは表示されない）。再実行はexit 2で、上書きしない |
| Fixtureの初期化 | 4工程SUCCESS。再実行は `already initialised; nothing changed` |
| 起動 | `healthy`。待受けは `127.0.0.1:18080` のみ |
| Bearer Token付きPOST | HTTP 200、`elevation_m: 81.44`、`dataset.source.provider: Fixture provider (not GSI data)` |
| 認証なし・不正なトークン | どちらもHTTP 401 |
| 再起動後のデータの保持 | `restart`・`down`→`up` の後も、同じ `publication_version` で200 |
| ログ | トークン・`Bearer`・`Authorization`・座標の出現は0件（request_id・status・error_codeのみ） |
| リソース | 約24MiB / 256MiB、CPU 0.02%、PIDs 1 |
| 強化設定（`docker inspect`） | root FS読取専用、uid 10001、`CapDrop=[ALL]`、`Privileged=false`、専用ネットワーク、メモリ上限256MiB、`unless-stopped`、データとトークンは読取専用のマウント |
| 既存のコンテナ | Mac上の `evacuation-navi-*`（OnHighGround2）は、検証の前後で状態が同じ |
| 後片付け | 検証用のコンテナ・Volume・イメージ・トークンを削除した |

### 自動テスト

| 確認 | 結果 |
|---|---|
| 全テスト | 1034 passed（既存1026 + 新規8） |
| `--container` の規則 | Fixtureデモ以外・トークンなし・不正な権限のトークン・privateモードでは拒否。非ループバックのFixtureデモは `--container` なしでは拒否 |
| 配備ファイルの静的検査 | `network_mode: host`・`privileged`・Docker Socket・`cap_add` がない。公開は `127.0.0.1:18080:8000` の1つだけ。名前はすべて `hererisk-fixture*`。トークンらしい文字列・実GSIの参照・private/productionのフラグがない。秘密の既定の場所はリポジトリの外 |

### 未実施（VPSでの実機受入）

Runbookの第1〜10章は、Debian 13のVPS上で未実行である。特に次はVPSで初めて確認される: Docker 29.7.2 / Compose v5.5.1 での動作、Linuxでのbind mountの所有者（uid 10001）とトークンファイルの権限、メモリ3.8GiB・Swap使用中の環境での実測、OnHighGround2・WordPressへの影響がないこと。

## Known Limitations

- 公開範囲はホストの `127.0.0.1:18080` だけである。外部（Mac）からはSSHトンネルで確認する。Caddyでの公開は今回の範囲外である。
- `--container` は、コンテナの中のFixtureデモのための例外である。ホストへの公開範囲は、Composeのポートの指定（`127.0.0.1`）で決まる。
- ベースイメージはタグで固定している（ダイジェストでは固定していない）。
- macOSのDocker Desktopではbind mountの所有者が変換される。Linuxでは、トークンのディレクトリ・ファイルがuid 10001の所有でなければならない（Runbook第3章）。

## Conclusion

Macで実施できる検証はすべてPASSした。VPSでの受入は、OWNERがRunbookに従って実行する。
