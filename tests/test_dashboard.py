"""Dashboard lifecycle preserves existing dashboards and never persists tasks."""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('pivot_dashboard', 'custom_components/pivot/dashboard.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class DashboardTests(unittest.TestCase):
    def test_registration_reload_and_user_dashboard_preservation(self):
        async def exercise(directory):
            panels = {}
            frontend = types.ModuleType('homeassistant.components.frontend')
            frontend.async_panel_exists = lambda hass, path: path in panels
            frontend.async_register_built_in_panel = lambda hass, component, **kw: panels.update({kw['frontend_url_path']:kw})
            frontend.async_remove_panel = lambda hass, path: panels.pop(path, None)
            components = types.ModuleType('homeassistant.components')
            components.frontend = frontend
            lovelace = types.ModuleType('homeassistant.components.lovelace')
            lovelace.LOVELACE_DATA = 'lovelace'
            dashboard = types.ModuleType('homeassistant.components.lovelace.dashboard')
            dashboard.LovelaceYAML = lambda hass, path, config: config
            async def executor(fn, *args): return fn(*args)
            hass = types.SimpleNamespace(data={'lovelace':types.SimpleNamespace(dashboards={})},
                config=types.SimpleNamespace(path=lambda filename:str(Path(directory)/filename)), async_add_executor_job=executor)
            with patch.dict(sys.modules, {'homeassistant':types.ModuleType('homeassistant'),
                'homeassistant.components':components, 'homeassistant.components.frontend':frontend,
                'homeassistant.components.lovelace':lovelace, 'homeassistant.components.lovelace.dashboard':dashboard}):
                self.assertTrue(await module.async_setup_dashboard(hass))
                self.assertFalse(await module.async_setup_dashboard(hass))
                self.assertFalse(panels[module.DASHBOARD_PATH]['require_admin'])
                path=Path(directory)/'pivot-dashboard.json'
                layout=json.loads(path.read_text())
                self.assertEqual(layout['views'][0]['cards'],[{'type':'custom:pivot-dashboard-card'}])
                layout['title']='Custom title';path.write_text(json.dumps(layout))
                await module.async_unload_dashboard(hass)
                self.assertTrue(await module.async_setup_dashboard(hass))
                self.assertEqual(json.loads(path.read_text())['title'],'Custom title')
                await module.async_unload_dashboard(hass)
                hass.data['lovelace'].dashboards[module.DASHBOARD_PATH]='user-owned'
                self.assertFalse(await module.async_setup_dashboard(hass))
                self.assertEqual(hass.data['lovelace'].dashboards[module.DASHBOARD_PATH],'user-owned')
        with tempfile.TemporaryDirectory() as directory: asyncio.run(exercise(directory))

if __name__ == '__main__': unittest.main()
