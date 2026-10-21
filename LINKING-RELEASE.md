# Pivot / Home Assistant 0.5.1 candidate

Baseline: existing `feature/ha-account-linking` 0.5.0 implementation, not the
standalone repository's older main branch. No deployment, infrastructure changes,
account resets or migration changes are part of this work.

## Confirmed code defects

- The HA button helper disabled actions permanently after errors, so Cancel and
  recovery actions stopped working until the view was recreated.
- The normal waiting screen exposed manual codes, technical delivery controls,
  explicit IDs and policy JSON. Its “Open Pivot” URL omitted automatic return
  state/context, leaving that route dependent on manual confirmation.
- Acknowledgement recovery depended on the automatic/manual flag, and the card
  did not check a saved delivery's remote revocation status before retrying ACK.
  The manager now passes through link status; the card resumes saved deliveries,
  or offers fresh approval when the delivery has expired/revoked.
- Cleanup/restart depended on the old local redemption proof. An invalid or stale
  proof could prevent cleanup indefinitely. The authenticated empty-body Cancel
  now invokes the existing subject-scoped revocation operation. No browser may
  choose another HA subject; installation authentication remains mandatory.
- Backend linking used one 30/minute request budget for the entire household,
  including failed requests. It now budgets each authenticated installation,
  subject and operation separately, preserving concurrency and input limits.
- Malformed manual codes reached backend validation and received confusing
  generic failures. Pivot validates the entire code and keeps the field editable.

These are source-confirmed and covered by regression tests. They do not establish
which error occurred on the deployed HA host. No real HA logs were supplied.
Network/proxy routing, installed module caching, protected-file permissions,
timeouts or an actual ACK deadline expiry remain possible deployed causes.

## Result and security

HA shows Connect to Pivot, a waiting state with Cancel, Connected as the approved
Pivot name and tasks, or a plain-English failure with Retry. Codes and explicit
manual confirmation stay under Advanced. Missing browser-return state starts a
fresh attempt rather than silently downgrading an automatic attempt to manual.

Pivot incoming approval shows the signed-in name and task consent choices. No
programme is preselected. Approval returns to HA automatically; the success text
explains that HA finishes connecting. Normal account settings show personal access
and revocation. Installer keys and encrypted provisioning delivery are confined to
administrator-only Advanced installation administration.

One-time installation authority and individual consent remain distinct. Live HA
identity, installation credentials, Pivot session/Origin/CSRF, authenticated return
state and result, single-use redemption, durable credential write before ACK,
60-second unacknowledged-delivery revocation, task ownership and grants are retained.
Task completion is never automatically repeated after an uncertain response.

## Verification

- Full `bash tests/check.sh` passed in a disposable Node 24 / PostgreSQL 18
  container: 147 browser/UI tests, 71 backend tests, all Python suites, source
  security guards, JavaScript/Python/shell syntax and Git whitespace checks.
- The shipped card and Pivot UI run against actual HTTP/PostgreSQL and the shipped
  Python manager: local and OIDC users each Connect → Allow → Connected, cancel
  an attempt, obtain a fresh approval, reject a different HA user's return, and
  preserve an existing link, and fetch real permitted tasks with the live Pivot
  account name. A deliberately lost ACK response recovers without
  credential replay. Backend tests cover genuine expired records, ACK deadline
  revocation, rejected permissions and isolated request budgets.
- Standalone HA checks: 12 card regressions, six manager regressions, dashboard and
  configuration-retry tests. Cancellation/approval races are covered, and the complete PostgreSQL
  journey passes with the final code.
- Actual installed HA/Companion browser behaviour and the household proxy are not
  tested here. The DOM harness is synthetic, not a running Home Assistant instance.
  PostgreSQL 16 and an actual application-container smoke deployment were not run
  during this change; no result is claimed for them.

The disposable cached test image initially lacked Python, then the existing
Python enrollment-test cryptography package. Those environment failures were
resolved in the test image only; the final full suite passes. No production
runtime dependency or infrastructure configuration was added.

## Release instructions (when separately authorised)

1. Review/test both application and HACS changes against the matching 0.5.0 base.
2. Release the Pivot backend/frontend first: the HA update requires the new
   subject-scoped Cancel contract. Use the normal application release process;
   no infrastructure edits or new migration are required by this patch.
3. Publish the HACS 0.5.1 candidate only after approval, update HA and restart it.
   Reload its dashboard so the `v=0.5.1` card module loads; reopen Pivot to load
   its updated service-worker shell.
4. Preserve installation credentials, existing account links and protected files.
   Existing installations do not need new installer keys or authorisation. For a
   failed pending attempt, use Cancel or Retry; do not delete protected files.
5. On installed HA, verify Connect → Allow → named Connected → permitted tasks
   with two synthetic users. Also cancel before approval, retry after expiry and
   interrupt the return/ACK. Confirm neither person's attempt affects the other.
   Check the actual HTTPS return route and HTTP task proxy without logging codes,
   credentials, return fragments or task contents.

Automatic return requires HTTPS in both browser applications; HA HTTP users can
explicitly use Advanced manual connection. Lost redemption responses require fresh
consent, preserving the single-use credential boundary. Cancel during an outage
reports failure and remains usable; remote revocation must succeed before the local
delivery is discarded. Account names come from the authenticated task response, so existing 0.5.0
links show the correct Pivot account without relinking or changing protected-file formats.

## 0.5.2 pending-request recovery

The sidebar previously rendered Waiting from local file membership before remote
inspection. Inspection failure then appended Failed to the same screen. It also
could not reconstruct automatic approval URLs: only the browser state's digest
was persisted. The waiting card provided no way to reopen the original approval.

The card now inspects before rendering Waiting and replaces that view on errors.
Ended, malformed, inaccessible, and uncertain attempts offer Connect to Pivot.
Fresh automatic requests persist their browser state in the existing protected
pending file. Inspection returns the approval locator/state/context only to the
live requesting HA subject, after checking remote pending status and validating
the unconsumed, unexpired local binding. Reopening does not consume the binding
or create a replacement request. Legacy requests without resumable state offer a
fresh connection. Restart still revokes the previous subject-scoped request before
removing local state, including any uncertain grant delivery.

The integration version is 0.5.2. The registered frontend URL uses the shipped
asset's SHA-256 prefix instead of a manually maintained version. The authenticated
`pivot/link_status` response includes `integration_version` and `frontend_version`.
After updating and restarting HA, compare those fields with the loaded module's
`/pivot/pivot-task-card.js?v=<frontend_version>` request in browser developer tools.
An already open page must be reloaded to replace its registered custom element.
Do not copy approval fragments or protected pending-file contents into logs.

Local verification: card regressions, all Python unittest suites, and whitespace
checks pass. Installed HA files and served assets were not accessible from this
workspace; matching deployed versions and live pending state remain unverified.
