# 実GSI 個人実験 受入手順（Mac・1タイル）v0.1

- Task ID: `phase1h-gsi-private-acceptance`。**OWNERだけが実行する**（本書の作成時には、どのコマンドも実GSIに対して実行していない）。
- 方針: [決定記録 2026-10-17](../decisions/2026-10-17-private-experiment-operation.md)。詳細手順・VPS: [個人実験Runbook](elevation-private-experiment-runbook-v0.1.md)
- 対象: `gsi-dem10b-candidate`（DEM10B `dem_png`）、地域 `13`、Z14、X `14552`、Y `6451`、照会地点 `35.681236, 139.767125`（このタイルの画素 (245, 168)）
- 置き場所: `$HOME/hererisk-private`（リポジトリの外。実データ・承認・トークンをGitに入れない）

## 実行前に決めること（OWNER）

**取得の実行許可は、まだ確定していない。** 測量法上の手続の要否（決定記録のQ-1〜Q-3）は未解決である。照会するか、照会せずに進めるかを決め、その判断を下の「利用条件確認記録」に書いてから手順3へ進む。

| 値 | 使う場所 | 状態・案 |
|---|---|---|
| 出典文言 | `--attribution-text`（APIの `attribution.text`） | **OWNERが決める**。案: `出典：国土地理院ウェブサイト（地理院タイル 標高タイル（基盤地図情報数値標高モデル）DEM10B）を加工して作成`（規約の例「出典：国土地理院ウェブサイト」と加工の表示に基づく案。国土地理院の確認は受けていない） |
| 鉛直基準の記述 | `--vertical-reference` | 案（確認済みの事実のみ）: `T.P.（一部離島を除く。基盤地図情報FAQ Q.4-12）。DEM10Bは2025年標高成果改定の対象外。測量時期は不明` |
| 利用条件確認記録の参照 | `--review-ref`、`--basis-ref`、`--usage-review-ref` | OWNERが作成する（下記）。例: `owner-usage-review-2026-10-XX` |
| ライセンス表記 | `--license`（手順5） | 案: `国土地理院コンテンツ利用規約（公共データ利用規約 第1.0版 PDL1.0）` |
| 出典URL | `--attribution-url`（手順5） | 案: `https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html` |
| 承認者 | `--approved-by` | OWNERの名前 |

`<…>` を含む値・空の値は、コマンドが受け付けない。

**利用条件確認記録**（`$HOME/hererisk-private/audit/usage-review.md` などリポジトリ外。[チェックリスト5.3](gsi-dem10b-usage-checklist-v0.1.md)の項目）: 利用形態（Mac、本人のみ）、非営利、対象タイル（上記1枚）・取得1回・保存場所、第三者に提供しないこと、未確認事項（Q-1〜Q-5）の扱いと理由、出典文言、確認日・確認者。この記録は個人実験の判断の記録であり、許諾や適法性の証明ではない。

## 準備（毎回のターミナルで）

```sh
cd ~/Documents/GitHub/HereRisk
export PYTHONPATH=src
hr() { .venv/bin/python -m hererisk.cli "$@"; }
BASE="$HOME/hererisk-private"
ID=apr-private-elevation-13-0001
T=(--api elevation --region 13 --source gsi-dem10b-candidate)
```

## 1. 環境と設定の準備・確認（初回のみ、通信なし）

```sh
hr private-init --base "$BASE"          # data / approvals / secrets(トークン) / audit を作る
hr private-definition --base "$BASE" --approval-id "$ID" --tile 14552,6451 \
  --attribution-text "<決めた出典文言>" \
  --vertical-reference "<鉛直基準の記述>" \
  --review-ref "<利用条件確認記録の参照>"
hr private-status --base "$BASE"
```

確認: `definition.tiles` が `[{"x": 14552, "y": 6451}]`、`approval_ref` が `$ID`、`approvals` が空、`token_file: true`。

## 2. Dry-run（通信なし）

```sh
hr approval-check "${T[@]}" --private-base "$BASE"
```

確認: 承認がまだないため `status: BLOCKED`（exit 3）。`definition_raw_sha256` を受入記録に控える。

## 3. 取得の承認と、実GSIタイル1枚の取得

OWNERの判断（上記）が済んでから実行する。承認はこのコマンドで登録した時点で初めて生じる（期限は7日など短くする）。

