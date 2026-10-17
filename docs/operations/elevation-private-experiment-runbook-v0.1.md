# 標高 個人実験（private_experiment）Runbook v0.1 — Mac・VPS本人専用

- Task ID: `phase1g-private-experiment`
- 対象: OWNERが許可した少数のDEM10B Z14タイルについて、実GSI取得 → Normalize → Validate → Private Publish → 本人専用のHTTP標高取得を行う
- **本書のコマンドは、OWNERだけが実行する。** 本書の作成時（Claude）には、実GSIへの通信、Private Publish、VPSの変更をいずれも実行していない。
- 契約: [運用区分と個人実験の契約](../architecture/private-experiment-v0.1.md)。利用条件: [GSI利用条件チェックリスト 第5章](gsi-dem10b-usage-checklist-v0.1.md)。一般公開の手順は[本番化Runbook](elevation-production-runbook-v0.1.md)（BLOCKED）。

## 0. 前提（OWNERが判断する）

| No | 前提 |
|---|---|
| 0-1 | [チェックリスト 5.3](gsi-dem10b-usage-checklist-v0.1.md) の利用条件の確認記録を作成した（利用形態、本人のみ、非営利、対象タイル、第三者に提供しないこと、未確認事項の扱い、出典文言、確認日・確認者）。照会した場合は、その回答を記録した |
| 0-2 | 対象タイル（最初は1タイル）と、取得の時期を決めた |
| 0-3 | 実行するマシン（Mac、またはVPS）と、データroot・承認ストア・確認記録の置き場所を決めた |

PoC（Phase 1-D.1）のPNGと証跡を、個人実験の入力や承認として使わない。一般公開の資格（`eligibility_status`）は使わない・作らない。

## 1. Mac での手順

以下は、リポジトリのルートで実行する。パスにsymlinkを含めない（例: `/tmp` ではなく実体のパスを使う）。

### 1.1 準備

```sh
cd ~/Documents/GitHub/HereRisk
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'      # 初回のみ
export PYTHONPATH=src
BASE="$HOME/hererisk-private"                                   # リポジトリの外
APPROVALS="$BASE/approvals"; DATA="$BASE/data"; AUDIT="$BASE/audit"
install -d -m 700 "$BASE" "$APPROVALS" "$APPROVALS/approvals" "$AUDIT"
install -d -m 750 "$DATA"
.venv/bin/python -m hererisk.cli init-private-root --data-root "$DATA"   # 空のディレクトリに区分の印を付ける
printf '{"schema": "hererisk-approval-revocations-v0.1", "revoked": []}\n' > "$APPROVALS/revocations.json"
chmod 600 "$APPROVALS/revocations.json"
```

### 1.2 取得対象の1タイルを設定する

1. タイルを求める（通信しない。計画の表示のみ）。

   ```sh
   .venv/bin/python -m hererisk.cli gsi-fetch-poc --lat 35.681236 --lon 139.767125 --zoom 14 \
     --output-dir "$(mktemp -d)"
   # 出力の "tile": {"x": 14552, "y": 6451, "z": 14}
   ```

2. `api/elevation/conf/sources.json` の `gsi-dem10b-candidate` を**作業ツリーで**編集する。この変更はコミットしない（committedの定義は未承認のままにする。テストもそれを確認している）。
   - `acquisition.tiles`: `[{"x": 14552, "y": 6451}]`
   - `vertical_reference`: 例 `"T.P.（基盤地図情報FAQ Q.4-12。一部離島を除く）。DEM10Bは2025年標高改定の対象外"`
   - `usage.attribution_text`: 確認記録に書いた出典文言（加工の表示を含む）
   - `usage.review_ref`: 確認記録の参照
   - `pipeline`: `{"id": "elevation-download", "version": "0.1"}`
   - `approval_ref`: `"apr-private-elevation-13-0001"`（`apr-private-` で始める）
   - `definition_revision`: 例 `"private-1"`

### 1.3 承認記録の登録

```sh
.venv/bin/python -m hererisk.cli approval-check --api elevation --region 13 \
  --source gsi-dem10b-candidate --approval-root "$APPROVALS" --context private_experiment
# BLOCKED（exit 3）。出力の definition_revision と definition_raw_sha256 を控える
```

[個人実験の記入例](../architecture/schemas/private-experiment-approval-record.example.json) を写して、`<…>` を置き換える。`_publish_を追加する場合の例…` のキーは削除する（最初は `publish` を含めない）。

```sh
vi "$BASE/apr-private-elevation-13-0001.json"
.venv/bin/python -m hererisk.cli approval-digest --record "$BASE/apr-private-elevation-13-0001.json"
# 表示された record_sha256 を記録に書き込む（内容を変えたら毎回計算し直す）
install -m 600 "$BASE/apr-private-elevation-13-0001.json" "$APPROVALS/approvals/"
printf '%s register apr-private-elevation-13-0001 sha256=%s review=%s\n' \
  "$(date -u +%FT%TZ)" "<record_sha256>" "<usage_review_ref>" >> "$AUDIT/approvals.log"
```

