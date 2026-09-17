# Merge-sweep workflow permission rollout

## Recommendation

Grant **Workflows: Read and write** to the existing `tauceti-review-bot` App,
then have only the trusted merge-sweep token explicitly request `workflows: write`.
Keep its repository scope at `TauCeti`. No PAT, new secret, or reviewer access to
this token is needed. The sweep runs trusted pinned Python and uses GitHub's
`update-branch` endpoint with `expected_head_sha`; it does not run PR code.
The permission does not bypass review, scope, build, or merge-queue requirements.

On 2026-09-17 the App registration and installation both lacked `workflows`.
Installation ID: **143500674**, organization: **TauCetiProject**.
The failure was [merge sweep run 35168272894](https://github.com/TauCetiProject/TauCeti/actions/runs/35168272894):
updating PR #7077 would incorporate `.github/workflows/ci.yml` changes already on
main. GitHub requires workflow permission for that update even though the PR's
own diff contains only Lean files.

## Changes prepared in code

- TauCetiReview's reusable `merge-sweep.yml` explicitly requests
  `permission-workflows: write`, with contents and pull-requests write.
- TauCeti's caller must pin the reviewed commit in **both** `uses:` and `review_ref:`.
- TauCeti's housekeeping, roadmap-label, and both dependency-update token steps
  receive explicit repository and permission lists. Previously they inherited
  every App permission; land those restrictions **before granting** Workflows.
- The review-error retry cap is preserved. Alert and diagnostic improvements are
  separate changes, and do not enable unlimited reviews.

## Critical manual steps

The App registration and installation approval require an organization owner's
GitHub settings session. A repository workflow's `permissions:` block cannot grant
this App permission, and `gh api` cannot replace the registration approval.

1. Review and merge the prepared TauCetiReview permission PR. Review and merge the
   TauCeti rollout PR, including the restricted tokens and exact sweep pin. If
   squash-merging changes the Review commit ID, update both caller pins to the
   resulting reviewed main commit before merging the caller. The new sweep cannot
   mint its token until steps 2–3 finish; a scheduled run during this short interval
   may fail at token creation.
2. Open [the App permissions settings](https://github.com/organizations/TauCetiProject/settings/apps/tauceti-review-bot/permissions).
   If the direct link does not open, go to **TauCetiProject → Settings → Developer
   settings → GitHub Apps → tauceti-review-bot → Permissions & events**.
   Under **Repository permissions**, set **Workflows → Read and write**, then save.
   Keep the other permissions as they are.
3. Open [the TauCetiProject installation](https://github.com/organizations/TauCetiProject/settings/installations/143500674).
   Review and accept the requested new permission. If GitHub already applied your
   approval while saving, there may be no pending request; verify the API below.
   Do not reinstall the App or rotate its private key.

## Verification after approval

These are operator commands; none prints a secret:

```bash
gh api apps/tauceti-review-bot --jq '.permissions.workflows'
gh api orgs/TauCetiProject/installations \
  --jq '.installations[] | select(.app_slug == "tauceti-review-bot") | .permissions.workflows'
```

Both must print `write`. Then dispatch a **dry run** from main:

```bash
gh workflow run merge-sweep.yml --repo TauCetiProject/TauCeti --ref main -f dry-run=true
gh run list --repo TauCetiProject/TauCeti --workflow merge-sweep.yml --event workflow_dispatch --limit 3
```

Use the new run's numeric ID with one monitor:

```bash
gh run watch RUN_ID --repo TauCetiProject/TauCeti --exit-status --interval 120
gh run view RUN_ID --repo TauCetiProject/TauCeti --json jobs
```

Confirm the mint step succeeds and the sweep completes. A dry run checks token
creation and planned actions; it does **not** prove an actual branch update.
Then dispatch the same workflow with `-f dry-run=false`, monitor its new run once,
and inspect any `update-branch` action. Success is an accepted update without the
workflow-permission 403; subsequent PR CI/review must still run normally.
If no PR needs updating, wait for the next real candidate rather than manufacturing
one or changing an unrelated branch just for a test.

#7077 separately has duplicate A₂ declarations against main. Permission repair
allows recovery to update and retest the branch; it does not repair those Lean
errors or guarantee that PR will merge.

## Rollback

Revert the TauCeti sweep caller's two pins together to the previous reviewed
commit. Keep the explicit token restrictions. Revoke Workflows permission in the
App settings if abandoning this approach. Do not revoke permission while leaving
a deployed sweep that explicitly requests it, because token creation will fail.

## References

- [GitHub: modifying an App registration](https://docs.github.com/en/apps/maintaining-github-apps/modifying-a-github-app-registration)
- [GitHub: create-github-app-token permission inputs](https://github.com/actions/create-github-app-token)
