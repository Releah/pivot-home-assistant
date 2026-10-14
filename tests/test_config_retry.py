"""Failed setup retains public connection inputs; no live HA or network needed."""
import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch
class Marker:
 def __init__(self,name,**kw):self.name=name;self.default=kw.get('default')
class Flow:
 def __init_subclass__(cls,**kw):pass
 def async_show_form(self,**kw):return kw
class RetryTests(unittest.TestCase):
 def test_failed_probe_preserves_all_fields_and_subsequent_edits(self):
  async def exercise():
   vol=types.ModuleType('voluptuous');vol.Required=Marker;vol.Schema=lambda s:s
   ha=types.ModuleType('homeassistant');entries=types.ModuleType('homeassistant.config_entries');entries.ConfigFlow=Flow;entries.OptionsFlow=Flow;ha.config_entries=entries
   core=types.ModuleType('homeassistant.core');core.callback=lambda f:f
   pkg=types.ModuleType('retry_test');pkg.__path__=[str(Path('custom_components/pivot').resolve())]
   with patch.dict(sys.modules,{'voluptuous':vol,'homeassistant':ha,'homeassistant.config_entries':entries,'homeassistant.core':core,'retry_test':pkg}):
    spec=importlib.util.spec_from_file_location('retry_test.config_flow',Path(pkg.__path__[0])/'config_flow.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    flow=mod.PivotConfigFlow()
    async def executor(fn,*args):return fn(*args)
    flow.hass=types.SimpleNamespace(async_add_executor_job=executor)
    with patch.object(mod,'transport_settings',return_value=('https://api.synthetic.invalid:443',True)),patch.object(mod,'async_probe',new=AsyncMock(side_effect=ValueError('synthetic connection failure'))):
     data={'origin':'https://api.synthetic.invalid:443','ca_file':'/ssl/custom-ca.pem','website_url':'https://web.synthetic.invalid'}
     for ca in ['/ssl/custom-ca.pem','/ssl/revised-ca.pem']:
      data['ca_file']=ca
      result=await flow.async_step_connection(data)
      self.assertEqual(result['errors'],{'base':'invalid_connection'})
      self.assertEqual({k.name:k.default for k in result['data_schema']},data)
     result=await flow.async_step_connection()
     self.assertEqual({k.name:k.default for k in result['data_schema']},data)
  asyncio.run(exercise())
if __name__=='__main__':unittest.main()
