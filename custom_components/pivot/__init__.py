"""Private per-request tasks: no entities, recorder state or credential diagnostics."""
import asyncio
import json
from .transport import transport_settings
from .provisioning import load_provisioning
from .linking import LinkManager

import aiohttp
import voluptuous as vol
from homeassistant.components import websocket_api

DOMAIN = "pivot"
CONFIG_SCHEMA = vol.Schema({DOMAIN: vol.Schema({vol.Required("provisioning_file"): str})}, extra=vol.ALLOW_EXTRA)

async def async_setup(hass, config):
    if DOMAIN not in config:
        return True
    # Operator-provisioned owner-only file, never frontend/config-entry storage.
    try:
        settings = await hass.async_add_executor_job(load_provisioning, config[DOMAIN]["provisioning_file"])
        origin, tls = await hass.async_add_executor_job(transport_settings, settings)
    except (OSError, ValueError, TypeError, KeyError):
        # Provisioning errors can include secrets; never expose exception details.
        return False
    lock = asyncio.Semaphore(2)
    path = config[DOMAIN]['provisioning_file']

    async def link_request(current, subject, operation, body):
        origin, tls = await hass.async_add_executor_job(transport_settings, current)
        headers = {'Authorization':'Bearer ' + current['installation_credential'], 'X-HA-Subject':subject}
        async with lock, aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15),
                skip_auto_headers={'Accept-Encoding'}, cookie_jar=aiohttp.DummyCookieJar()) as session:
            async with session.post(origin + '/api/ha/v1/link/' + operation, headers=headers,
                    json=body, ssl=tls, allow_redirects=False) as response:
                raw = await response.content.read(1048577)
                if response.status != 200 or len(raw) > 1048576:
                    raise ValueError('link_request_failed')
                return json.loads(raw)

    manager = LinkManager(path, hass.async_add_executor_job, link_request)

    async def request(connection, msg, complete=False):
        # Re-resolve the live account on every call. No caller-selected subject.
        user = await hass.auth.async_get_user(connection.user.id)
        if not user or not user.is_active or user.system_generated:
            connection.send_error(msg["id"], "access_denied", "Active personal account required")
            return
        try:
            current = await hass.async_add_executor_job(load_provisioning, path)
            origin, tls = await hass.async_add_executor_job(transport_settings, current)
        except (OSError, ValueError, TypeError, KeyError):
            connection.send_error(msg['id'], 'pivot_unavailable', 'Check Pivot configuration')
            return
        binding = current["members"].get(user.id)
        if not binding:
            connection.send_error(msg["id"], "access_denied", "Pairing required")
            return
        headers = {"Authorization": "Bearer " + current["installation_credential"],
                   "X-HA-Subject": user.id, "X-Pivot-Link": binding["link_id"],
                   "X-Pivot-Grant": binding["credential"]}
        target = "/api/ha/v1/tasks"
        if complete:
            target += "/" + msg["task_id"] + "/complete"
            headers["If-Match"] = msg["etag"]
        try:
            async with lock, aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15),
                    skip_auto_headers={"Accept-Encoding", "Content-Type"}, cookie_jar=aiohttp.DummyCookieJar()) as session:
                async with session.request("POST" if complete else "GET", origin + target,
                        headers=headers, ssl=tls, allow_redirects=False) as response:
                    raw = await response.content.read(1048577)
                    if response.status != 200 or len(raw) > 1048576:
                        raise ValueError("request_failed")
                    result = json.loads(raw)
            connection.send_result(msg["id"], result)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            # No exception details, URLs, headers, credentials or task titles.
            connection.send_error(msg["id"], "pivot_unavailable", "Refresh before retrying; completion may have committed")

    @websocket_api.websocket_command({vol.Required("type"): "pivot/tasks"})
    @websocket_api.async_response
    async def tasks(hass, connection, msg):
        await request(connection, msg)

    @websocket_api.websocket_command({vol.Required("type"): "pivot/complete",
        vol.Required("task_id"): vol.All(str, vol.Match(r"^[0-9a-f-]{36}$")),
        vol.Required("etag"): vol.All(str, vol.Length(max=100))})
    @websocket_api.async_response
    async def complete(hass, connection, msg):
        await request(connection, msg, True)

    @websocket_api.websocket_command({vol.Required("type"): "pivot/setup_identity"})
    @websocket_api.async_response
    async def setup_identity(hass, connection, msg):
        user = await hass.auth.async_get_user(connection.user.id)
        if not user or not user.is_active or user.system_generated:
            connection.send_error(msg["id"], "access_denied", "Active personal account required")
            return
        connection.send_result(msg["id"], {"subject": user.id})

    @websocket_api.websocket_command({vol.Required('type'):'pivot/link_status'})
    @websocket_api.async_response
    async def link_status(hass, connection, msg):
        user = await hass.auth.async_get_user(connection.user.id)
        if not user or not user.is_active or user.system_generated:
            connection.send_error(msg['id'], 'access_denied', 'Active personal account required')
            return
        try:
            current = await hass.async_add_executor_job(load_provisioning, path)
            pending = await manager.pending()
            connection.send_result(msg['id'], {'subject':user.id, 'ha_name':user.name,
                'installation_ready':bool(current['installation_credential']),
                'linked':user.id in current['members'], 'pending':user.id in pending,
                'locator':pending.get(user.id, {}).get('locator'),
                'website_url':config[DOMAIN].get('website_url', '')})
        except (OSError, ValueError, TypeError, KeyError):
            connection.send_error(msg['id'], 'pivot_unavailable', 'Check Pivot configuration')

    @websocket_api.websocket_command({vol.Required('type'):'pivot/link',
        vol.Required('action'):vol.In(['start','inspect','finish','acknowledge','cancel','unlink']),
        vol.Optional('confirmation'): {vol.Required('userId'):str, vol.Required('consentId'):str}})
    @websocket_api.async_response
    async def link(hass, connection, msg):
        user = await hass.auth.async_get_user(connection.user.id)
        if not user or not user.is_active or user.system_generated:
            connection.send_error(msg['id'], 'access_denied', 'Active personal account required')
            return
        try:
            result = await manager.run(user.id, msg['action'], msg.get('confirmation'))
            connection.send_result(msg['id'], result)
        except (OSError, ValueError, TypeError, KeyError, aiohttp.ClientError, asyncio.TimeoutError):
            connection.send_error(msg['id'], 'link_failed', 'Check pairing status before retrying. Approval expires after five minutes.')

    websocket_api.async_register_command(hass, link_status)
    websocket_api.async_register_command(hass, link)
    websocket_api.async_register_command(hass, setup_identity)
    websocket_api.async_register_command(hass, tasks)
    websocket_api.async_register_command(hass, complete)
    return True


