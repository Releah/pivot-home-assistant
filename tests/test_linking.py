import asyncio
import copy
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

pkg=types.ModuleType('pivot_linking_test')
pkg.__path__=[str(Path('custom_components/pivot').resolve())]
sys.modules[pkg.__name__]=pkg
spec=importlib.util.spec_from_file_location('pivot_linking_test.linking',Path(pkg.__path__[0])/'linking.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

class LinkingTests(unittest.TestCase):
    def test_two_people_explicit_confirmation_and_durable_delivery(self):
        async def exercise():
            path='/protected/pivot.json';pending='/protected/pending-links.json'
            files={path:{'transport':'https','origin':'https://synthetic.invalid:443','ca_file':'/public/ca.pem',
                'installation_credential':'synthetic-installation','members':{}}}
            events=[]
            def load(name):
                if str(name) not in files:raise FileNotFoundError()
                return copy.deepcopy(files[str(name)])
            def save(name,value):
                events.append(('save',str(name)));files[str(name)]=copy.deepcopy(value)
            async def executor(fn,*args):return fn(*args)
            async def remote(settings,subject,operation,body):
                events.append((operation,subject))
                if operation=='start':return {'pairingId':'synthetic-pairing-'+subject,'redemptionProof':'synthetic-proof','locator':'synthetic-locator'}
                if operation=='finish':
                    self.assertEqual(body['confirmation'],{'userId':'synthetic-pivot-a','consentId':'synthetic-consent'})
                    return {'linkId':'synthetic-link','credential':'synthetic-grant','userId':'synthetic-pivot-a','consentId':'synthetic-consent'}
                if operation=='acknowledge':self.assertEqual(files[path]['members'][subject]['credential'],'synthetic-grant')
                return {}
            manager=mod.LinkManager(path,executor,remote)
            with patch.object(mod,'load_provisioning',load),patch.object(mod,'load_private_json',load),patch.object(mod,'save_private_json',save):
                self.assertEqual(await manager.run('ha-a','start'),{'locator':'synthetic-locator'})
                with self.assertRaises(ValueError):await manager.run('ha-b','finish',{'userId':'synthetic-pivot-a','consentId':'synthetic-consent'})
                with self.assertRaises(ValueError):await manager.run('ha-a','finish')
                result=await manager.run('ha-a','finish',{'userId':'synthetic-pivot-a','consentId':'synthetic-consent'})
                self.assertEqual(result,{'linked':True,'pivot_user_id':'synthetic-pivot-a'})
                self.assertNotIn('credential',result);self.assertEqual(set(files[path]['members']),{'ha-a'})
                self.assertLess(events.index(('save',path)),events.index(('acknowledge','ha-a')))
                await manager.run('ha-a','unlink');self.assertEqual(files[path]['members'],{})
        asyncio.run(exercise())

class RetryTests(unittest.TestCase):
    def test_restart_and_household_isolation_survive_manager_restart(self):
        async def exercise():
            path='/protected/pivot.json';pending='/protected/pending-links.json'
            files={path:{'installation_credential':'synthetic','members':{}}};calls=[];sequence=0
            def load(name):
                if name not in files:raise FileNotFoundError()
                return copy.deepcopy(files[name])
            def save(name,value):files[name]=copy.deepcopy(value)
            async def executor(fn,*args):return fn(*args)
            async def remote(settings,subject,operation,body):
                nonlocal sequence
                calls.append((subject,operation,body))
                if operation=='start':
                    sequence+=1
                    return {'pairingId':str(sequence),'redemptionProof':'synthetic-proof-'+str(sequence),'locator':'synthetic-locator-'+str(sequence)}
                return {}
            with patch.object(mod,'load_provisioning',load),patch.object(mod,'load_private_json',load),patch.object(mod,'save_private_json',save):
                manager=mod.LinkManager(path,executor,remote)
                first,other=await asyncio.gather(manager.run('ha-a','start'),manager.run('ha-b','start'))
                manager=mod.LinkManager(path,executor,remote)
                fresh=await manager.run('ha-a','start')
                self.assertNotEqual(first,fresh)
                self.assertEqual(files[pending]['ha-b']['locator'],other['locator'])
                self.assertIn(('ha-a','cancel',{}),calls)
                await manager.run('ha-a','cancel')
                final=await manager.run('ha-a','start')
                self.assertNotEqual(fresh,final)
                self.assertNotIn('ha-a',files[path]['members'])
                files[path]['members']['ha-a']={'link_id':'working','credential':'synthetic-working'}
                files[pending].pop('ha-a')
                with self.assertRaisesRegex(ValueError,'link_exists'):await manager.run('ha-a','start')
                self.assertEqual(files[path]['members']['ha-a']['link_id'],'working')
        asyncio.run(exercise())


class UncertainDeliveryTests(unittest.TestCase):
    def test_timeout_after_redemption_is_never_redeemed_again_after_restart(self):
        async def exercise():
            path='/protected/pivot.json';pending='/protected/pending-links.json'
            files={path:{'installation_credential':'synthetic','members':{}},pending:{'ha-a':{
                'pairingId':'synthetic-pair','redemptionProof':'synthetic-proof','locator':'synthetic-locator'}}}
            calls=[]
            def load(name):return copy.deepcopy(files[name])
            def save(name,value):files[name]=copy.deepcopy(value)
            async def executor(fn,*args):return fn(*args)
            async def remote(settings,subject,operation,body):
                calls.append(operation)
                if operation=='finish':
                    self.assertTrue(files[pending][subject]['redemption_started'])
                    raise asyncio.TimeoutError()
                return {}
            confirmation={'userId':'synthetic-user','consentId':'synthetic-consent'}
            with patch.object(mod,'load_provisioning',load),patch.object(mod,'load_private_json',load),patch.object(mod,'save_private_json',save):
                manager=mod.LinkManager(path,executor,remote)
                with self.assertRaises(asyncio.TimeoutError):await manager.run('ha-a','finish',confirmation)
                manager=mod.LinkManager(path,executor,remote)
                with self.assertRaisesRegex(ValueError,'delivery_uncertain_restart_required'):
                    await manager.run('ha-a','finish',confirmation)
                self.assertEqual(calls,['finish'])
                self.assertEqual(files[path]['members'],{})
                await manager.run('ha-a','cancel')
                self.assertEqual(calls,['finish','cancel'])
                self.assertEqual(files[pending],{})
        asyncio.run(exercise())



class AutomaticTests(unittest.TestCase):
    def test_automatic_return_persists_before_ack_and_preserves_an_existing_connection(self):
        async def exercise():
            import time
            path='/protected/pivot.json';pending='/protected/pending-links.json'
            existing={'link_id':'synthetic-existing-link','credential':'synthetic-existing-grant'}
            files={path:{'installation_credential':'synthetic-installation','members':{'ha-existing':existing}},pending:{}}
            calls=[];sequence=0;ack_fails=True
            def load(name):return copy.deepcopy(files[name])
            def save(name,value):files[name]=copy.deepcopy(value)
            async def executor(fn,*args):return fn(*args)
            async def remote(settings,subject,operation,body):
                nonlocal sequence,ack_fails
                calls.append((subject,operation,copy.deepcopy(body)))
                if operation=='start':
                    sequence+=1
                    self.assertEqual(body['returnUrl'],'https://ha.example.invalid/pivot-tasks/tasks')
                    return {'pairingId':'synthetic-pair-'+str(sequence),'redemptionProof':'synthetic-proof-'+str(sequence),
                            'locator':'hl1.'+'L'*43,'returnContext':'synthetic-encrypted-context','expiresAt':int((time.time()+86400)*1000)}
                if operation=='finish':
                    self.assertTrue(files[pending][subject]['browser_return']['consumed'])
                    self.assertTrue(files[pending][subject]['redemption_started'])
                    self.assertEqual(body['result'],'synthetic-authenticated-result')
                    self.assertNotIn('confirmation',body)
                    return {'linkId':'synthetic-new-link','credential':'synthetic-new-grant','userId':'synthetic-user','consentId':'synthetic-consent'}
                if operation=='acknowledge':
                    self.assertEqual(files[path]['members'][subject]['credential'],'synthetic-new-grant')
                    if ack_fails:raise asyncio.TimeoutError()
                return {}
            with patch.object(mod,'load_provisioning',load),patch.object(mod,'load_private_json',load),patch.object(mod,'save_private_json',save):
                manager=mod.LinkManager(path,executor,remote)
                started=await manager.run('ha-new','start_return',browser_return={'returnUrl':'https://ha.example.invalid/pivot-tasks/tasks'})
                self.assertNotIn('redemptionProof',started);self.assertEqual(files[pending]['ha-new']['approval_state'],started['state'])
                # Reopening after restart returns exactly this person's original approval.
                original_remote = manager.request
                async def inspect_remote(settings, subject, operation, body):
                    if operation == 'inspect':return {'pairing':{'status':'pending'}}
                    return await original_remote(settings, subject, operation, body)
                manager = mod.LinkManager(path, executor, inspect_remote)
                inspected = await manager.run('ha-new', 'inspect')
                self.assertEqual(inspected['approval'], started)
                self.assertNotIn('redemptionProof', inspected['approval'])
                self.assertNotIn('consumed', files[pending]['ha-new']['browser_return'])
                legacy = copy.deepcopy(files[pending]['ha-new'])
                del files[pending]['ha-new']['approval_state']
                self.assertEqual((await manager.run('ha-new', 'inspect'))['pairing']['status'], 'unavailable')
                files[pending]['ha-new'] = copy.deepcopy(legacy)
                files[pending]['ha-new']['browser_return']['expires_at'] = 0
                self.assertEqual((await manager.run('ha-new', 'inspect'))['pairing']['status'], 'unavailable')
                files[pending]['ha-new'] = legacy
                returned={'pairingId':'synthetic-pair-1','state':started['state'],'result':'synthetic-authenticated-result'}
                with self.assertRaisesRegex(ValueError,'pairing_required'):
                    await manager.run('ha-other','finish_return',browser_return=returned)
                for change in ({'state':'X'*43},{'pairingId':'synthetic-other-pair'}):
                    with self.assertRaises(ValueError):await manager.run('ha-new','finish_return',browser_return=returned|change)
                self.assertFalse(any(c[1]=='finish' for c in calls))
                with self.assertRaises(asyncio.TimeoutError):await manager.run('ha-new','finish_return',browser_return=returned)
                self.assertEqual(files[path]['members']['ha-existing'],existing)
                self.assertIn('issued',files[pending]['ha-new'])
                # Resume persisted delivery after process restart, without returning
                # a credential to the browser or redeeming again.
                ack_fails=False;manager=mod.LinkManager(path,executor,remote)
                linked=await manager.run('ha-new','acknowledge')
                self.assertEqual(linked,{'linked':True,'pivot_user_id':'synthetic-user'})
                self.assertEqual(files[pending],{})
                self.assertEqual(len([c for c in calls if c[1]=='finish']),1)
                with self.assertRaises(ValueError):await manager.run('ha-new','finish_return',browser_return=returned)
                with self.assertRaisesRegex(ValueError,'link_exists'):
                    await manager.run('ha-existing','start_return',browser_return={'returnUrl':'https://ha.example.invalid/pivot-tasks/tasks'})
                self.assertEqual(files[path]['members']['ha-existing'],existing)
        asyncio.run(exercise())

    def test_cancel_retry_rotates_nonce_proof_and_attempt_without_touching_another_person(self):
        async def exercise():
            import time
            path='/protected/pivot.json';pending='/protected/pending-links.json';sequence=0;calls=[]
            files={path:{'installation_credential':'synthetic','members':{'ha-existing':{'link_id':'existing','credential':'existing'}}},pending:{}}
            def load(name):return copy.deepcopy(files[name])
            def save(name,value):files[name]=copy.deepcopy(value)
            async def executor(fn,*args):return fn(*args)
            async def remote(settings,subject,operation,body):
                nonlocal sequence
                calls.append(operation)
                if operation=='start':
                    sequence+=1
                    return {'pairingId':str(sequence),'redemptionProof':'proof-'+str(sequence),'locator':'locator-'+str(sequence),'returnContext':'context','expiresAt':int((time.time()+86400)*1000)}
                return {}
            with patch.object(mod,'load_provisioning',load),patch.object(mod,'load_private_json',load),patch.object(mod,'save_private_json',save):
                manager=mod.LinkManager(path,executor,remote)
                first=await manager.run('ha-new','start_return',browser_return={'returnUrl':'https://ha.example.invalid/pivot-tasks/tasks'})
                second=await manager.run('ha-new','start_return',browser_return={'returnUrl':'https://ha.example.invalid/pivot-tasks/tasks'})
                self.assertNotEqual(first['state'],second['state']);self.assertEqual(calls,['start','cancel','start'])
                await manager.run('ha-new','cancel')
                third=await manager.run('ha-new','start_return',browser_return={'returnUrl':'https://ha.example.invalid/pivot-tasks/tasks'})
                self.assertNotEqual(second['state'],third['state'])
                self.assertEqual(files[path]['members'],{'ha-existing':{'link_id':'existing','credential':'existing'}})
        asyncio.run(exercise())



class StaleProofTests(unittest.TestCase):
    def test_stale_proof_can_be_cancelled_without_touching_other_members(self):
        async def exercise():
            path='/protected/pivot.json';pending='/protected/pending-links.json'
            files={path:{'installation_credential':'synthetic','members':{}},pending:{
                'ha-a':{'pairingId':'old','redemptionProof':'old','locator':'old'},
                'ha-b':{'pairingId':'other','redemptionProof':'other','locator':'other'}}}
            def load(name):return copy.deepcopy(files[name])
            def save(name,value):files[name]=copy.deepcopy(value)
            async def executor(fn,*args):return fn(*args)
            calls=[]
            async def remote(settings,subject,operation,body):
                calls.append((subject,operation,body))
                if operation=='inspect':raise mod.LinkRequestError('pairing_access_required')
                return {'cancelled':True}
            with patch.object(mod,'load_provisioning',load),patch.object(mod,'load_private_json',load),patch.object(mod,'save_private_json',save):
                manager=mod.LinkManager(path,executor,remote)
                status=await manager.run('ha-a','inspect')
                self.assertEqual(status['pairing']['status'],'unavailable')
                self.assertIn('ha-a',files[pending])
                # Recovery also works if an old local entry no longer has a proof.
                del files[pending]['ha-a']['redemptionProof']
                self.assertEqual((await manager.run('ha-a','inspect'))['pairing']['status'], 'unavailable')
                await manager.run('ha-a','cancel')
                self.assertEqual(set(files[pending]),{'ha-b'})
                self.assertEqual(calls[-1],('ha-a','cancel',{}))
                before=len(calls)
                self.assertEqual(await manager.run('ha-a','cancel'),{'cancelled':True})
                self.assertEqual(len(calls),before)
                files[path]['members']['ha-a']={'link_id':'just-finished','credential':'synthetic'}
                files[path]['members']['ha-existing']={'link_id':'existing','credential':'synthetic'}
                await manager.run('ha-a','cancel')
                self.assertEqual(set(files[path]['members']),{'ha-existing'})
                self.assertEqual(set(files[pending]),{'ha-b'})
        asyncio.run(exercise())



class ReconciliationTests(unittest.TestCase):
    def test_two_people_revocation_outage_and_reconnection(self):
        async def exercise():
            path='/protected/pivot.json'; pending='/protected/pending-links.json'
            files={path:{'installation_credential':'synthetic','members':{
                subject:{'link_id':subject,'credential':'synthetic'} for subject in ('ha-a','ha-b')}},
                pending:{'ha-a':{'issued':{}},'ha-b':{'issued':{}}}}
            statuses={'ha-a':'active','ha-b':'active'}
            def load(name):return copy.deepcopy(files[name])
            def save(name,value):files[name]=copy.deepcopy(value)
            async def executor(fn,*args):return fn(*args)
            async def remote(settings,subject,operation,body):
                if operation=='status':
                    if statuses[subject]=='timeout':raise asyncio.TimeoutError()
                    return {'status':statuses[subject]}
                if operation=='start':return {'pairingId':subject,'redemptionProof':'synthetic','locator':'synthetic'}
                if operation=='finish':return {'linkId':subject+'-new','credential':'synthetic-new','userId':subject+'-pivot','consentId':'synthetic'}
                return {}
            with patch.object(mod,'load_provisioning',load),patch.object(mod,'load_private_json',load),patch.object(mod,'save_private_json',save):
                manager=mod.LinkManager(path,executor,remote)
                self.assertEqual(await manager.reconcile('ha-a'),'active')
                statuses['ha-a']='timeout'
                with self.assertRaises(asyncio.TimeoutError):await manager.reconcile('ha-a')
                self.assertIn('ha-a',files[path]['members'])
                for subject,terminal in [('ha-a','revoked'),('ha-b','expired')]:
                    other='ha-b' if subject=='ha-a' else 'ha-a'
                    before=copy.deepcopy(files[path]['members'][other])
                    statuses[subject]=terminal
                    self.assertEqual(await manager.reconcile(subject),terminal)
                    self.assertNotIn(subject,files[path]['members']);self.assertNotIn(subject,files[pending])
                    self.assertEqual(files[path]['members'][other],before)
                    await manager.run(subject,'start')
                    await manager.run(subject,'finish',{'userId':subject+'-pivot','consentId':'synthetic'})
                    statuses[subject]='active'
                    manager=mod.LinkManager(path,executor,remote)
                    self.assertEqual(await manager.reconcile(subject),'active')
                    self.assertEqual(files[path]['members'][subject]['link_id'],subject+'-new')
        asyncio.run(exercise())

if __name__=='__main__':unittest.main()
