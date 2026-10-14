# Pivot household tasks for Home Assistant

Standalone Home Assistant integration and dashboard card, version 0.3.0.
The Pivot website/backend and Ansible configuration are not included.

## Install

HACS requires a **public GitHub repository**. A private repository can be used
for manual installation and development, but cannot be added to HACS.

For manual testing, copy `custom_components/pivot` into
`/config/custom_components/pivot` and restart Home Assistant. Then add
**Pivot household tasks** under **Settings > Devices & services**.

For HACS, add this repository as a custom repository with category Integration
using `https://github.com/Releah/pivot-home-assistant`.

## Requirements

- Home Assistant 2025.3 or later; installed-HA acceptance is still required.
- A private HTTPS Pivot API endpoint and the readable public CA certificate on HA.
- A Pivot backend supporting the HA task and UI-linking API.
- Firewall access restricted to the Home Assistant installation.

The matching backend/UI-linking changes were developed on the Pivot branch
`feature/ha-hacs-setup`. Creating this integration repository does not deploy
those backend changes. The existing two-task route alone is not sufficient for
UI pairing: private routing must additionally allow authenticated POST requests
for `/api/ha/v1/link/start`, `inspect`, `finish`, `acknowledge`, `cancel` and `unlink`.
Keep Authentik on Pivot's website/browser setup; the private machine API uses
Pivot's installation and per-person credentials instead.

## Configure and link accounts

1. Enter the HTTPS API origin including port, CA file path and Pivot website URL.
2. The wizard shows a generated public key and fingerprint. A freshly signed-in
   Pivot administrator authorizes it under Pivot Settings > Home Assistant.
3. Paste the encrypted delivery JSON into the HA wizard. The private key stays
   in HA memory; decrypted credentials go into owner-only local files, not HA
   configuration entries. Revoke abandoned authorizations if the flow is lost.
4. Existing enrolled installations can import their protected provisioning file.
   Remove their old YAML entry after switching to UI configuration.
5. Each person uses their own signed-in HA account, starts linking from the card,
   and approves the five-minute locator from their own freshly signed-in Pivot
   account with explicit task permissions and expiry.
6. Back in HA, review both account IDs and all permissions, then confirm. HA saves
   the grant before acknowledging delivery. Names/emails never auto-link accounts.

## Task dashboard card

Add `/pivot/pivot-task-card.js` as a JavaScript module dashboard resource, then:

```yaml
type: custom:pivot-task-card
```

Tasks stay scoped to the signed-in person and are fetched on demand. Completion
uses version checks and is not retried automatically after uncertain results.
Refresh to check the result. Delivery acknowledgement can be retried from the
card; each person can revoke their own link. Tasks are not shared HA entities or
recorder history. Protect the HA host and backups: the host owner remains trusted.

The Configure dialog lets you change the API URL, CA certificate file and Pivot
website URL. It shows your current values and preserves account links and
credentials. Example addresses in the setup wizard must be replaced with your
own deployment settings; no household addresses or people are preconfigured.
Removing the integration preserves local credentials for recovery; revoke in
Pivot before permanently removing the protected files.

Development source: Pivot feature branch `feature/ha-hacs-setup`.
The standalone package does not include its Git history, backend or infrastructure.
