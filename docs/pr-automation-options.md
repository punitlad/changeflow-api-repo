# API-Driven PR Automation: Merge Mode Options and Recommendation

## Context

`changeflow` is an API that, on request, opens a pull request against a target repo, gets it
merged, and approves the deployment pipeline that merge triggers. The target repos are owned and
maintained by partner teams, not by us — so any approach we propose has to layer on top of a
partner team's existing branch-protection and deployment setup without changing how their human
contributors already work.

**Requirements:**
1. The API can open a PR and have it auto-merge once whatever validation the target repo requires
   has passed.
2. The API can approve the deployment pipeline that its own automated merge triggers (pipelines
   gated behind an environment/manual-approval step shouldn't require a human to click anything
   for an automated change).
3. **The existing human contributor flow must be unaffected.** Whatever we ask a partner team to
   add should be additive, not a replacement of their current protections.

We built and live-tested four candidate approaches against disposable repos that mirror a typical
partner team's setup (a branch ruleset requiring a PR + a status check, and a `production`
environment with a required reviewer gating deployment).

## The four approaches

| Approach | Mechanism | What we ask the target team for |
|---|---|---|
| **Native auto-merge** | We enable GitHub's built-in `enablePullRequestAutoMerge` on our PR; GitHub itself merges once their required check passes — the same mechanism any human's PR with auto-merge enabled would use | "Allow auto-merge" turned on for the repo. Nothing else changes about their ruleset. |
| **Ruleset bypass** | Our identity is added to their branch ruleset's bypass list; we merge directly via the REST API with no wait on checks | Add our App as a bypass actor, scoped to "pull requests only." This is the largest trust grant of the four. |
| **Workflow-gated** | Nothing on our side — their own GitHub Actions workflow recognizes our PR by author and merges it themselves, using a credential they control | They write and maintain a merge-automation workflow that allow-lists our bot's identity by **author** (not a label, which is spoofable) |
| **Scoped validation** *(not a merge mechanism — an add-on to either of the above)* | The required check itself runs different rules depending on who opened the PR — e.g. a human gets a naming-convention lint, our automated PR gets a stricter "blast radius" check confirming the diff only touches what it's supposed to | No new ask beyond whichever merge mechanism it's paired with — this only changes what their existing check verifies |

All four preserve requirement 3 by inheriting the target repo's existing ruleset and required
check rather than replacing it — a human's PR still has to pass the same gate it always did.

## What we validated

We ran all four end-to-end against live GitHub repos, including deliberately exercising the human
path (not just our own automated PRs) to confirm nothing regressed for a normal contributor.

- **Native auto-merge** and **ruleset bypass**: validated cleanly, no surprises.
- **Workflow-gated**: our first implementation had a gap — the target repo had no required check
  at all, meaning a human merging there actually had *less* protection than before, not just an
  API-specific bypass. We restored the same required check and ruleset the other modes rely on,
  then re-validated. Along the way we also found and fixed two bugs in the custom merge workflow
  itself (a missing repository context, and a GitHub identity format mismatch that silently
  prevented merges without ever raising an error). Both are the kind of issue a partner team
  writing their own version of this workflow should expect to hit and budget time for.
- **Scoped validation**: validated in both directions — our automated PR correctly ran the
  stricter machine-only check, and a manually-opened PR with an invalid value was correctly
  blocked by the normal required check and couldn't be merged without an administrative override.

## Recommendation

Ranked by trust ask, latency, and — now that we've run them live — operational reliability:

1. **Native auto-merge — our default recommendation.** Smallest possible ask of a partner team
   (just "turn on auto-merge"), reuses GitHub's own merge mechanism rather than custom workflow
   code, and in testing this was the only approach with zero implementation bugs — because
   there's no custom workflow to get wrong. The one hard limitation: it can't work if the target
   repo's ruleset requires an approving review, since an automated identity can't approve its own
   PR.
2. **Ruleset bypass — best for partner teams willing to extend more trust in exchange for speed.**
   Fastest option and requires no custom workflow maintenance on their side, but it is the largest
   trust grant and the one most likely to need a security review before a partner team agrees to
   it.
3. **Workflow-gated — keep as a fallback, not a first choice.** It's often pitched as the
   "lowest-trust" option because the target team's own code does the merging, but that's also its
   weakness: it hands them a non-trivial piece of automation to build and keep correct, and we
   found real bugs in our own first attempt at exactly this pattern. Recommend this only when a
   partner team genuinely cannot enable auto-merge or add a bypass actor.
4. **Scoped validation — an enhancement to pair with #1 or #2, not a standalone option.** Worth
   proposing whenever a partner team wants the automated path held to different scrutiny than a
   human's arbitrary diff, independent of which merge mechanism is chosen.

## Open items

- **Pipeline approval currently relies on a human-equivalent credential** acting as a required
  reviewer on the deployment environment, since GitHub Apps can't be environment reviewers
  directly. A cleaner, credential-free approval path (our App responding to a deployment
  protection rule webhook) is a known follow-up, deliberately out of scope for this round.
- Each option's required ask (auto-merge toggle, bypass actor, or a workflow + secret) should be
  confirmed directly with each partner team before we commit to a repo-by-repo rollout plan.
