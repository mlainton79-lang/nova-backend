# Android repo status — 2026-07-23

## Android repo `git status --short` (verbatim, pre-push-test)

```
 M gradle.properties
```

Tree was **dirty**: a single unstaged modification to `gradle.properties`. No untracked files. The push-test commit only staged the new `docs/reviews/PUSH-TEST.md`; the `gradle.properties` change was left unstaged and did not go up.

Last commit before the test: `ac829d5 feat(daily): add Android daily loop screen`.

## Push test result

Push **succeeded**. Origin was reset to `https://github.com/mlainton79-lang/nova-android.git` and `gh auth setup-git` was run. The test commit `f734ac8 docs: push auth test` was pushed to `master`:

```
remote: Bypassed rule violations for refs/heads/master:
remote:
remote: - Required status check "build" is expected.
remote:
To https://github.com/mlainton79-lang/nova-android.git
   ac829d5..f734ac8  master -> master
```

Note: branch protection expected a `build` status check; the push bypassed it (admin/owner bypass on this account). Not an error — the ref updated.

Push auth is **restored**. The 17 Jul PAT revocation is no longer blocking the android repo.

## `gh auth status` summary (tokens redacted)

- Host: `github.com`
- Account: `mlainton79-lang` (active)
- Config: `/root/.config/gh/hosts.yml`
- Git protocol: `https`
- Token scopes: `gist`, `read:org`, `repo`, `workflow`

Same account and scope set used by this backend repo, which is why push works from both now.
