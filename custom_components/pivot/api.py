"""Bounded API requests and diagnostics containing no request/response content."""
import asyncio
import json
import logging
import aiohttp
from .linking import LinkRequestError

_LOGGER = logging.getLogger(__name__)
SAFE_CODES = frozenset(('ha_request_invalid', 'ha_installation_required', 'ha_rate_limited',
    'installation_authority_required', 'pairing_access_required', 'pairing_unavailable',
    'pairing_in_progress', 'pairing_not_approved', 'pairing_confirmation_mismatch',
    'pairing_return_invalid', 'link_exists', 'pivot_access_required', 'delivery_unavailable',
    'pairing_migration_required', 'ha_installation_unavailable', 'delegated_access_required',
    'version_required', 'version_conflict', 'invalid_version', 'not_found', 'task_list_too_large'))


async def api_request(lock, origin, tls, operation, method, target, headers, body=None):
    status = None
    try:
        async with lock, aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15),
                skip_auto_headers={'Accept-Encoding', 'Content-Type'} if body is None else {'Accept-Encoding'},
                cookie_jar=aiohttp.DummyCookieJar()) as session:
            kwargs = {} if body is None else {'json': body}
            async with session.request(method, origin + target, headers=headers, ssl=tls,
                    allow_redirects=False, **kwargs) as response:
                status = response.status
                raw = await response.content.read(1048577)
                if len(raw) > 1048576:
                    raise ValueError('response_too_large')
                # Status remains visible even for HTML proxy errors or empty replies.
                try:
                    result = json.loads(raw)
                except (ValueError, UnicodeError):
                    if status != 200:
                        raise LinkRequestError('unavailable', status) from None
                    raise ValueError('invalid_response') from None
                if status != 200:
                    code = result.get('error') if isinstance(result, dict) else None
                    raise LinkRequestError(code if isinstance(code, str) and code in SAFE_CODES else 'unavailable', status)
                if not isinstance(result, dict):
                    raise ValueError('invalid_response')
        _LOGGER.debug('Pivot operation=%s status=%s', operation, status)
        return result
    except LinkRequestError as error:
        _LOGGER.warning('Pivot operation=%s status=%s code=%s', operation, status, error.code)
        raise
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError) as error:
        # Never log str(error), traceback, URLs, headers, subjects, or bodies.
        _LOGGER.warning('Pivot operation=%s status=%s exception=%s', operation, status, type(error).__name__)
        raise