### 1.4 事前確認（Dry-run）

```sh
.venv/bin/python -m hererisk.cli approval-check --api elevation --region 13 \
  --source gsi-dem10b-candidate --approval-root "$APPROVALS" --context private_experiment
echo "exit=$?"     # 0 で、download / normalize / validate がすべて GRANTED
```

### 1.5 取得・検証（ここで初めて実GSIへ通信する）

```sh
.venv/bin/python -m hererisk.cli pipeline --api elevation --region 13 \
  --source gsi-dem10b-candidate --private-experiment --allow-network \
  --approval-root "$APPROVALS" --data-root "$DATA" 2> "$AUDIT/run-$(date -u +%Y%m%dT%H%M%SZ).log"
echo "exit=$?"     # stdout の run_id を控える
```

確認: `$DATA/elevation/records/` の各記録の `execution_context` が `private_experiment`、`authorization_ref` が承認ID。`$DATA/elevation/rel/` はまだない。

### 1.6 Private Publish

1. 記録に `publish` と `publication`（`private_use` を含む。記入例の `_publish_…` を参照）を追加し、`approval-digest` で計算し直して置き換え、監査記録に追記する。
2. `approval-check … --context private_experiment --publish` で、4操作が `GRANTED` であることを確認する。
3. 同じ `run_id` で再開する（取得済みのタイルは再利用し、通信しない）。

```sh
.venv/bin/python -m hererisk.cli pipeline --api elevation --region 13 \
  --source gsi-dem10b-candidate --private-experiment --allow-network --publish \
  --approval-root "$APPROVALS" --data-root "$DATA" --resume-run-id "<run_id>"
```

### 1.7 個人実験APIの起動とcurlでの確認

```sh
.venv/bin/python -m hererisk.elevation.api.server --data-root "$DATA" \
  --host 127.0.0.1 --port 8000 --private-experiment
# 別のターミナルで
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"lat": 35.681236, "lon": 139.767125}' http://127.0.0.1:8000/api/v1/elevation
```

- `status: success`、`dataset.publication_version = pub-<run_id>`、`dataset.attribution` が承認記録の値であること。
- 対象外の地点は `no_coverage` になること。
- `--private-experiment` なしで同じrootを指定すると、起動しない（exit 3）こと（一般公開のモードは個人実験のrootを読まない）。
- 待受けの確認: `lsof -nP -iTCP:8000 -sTCP:LISTEN` の結果が `127.0.0.1:8000` だけであること。

## 2. VPS での手順（本人専用API）

### 2.1 方針

- APIは `127.0.0.1` でだけ待ち受ける（`--private-experiment` はループバック以外のアドレスでは起動しない）。
- Caddy・nginx等の公開リバースプロキシからこのAPIへルーティングしない。
- OWNERは、SSHトンネルで接続する。未認証のインターネット利用者は到達できない。
- データは、次のどちらかで用意する。
  - A（推奨）: VPS上で第1.1〜1.6節と同じ手順を実行する。承認ストア・確認記録はVPS上に置く
  - B: Macで作った個人実験のdata rootを、VPSへ複製する（第2.3節）

### 2.2 配置（例）

```sh
# VPS上で、管理者が実行する
sudo useradd --system --home /srv/hererisk --shell /usr/sbin/nologin hererisk
sudo install -d -o hererisk -g hererisk -m 750 /srv/hererisk /srv/hererisk/private
sudo install -d -o hererisk -g hererisk -m 700 /srv/hererisk/approvals /srv/hererisk/approvals/approvals /srv/hererisk/audit
sudo git clone https://github.com/brokendish/HereRisk.git /opt/hererisk     # 読取専用で使う
sudo python3 -m venv /opt/hererisk/.venv && sudo /opt/hererisk/.venv/bin/pip install /opt/hererisk
sudo -u hererisk env PYTHONPATH=/opt/hererisk/src /opt/hererisk/.venv/bin/python \
  -m hererisk.cli init-private-root --data-root /srv/hererisk/private
```

`/opt/hererisk/api/elevation/conf/sources.json` は、第1.2節と同じ内容に（作業ツリーで）編集する。Aの場合は、VPS上で第1.3〜1.6節を `sudo -u hererisk` で実行する（`APPROVALS=/srv/hererisk/approvals`、`DATA=/srv/hererisk/private`）。

### 2.3 Bの場合: Macのdata rootを複製する

