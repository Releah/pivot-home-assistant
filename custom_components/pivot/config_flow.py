"""HA UI setup; config entries contain only paths, never credentials."""
from pathlib import Path
from urllib.parse import urlsplit
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from .enrollment import generate_enrollment, decrypt_enrollment
from .provisioning import load_provisioning, save_private_json
from .transport import transport_settings

DOMAIN = 'pivot'


async def async_probe(origin, tls):
    import aiohttp
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10), cookie_jar=aiohttp.DummyCookieJar(),
            skip_auto_headers={'Accept-Encoding'}) as session:
        async with session.get(origin + '/api/ha/v1/tasks', ssl=tls, allow_redirects=False) as response:
            raw = await response.content.read(4097)
            if response.status != 401 or len(raw) > 4096:
                raise ValueError('cannot_connect')
            import json
            if json.loads(raw).get('error') != 'ha_installation_required':
                raise ValueError('cannot_connect')


def website(value):
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise ValueError('invalid_website')
    return value.rstrip('/')


class PivotConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    def __init__(self):
        self._settings = None
        self._key = None
        self._public_key = ''
        self._fingerprint = ''
        self._website = ''

    async def async_step_user(self, user_input=None):
        await self.async_set_unique_id('pivot-household')
        self._abort_if_unique_id_configured()
        if self._async_current_entries():
            return self.async_abort(reason='already_configured')
        return self.async_show_menu(step_id='user', menu_options=['connection', 'existing'])

    async def async_step_connection(self, user_input=None):
        errors = {}
        if user_input:
            try:
                self._settings = {'transport':'https', 'origin':user_input['origin'], 'ca_file':user_input['ca_file'], 'installation_credential':None, 'members':{}}
                self._website = website(user_input['website_url'])
                origin, tls = await self.hass.async_add_executor_job(transport_settings, self._settings)
                try:
                    await async_probe(origin, tls)
                except Exception:
                    # Transport errors can contain URLs; expose only a fixed form error.
                    raise ValueError('cannot_connect') from None
                self._key, self._public_key, self._fingerprint = await self.hass.async_add_executor_job(generate_enrollment)
                return await self.async_step_enroll()
            except (OSError, ValueError, TypeError, KeyError):
                errors['base'] = 'invalid_connection'
        return self.async_show_form(step_id='connection', data_schema=vol.Schema({
            vol.Required('origin', default='https://pivot-api.example.com:443'):str,
            vol.Required('ca_file', default='/ssl/pivot-ca.pem'):str,
            vol.Required('website_url', default='https://pivot.example.com'):str}), errors=errors)

    async def async_step_enroll(self, user_input=None):
        errors = {}
        if user_input:
            try:
                credential = await self.hass.async_add_executor_job(decrypt_enrollment, self._key, self._fingerprint, user_input['envelope'])
                settings = dict(self._settings, installation_credential=credential)
                path = await self.hass.async_add_executor_job(self._install, settings)
                self._key = None
                return self.async_create_entry(title='Pivot household tasks', data={'provisioning_file':path, 'website_url':self._website})
            except (OSError, ValueError, TypeError, KeyError):
                errors['base'] = 'invalid_envelope'
        return self.async_show_form(step_id='enroll', data_schema=vol.Schema({vol.Required('envelope'):str}),
            description_placeholders={'public_key':self._public_key, 'fingerprint':self._fingerprint, 'website':self._website}, errors=errors)

    def _install(self, settings):
        directory = Path(self.hass.config.path('.storage', 'pivot')).absolute()
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = directory / 'provisioning.json'
        if path.exists() or path.is_symlink():
            raise ValueError('existing_provisioning')
        save_private_json(path, settings)
        return str(path)

    async def async_step_existing(self, user_input=None):
        errors = {}
        if user_input:
            try:
                settings = await self.hass.async_add_executor_job(load_provisioning, user_input['provisioning_file'])
                if not settings['installation_credential']:
                    raise ValueError('installation_required')
                await self.hass.async_add_executor_job(transport_settings, settings)
                url = website(user_input['website_url'])
                return self.async_create_entry(title='Pivot household tasks', data={'provisioning_file':user_input['provisioning_file'], 'website_url':url})
            except (OSError, ValueError, TypeError, KeyError):
                errors['base'] = 'invalid_provisioning'
        return self.async_show_form(step_id='existing', data_schema=vol.Schema({vol.Required('provisioning_file'):str,
            vol.Required('website_url', default='https://pivot.example.com'):str}), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return PivotOptionsFlow()


class PivotOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input:
            try:
                path = self.config_entry.data['provisioning_file']
                settings = await self.hass.async_add_executor_job(load_provisioning, path)
                settings.update(transport='https', origin=user_input['origin'], ca_file=user_input['ca_file'])
                await self.hass.async_add_executor_job(transport_settings, settings)
                await self.hass.async_add_executor_job(save_private_json, path, settings)
                return self.async_create_entry(title='', data={})
            except (OSError, ValueError, TypeError, KeyError):
                errors['base'] = 'invalid_connection'
        return self.async_show_form(step_id='init', data_schema=vol.Schema({vol.Required('origin'):str, vol.Required('ca_file'):str}), errors=errors)
