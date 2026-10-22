# Pivot–Home Assistant lifecycle investigation

Source investigation and disposable tests, 21 October 2026. No live HA logs,
protected provisioning, user credentials, or production task data were inspected.
The affected deployed versions and the cause of the live pre-approval failure
remain unverified. Tests use two synthetic users, not the real household accounts.

## Findings

- **Confirmed stale HA state:** `pivot/link_status` previously treated membership
  in the protected local `members` file as a live link. Pivot revocation could
  leave HA reporting connected indefinitely. Pivot task requests still checked
  permission and denied access. Local write failure after remote unlink could
  produce the same misleading state.
- **Confirmed missing diagnostics:** HA caught API, JSON, transport and timeout
  failures without recording operation or status. Missing system-log entries did
  not mean the API was healthy. Non-JSON proxy errors also hid their HTTP status.
- **Frontend:** guarded `customElements.define` already existed. However repeated
  classic-script evaluation could redeclare top-level classes, and discovery
  metadata accumulated duplicates. The script is now scoped and discovery is
  idempotent. Previously loaded older scripts require a browser reload. This does
  not prove which script generated the observed registration error.
- **Retry controls:** multiple failing action buttons could all become “Retry”
  and append repeated errors. Action labels now remain distinct, with one error
  message per rendered body. The refresh failure retains its single Retry action.
- **Not established:** a live TLS failure, proxy rejection, invalid installation,
  invalid grant, or backend database problem. These remain separate possibilities,
  now distinguishable by diagnostics. Browser HTTPS/website validation can fail
  before HA sends `link/start`, so no Pivot approval or HA API error would exist.

## Request and durable-state sequence

All HA commands resolve the live authenticated HA user; the browser cannot supply
an HA subject. API requests use the protected installation credential. Task calls
also require that person's link and grant credential. Requests verify configured
TLS trust, forbid redirects, have bounded replies and a 15-second timeout.

| Operation | Actual request and response | Local lifecycle |
| --- | --- | --- |
| Connection probe | `GET /api/ha/v1/tasks`, no authority; expected `401 ha_installation_required` | Tests the configured API/TLS path, not an enrolled account or task permission. |
| Start | `POST /api/ha/v1/link/start`, `{}` or state digest and HTTPS return URL; `200` pairing ID, private redemption proof, locator and optional encrypted return context | Saves subject-scoped pending state before returning approval navigation to the browser. Protected proof never reaches the browser. An interrupted previous attempt is cancelled before replacement. |
| Approve | Pivot browser `POST /api/ha/setup/approve`, session, CSRF, locator, selected policy and optional authenticated return context | Pivot alone records the approving user and permission scope. Opening a page alone never grants access. |
| Inspect | `POST /api/ha/v1/link/inspect`, private pairing proof; `200` pairing and effective delivery state | Pending HA state is only a recovery aid. Invalid/stale proof can be cancelled through installation plus live-subject authority. |
| Finish | `POST /api/ha/v1/link/finish`, proof plus explicit confirmation or authenticated browser result; `200` one-time credential | Persists redemption-started before the request, saves issued credential, then fsyncs the local member binding before ACK. A lost finish response cannot trigger a second redemption; cancel/restart is required. |
| Acknowledge | `POST /api/ha/v1/link/acknowledge`, proof, consent ID and received credential; `200` acknowledgement | Pivot enables delivered link only after receipt, within its delivery deadline. HA removes pending state after ACK. Lost ACK can be retried from protected saved issuance, without redeeming again. |
| Reconcile | New `POST /api/ha/v1/link/status`, link ID and credential; `200` fixed status | Pivot validates installation, subject, credential, user eligibility, grant/consent consistency, expiry, revocation and delivery. Only active reports linked. Invalid/ineligible bindings are cancelled with authenticated subject authority before local cleanup, permitting a fresh approval. Explicit terminal status removes this subject's member/pending entries under the same lock as linking. Network/HTTP/invalid-response failures preserve recovery state and never report connected. |
| Retrieve | `GET /api/ha/v1/tasks`; `200` permitted tasks and account name | Every call independently validates authority in Pivot; UI state grants nothing. A delegated denial triggers reconciliation, not unconditional credential deletion. |
| Complete | `POST /api/ha/v1/tasks/<uuid>/complete`, `If-Match`; `200` confirmed result | Read and complete permissions remain independent. A denied completion never clears a still-valid read link. Timeout may follow a committed write, so no blind automatic completion retry. |
| Revoke in Pivot | `POST /api/ha/setup/unlink`, authenticated owner and link ID | Pivot revokes link/grant. HA reconciles on refresh, task denial, or the connected card's 30-second refresh. Offline HA cannot instantly learn remote revocation. |
| Unlink in HA | `POST /api/ha/v1/link/unlink`, this subject's link ID; `200` idempotent confirmation | Remote revoke precedes local removal. Lost response or failed local persistence is corrected by subsequent authoritative status. Other people remain untouched. |
| Cancel | `POST /api/ha/v1/link/cancel`, empty object for subject recovery | Revokes only the authenticated subject's outstanding attempts/grants before removing that person's local state. |

A pending record is not an active connection. An undelivered link with no recovery
record offers Disconnect before restarting rather than incorrectly claiming Connected.

## Diagnostics and deployment order

Ship the matching Pivot backend first: an older backend rejects the new status
operation; HA fails closed and preserves local state in that case. Then update HA,
reload its integration and reload browser tabs so older registered cards are gone.
No database migration or permission relaxation is required. No deployment was made.

HA warning logs identify operation, numeric HTTP status when available, fixed
allowlisted API code, or exception class. Successful request diagnostics are DEBUG
under `custom_components.pivot.api`; failures are WARNING without requiring debug.
The initial probe and local setup/status/link failures also log safe operation
names and exception classes. Pivot logs linking/task HTTP failures with the fixed
operation, response status and allowlisted code. Browser preflight failures log
only allowlisted reason codes in the console. No raw error messages or tracebacks,
headers, URLs, subject IDs, grants, locator/state/return tokens, or task content
are logged by these diagnostics.

Interpret the next reproduced failure by the first failed operation:

- Browser `secure_return_required` / `secure_website_required`: approval navigation
  failed before an API request. Use the existing trusted HTTPS entry points.
- No HTTP status with a certificate/connector/timeout exception: request/response
  did not finish; distinguish trust, DNS/connectivity and timeout by exception class.
- HTTP 400 `ha_request_invalid`: protocol or proxy headers/request rejected.
- HTTP 401: installation authentication failed; this is not a person's grant.
- HTTP 403 with a pairing or delegated code: Pivot rejected proof/permission;
  inspect authoritative status before replacing state.
- HTTP 409 `delivery_unavailable`: delivery deadline expired; cancel and reconnect.
- HTTP 429: rate budget/concurrency; repeated retry is not a connectivity fix.
- HTTP 5xx or non-JSON proxy response: API/backend/proxy failure, with status retained.

For a live reproduction record only deployed integration/frontend version, failed
operation, status/code or exception class, and whether the other person still works.
Do not share provisioning files, browser return fragments, request headers, or task
response bodies. Real-account verification requires each person's own approval.