```sh
# Mac側（APIを止めてから）。-H を付けない（ハードリンクを作らない）
rsync -a --delete "$HOME/hererisk-private/data/" vps:hererisk-private-staging/
# VPS側: APIを止め、所有者を API の実行ユーザーにして配置する
ssh vps 'sudo systemctl stop hererisk-elevation-private; \
  sudo rsync -a --delete ~/hererisk-private-staging/ /srv/hererisk/private/ && \
  sudo chown -R hererisk:hererisk /srv/hererisk/private'
```

APIは起動時に、Registry・全実体のchecksumを検証する。複製が不完全な場合は起動しない。

### 2.4 systemd サービス例

`/etc/systemd/system/hererisk-elevation-private.service`:

```ini
[Unit]
Description=HereRisk elevation API (private_experiment, loopback only)
After=network.target

[Service]
Type=simple
User=hererisk
Group=hererisk
WorkingDirectory=/opt/hererisk
Environment=PYTHONPATH=/opt/hererisk/src
ExecStart=/opt/hererisk/.venv/bin/python -m hererisk.elevation.api.server \
  --data-root /srv/hererisk/private --host 127.0.0.1 --port 8000 --private-experiment
Restart=on-failure
RestartPreventExitStatus=3
# 強化設定（APIはデータを読むだけで、外部へ通信しない）
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
ReadOnlyPaths=/srv/hererisk/private /opt/hererisk
InaccessiblePaths=/srv/hererisk/approvals /srv/hererisk/audit
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
IPAddressDeny=any
IPAddressAllow=localhost

[Install]
WantedBy=multi-user.target
```

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now hererisk-elevation-private
sudo systemctl status hererisk-elevation-private
journalctl -u hererisk-elevation-private -n 20     # 座標・本文は記録されない（request_id・status・error_codeのみ）
```

- exit 3（検証の失敗）では再起動しない（`RestartPreventExitStatus=3`）。原因を調べてから起動する。
- APIのプロセスには、承認ストアと監査記録へのアクセスを与えない（`InaccessiblePaths`）。

### 2.5 SSHトンネルでの接続（OWNERのMacから）

```sh
ssh -N -L 18000:127.0.0.1:8000 <owner>@<vps>
# 別のターミナルで
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"lat": 35.681236, "lon": 139.767125}' http://127.0.0.1:18000/api/v1/elevation
```

SSHは鍵認証のみとし、パスワード認証を無効にする（`PasswordAuthentication no`）。

### 2.6 ネットワークに公開されていないことの確認

VPS上で:

```sh
sudo ss -ltnp | grep ':8000'                  # 127.0.0.1:8000 だけであること（0.0.0.0 や [::] がないこと）
sudo grep -rnE '8000|reverse_proxy' /etc/caddy 2>/dev/null   # このAPIへのルーティングがないこと
sudo ufw status verbose 2>/dev/null           # 8000/tcp を許可していないこと
systemctl show hererisk-elevation-private -p IPAddressDeny -p IPAddressAllow
```

VPSの外（Mac）から、トンネルを使わずに:

```sh
curl -m 5 -s -o /dev/null -w '%{http_code}\n' http://<vps-public-ip>:8000/api/v1/elevation
# 接続できない（000）こと
```

確認の結果は、日時とともに監査記録に残す。

## 3. 停止・失効・復旧

| 状況 | 手順 |
|---|---|
| APIを止める | Mac: Ctrl+C。VPS: `sudo systemctl stop hererisk-elevation-private`（常駐をやめる場合は `disable`） |
| 承認を取り消す | `revocations.json` の `revoked` に `{"approval_id": "apr-private-…", "revoked_at": "<UTC>", "reason_ref": "<理由>"}` を追加する。以後の取得・Publishはすべて BLOCKED になる。監査記録に追記する。公開済みの個人実験データは残るため、使わない場合はAPIを止める |
| 期限切れ | `approval-check` が `production approval not in force` 等の理由でBLOCKEDを返す。延長する場合は、確認記録を見直したうえで `expires_at` を変更し、digestを計算し直す |
| 取得・検証の失敗（exit 10・11・12） | 自動で再試行しない。stderrのログと記録を確認し、必要なら `--resume-run-id` で再開する |
| Publishの記録だけ失敗（exit 13） | 公開自体は有効。同じ `run_id` で再開すると、記録が補完される |
| API が起動しない（exit 3） | rootの区分の印、Registryの破損、実体の欠落・改ざんのいずれか。印を手で付け替えたり、Registryを手で直したりしない。直前の状態に戻す場合は、Bの複製をやり直すか、取得からやり直す |
| 一般公開に使いたくなった | 個人実験のデータ・Registry・承認は使えない（拒否される）。一般公開の公開資格（[本番化Runbook](elevation-production-runbook-v0.1.md)。現在BLOCKED）を得たうえで、一般公開のrootで取得からやり直す |