async def async_setup_entry(hass, entry):
    from pathlib import Path
    from homeassistant.components.http import StaticPathConfig
    from homeassistant.exceptions import ConfigEntryNotReady
    try:
        ready = await async_setup(hass, {DOMAIN: dict(entry.data)})
        if not ready:
            raise ConfigEntryNotReady('Invalid protected Pivot configuration')
        domain_data = hass.data.setdefault(DOMAIN, {})
        if not domain_data.get('card_registered'):
            await hass.http.async_register_static_paths([StaticPathConfig('/pivot/pivot-task-card.js',
                str(Path(__file__).parent / 'www' / 'pivot-task-card.js'), False)])
            domain_data['card_registered'] = True
        from homeassistant.components import frontend
        from .dashboard import async_setup_dashboard
        frontend.add_extra_js_url(hass, '/pivot/pivot-task-card.js?v=0.4.1')
        if await async_setup_dashboard(hass):
            domain_data['dashboard_owned'] = True
        domain_data['entry'] = entry.entry_id
        entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
        return True
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise ConfigEntryNotReady('Invalid protected Pivot configuration') from None


async def _async_reload_entry(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    from .dashboard import async_unload_dashboard
    if hass.data.get(DOMAIN, {}).pop('dashboard_owned', False):
        await async_unload_dashboard(hass)
    # Replace handlers with a safe error; loaded tasks/credentials are not retained.
    for command in ['pivot/tasks','pivot/complete','pivot/link','pivot/link_status','pivot/setup_identity']:
        # Each replacement needs its own fixed type schema.
        async def handler(hass, connection, msg):
            connection.send_error(msg['id'], 'pivot_unavailable', 'Pivot integration is unloaded')
        handler = websocket_api.async_response(handler)
        handler = websocket_api.websocket_command({vol.Required('type'):command})(handler)
        websocket_api.async_register_command(hass, handler)
    return True
