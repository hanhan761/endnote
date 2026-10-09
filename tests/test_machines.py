import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from endnote.service import Store, Settings, APIError, digest
from scripts.enroll_owner import enroll_owner
from endnote.web.machine_agent import Collector, gpu_metrics

class MachineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.now=1700000000.;self.store=Store(Settings(str(Path(self.tmp.name)/'machines.db')),clock=lambda:self.now)
        enroll_owner(self.store,'owner@example.com',digest('owner-key'))
        enroll_owner(self.store,'other@example.com',digest('other-key'))
        with self.store.db() as c:
            self.token=c.execute('SELECT token FROM dashboards WHERE recipient_hash=?',(digest('owner@example.com'),)).fetchone()[0]
            self.other=c.execute('SELECT token FROM dashboards WHERE recipient_hash=?',(digest('other@example.com'),)).fetchone()[0]
        self.manager=self.store.machines
    def create(self,name='Workstation'):return self.manager.create(self.token,{'name':name})
    def test_multiple_machines_isolated_scoped_credentials_and_no_secrets_in_read(self):
        one=self.create();two=self.create('Second')
        self.manager.ingest(one['machine_key'],one['id'],{'cpu_percent':75,'gpus':[]})
        self.assertEqual(len(self.manager.list(self.token)),2)
        self.assertEqual(self.manager.list(self.other),[])
        self.assertNotIn(one['machine_key'],json.dumps(self.manager.list(self.token)))
        with self.assertRaises(APIError):self.manager.ingest(one['machine_key'],two['id'],{})
        with self.assertRaises(APIError):self.manager.enable(self.other,one['id'],False)
        with self.assertRaises(APIError):self.store.create_task(one['machine_key'],{'name':'bad'})
        with self.store.db() as c:self.assertNotEqual(c.execute('SELECT key_hash FROM machines WHERE id=?',(one['id'],)).fetchone()[0],one['machine_key'])
    def test_optional_no_fake_zero_expiry_and_disable_reenable(self):
        self.assertEqual(self.manager.list(self.token),[])
        one=self.create();self.assertEqual(self.manager.list(self.token)[0]['state'],'waiting')
        self.manager.ingest(one['machine_key'],one['id'],{'cpu_percent':None,'gpus':[]})
        self.assertIsNone(self.manager.list(self.token)[0]['metrics']['cpu_percent'])
        self.now+=90;self.assertEqual(self.manager.list(self.token)[0]['state'],'offline')
        self.manager.enable(self.token,one['id'],False)
        with self.assertRaises(APIError) as e:self.manager.ingest(one['machine_key'],one['id'],{})
        self.assertEqual(e.exception.status,403)
        self.manager.enable(self.token,one['id'],True);self.manager.ingest(one['machine_key'],one['id'],{})
        self.assertEqual(self.manager.list(self.token)[0]['state'],'online')
    def test_validation_numeric_bounds_and_no_urls_or_commands(self):
        one=self.create()
        for payload in [{'cpu_percent':True},{'cpu_percent':math.nan},{'cpu_percent':101},{'memory_used':20,'memory_total':10},{'command':'rm -rf /'},{'url':'https://private.example'}, {'gpus':[{'index':0,'name':'GPU','percent':-1}]}]:
            with self.assertRaises(APIError):self.manager.ingest(one['machine_key'],one['id'],payload)
        with self.assertRaises(APIError):self.manager.create(self.token,{'name':'host','url':'http://internal'})
        with self.assertRaises(APIError):self.manager.create(self.token,{'name':'x\nheader'})
    def test_bounded_report_rate_and_machine_count(self):
        one=self.create()
        for _ in range(90):self.manager.ingest(one['machine_key'],one['id'],{})
        with self.assertRaises(APIError) as e:self.manager.ingest(one['machine_key'],one['id'],{})
        self.assertEqual(e.exception.status,429)
        for index in range(1,12):self.now+=3601;self.create('Machine '+str(index))
        self.now+=3601
        with self.assertRaises(APIError):self.create('Too many')
    def test_one_second_reports_remain_bounded_and_latest_only(self):
        one=self.create();self.assertEqual(one['interval'],1)
        for tick in range(180):
            self.manager.ingest(one['machine_key'],one['id'],{'cpu_percent':tick%100})
            self.now+=1
        self.assertEqual(len(self.manager.list(self.token)),1)
        self.assertEqual(self.manager.list(self.token)[0]['metrics']['cpu_percent'],79)
        with self.store.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM machines').fetchone()[0],1)

    def test_sample_cpu_delta_and_missing_gpu(self):
        with patch.object(Collector,'cpu_times',side_effect=[(30,100),(40,200)]),patch.object(Collector,'memory',return_value=(1000,500)),patch.object(Collector,'temperature',return_value=None),patch('endnote.web.machine_agent.gpu_metrics',return_value=[]):
            metric=Collector().sample();self.assertEqual(metric['cpu_percent'],90);self.assertIsNone(metric['cpu_temperature']);self.assertEqual(metric['gpus'],[])
        with patch('endnote.web.machine_agent.shutil.which',return_value=None):self.assertEqual(gpu_metrics(),[])

    def test_http_download_reporting_scope_and_origin(self):
        import threading
        from urllib.request import Request,urlopen
        from urllib.error import HTTPError
        from endnote.server import Server
        server=Server(('127.0.0.1',0),self.store)
        base='http://127.0.0.1:'+str(server.server_address[1])+'/endnote'
        self.store.settings.public_url=base
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def close():server.shutdown();thread.join(3);server.server_close()
        self.addCleanup(close)
        def request(route,data=None,key=None,origin=None):
            headers={'Content-Type':'application/json'}
            if key:headers['Authorization']='Bearer '+key
            if origin:headers['Origin']=origin
            with urlopen(Request(base+route,json.dumps(data).encode() if data is not None else None,headers),timeout=5) as response:return response.status,json.load(response)
        status,result=request('/v1/dashboard/'+self.token+'/machines',{'name':'HTTP machine'})
        self.assertEqual(status,201);compile(result['script'],'downloaded-agent.py','exec')
        self.assertIn(result['machine_key'],result['script'])
        route='/v1/machines/'+result['id']+'/telemetry'
        self.assertEqual(request(route,{'cpu_percent':22},result['machine_key'])[0],200)
        snapshot=request('/v1/dashboard/'+self.token+'?trends=0')[1]
        self.assertEqual(snapshot['machines'][0]['metrics']['cpu_percent'],22)
        self.assertNotIn(result['machine_key'],json.dumps(snapshot))
        self.assertEqual(request('/v1/dashboard/'+self.other+'/machines')[1]['machines'],[])
        for wrong,data,key,origin in [(route,{},'wrong',None),('/v1/tasks',{'name':'abuse'},result['machine_key'],None),('/v1/dashboard/'+self.token+'/machines',{'name':'cross-origin'},None,'https://evil.example')]:
            with self.assertRaises(HTTPError):request(wrong,data,key,origin)
        with self.assertRaises(HTTPError):request('/v1/dashboard/'+self.other+'/machines/'+result['id'],{'enabled':False})
