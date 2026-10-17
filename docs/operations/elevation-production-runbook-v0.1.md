# 標高 本番化Runbook v0.1（管理者向け）

- Task ID: `phase1f-elevation-production-readiness`
- 対象: 国土地理院 DEM10B `dem_png` Z14 の本番取得 → Normalize → Validate → Publish → 公開APIでの確認
- **現状: 実行不可（BLOCKED）**。[GSI利用条件チェックリスト](gsi-dem10b-usage-checklist-v0.1.md) の公開資格がBLOCKEDで、本番の承認記録は存在しない。本書は、前提がそろった後にOWNER（管理者）が実行する手順である。本書の作成時に、これらの手順は実行していない。
- 設計: [本番認可設計](../architecture/production-authorization-v0.1.md)、[実装仕様](../pipeline/elevation-publish-api-v0.1.md)、[契約改訂案 P1〜P7](../pipeline/elevation-contract-revision-p1-p7-v0.1.md)

以下、`$REPO` はリポジトリのルートで、コマンドはすべて `$REPO` で実行する。

## 0. 前提（すべてOWNERの判断。満たされるまで先に進まない）

| No | 前提 | 確認先 |
|---|---|---|
| 0-1 | 測量法上の手続の要否が判明し、必要なら承認を得ている | チェックリスト B-6・B-7・B-9、第3章の照会 |
| 0-2 | 出典文言・ライセンス表記・URLを確定している（加工の表示を含む） | チェックリスト B-4 |
| 0-3 | DEM10Bの鉛直基準（T.P.、離島は例外）・測量時期（不明）・改定対象外であることを了承している | チェックリスト B-10 |
| 0-4 | 契約改訂案 P1〜P7 の採否を決めている → **2026-10-17 に正式採用（済み）** | [決定記録](../decisions/2026-10-17-elevation-p1-p7.md) |
| 0-5 | 取得対象タイル（地域・数）と、取得の時期・間隔を承認している | 本書 第2章 |
| 0-6 | 実行ホスト・実行ユーザー・データroot・承認ストアの置き場所を決めている | 本書 第1章 |

PoC（Phase 1-D.1）で取得したPNGと証跡を、本番の取得・公開の承認や入力として使わない。

## 1. 置き場所と権限

| 対象 | 例 | 権限 |
|---|---|---|
| 承認ストア | `/srv/hererisk/approvals`（リポジトリの外） | 所有者 = 実行ユーザー（またはroot）。ディレクトリ 0700（最低でもgroup/otherの書込み不可）、ファイル 0600 または 0644 |
| 本番データroot | `/srv/hererisk/data`（空のディレクトリ。`init-fixture-root` はしない） | 実行ユーザーが所有。0750 |
| 監査記録 | `/srv/hererisk/audit/approvals.log`（リポジトリの外） | 管理者のみ書込み |

- 承認ストアは、リポジトリやfixtureのディレクトリの中に置かない（置くと拒否される）。パスにsymlinkを含めない（macOSの `/tmp` は `/private/tmp` へのsymlinkであるため、実体のパスを指定する）。
- 承認記録を作成・変更できるのは、承認ストアの所有者（管理者）だけである。他の利用者が書けるストアは拒否される。

## 2. 取得対象の確認

1. 対象タイルを決める（Z14のx・y）。地点からタイルを求める場合は、PoCの計画表示（通信しない）を使える。

   ```sh
   PYTHONPATH=src .venv/bin/python -m hererisk.cli gsi-fetch-poc --lat 35.681236 --lon 139.767125 \
     --zoom 14 --output-dir "$(mktemp -d)"     # --allow-network を付けない = 計画の表示のみ
   ```

2. Source Definition（`api/elevation/conf/sources.json`）の `gsi-dem10b-candidate` を、通常のレビューを経たコミットで更新する。
   - `acquisition.tiles`: 承認したタイル `[{"x": …, "y": …}]`
   - `vertical_reference`: 0-3で了承した記述
   - `usage.attribution_text`: 0-2で確定した文言
   - `usage.review_ref`: 利用条件レビューの参照
   - `pipeline`: `{"id": "elevation-download", "version": "0.1"}`
   - `approval_ref`: これから作る承認記録のID（例 `apr-elevation-13-0001`）
   - `definition_revision`: 新しい版
   - **このコミットだけでは権限は生じない**（承認記録がないためBLOCKEDのまま）。

