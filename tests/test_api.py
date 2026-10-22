"""Exercise response diagnostics without HA, credentials, or a live service."""
import asyncio
import importlib
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

class ClientError(Exception):pass
class Context:
    def __init__(self,value):self.value=value
    async def __aenter__(self):return self.value
    async def __aexit__(self,*args):pass

class ApiTests(unittest.TestCase):
    def test_status_proxy_html_tls_timeout_and_redaction(self):
        async def exercise():
            package=types.ModuleType('api_test');package.__path__=[str(Path('custom_components/pivot').resolve())]
            aio=types.ModuleType('aiohttp');aio.ClientError=ClientError
            aio.ClientTimeout=lambda **kwargs:None;aio.DummyCookieJar=lambda:None
            with patch.dict(sys.modules,{'api_test':package,'aiohttp':aio}):
                api=importlib.import_module('api_test.api')
                async def run(status,raw,exception=None):
                    async def read(limit):return raw
                    response=types.SimpleNamespace(status=status,content=types.SimpleNamespace(read=read))
                    def request(*args,**kwargs):
                        self.assertFalse(kwargs['allow_redirects'])
                        if exception:raise exception
                        return Context(response)
                    aio.ClientSession=lambda **kwargs:Context(types.SimpleNamespace(request=request))
                    return await api.api_request(asyncio.Semaphore(1),'https://synthetic.invalid:443',True,
                        'link/start','POST','/api/ha/v1/link/start',{'Authorization':'synthetic-secret'}, {})
                self.assertEqual(await run(200,b'{"status":"active"}'),{'status':'active'})
                for status,raw,code in [(403,b'{"error":"pairing_access_required"}','pairing_access_required'),
                        (502,b'<html>synthetic-secret</html>','unavailable'),
                        (401,b'{"error":"synthetic-secret"}','unavailable')]:
                    with self.assertLogs(api._LOGGER,level='WARNING') as logs:
                        with self.assertRaises(api.LinkRequestError) as raised:await run(status,raw)
                    self.assertEqual(raised.exception.status,status);self.assertEqual(raised.exception.code,code)
                    self.assertIn('status='+str(status),str(logs.output));self.assertNotIn('synthetic-secret',str(logs.output))
                for error in [ClientError('synthetic-secret'),asyncio.TimeoutError('synthetic-secret')]:
                    with self.assertLogs(api._LOGGER,level='WARNING') as logs:
                        with self.assertRaises(type(error)):await run(None,b'',error)
                    self.assertIn(type(error).__name__,str(logs.output));self.assertNotIn('synthetic-secret',str(logs.output))
        asyncio.run(exercise())

if __name__=='__main__':unittest.main()