```sh
hr approval-register --base "$BASE" --approval-id "$ID" --confirm "$ID" \
  --operations download,normalize,validate --region 13 \
  --approved-by "<OWNERの名前>" --basis-ref "<利用条件確認記録の参照>" --valid-days 7
hr approval-check "${T[@]}" --private-base "$BASE"        # download/normalize/validate が GRANTED（exit 0）
hr pipeline "${T[@]}" --private-experiment --private-base "$BASE" --allow-network \
  2> "$BASE/audit/run-acquire.log"                          # ここで初めて実GSIへ1回通信する
```

stdoutの `run_id` を控える（以下 `RUN=<run_id>`）。exit 0以外の場合は、自動で再試行しない（[Runbook 第3章](elevation-private-experiment-runbook-v0.1.md)）。

## 4. Normalize / Validate の結果確認

```sh
hr private-status --base "$BASE"                            # normalizations / validations が SUCCESS
cat "$BASE/data/elevation/records/validations/$RUN.json"     # 統計（有効画素数・欠損・最小・最大）
```

確認: `execution_context: private_experiment`、`authorization_ref: $ID`。`rel/`（公開）はまだない。

## 5. Private Publish の承認（OWNER）

手順4の結果を確認したうえで、同じ承認に `publish` を加える（確認した run を指定する。確認前の run では登録できない）。

```sh
hr approval-register --base "$BASE" --approval-id "$ID" --confirm "$ID" --replace \
  --operations download,normalize,validate,publish --region 13 \
  --approved-by "<OWNERの名前>" --basis-ref "<利用条件確認記録の参照>" --valid-days 7 \
  --license "<ライセンス表記>" --attribution-url "<出典URL>" \
  --usage-review-ref "<利用条件確認記録の参照>" --reviewed-run-id "$RUN"
hr approval-check "${T[@]}" --private-base "$BASE" --publish  # 4操作が GRANTED
```

## 6. Publish の実行（同じ run を再開。再取得しない）

```sh
hr pipeline "${T[@]}" --private-experiment --private-base "$BASE" --allow-network --publish \
  --resume-run-id "$RUN" 2> "$BASE/audit/run-publish.log"
hr private-status --base "$BASE"                            # registry: {"13": "rev-<RUN>"}
```

## 7. Bearer Token 付きAPIで標高を取得

```sh
.venv/bin/python -m hererisk.elevation.api.server --private-experiment --private-base "$BASE"
# 別のターミナルで（127.0.0.1:8000 で待受け）
curl -sS -X POST -H @"$HOME/hererisk-private/secrets/auth-header" -H 'Content-Type: application/json' \
  -d '{"lat": 35.681236, "lon": 139.767125}' http://127.0.0.1:8000/api/v1/elevation
curl -sS -o /dev/null -w '%{http_code}\n' -X POST -H 'Content-Type: application/json' \
  -d '{"lat": 35.681236, "lon": 139.767125}' http://127.0.0.1:8000/api/v1/elevation   # 401
lsof -nP -iTCP:8000 -sTCP:LISTEN                            # 127.0.0.1:8000 のみ
```

確認: `status: success`、`dataset.publication_version: pub-<RUN>`、`dataset.attribution` が登録した値。返った `elevation_m` を記録する（期待値は事前に決めない。DEM10Bの値で、精度は5m以内のRMSと規定されている）。

## 8. 後片付けと受入結果の記録

```sh
# APIを Ctrl+C で止める。実験を終える場合は承認を失効させる
hr approval-revoke --base "$BASE" --approval-id "$ID" --confirm "$ID" --reason-ref "acceptance finished"
hr private-status --base "$BASE"                            # revoked: true
git status --short                                          # 何も出ないこと（実データ・秘密はGitの外）
```

受入記録（`$BASE/audit/acceptance.md`。リポジトリ外）に書く: 実施日時、`definition_raw_sha256`、`$ID` の `record_sha256`（`audit/approvals.log`）、`RUN`、手順3〜7の終了コード、Validateの統計、取得した `elevation_m`、401の確認、待受けの確認、未確認事項（Q-1〜Q-5）の扱い。リポジトリには、受入の結論（実データ・トークン・座標以外）だけを、必要ならOWNERが記録する。

データを残すか消すかはOWNERが決める。消す場合は `rm -rf "$BASE/data"` などで、`$BASE/approvals`・`$BASE/audit` は監査のために残す。
