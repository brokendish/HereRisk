# 標高API Fixture VPS受入 Runbook v0.1（KAGOYA VPS・Debian 13・Docker Compose）

- Task ID: `phase1i-fixture-vps-deploy`。**OWNERだけが実行する**（作成時にVPSへは接続していない）。
- 対象: Fixture（合成データ）での受入のみ。実GSIデータの取得・転送・公開はしない。`private_experiment`・`public_production` は使わない。
- 構成: `deploy/fixture-vps/`（`compose.yaml`・`Dockerfile`・`init-fixture.sh`）。Composeプロジェクト `hererisk-fixture`、コンテナ `hererisk-fixture-api`、Volume `hererisk-fixture-data`、ネットワーク `hererisk-fixture_default`。
- 公開範囲: 本Runbookの手順では、ホストの `127.0.0.1:18080` だけ（本Runbookの手順はCaddy・Firewallを変更しない）。APIはBearer Token必須。
- Phase 1-J（2026-10-18）で、OWNERが既存のCaddyから `https://hererisk.brokendish.org` → `127.0.0.1:18080` のHTTPS中継をVPS上で追加した（Caddyfile・DNSはリポジトリの外にあり、OWNERがVPSで管理する。本リポジトリのファイルではない）。受入記録: [Phase 1-I VPS受入](../../reviews/phase1/phase1i-vps-owner-acceptance.md)、[Phase 1-J HTTPS受入](../../reviews/phase1/phase1j-https-owner-acceptance.md)
- VPSでの配置先（実際の受入時）: `/home/debian/Development/GitHub/HereRisk`
- 変更しないもの: OnHighGround2（Compose・コンテナ・Volume・Network）、WordPress・PHP-FPM・MariaDB、Caddyfile、Firewall、SSH設定、ドメイン・DNS。
- **すべての `docker compose` は、`/home/debian/Development/GitHub/HereRisk` で `-f deploy/fixture-vps/compose.yaml` を付けて実行する**（他のプロジェクトを操作しないため）。

配置:

| 対象 | 場所 | 権限 |
|---|---|---|
| ソースコード | `/home/debian/Development/GitHub/HereRisk`（GitHubから取得） | OWNER |
| APIトークン | `/srv/hererisk-fixture/secrets/api-token`（Git・イメージの外） | uid 10001、0600（ディレクトリ0700） |
| 生成データ | Docker Volume `hererisk-fixture-data` | uid 10001。APIは読取専用でマウント |
| curl用ヘッダー | `~/.hererisk-fixture-auth-header` | OWNER、0600 |

## 1. 前提確認

```sh
docker version --format '{{.Server.Version}}'
docker compose version
free -h
sudo ss -ltnp | grep -E ':18080\b' || echo "18080 free"
docker ps --format '{{.Names}}\t{{.Status}}'
docker volume ls --format '{{.Name}}' | grep hererisk || echo "no hererisk volume"
```

確認: 18080が空いている。`docker ps` の一覧を控える（第9章の後と比べる）。

## 2. GitHubからの取得

```sh
mkdir -p /home/debian/Development/GitHub
git clone https://github.com/brokendish/HereRisk.git /home/debian/Development/GitHub/HereRisk
cd /home/debian/Development/GitHub/HereRisk
git log -1 --format='%H %s'
```

更新する場合:

```sh
cd /home/debian/Development/GitHub/HereRisk
git pull --ff-only origin main
git log -1 --format='%H %s'
```

## 3. Build と秘密ファイルの作成

```sh
cd /home/debian/Development/GitHub/HereRisk
docker compose -f deploy/fixture-vps/compose.yaml build api
sudo install -d -o root -g root -m 0755 /srv/hererisk-fixture
sudo install -d -o 10001 -g 10001 -m 0700 /srv/hererisk-fixture/secrets
docker compose -f deploy/fixture-vps/compose.yaml --profile init run --rm token
sudo ls -ln /srv/hererisk-fixture/secrets
```

確認: `api-token` が uid 10001・`-rw-------`。トークンは画面に出ない。既にファイルがある場合は作り直さず、exit 2で止まる（上書きしない）。

curl用のヘッダーファイル（トークンをコマンドラインに出さない）:

```sh
umask 077
printf 'Authorization: Bearer %s\n' "$(sudo cat /srv/hererisk-fixture/secrets/api-token)" > "$HOME/.hererisk-fixture-auth-header"
umask 022
ls -l "$HOME/.hererisk-fixture-auth-header"
```

## 4. Fixture の初期化（1回だけ）

```sh
cd /home/debian/Development/GitHub/HereRisk
docker compose -f deploy/fixture-vps/compose.yaml --profile init run --rm init
```

確認: 最後のJSONの `status` が `SUCCESS`（Download → Normalize → Validate → Publish）。もう一度実行しても `already initialised; nothing changed` で、既存のRegistryは変わらない。初期化はネットワークなし（`network_mode: none`）で行う。

## 5. 起動

```sh
cd /home/debian/Development/GitHub/HereRisk
docker compose -f deploy/fixture-vps/compose.yaml up -d api
docker compose -f deploy/fixture-vps/compose.yaml ps
sudo ss -ltnp | grep -E ':18080\b'
```

