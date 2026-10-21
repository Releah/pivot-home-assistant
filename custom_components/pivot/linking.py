"""Per-person automatic linking, durable delivery and legacy manual fallback."""
import asyncio
import secrets
import time
from urllib.parse import urlsplit
from .pairing_return import create_binding, consume_binding, _digest
from pathlib import Path
from .provisioning import load_provisioning, load_private_json, save_private_json


class LinkRequestError(ValueError):
    """A fixed upstream code, never raw response text or credentials."""
    def __init__(self, code):
        super().__init__('link_request_failed')
        self.code = code


class LinkManager:
    def __init__(self, path, executor, request):
        self.path = path
        self.pending_path = str(Path(path).with_name('pending-links.json'))
        self.executor = executor
        self.request = request
        self.lock = asyncio.Lock()

    async def pending(self):
        try:
            return await self.executor(load_private_json, self.pending_path)
        except FileNotFoundError:
            return {}

    async def run(self, subject, action, confirmation=None, browser_return=None):
        async with self.lock:
            settings = await self.executor(load_provisioning, self.path)
            if not settings['installation_credential']:
                raise ValueError('installation_required')
            pending = await self.pending()
            async def call(operation, body):
                return await self.request(settings, subject, operation, body)
            if action in ('start', 'start_return'):
                automatic = action == 'start_return'
                if automatic:
                    if (not isinstance(browser_return, dict) or set(browser_return) != {'returnUrl'}
                            or not isinstance(browser_return['returnUrl'], str)):
                        raise ValueError('invalid_return_url')
                    url = urlsplit(browser_return['returnUrl'])
                    if (url.scheme != 'https' or not url.netloc or url.username or url.password
                            or url.path != '/pivot-tasks/tasks' or url.query or url.fragment
                            or len(browser_return['returnUrl']) > 1024):
                        raise ValueError('invalid_return_url')
                    state = secrets.token_urlsafe(32)
                previous = pending.get(subject)
                if subject in settings['members'] and not previous:
                    raise ValueError('link_exists')
                if previous:
                    # Revoke uncertain deliveries before replacement. Never discard
                    # a protected credential while its remote grant could be active.
                    await call('cancel', {})
                    pending.pop(subject)
                    settings['members'].pop(subject, None)
                    await self.executor(save_private_json, self.path, settings)
                    await self.executor(save_private_json, self.pending_path, pending)
                value = await call('start', {'stateDigest':_digest(state), 'returnUrl':browser_return['returnUrl']}) if automatic else await call('start', {})
                expected = {'pairingId','redemptionProof','locator'} | ({'expiresAt','returnContext'} if automatic else set())
                if set(value) != expected:
                    raise ValueError('invalid_response')
                if automatic:
                    now = time.time()
                    _, binding = create_binding(subject, value['pairingId'], min(value['expiresAt']/1000, now+86400), now, state=state)
                    value['browser_return'] = binding
                    # Protected, subject-scoped storage allows reopening approval.
                    value['approval_state'] = state
                pending[subject] = value
                try:
                    await self.executor(save_private_json, self.pending_path, pending)
                except (OSError, ValueError):
                    await call('cancel', {'pairingId':value['pairingId'], 'redemptionProof':value['redemptionProof']})
                    raise
                # No grant or redemption proof reaches the browser.
                return ({'locator':value['locator'], 'state':state, 'returnContext':value['returnContext']}
                        if automatic else {'locator':value['locator']})
            if action == 'unlink':
                binding = settings['members'].get(subject)
                if not binding:
                    raise ValueError('pairing_required')
                await call('unlink', {'linkId':binding['link_id']})
                del settings['members'][subject]
                await self.executor(save_private_json, self.path, settings)
                pending.pop(subject, None)
                await self.executor(save_private_json, self.pending_path, pending)
                return {'unlinked':True}
            value = pending.get(subject)
            if not value and action == 'cancel':
                # Approval may have finished while the waiting card's Cancel
                # request was in flight. Honour that person's cancellation.
                if subject in settings['members']:
                    await call('cancel', {})
                    settings['members'].pop(subject)
                    await self.executor(save_private_json, self.path, settings)
                return {'cancelled':True}
            if not value:
                raise ValueError('pairing_required')
            if action == 'cancel':
                await call('cancel', {})
                pending.pop(subject)
                settings['members'].pop(subject, None)
                await self.executor(save_private_json, self.path, settings)
                await self.executor(save_private_json, self.pending_path, pending)
                return {'cancelled':True}
            if action == 'inspect' and not all(isinstance(value.get(key), str) and value[key] for key in ('pairingId', 'redemptionProof', 'locator')):
                return {'pairing':{'status':'unavailable'}, 'awaiting_delivery':False}
            proof = {'pairingId':value['pairingId'], 'redemptionProof':value['redemptionProof']}
            if action == 'inspect':
                try:
                    result = await call('inspect', proof)
                except LinkRequestError as error:
                    if error.code not in ('pairing_access_required', 'pairing_unavailable'):
                        raise
                    return {'pairing':{'status':'unavailable'}, 'awaiting_delivery':False}

                approval = None
                if result['pairing']['status'] == 'pending' and 'browser_return' in value and not value.get('redemption_started'):
                    try:
                        # Validate a copy: reopening must not consume the return.
                        consume_binding(dict(value['browser_return']), subject=subject, pairing_id=value['pairingId'],
                                        state=value.get('approval_state'), now=time.time())
                        approval = {'locator':value['locator'], 'state':value['approval_state'], 'returnContext':value['returnContext']}
                    except (ValueError, TypeError, KeyError):
                        return {'pairing':{'status':'unavailable'}, 'awaiting_delivery':False}

                # An explicit HA-person confirmation must match this server inspection.
                return {'approval':approval, 'pairing':result['pairing'], 'approved_user_name':result.get('approvedUserName'),
                        'link':result.get('link'), 'awaiting_delivery': 'issued' in value, 'automatic_delivery':'browser_return' in value, 'delivery_uncertain':bool(value.get('redemption_started')) and 'issued' not in value}
            if action not in ('finish','finish_return','acknowledge'):
                raise ValueError('invalid_action')
            if action in ('finish','finish_return'):
                automatic = action == 'finish_return'
                if not automatic and (not isinstance(confirmation, dict) or set(confirmation) != {'userId','consentId'}):
                    raise ValueError('confirmation_required')
                if 'issued' in value:
                    raise ValueError('acknowledgement_required')
                if value.get('redemption_started'):
                    # A timeout or crash may have followed a committed redemption.
                    # Never request another credential after an uncertain response.
                    raise ValueError('delivery_uncertain_restart_required')
                if automatic:
                    if (not isinstance(browser_return, dict) or set(browser_return) != {'pairingId','state','result'}
                            or browser_return['pairingId'] != value['pairingId']
                            or not isinstance(browser_return['result'], str) or len(browser_return['result']) > 3072):
                        raise ValueError('invalid_return_result')
                    # Local binding is a prerequisite, never proof of Pivot approval.
                    # The remote finish operation verifies the authenticated receipt and redeems
                    # atomically; failures leave a consumed attempt for cancellation.
                    consume_binding(value.get('browser_return'), subject=subject, pairing_id=value['pairingId'],
                                    state=browser_return['state'], now=time.time())
                value['redemption_started'] = True
                await self.executor(save_private_json, self.pending_path, pending)
                issued = (await call('finish', dict(proof, state=browser_return['state'], result=browser_return['result']))
                          if automatic else await call('finish', dict(proof, confirmation=confirmation)))
                value['issued'] = issued
                await self.executor(save_private_json, self.pending_path, pending)
            else:
                if 'issued' not in value:
                    raise ValueError('pairing_required')
                issued = value['issued']
            # Write and fsync the grant before acknowledging delivery remotely.
            settings['members'][subject] = {'link_id':issued['linkId'], 'credential':issued['credential']}
            await self.executor(save_private_json, self.path, settings)
            await call('acknowledge', dict(proof, consentId=issued['consentId'], credential=issued['credential']))
            pending.pop(subject)
            await self.executor(save_private_json, self.pending_path, pending)
            return {'linked':True, 'pivot_user_id':issued['userId']}