## 3. 承認記録の登録（管理者）

### 3.0 準備

```sh
cd "$REPO"
APPROVALS=/srv/hererisk/approvals
DATA=/srv/hererisk/data
install -d -m 700 "$APPROVALS" "$APPROVALS/approvals"
install -d -m 750 "$DATA"
```

### 3.1 失効一覧（初回のみ。失効がなくても必須）

```sh
cat > "$APPROVALS/revocations.json" <<'JSON'
{"schema": "hererisk-approval-revocations-v0.1", "revoked": []}
JSON
chmod 600 "$APPROVALS/revocations.json"
```

### 3.2 Source Definitionのハッシュを得る（通信・書込みなし）

```sh
PYTHONPATH=src .venv/bin/python -m hererisk.cli approval-check --api elevation --region 13 \
  --source gsi-dem10b-candidate --approval-root "$APPROVALS"
# 記録がまだないのでBLOCKED（exit 3）。出力の definition_revision と definition_raw_sha256 を控える
```

### 3.3 記録を手で作成する

[記入例](../architecture/schemas/production-approval-record.example.json) を写し、`<…>` をすべて実際の値に置き換える。

- **最初は `publish` を含めない**（取得・検証の結果を確認してから、第6章で追加する）。
- `tiles`・`region_codes` は、0-5で承認した範囲だけにする。
- `max_tiles_per_run` はタイル数以下、`max_pending_acquisitions` は小さくする。
- `valid_from`・`expires_at` は、実行する期間だけにする（例: 1週間）。
- `approved_by`・`approval_basis_ref` には、承認者と承認根拠（議事録・照会結果の番号）を書く。

```sh
vi /tmp/apr-elevation-13-0001.json        # 作業用コピー（record_sha256 は仮の値）
PYTHONPATH=src .venv/bin/python -m hererisk.cli approval-digest --record /tmp/apr-elevation-13-0001.json
# {"record_sha256": "<値>"} -> 記録の record_sha256 に書き込む（内容を変えたら、毎回計算し直す）
install -m 600 /tmp/apr-elevation-13-0001.json "$APPROVALS/approvals/apr-elevation-13-0001.json"
```

`approval-digest` は値を表示するだけで、記録を作成・補完しない。

### 3.4 監査記録

登録・変更・失効のたびに、日時・操作者・`approval_id`・`record_sha256`・承認根拠を監査記録に追記する。

```sh
printf '%s register apr-elevation-13-0001 sha256=%s basis=%s by=%s\n' \
  "$(date -u +%FT%TZ)" "<record_sha256>" "<approval_basis_ref>" "$(id -un)" >> /srv/hererisk/audit/approvals.log
ls -ln "$APPROVALS" "$APPROVALS/approvals"     # 所有者・権限を確認して記録する
```

## 4. 事前確認（Dry-run）

```sh
PYTHONPATH=src .venv/bin/python -m hererisk.cli approval-check --api elevation --region 13 \
  --source gsi-dem10b-candidate --approval-root "$APPROVALS"
echo "exit=$?"
```

- `status: GRANTED`（exit 0）で、download・normalize・validate がすべて `GRANTED` であること。
- BLOCKEDの場合は `reason` を見る。主なもの:
  - `no matching production approval`: API・取得元・地域・Source Definitionのハッシュが記録と一致しない（Source Definitionを変更した場合は、記録の更新が必要）
  - `source definition names another approval`: `approval_ref` と `approval_id` が違う
  - `production approval not in force`: 有効期間外
  - `production approval revoked`: 失効済み
  - `tiles not approved` / `more tiles than approved per run` / `acquisition host not approved`
  - `approval store rejected: …`: 権限・所有者・symlink・ファイル名・digest・Schemaの問題（ストア全体を拒否する）
- この確認は、通信もデータrootへの書込みもしない。

## 5. 正式実行（取得 → 正規化 → 検証）

```sh
PYTHONPATH=src .venv/bin/python -m hererisk.cli pipeline --api elevation --region 13 \
  --source gsi-dem10b-candidate --production --allow-network \
  --approval-root "$APPROVALS" --data-root "$DATA" 2> /srv/hererisk/audit/run-$(date -u +%Y%m%dT%H%M%SZ).log
echo "exit=$?"
```