確認: `hererisk-fixture-api` が `healthy`。待受けが `127.0.0.1:18080` だけ（`0.0.0.0:18080` がない）。

起動・再起動の直後は、`health: starting` の間に接続がリセットされることがある（VPSの受入で、再起動直後の最初のcurlがHTTP 000になり、再試行で200になった）。`healthy` になってから第6章を実行する:

```sh
docker inspect -f '{{.State.Health.Status}}' hererisk-fixture-api
```

## 6. HTTP 200 / 401 の受入

```sh
curl -sS -w '\nHTTP %{http_code}\n' -X POST -H @"$HOME/.hererisk-fixture-auth-header" -H 'Content-Type: application/json' -d '{"lat": 35.701882, "lon": 139.713178}' http://127.0.0.1:18080/api/v1/elevation
curl -sS -o /dev/null -w 'HTTP %{http_code}\n' -X POST -H 'Content-Type: application/json' -d '{"lat": 35.701882, "lon": 139.713178}' http://127.0.0.1:18080/api/v1/elevation
curl -sS -o /dev/null -w 'HTTP %{http_code}\n' -X POST -H 'Authorization: Bearer invalidinvalidinvalidinvalidinvalidinvalid12' -H 'Content-Type: application/json' -d '{"lat": 35.701882, "lon": 139.713178}' http://127.0.0.1:18080/api/v1/elevation
```

期待:

1. HTTP 200、`"status":"success"`、`"elevation_m":81.44`、`dataset.source.provider` が `Fixture provider (not GSI data)`（Fixture由来であることが応答で分かる）
2. HTTP 401（トークンなし）
3. HTTP 401（不正なトークン）

Macから確認する場合は、SSHトンネルを使う（本Runbookの手順はCaddyを変更しない）。Phase 1-JのHTTPS中継がある場合は、トンネルなしで `https://hererisk.brokendish.org/api/v1/elevation` へ同じcurl（Bearer Token付き）を送れる:

```sh
ssh -N -L 18080:127.0.0.1:18080 <owner>@<vps>
```

## 7. リソース確認

```sh
docker stats --no-stream hererisk-fixture-api
free -h
```

目安: Macで約24MiB、VPSで23.5MiB（上限256MiB。VPSは2026-10-17〜18のOWNER実測）。上限は `compose.yaml` の `mem_limit` で変更できる。VPSはSwapの使用が多い（実測約1.6GiB）ため、`free -h` で継続して監視する。

## 8. 停止・再起動・ログ

```sh
cd /home/debian/Development/GitHub/HereRisk
docker compose -f deploy/fixture-vps/compose.yaml stop api
docker compose -f deploy/fixture-vps/compose.yaml start api
docker compose -f deploy/fixture-vps/compose.yaml restart api
docker compose -f deploy/fixture-vps/compose.yaml logs --tail 50 api
docker compose -f deploy/fixture-vps/compose.yaml logs api | grep -c -e 'Bearer' -e 'Authorization' -e '35.70'
```

確認: 再起動後も第6章の1が同じ `publication_version` で200（データはVolumeに保持）。最後のコマンドの結果が `0`（ログにトークン・ヘッダー・座標がない）。ログは request_id・status・error_code だけ。

## 9. ロールバック

コンテナだけを止めて削除する（データ・トークンは残る）:

```sh
cd /home/debian/Development/GitHub/HereRisk
docker compose -f deploy/fixture-vps/compose.yaml down
docker ps --format '{{.Names}}\t{{.Status}}'
```

前の版のコードに戻す:

```sh
cd /home/debian/Development/GitHub/HereRisk
git log --oneline -5
git checkout <前のコミットSHA>
docker compose -f deploy/fixture-vps/compose.yaml build api
docker compose -f deploy/fixture-vps/compose.yaml up -d api
```

HereRiskのFixture環境を完全に削除する（このプロジェクトのVolume・イメージ・トークンだけ）:

```sh
cd /home/debian/Development/GitHub/HereRisk
docker compose -f deploy/fixture-vps/compose.yaml down --volumes
docker image rm hererisk-elevation-fixture:local
sudo rm -r /srv/hererisk-fixture
rm "$HOME/.hererisk-fixture-auth-header"
docker volume ls --format '{{.Name}}' | grep hererisk || echo "no hererisk volume"
docker ps --format '{{.Names}}\t{{.Status}}'
```

確認: `docker ps` が第1章の一覧と同じ（OnHighGround2・WordPressのコンテナが変わらない）。`down --volumes` は、`-f deploy/fixture-vps/compose.yaml`（プロジェクト `hererisk-fixture`）のVolumeだけを削除する。

## 10. Git管理外であることの確認

```sh
cd /home/debian/Development/GitHub/HereRisk
git status --short
git ls-files | grep -E 'api-token|auth-header' || echo "no secret in git"
ls -la deploy/fixture-vps
```

確認: `git status --short` が空。トークン・ヘッダー・生成データは `/srv/hererisk-fixture`・Docker Volume・ホームにだけあり、リポジトリにもイメージにもない（イメージに入るのは `Dockerfile.dockerignore` で許可したソース・設定・Fixtureだけ）。
