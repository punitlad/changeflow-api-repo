# changeflow

Your API → opens a standardized PR in the external service's repo → gets it merged → approves the
resulting pipeline → monitors it to a conclusion.

```
POST /team-onboardings {team, requested_by}        202 + job id
        │
        ▼  (background task)
1. open_onboarding_pr     branch onboard/<team>, commit adds {"team": "<team>"} to the JSON array, open PR
2. MergeStrategy          native auto-merge | ruleset bypass | their workflow merges   → wait for merge SHA
3. find_run               workflow run whose head_sha == merge SHA (event=push)
4. approve_pending        approve environment gate when status == "waiting"
5. monitor                poll run → success | failure (+ failed job/step names)
        │
GET /team-onboardings/{id}   phase, pr_url, run_url, error, failed_jobs
```

## Layout

| File | Responsibility |
|---|---|
| `config.py` | Env-driven settings (`CHANGEFLOW_*`) incl. merge/approval mode |
| `github_client.py` | GitHub App JWT → installation token (cached), REST + GraphQL |
| `change_request.py` | Idempotent JSON append, branch, commit, PR |
| `merge_strategies.py` | The three merge options + `wait_until_merged` |
| `pipeline.py` | Run discovery, approval, monitoring |
| `orchestrator.py` | Job state machine + in-memory store |
| `api.py` | FastAPI endpoints |

## Merge options: pick one with `CHANGEFLOW_MERGE_MODE`

All three were validated end-to-end against live test repos (see `../test-repos/`). Default is
**`ruleset_bypass`** — fastest merge (no wait on checks), and the trust grant is a one-time
ruleset config on their side rather than an ongoing workflow they have to maintain.

| Mode | How it works | Ask of the target repo | Watch out for |
|---|---|---|---|
| `native_auto_merge` | GraphQL `enablePullRequestAutoMerge` | "Allow auto-merge" on; ruleset with required checks | An App can't approve its own PR, so this fails if a review is required |
| `ruleset_bypass` (default) | `PUT /pulls/{n}/merge` | Add our App to the ruleset bypass list | Largest trust grant; use "pull requests only" bypass if available |
| `workflow_gated` | Their `pull_request_target` workflow merges if PR author is `<app-slug>[bot]` | Add the allow-list workflow | Trust logic is theirs, usually the easiest approval; make sure they check the *author*, not a label or title. **Also:** if their merge step uses the default `GITHUB_TOKEN`, the merge push won't trigger their deploy workflow (GitHub's loop-prevention) — they need a PAT there instead. Found this the hard way testing `test-repos/workflow-gated/`. |

The "who opens this" gate is identity-based in all three: it works because the PR is authored by
**our App's bot identity**, not by a human, so they can scope trust to exactly that actor.

## Approval: the part most likely to need a conversation with them

1. **GitHub Apps can't be environment required reviewers** (only users/teams). So
   `approval_mode=pending_deployments` needs a **machine user PAT** (`CHANGEFLOW_APPROVER_TOKEN`) that
   is listed as a reviewer. Endpoint: `POST /repos/{o}/{r}/actions/runs/{id}/pending_deployments`.
2. **"Prevent self-review"**: if enabled, the identity that triggered the deployment can't approve it.
   The trigger is whoever merged. With `ruleset_bypass` the App merges and the machine user approves, so
   they differ: fine. If you ever merge *as* the machine user, this will 422.
3. **Cleaner alternative: `approval_mode=protection_rule`**: register our App as a *custom deployment
   protection rule*. GitHub sends a `deployment_protection_rule` webhook to us and we answer with
   `approve_protection_rule()`. No PAT, but needs a webhook endpoint (not wired in `api.py` yet) and
   their environment configured to use it.

## Things I assumed: verify against their repo

- Pipeline is `deploy.yml` triggered on `push` to `main` (so the merge commit SHA identifies the run).
  If it's `workflow_run`, `pull_request: closed`, or a `workflow_dispatch`, `find_run` changes.
- JSON shape is `{"teams": [{"team": "x"}]}` at `teams.json`. Set `CHANGEFLOW_JSON_ARRAY_KEY=""` for a root array.
- Squash merge, which changes the SHA; we use `merge_commit_sha` from the PR, which is correct for all methods.

## Required GitHub App permissions (on the target repo)

Contents: write · Pull requests: write · Actions: read · Metadata: read. (Add Deployments: write
only for the protection-rule mode.) The App must be installed on the target repo/org by them.

## Not done yet (deliberate)

- Durable job store (in-memory now; background task dies with the pod)
- AuthN/Z on your own endpoints, and mapping caller → `requested_by`
- Webhook receiver (would replace polling and enable protection-rule approvals)
- Retries/backoff and rate-limit handling (`X-RateLimit-Remaining`, secondary limits)
- Handling a PR that needs conflict resolution if two teams onboard concurrently (the contents
  API commit will 409 on a stale blob SHA; a simple re-fetch-and-retry fixes it)

## Run

```bash
pip install -e '.[dev]' && pytest
export CHANGEFLOW_APP_ID=... CHANGEFLOW_APP_PRIVATE_KEY="$(cat key.pem)" CHANGEFLOW_INSTALLATION_ID=... \
       CHANGEFLOW_TARGET_OWNER=... CHANGEFLOW_TARGET_REPO=... CHANGEFLOW_APPROVER_TOKEN=...
uvicorn changeflow.api:app
```
