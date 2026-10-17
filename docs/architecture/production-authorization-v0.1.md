# 本番実行認可（Production Authorizer）・承認記録 設計 v0.1

- Task ID: `phase1f-elevation-production-readiness`
- 状態: 実装済み（`src/hererisk/common/authorization.py` の `ProductionAuthorizer`、`src/hererisk/common/approval_store.py`）。**本番の承認記録は1件も存在しない**（作成していない）。
- Schema: [承認記録](schemas/production-approval-record.schema.json)、[失効一覧](schemas/approval-revocations.schema.json)、[記入例（テンプレート。有効な記録ではない）](schemas/production-approval-record.example.json)
- 運用手順: [本番化Runbook](../operations/elevation-production-runbook-v0.1.md)

> Phase 1-G（2026-10-17）: 同じ仕組みを `private_experiment`（個人実験）にも使う。認可器は1つの区分だけを扱い、記録の `execution_context`・IDの空間（`apr-private-*`）・Publishの資格（`private_use` / `eligibility_*`）で区分を分ける。詳細は[運用区分と個人実験の契約](private-experiment-v0.1.md)、記入例は[個人実験の承認記録](schemas/private-experiment-approval-record.example.json)。以下の本文は public_production（`production`）についての記述である。

## 1. 原則

1. **既定は拒否。** 承認ストアを指定しない場合（`--approval-root` なし）、すべての本番操作はAPPROVAL_REQUIREDになる。
2. **明示的な記録がある操作だけを許可する。** `download`・`normalize`・`validate`・`publish` は別々の操作であり、記録の `operations` に列挙された操作だけを許可する。
3. **全工程の事前認可を維持する。** Orchestratorは、通信・書込みの前に、実行する全工程の認可を取得する。1工程でも拒否されれば、その工程名でBLOCKEDを返し、何も書かない。
4. **権限を広げない。** 要求した地域は記録の地域の部分集合、Source Definitionのタイルは記録のタイルの部分集合でなければならない。
5. **Gitの変更だけでは権限が生じない。** 承認ストアはリポジトリの外にあり、リポジトリ内のストアは拒否する。記録はSource Definitionのバイト列（SHA-256）に結び付いているため、Source Definitionを変更すると、既存の記録は無効になる。
6. **fixture・テストの承認は使えない。** fixtureの認可ファイルは形式が違うため、ストアに置いても拒否される。fixtureのマーカーを持つディレクトリは、承認ストアとしても本番のデータrootとしても拒否する。テストの承認記録は一時ディレクトリにだけ存在する。
7. **APIプロセスは管理権限を持たない。** 公開APIは、認可・承認ストア・Orchestratorのモジュールを読み込まない（テストで確認）。データrootの `rel/` を読むだけである。

## 2. 承認ストアの構成と信頼境界

```text
<approval_root>/                 管理者が作成。所有者は実行ユーザーまたはroot、group/otherに書込み権限なし
  revocations.json               必須（失効がなくても空の一覧で置く）
  approvals/                     同上
    <approval_id>.json           1記録1ファイル。ファイル名 = approval_id + ".json"
```

ストアを読むときに、次をすべて確認する（1つでも満たさなければ、**ストア全体を拒否する**）。

| 確認 | 目的 |
|---|---|
| `/` から1要素ずつ開き、途中にsymlinkがあれば拒否する | パスのすり替え防止 |
| ルートと `approvals/` がディレクトリで、所有者が実行ユーザーかrootで、group/otherに書込み権限がない | 他の利用者による記録の追加防止 |
| 各ファイルが通常ファイル・リンク数1・同じ所有者条件・group/other書込み不可・64 KiB以下 | hardlink・symlinkによる差し替え防止 |
| ルートがリポジトリ（設定・Schemaのルート）の中にない | コミットされたファイルを承認として使わせない |
| ルートにfixtureのマーカーがない | fixtureのディレクトリを使わせない |
| `approvals/` には `apr-*.json` だけがあり、ファイル名と `approval_id` が一致する | 想定外のファイルの見落とし防止 |
| 厳密なJSON解析とSchema検査、`record_sha256` の一致、`valid_from < expires_at` | 改ざん・部分編集の検出 |
| 記録は最大256件 | 資源の上限 |

`record_sha256` は、`record_sha256` 自体を除いた記録の正規化JSON（キー順、区切り `,` `:`、UTF-8）のSHA-256である。これは**部分的・偶発的な編集を検出するもので、署名ではない**。記録の真正性は、ファイルの所有者・権限と、管理者の登録・監査の手順（Runbook）に依拠する。署名による真正性の確認は、今後の課題である（第6章）。

