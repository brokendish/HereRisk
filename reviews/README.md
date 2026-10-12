# 公開検証サマリー

`reviews/` は、GitHub上で成果物レビューに必要な公開可能な検証結果を管理する。正式な設計書・API契約・テストコードとともにGit管理対象とする。

- [Phase 0：AI開発基盤整備・GitHubレビュー連携](phase0/ai-development-setup.md)
- [AI共通作業規約](../docs/development/ai-development-policy.md)

詳細指示書・詳細報告書は公開しない。公開サマリーは詳細報告書から必要な情報だけを抽出し、共通の作業IDで対応付ける。秘密情報、内部IPアドレス、認証情報、個人情報、機密性の高い脆弱性情報を記載しない。機密性の高い問題は非公開報告書でOWNERへ通知する。

対象コミットは実際に検証したSHAとし、未コミットなら「未コミット」と記載する。実装担当・検証担当を記載し、自己検証を独立検証と表記しない。OWNERの共有許可と最終承認は区別して記録する。

判定はPASS、PASS WITH FINDINGS、FAIL、BLOCKED、NOT RUNを用いる。基準はAI共通作業規約を参照する。未実施はNOT RUNと理由を記録し、実施済みと誤認させない。総合判定には対象範囲と制約を併記する。

## 標準形式

```markdown
# Verification Summary

## Metadata

- Task ID:
- Task:
- Implementer:
- Reviewer:
- Target Commit:
- Status:
- OWNER Approval:

## Changes

公開可能な変更概要

## Verification

| Check | Result |
|---|---|
| Contract | |
| Unit Tests | |
| Security | |
| Documentation | |

## Findings

公開可能な指摘事項

## Limitations

未検証事項・制約

## Conclusion

総合判定とOWNER確認事項
```

作業に応じて検証行を追加・変更してよい。公開前にはサマリー自身の秘密情報チェックも実施する。