- stdoutは結果のJSON 1行である。`run_id` を控える。
- 確認するもの:
  - `$DATA/elevation/records/acquisitions/<run_id>/`: 取得URL、SHA-256、`usage_snapshot.approval_ref`
  - `records/normalizations/<run_id>.json` と `records/validations/<run_id>.json`: `authorization_ref`、`execution_context = production`、統計
- この段階では、何も公開されない（`rel/` は作られない）。

## 6. Publish

1. 第5章の結果を確認したうえで、同じ承認記録に `publish` と `publication` を追加する。
   - `publication.license`・`attribution_url`・`attribution_text`: 0-2で確定した値。`attribution_text` はSource Definitionと同じ文言にする
   - `eligibility_status`: `approved`。**0-1〜0-3がすべて満たされた場合だけ**
   - `eligibility_ref`: 公開資格を判断した記録の参照
2. `approval-digest` で `record_sha256` を計算し直し、記録を置き換え、監査記録に追記する（第3.3〜3.4節）。
3. `approval-check ... --publish` で、4操作すべてが `GRANTED` であることを確認する。
4. 同じ `run_id` で再開し、Publishまで実行する（取得済みのタイルは再利用し、通信しない）。

   ```sh
   PYTHONPATH=src .venv/bin/python -m hererisk.cli pipeline --api elevation --region 13 \
     --source gsi-dem10b-candidate --production --allow-network --publish \
     --approval-root "$APPROVALS" --data-root "$DATA" --resume-run-id "<run_id>"
   ```

5. `$DATA/elevation/rel/registry/13/current.json` が `rev-<run_id>` を指し、`records/publications/<run_id>.json` が `SUCCESS` であることを確認する。

## 7. 公開APIでの確認

```sh
PYTHONPATH=src .venv/bin/python -m hererisk.elevation.api.server --data-root "$DATA" \
  --host 127.0.0.1 --port 8000          # 本番データrootには --fixture-demo を付けない
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"lat": 35.681236, "lon": 139.767125}' http://127.0.0.1:8000/api/v1/elevation
```

- `status: success`、`dataset.publication_version = pub-<run_id>`、`dataset.attribution` が承認記録の値と一致すること。
- 公開対象外の地点は `no_coverage` になること。
- 起動時の検証に失敗するとexit 3で、起動しない。
- 一般公開（ループバック以外での待受け、デプロイ）は、別途OWNERが承認する（本書の範囲外）。

## 8. 失敗時の停止と調査

| 状況 | 対応 |
|---|---|
| exit 3（BLOCKED） | 第4章の `approval-check` で理由を確認する。記録やストアを「通るように」書き換えない。承認の範囲を広げる場合は、OWNERの承認を得てから記録を更新する |
| exit 10（転送失敗: HTTP_404・TIMEOUT・TLS_FAILED等） | 自動で再試行しない。ログ（stderr）とAcquisition Recordを確認する。再実行する場合は `--resume-run-id` を使う |
| exit 11（PNG・検証の失敗） | 公開されない。Normalize・Validateの記録で原因を確認する |
| exit 12（保存の失敗） | 容量・権限を確認する。`rel/` の現行ポインタは変わっていない（切替前の失敗では旧公開状態を維持する） |
| exit 13（RECORD_COMMIT_FAILED） | Publishの切替後に記録だけが失敗した場合、公開自体は有効である。同じ `run_id` で再開すると、記録が補完される |
| TARGET_BUSY | 同じ取得元の別の実行が動いている。終了を待つ。ロックを手で消さない |
| 誤った承認を見つけた | ただちに `revocations.json` に追加する（`approval_id`・`revoked_at`・`reason_ref`）。以後のすべての操作がBLOCKEDになる。監査記録に追記する |
| 公開済みデータに問題がある | APIを停止する。旧改訂・旧実体は残っているが、Rollbackの機能はまだない（OWNERが対応を判断する） |

すべての実行で、stderrのログ（構造化JSON）を監査ディレクトリに保存する。ログに緯度経度・認証情報は含まれない。

## 9. 定期的な監査

- `ls -ln` で、承認ストアの所有者・権限が第1章のとおりであること。
- 各記録の `record_sha256` が、監査記録の最新の値と一致すること（`approval-digest` で再計算する）。
- 期限切れの記録を `approvals/` から外し、監査ディレクトリに移すこと（失効一覧には残す）。
- 各runの記録の `authorization_ref` が、監査記録にある承認IDであること。
