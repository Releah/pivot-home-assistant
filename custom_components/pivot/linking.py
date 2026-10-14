"""Per-person linking with durable delivery and explicit account confirmation."""
import asyncio
from pathlib import Path
from .provisioning import load_provisioning, load_private_json, save_private_json


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

    async def run(self, subject, action, confirmation=None):
        async with self.lock:
            settings = await self.executor(load_provisioning, self.path)
            if not settings['installation_credential']:
                raise ValueError('installation_required')
            pending = await self.pending()
            async def call(operation, body):
                return await self.request(settings, subject, operation, body)
            if action == 'start':
                if subject in pending or subject in settings['members']:
                    raise ValueError('pairing_in_progress')
                value = await call('start', {})
                if set(value) != {'pairingId','redemptionProof','locator'}:
                    raise ValueError('invalid_response')
                pending[subject] = value
                try:
                    await self.executor(save_private_json, self.pending_path, pending)
                except (OSError, ValueError):
                    await call('cancel', {'pairingId':value['pairingId'], 'redemptionProof':value['redemptionProof']})
                    raise
                # Only the locator reaches the browser; the redemption proof stays here.
                return {'locator':value['locator']}
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
            if not value:
                raise ValueError('pairing_required')
            proof = {'pairingId':value['pairingId'], 'redemptionProof':value['redemptionProof']}
            if action == 'inspect':
                result = await call('inspect', proof)
                # An explicit HA-person confirmation must match this server inspection.
                return {'pairing':result['pairing'], 'approved_user_name':result.get('approvedUserName'),
                        'awaiting_delivery': 'issued' in value}
            if action == 'cancel':
                await call('cancel', proof)
                pending.pop(subject)
                settings['members'].pop(subject, None)
                await self.executor(save_private_json, self.path, settings)
                await self.executor(save_private_json, self.pending_path, pending)
                return {'cancelled':True}
            if action not in ('finish','acknowledge'):
                raise ValueError('invalid_action')
            if action == 'finish':
                if not isinstance(confirmation, dict) or set(confirmation) != {'userId','consentId'}:
                    raise ValueError('confirmation_required')
                if 'issued' in value:
                    raise ValueError('acknowledgement_required')
                issued = await call('finish', dict(proof, confirmation=confirmation))
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
