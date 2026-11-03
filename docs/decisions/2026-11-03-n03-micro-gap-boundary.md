# ADR-003: N03原典の微小な隙間は修復せず、許容距離内の境界として扱う（O-14）

- 決定日: 2026-11-03
- 決定者: OWNER（Phase 4-N.3 の指示による決定 O-14）
- 状態: **ACCEPTED**
- 関連: [Location Resolver 実装仕様 v0.1](../api/location-resolver-impl-v0.1.md) 6.1節、[Location Resolver / Source Resolver 契約 v0.1](../api/location-resolver-contract-v0.1.md) 2.4節、[全国対応の設計 v0.1](../architecture/nationwide-location-index-design-v0.1.md) O-14、[Design Principles](../architecture/design-principles-v1.0.md)（DP-01 原典尊重、DP-07 不確実性の明示）、[ADR-002](2026-11-03-polygon-engine-responsibility.md)（修復の関数を置かない）
- 注意: この決定は行政区域（N03）の扱いである。ハザードの区域のPolygonの扱い（判定保留・参考解析）を変えない。Providerへの組込みを承認するものではない。

## 背景

Phase 4-N.2 の比較で、国土数値情報 N03（2026年1月1日）の隣り合うFeatureの間に、面積1m²未満の隙間が見つかった（東京48か所・最大約0.0005m²、神奈川133か所・最大約0.000002m²。例: 千代田区と新宿区、横須賀市と葉山町）。

- 共通Location Resolverは、地点の近く（許容距離10m以内）の区域だけを結合するため、隙間が残り、その周り10m以内を `boundary` と判定する。
- 既存の `_Region`（洪水・津波Provider）は、都道府県（の集合）の全Polygonを1つに結合する。GEOSの結合で隙間が消える場合があり、`inside` と判定する。消えるかどうかは、**結合する集合によって変わる**（例: 横須賀市・葉山町の点で `{14}` は `boundary`、`{13,14}` は `inside`）。
- その結果の既知の差異: 東京だけの索引で `{13}` の7件（原因 `source_micro_gap`）、東京＋神奈川で `{13,14}` の38件（原因 `reference_union_depends_on_set`）。Phase 4-N.3 の Source Resolver と現在の洪水・津波Providerの比較（41,506点、隙間の周りの点を含む）では、各85件がすべて `source_micro_gap`。

## 決定

1. 原典のPolygonを**修復・補正しない**。
2. 微小な隙間を**自動的に埋めない**（隙間の面積の閾値で埋める、緩衝・スナップする等をしない）。
3. 許容距離10m以内に区域の外縁（隙間の縁を含む）がある地点は `boundary` として扱う。Location Resolver の判定規則（`resolve`・`region_relation`）は変えない。
4. 既存の全体結合方式との差異は、**原因を明示した仕様上の差異**として受け入れる。受け入れる原因は次の2つだけ:
   - `source_micro_gap`: 地点の周り（許容距離の3倍の矩形）で、登録したN03のFeatureに覆われていない部分のうち、地点から許容距離以内にあるものが（1つ以上あり）すべて1m²未満である。閉じた隙間も、遠くで外側につながる細長い隙間も含む。海や隣県のような実際の外側は、この矩形の中で1m²よりはるかに大きい。Resolverの判定を使わず、原典の形状だけで確認する（`hererisk.research.resolver_compare.MicroGap`）
   - `reference_union_depends_on_set`: 候補の区域がすべて1つの都道府県Pにあり、既存の `{P}` の判定がResolverと同じ答え（既存の答えが、許容距離より遠いPolygonを含む結合の集合に依存している）
5. **原因を説明できない差異は許容しない**。比較・回帰で未分類の差異が1件でもあれば不合格とする。
6. 差異の件数（東京だけ7件、東京＋神奈川38件）は、Phase 4-N.2 の検証地点での既知の値として記録する。地点の集合・N03の版が変われば件数は変わりうる。そのときも、すべてが上の2つの原因に分類されることを条件とする。

## 帰結

- 隙間の周り10m以内では、ハザードの対象地域の関係が `boundary` になり、Location API ではハザードのセクションが（区域がなければ）`unknown`（`service_region_boundary`）になる。現在の `no_match` より安全側で、「該当なし」と言わない。
- Providerを Location Resolver・Source Resolver に切り替える段階で、隙間の近くの地点の応答が変わりうる。回帰では、変わった地点がすべて上の原因に分類されることを確認する。
- 原典の隙間は原典の事実として残る。N03の版が更新されたら、隙間の数を記録し直す。

## この決定に含まれないこと

- ハザードのPolygon（A31a・A40等）の無効形状・隙間の扱い（既存の判定保留の規則のまま）。
- 許容距離10mの値の見直し（設計 O-3）。
- Providerへの組込み（OWNERの承認後）。
