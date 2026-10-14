"""Register a generated private-task Lovelace dashboard without editing user dashboards."""
import json
from pathlib import Path
DASHBOARD_PATH = 'pivot-tasks'

def create_layout(path):
    path = Path(path)
    # The config contains only a card declaration, never any task/account data.
    try:
        with path.open('x', encoding='utf-8') as stream:
            json.dump({'title':'Pivot','views':[{'title':'My tasks','path':'tasks','icon':'mdi:clipboard-check-outline','type':'panel',
                'cards':[{'type':'custom:pivot-dashboard-card'}]}]}, stream)
    except FileExistsError:
        pass

async def async_setup_dashboard(hass):
    from homeassistant.components import frontend
    from homeassistant.components.lovelace import LOVELACE_DATA
    from homeassistant.components.lovelace.dashboard import LovelaceYAML
    data = hass.data[LOVELACE_DATA]
    dashboards = data.dashboards if hasattr(data, 'dashboards') else data['dashboards']
    if DASHBOARD_PATH in dashboards or frontend.async_panel_exists(hass, DASHBOARD_PATH):
        return False
    filename = 'pivot-dashboard.json'
    await hass.async_add_executor_job(create_layout, hass.config.path(filename))
    config = {'mode':'yaml','filename':filename,'title':'Pivot','icon':'mdi:clipboard-check-outline',
        'show_in_sidebar':True,'require_admin':False}
    dashboards[DASHBOARD_PATH] = LovelaceYAML(hass, DASHBOARD_PATH, config)
    try:
        frontend.async_register_built_in_panel(hass, 'lovelace', sidebar_title='Pivot',
            sidebar_icon='mdi:clipboard-check-outline', frontend_url_path=DASHBOARD_PATH,
            config={'mode':'yaml'}, require_admin=False)
    except Exception:
        dashboards.pop(DASHBOARD_PATH, None)
        raise
    return True

async def async_unload_dashboard(hass):
    from homeassistant.components import frontend
    from homeassistant.components.lovelace import LOVELACE_DATA
    data = hass.data.get(LOVELACE_DATA)
    if data:
        dashboards = data.dashboards if hasattr(data, 'dashboards') else data['dashboards']
        dashboards.pop(DASHBOARD_PATH, None)
    frontend.async_remove_panel(hass, DASHBOARD_PATH)
