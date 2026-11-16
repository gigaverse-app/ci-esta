# Evidence discovery: what to read and when to stop

This is the maintainer map for the GitHub evidence boundary. [Selection policy](test-selection-policy.md) owns what work is required; discovery can prove that work already ran, never redefine it.

## One live snapshot, explicit source decisions

`actions/resolve-incremental-pr-base/search.cjs` owns the invocation's observation time, API data, pagination completeness, request counts, cached failures and job/receipt refusal barriers. PR lookup, check-index recovery, merged/release lookup and trusted push lookup use that owner. It does not persist across workflow runs. The lane action passes one snapshot through every source and lane.

`resolve.cjs` owns PR/ancestor eligibility. Its `receiptEvidence` is the single receipt verdict used by PR and default-branch proof. `trusted.cjs` supplies the default-branch source, not another definition of a successful receipt.

| Scenario | Useful evidence and query scope | Stop / recovery rule |
| --- | --- | --- |
| First PR execution | This workflow and branch since this PR opened, when its creation time is available | Exclude an older branch incarnation without fetching its jobs |
| Same-input lane | Fresh, owned, completed runs in completion order; the lane's successful receipt | Stop on proof; never hydrate older owners speculatively |
| Long PR | Complete run metadata, shared by every lane; jobs only for eligible candidates | No ten-candidate cutoff. Page two may contain proof or a newer rerun failure |
| Recreated merge or normalized pin | The same input receipt can appear on another head | Do not restrict receipt search to the current SHA |
| Incomplete indexed chronology | No safe statement about newer contradictions | Execute fresh; do not bypass the incomplete index through a fallback |
| Listing lag, receipt mode | Current head's check records; only records naming the requested job lead to run-detail reads | Validate ownership, attempt and receipt; unrelated named checks cost no run lookup |
| Listing lag, incremental scan | First-parent heads until proof, an already-indexed completed run, PR boundary, or the existing bounded recovery horizon | Retain rapid-push/cancelled-parent recovery; this is a compatibility fallback, not primary search policy |
| Validation baseline | Newest owned validation result and its tested merge | Do not walk past failed/unknown validation to narrow the scan |
| Independent pytest | A run-bound status, or planner/test completion; same-head failures revoke reuse | Failed shard evidence proposes a candidate only; downstream failure-artifact validation remains mandatory |
| Default-branch proof | Recent push runs from this workflow; matching first-attempt receipt | Only after finding proof, inspect older-created metadata for newer completions/reruns that could revoke it; never hydrate old jobs merely to enumerate history |
| Earlier PR failure, later default pass | Compare source completion times for the same job/receipt | A newer trusted pass can supersede a known failure; an older pass cannot. Unknown chronology cannot be superseded |
| Explicit rerun | Attempt identity in run metadata and returned jobs | Reruns revoke but never issue reusable proof; an attempt race retains execution |
| 403/429 on discovery | No further optional read can establish a complete snapshot | Stop requests for the invocation, including other lanes/sources; execute required work |
| Other API uncertainty | Its scope and position in chronology | Unknown newer receipt/ownership blocks older proof. Older unknown runs are not read after newer proof succeeds |

Creation and completion times differ. A PR's opening time excludes an older incarnation of its branch. A freshness cutoff on **creation** cannot exclude all contradictions: an older run can be rerun or finish recently. The trusted source defers its older-metadata query until there is useful proof, and fetches jobs only for results newer than that candidate.

GitHub [limits filtered workflow searches to 1,000 results](https://docs.github.com/en/rest/actions/workflow-runs#list-workflow-runs-for-a-workflow). When the reported total exceeds that limit, more pages cannot establish completeness. Stop immediately and execute fresh. Repeated pages, missing pages and mismatched totals also cannot prove completeness. This is a service limit, not an arbitrary candidate truncation.

The bounded first-parent recovery horizon remains a separate last-resort limit: it prevents a missing index from turning into an API scan of the whole Git graph. The normal path searches the complete scoped run index without that limit.

## Data reuse and auditability

Cache raw reads, including failures, for one invocation. Share jobs across owner recovery, lane receipts and measurements; share status, commit and comparison reads across lanes. Never share a positive verdict between lanes. Refusals carry the job/receipt and, when known, the contradicting run; they are not global vetoes on unrelated lanes. Missing chronology is stronger than a known temporal barrier.

Do not persist proof in an Actions cache. Completed run metadata can change on a rerun, and a cache written by PR code is not an authenticated GitHub result. Immutable content-addressed Git blobs are a different contract and can be cached.

`Evidence discovery` log records expose cumulative actual request counts by endpoint class, stop state and refusal reasons. They contain no tokens. Compare counts for the whole invocation rather than adding cumulative per-lane snapshots. The public action records a final snapshot after default-branch fallback too.

### Checkout objects before Git API reads

`resolve-lane-evidence/inputs.cjs` owns immutable object acquisition for lane and
security inventory identities. It first asks the stdlib-only `local_git.py`
boundary to read the requested SHA from `GITHUB_WORKSPACE`. Python runs in
isolated mode. Git replacement refs and partial-clone lazy fetches are disabled;
the reader verifies the object's SHA before returning the API-compatible shape.
Working files, including uncommitted lockfile edits, never become evidence.

This changes transport only: input paths, pin normalization, receipt format and
proof decisions stay unchanged. A missing checkout, Python runtime or object
falls back to the existing API call for that object. Existing full checkouts
avoid commit/tree/blob calls; shallow checkouts still save all available reads.
The dependency repository's pinned commit generally remains one API read per
identity calculation because its object is absent from the consumer checkout.
No history fetch or persistent proof cache is added.

## Optional reporting is a different decision

The reporter does not authorize skips. Sampling belongs to `ci_observability.action`, using the canonical report/reference models:

- No savings-reference search when every file ran: there is no skipped work to price.
- First-attempt latest jobs also constitute billing history. Fetch separate history only for reruns or reports of an older attempt.
- Historical pricing uses a recent artifact page, excludes the current run and forks, and seeks five comparable samples within a small optional download budget. Missing samples leave estimates unknown; they never authorize validation.
- Individual malformed/incompatible samples can be replaced. A 403/429 ends sampling after the in-flight batch instead of scheduling another batch.

The pricing sample budget deliberately differs from proof discovery. Dropping a pricing sample affects an estimate; dropping a newer contradictory result could incorrectly skip required work. Do not share a truncation rule between them.