## 3. 承認記録

| フィールド | 必須 | 内容 |
|---|---|---|
| `schema` | ○ | `hererisk-production-approval-v0.1` |
| `approval_id` | ○ | `apr-` で始まる識別子。Source Definitionの `approval_ref` と一致すること |
| `execution_context` | ○ | `production` 固定 |
| `api_id`・`source_ref` | ○ | 対象のAPIと取得元。`fixture-` で始まる取得元は不可 |
| `operations` | ○ | 許可する操作の一覧（重複なし） |
| `region_codes` | ○ | 許可する都道府県コード |
| `tiles` | ○ | 許可するタイル `{z, x, y}`（最大1024） |
| `definition` | ○ | `revision` と `raw_sha256`（Source Definitionファイルのバイト列のSHA-256） |
| `valid_from`・`expires_at` | ○ | 有効期間（UTC、`YYYY-MM-DDTHH:MM:SSZ`）。`valid_from <= 現在 < expires_at` の場合だけ有効 |
| `approved_by`・`approval_basis_ref` | ○ | 承認者と、承認根拠への参照（議事録・照会結果など） |
| `acquisition` | `download` を含む場合は必須、それ以外は不可 | `allowed_host`、`max_tiles_per_run`（1〜1024）、`max_tile_bytes`（1 MiB以下）、`max_pending_acquisitions` |
| `publication` | `publish` を含む場合は必須、それ以外は不可 | `license`、`attribution_url`（HTTPS）、`attribution_text`、`eligibility_status`（`approved` のみ）、`eligibility_ref` |
| `record_sha256` | ○ | 第2章 |

失効一覧 `revocations.json`: `{"schema": "hererisk-approval-revocations-v0.1", "revoked": [{"approval_id", "revoked_at", "reason_ref"}]}`。一覧にあるIDの記録は、有効期間内でも拒否する。

## 4. 認可の判定

`ProductionAuthorizer.authorize(api_id, operation, source_ref, region_codes, definition)` は、次の順に判定する。どれかに当たれば `APPROVAL_REQUIRED` である。

1. 承認ストアが指定されていない、または第2章の検証に失敗した
2. 該当する記録がない。該当の条件は、api_id・source_ref が一致し、operation が `operations` にあり、要求地域 ⊆ `region_codes`、`definition.raw_sha256` が一致すること
3. 該当する記録が2件以上ある（あいまい）
4. Source Definitionの `approval_ref` が、その記録の `approval_id` と違う
5. 失効している、または有効期間外である
6. `download` の場合:
   - Source Definitionのタイルが空、または承認したタイルに含まれないものがある
   - タイル数が `max_tiles_per_run` を超える
   - URLテンプレートがHTTPSでない、ホストが `allowed_host` と違う、またはポートの指定がある
7. `publish` の場合: Source Definitionの出典文言が、記録の `publication.attribution_text` と違う

許可した場合、`Authorization` の内容は次のとおり:

- `authorization_ref = approval_id`
- `download` の `policy` = `{policy_id = approval_id, version = definition.revision, max_tile_bytes, max_tiles_per_request = max_tiles_per_run, max_pending_acquisitions}`
- `publish` の `policy` = `{license, attribution_url}`（PublishStageの要件と同じ）

`approval_id` は、Download・Normalize・Validate・Publishの各記録の `authorization_ref`（Downloadは `usage_snapshot.approval_ref`）に残るため、監査で辿れる。

Orchestratorは、本番の実行で、fixtureのマーカー（内容を問わない）を持つデータrootを拒否する（INVALID_INPUT）。

## 5. 既存機能との関係

- `FixtureAuthorizer` は変更していない。
- `ProductionAuthorizer()`（引数なし）の挙動は従来と同じで、常に拒否する。
- 管理CLIの既存の動作は維持する。追加したのは次のとおり。
  - `pipeline --approval-root`（`--production` と組み合わせた場合だけ有効。fixtureと組み合わせるとINVALID_INPUT）
  - `approval-check`（事前確認。通信・書込みなし）
  - `approval-digest`（`record_sha256` の表示のみ。ファイルは書かない）
- 認可の失敗は、常にBLOCKED（exit 3）である。NoDataやSUCCESSには変換しない。

## 6. 残課題

- 署名（例: 管理者の鍵による署名）による記録の真正性の確認。現在は、OSのファイル所有者・権限による信頼境界である。
- 複数ホストでの運用（承認ストアの配布・同期）。現在は、単一ホストを前提とする。
- 承認記録の登録・失効の履歴を、改ざんできない形で残す方式（現在は、Runbookの手順による監査記録）。
