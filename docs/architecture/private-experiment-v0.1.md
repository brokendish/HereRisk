# 運用区分と個人実験（private_experiment）契約 v0.1

- Task ID: `phase1g-private-experiment`
- OWNER方針: 2026-10-17（非営利・個人実験環境を、一般公開と完全に分離して実装する。一般公開はBLOCKEDのまま維持する）
- 状態: 実装済み。**実GSIの取得・Private Publishは未実行**（OWNERが別途明示して実行する）。個人実験の承認記録・確認記録は存在しない。
- 関連: [本番認可設計](production-authorization-v0.1.md)、[GSI利用条件チェックリスト 第5章](../operations/gsi-dem10b-usage-checklist-v0.1.md)、[個人実験Runbook](../operations/elevation-private-experiment-runbook-v0.1.md)

## 1. 運用区分

| 区分 | `execution_context` の値 | 用途 | 認可 | データroot | API |
|---|---|---|---|---|---|
| `fixture` | `fixture` | 合成データでの開発・テスト | `FixtureAuthorizer`（fixtureの認可ファイル） | `init-fixture-root` で印を付けた一時root | `--fixture-demo`（ループバックのみ） |
| `private_experiment` | `private_experiment` | OWNER本人の非営利の個人実験（Mac、VPSの本人専用API） | `ProductionAuthorizer(context=private_experiment)` + `apr-private-*` の承認記録 | `init-private-root` で印を付けた専用root | `--private-experiment`（ループバックのみ） |
| `public_production` | `production`（既存の記録との互換のため値は変えない） | 一般公開サービス | `ProductionAuthorizer()` + `apr-*`（`apr-private-` 以外）の承認記録 | 印のないroot | 既定のモード |

**一般公開（public_production）の公開資格はBLOCKEDである。** 一般公開の承認記録は存在せず、作成できる前提（[チェックリスト](../operations/gsi-dem10b-usage-checklist-v0.1.md) 第2章）もそろっていない。

## 2. 認可

既存の `ProductionAuthorizer` の仕組み（承認ストアの信頼境界、Source Definitionのハッシュ照合、`approval_ref` との一致、失効、有効期間、タイル・ホスト・件数の制限、操作ごとの明示的な許可、全工程の事前認可）をそのまま使う。追加した規則は次のとおり。

1. **1つの認可器は1つの区分だけを扱う。** `ProductionAuthorizer(context=...)` は、記録の `execution_context` が自分の区分と一致する記録だけを照合する。一致しない記録は、存在しないものとして扱う。
   - private の承認は public に継承されず、public の承認も private に継承されない。
2. **IDの空間を分ける。** private の記録は `apr-private-` で始まり、public の記録は `apr-private-` で始まってはならない（Schemaで検査する）。Source Definitionの `approval_ref` は1つの記録を指すため、同じSource Definitionで両方の区分が同時に有効になることはない。
3. **Publishの資格を分ける。**

   | 区分 | `publication` に必須 | `publication` に禁止 |
   |---|---|---|
   | private_experiment | `license`・`attribution_url`・`attribution_text`・`private_use`（`purpose = non_commercial_personal_experiment`、`access = owner_only_loopback`、`usage_review_ref`、`confirmed_by`、`confirmed_at`） | `eligibility_status`・`eligibility_ref` |
   | public_production | `license`・`attribution_url`・`attribution_text`・`eligibility_status = approved`・`eligibility_ref` | `private_use` |

   - Schemaで拒否し、認可器でも同じ規則を再確認する（多重の防御）。
   - private の承認に、一般公開用の `eligibility_status = approved` を流用することはできない。
4. `private_use` は、OWNERの**利用条件の確認記録**（[チェックリスト 5.3](../operations/gsi-dem10b-usage-checklist-v0.1.md)）への参照である。このフィールドを書くことで、法令や利用規約に適合したことになるわけではない。
5. 既定は拒否である。`--approval-root` がない場合、または該当する記録がない場合はAPPROVAL_REQUIRED（通信・書込みの前）になる。

## 3. データ・Registryの分離

```text
<private_root>/                       init-private-root で作成（空のディレクトリに印を付ける）
  .hererisk-private-experiment-root   区分の印（内容は固定。本人所有・リンク数1）
  elevation/
    dl/ work/ records/
    rel/versions/  rel/registry/      private の公開実体とRegistryだけ

<public_root>/                        印のないディレクトリ（現在は使わない。一般公開はBLOCKED）
  elevation/ ...
```

- 既存の `ApiDataArea`（`<data_root>/<api>/` への閉じ込め、symlinkを辿らない固定、上書き禁止）、Publishの原子的な切替（P6）、旧実体の保護、証跡の再検証は変更していない。区分は**データrootの単位**で分ける。
- 印の検査は、固定したroot（fd）で行う。

  | 実行 | 受け付けるroot | 拒否するroot |
  |---|---|---|
  | fixture | 正確なfixtureの印があり、保護領域の外 | private の印（内容を問わない）がある |
  | private_experiment | 正確なprivateの印があり、fixtureの印がなく、リポジトリの外 | 印がない、印の内容が違う、fixtureの印がある |
  | public_production | 印がない | fixture または private の印（内容を問わない）がある |

- Private Registryは、private rootの中の実体だけを参照する（Registryの `publication.path` は、そのroot内の `rel/` からの相対パスである）。
- Privateからpublicへのコピー・昇格・Registryの共用をする機能はない。publicのrootに書けるのは、public の承認によるpublicの実行だけである。将来publicへ移行する場合は、publicの公開資格と承認記録を得たうえで、publicのrootで取得からPublishまでを行う。
- 汎用のRegistryシステムへの作り替えはしていない。

## 4. HTTP API

`POST /api/v1/elevation` の契約（入力・7キーの応答・status・ログ）と標高の計算は変更していない。

| モード | 起動 | 受け付けるroot | 待受け |
|---|---|---|---|
| public（既定） | `hererisk.elevation.api.server --data-root …` | 印のないroot。private の印（内容を問わない）またはfixtureの印があれば起動しない | 指定どおり |
| private | `… --private-experiment` | 正確なprivateの印があり、fixtureの印がないroot | **ループバックのみ**（127.0.0.1 / ::1）。それ以外のアドレスは起動しない |
| fixture demo | `… --fixture-demo` | fixtureのroot | ループバックのみ |

- `--private-experiment` と `--fixture-demo` は同時に指定できない。
- 起動時の検証（ポインタ → 改訂 → 全実体のchecksum → Validate）に失敗すると、exit 3で起動しない。
- アプリケーションのログには、request_id・status・error_codeだけを出す。座標・本文・パスは出さない。標準ライブラリのアクセスログは無効にしている。
- 独自のユーザー管理はない。本人限定であることは、ループバックでの待受けとSSHトンネル（[Runbook](../operations/elevation-private-experiment-runbook-v0.1.md)）で保証する。VPSでは、Caddy等の公開リバースプロキシからこのAPIへルーティングしない。

## 5. 互換性

- `fixture` の実行・認可、`public_production` のBLOCKED、既存のCLIの動作は変更していない。
- 既存の記録の `execution_context = production` は、そのまま public_production を意味する。
- private の実行の記録は、`execution_context = private_experiment` で、パイプライン版・Validateのprofileは本番形式（`elevation-download` 0.1、`elevation-normalized-v0.1`）である。
