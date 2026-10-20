"""One-use HA browser state. This binds the live HA subject to the attempt.

Consuming state reserves a delivery attempt, not approval authority. The trusted
Pivot finish operation must authenticate its receipt and redeem transactionally.
"""
import hashlib
import hmac
import math
import re
import secrets

_TOKEN = re.compile(r'^[A-Za-z0-9_-]{43}$')


def _digest(value):
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise ValueError('invalid_return_state')
    return hashlib.sha256(b'pivot-ha-browser-return-v1\0' + value.encode('ascii')).hexdigest()


def create_binding(subject, pairing_id, expires_at, now, *, state=None):
    """Create state without extending the original pairing's absolute expiry."""
    if (not isinstance(subject, str) or not subject or len(subject) > 128
            or not isinstance(pairing_id, str) or not pairing_id or len(pairing_id) > 128
            or not _time(now) or not _time(expires_at)
            or not now < expires_at <= now + 86400):
        raise ValueError('invalid_return_binding')
    state = secrets.token_urlsafe(32) if state is None else state
    return state, {'subject': subject, 'pairing_id': pairing_id,
                   'expires_at': expires_at, 'state_digest': _digest(state)}


def _time(value):
    return type(value) in (int, float) and math.isfinite(value)


def consume_binding(binding, *, subject, pairing_id, state, now):
    """Reserve one return under the manager lock before remote redemption.

    Persist before sending. A timeout must require cancel/restart, never another
    redemption. An already persisted issued credential resumes acknowledgement.
    """
    if (not isinstance(binding, dict) or binding.get('consumed') is True
            or binding.get('subject') != subject
            or binding.get('pairing_id') != pairing_id
            or not _time(now) or not _time(binding.get('expires_at'))
            or now >= binding['expires_at']):
        raise ValueError('return_not_available')
    digest = _digest(state)
    expected = binding.get('state_digest')
    if not isinstance(expected, str) or not hmac.compare_digest(expected, digest):
        raise ValueError('return_not_available')
    binding['consumed'] = True
    binding.pop('state_digest')
