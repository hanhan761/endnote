import concurrent.futures
import json
import re
import subprocess
import sys
import os
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request,urlopen
from endnote.service import APIError,Settings,Store
from endnote.server import Server
from endnote.client import Client

class Behavior(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.now=1700000000.
        self.sent=[]
        self.cfg=Settings(str(Path(self.tmp.name)/"test.db"),mail_enabled=True,signup_enabled=True)
        self.store=Store(self.cfg,lambda *args:self.sent.append(args),lambda:self.now)
        self.key=self.signup("a@example.com","1.2.3.4")
    def tearDown(self): self.tmp.cleanup()
    def signup(self,address,ip):
        self.store.request_verification(address,ip)
        self.store.deliver_one()
        token=re.search(r"\n\n([A-Za-z0-9_-]{43})\n",self.sent[-1][2]).group(1)
        key=self.store.verify(address,token,ip)["api_key"]
        self.store.deliver_one()  # Drain the first-binding notification.
        return key
    def task(self,**config):
        return self.store.create_task(self.key,dict(name="test",notify_start=False,**config))
    def event(self,task,kind,event_id="event",**data):
        return self.store.event(task["task_key"],task["id"],dict(event_id=event_id,type=kind,**data))
    def count(self,task,kind=None):
        with self.store.db() as c:
            query="SELECT count(*) FROM notices WHERE task=?"
            args=[task["id"]]
            if kind: query+=" AND kind=?";args.append(kind)
            return c.execute(query,args).fetchone()[0]
    def test_verification_single_use_and_keys_hashed(self):
        with self.store.db() as c:
            raw=c.execute("SELECT key_hash FROM accounts").fetchone()[0]
            self.assertNotEqual(raw,self.key)
            self.assertFalse(c.execute("SELECT * FROM challenges").fetchall())
            self.assertTrue(all(not x[0] for x in c.execute("SELECT body FROM notices WHERE kind='verification'")))
        with self.assertRaises(APIError): self.store.verify("a@example.com","wrong","1.2.3.4")
    def test_first_binding_sends_success_mail_once(self):
        binding=[x for x in self.sent if x[1]=="[endnote] 邮箱绑定成功"]
        self.assertEqual(len(binding),1)
        self.assertEqual(binding[0][0],"a@example.com")
        self.assertNotIn(self.key,binding[0][2])
        self.signup("a@example.com","1.2.3.4")
        self.assertEqual(len([x for x in self.sent if x[1]=="[endnote] 邮箱绑定成功"]),1)

    def test_owner_console_enrollment_hash_only_and_one_test_mail(self):
        from scripts.enroll_owner import enroll_owner
        from endnote.service import digest
        key="en_account_owner_test_key"
        result=enroll_owner(self.store,"owner@example.com",digest(key))
        self.assertEqual(result["binding_test"],"queued")
        self.assertEqual(self.store.list_tasks(key),{"tasks":[]})
        result=enroll_owner(self.store,"owner@example.com",digest(key))
        self.assertEqual(result["binding_test"],"already_requested")
        with self.store.db() as c:
            row=c.execute("SELECT key_hash FROM accounts WHERE email='owner@example.com'").fetchone()
            self.assertEqual(row[0],digest(key))
            self.assertEqual(c.execute("SELECT count(*) FROM notices WHERE owner=? AND kind='binding'",(result["account_id"],)).fetchone()[0],1)
        with self.assertRaises(ValueError):enroll_owner(self.store,"owner@example.com",key)

    def test_quick_entry_no_verification_and_isolated_same_recipient(self):
        one=self.store.quick_task({"email":"quick@example.com","name":"实验一"},"2.2.2.2")
        two=self.store.quick_task({"email":"quick@example.com","name":"实验二"},"3.3.3.3")
        self.assertEqual(self.store.task_detail(one["task_key"],one["id"])["name"],"实验一")
        with self.assertRaises(APIError):self.store.task_detail(one["task_key"],two["id"])
        self.event(one,"succeeded")
        with self.store.db() as c:
            notice=c.execute("SELECT recipient,body FROM notices WHERE task=?",(one["id"],)).fetchone()
            self.assertEqual(notice[0],"quick@example.com")
            self.assertIn("/unsubscribe/",notice[1])
            self.assertNotIn("quick@example.com",notice[1])
        self.store.delete_task(two["task_key"],two["id"])
        with self.assertRaises(APIError):self.store.task_detail(two["task_key"],two["id"])

    def test_blacklist_stops_all_tasks_and_future_mail(self):
        owner_task=self.task()
        guest=self.store.quick_task({"email":"a@example.com","name":"公开实验"},"2.2.2.2")
        self.event(owner_task,"metric",metrics={"loss":.5})
        with self.store.db() as c:
            token=c.execute("SELECT token FROM mail_preferences LIMIT 1").fetchone()[0]
            self.store.queue(c,None,None,"a@example.com","test","test","test")
        self.assertTrue(self.store.unsubscribe(token)["blocked"])
        self.assertTrue(self.store.unsubscribe(token)["blocked"])
        self.assertEqual(self.store.task_detail(self.key,owner_task["id"])["status"],"cancelled")
        self.assertEqual(self.store.task_detail(guest["task_key"],guest["id"])["status"],"cancelled")
        with self.store.db() as c:
            self.assertEqual(c.execute("SELECT count(*) FROM notices WHERE state='pending'").fetchone()[0],0)
        for action in [lambda:self.store.quick_task({"email":"A@EXAMPLE.COM","name":"test"},"9.9.9.9"),lambda:self.task(),lambda:self.store.request_verification("a@example.com","1.1.1.1")]:
            with self.assertRaises(APIError) as e:action()
            self.assertEqual(e.exception.status,403)
        with self.assertRaises(APIError):self.store.unsubscribe("bad-token")

    def test_guest_limits_fixed_content_and_recipient_budget(self):
        task=self.store.quick_task({"email":"quick@example.com","name":"实验","subject":"ignored","body":"ignored"},"2.2.2.2")
        detail=self.store.task_detail(task["task_key"],task["id"])
        self.assertNotEqual(detail["config"]["subject"],"ignored")
        with self.assertRaises(APIError):self.store.quick_task({"email":"other@example.com","name":"https://spam.example"},"2.2.2.2")
        for i in range(2):self.store.quick_task({"email":"quick@example.com","name":"实验"},"2.2.2.2")
        with self.assertRaises(APIError) as e:self.store.quick_task({"email":"quick@example.com","name":"实验"},"2.2.2.2")
        self.assertEqual(e.exception.status,429)
        for i in range(4):
            with self.store.db() as c:self.store.queue(c,None,None,"quick@example.com","x","x","test")
        # Recipient quota applies to every quick-entry notice, not just per-task owners.
        with self.store.db() as c:
            owner=c.execute("SELECT owner FROM tasks WHERE id=?",(task["id"],)).fetchone()[0]
            c.execute("UPDATE notices SET owner=? WHERE recipient='quick@example.com'",(owner,))
        for _ in range(5):self.store.deliver_one()
        self.assertEqual(len([x for x in self.sent if x[0]=="quick@example.com"]),3)

    def test_start_mail_and_dashboard_scope_are_recipient_only(self):
        owner=self.store.create_task(self.key,{'name':'账号实验'})
        guest=self.store.quick_task({'email':'A@EXAMPLE.COM','name':'公开实验'},'6.6.6.6')
        other=self.store.quick_task({'email':'other@example.com','name':'其他邮箱'},'7.7.7.7')
        with self.store.db() as c:
            row=c.execute("SELECT subject,body FROM notices WHERE task=? AND kind='started'",(owner['id'],)).fetchone()
        self.assertIn('[开始]',row['subject'])
        self.assertIn(owner['id'][:8],row['subject'])
        token=re.search(r'/dashboard/([A-Za-z0-9_-]{43})',row['body']).group(1)
        self.assertNotIn(token,json.dumps(owner))
        self.assertNotIn(token,json.dumps(self.store.task_detail(self.key,owner['id'])))
        result=self.store.dashboard(token)
        self.assertEqual({x['id'] for x in result['tasks']},{owner['id'],guest['id']})
        self.assertNotIn('key_hash',json.dumps(result));self.assertNotIn('task_key',json.dumps(result))
        self.assertEqual(self.count(owner,'started'),1)
        self.store.tick();self.store.tick()
        self.assertEqual(self.count(owner,'started'),1)
        with self.assertRaises(APIError):self.store.dashboard('bad-token')
        with self.assertRaises(APIError):self.store.dashboard('x'*43)
        silent=self.store.create_task(self.key,{'name':'不通知开始','notify_start':False})
        self.assertEqual(self.count(silent,'started'),0)
        self.now+=301
        result=self.store.dashboard(token)
        self.assertTrue(next(x for x in result['tasks'] if x['id']==owner['id'])['outage'])
        with self.store.db() as c:
            block=c.execute("SELECT token FROM mail_preferences WHERE recipient_hash=?",(__import__('endnote.service',fromlist=['digest']).digest('a@example.com'),)).fetchone()[0]
        self.store.unsubscribe(block)
        self.assertTrue(self.store.dashboard(token)['blocked'])

    def test_read_snapshot_does_not_block_event_writes(self):
        task=self.task()
        with self.store.db(read_only=True) as reader:
            reader.execute('SELECT count(*) FROM tasks').fetchone()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                result=pool.submit(self.event,task,'heartbeat').result(timeout=1)
                self.assertTrue(result['ok'])

    def test_start_notice_wakes_idle_worker(self):
        from endnote.server import worker
        stop=threading.Event();ready=threading.Event();delivered=threading.Event()
        original_tick=self.store.tick
        def tick():original_tick();ready.set()
        self.store.tick=tick
        self.store.sender=lambda *args:delivered.set()
        self.store.wakeup.clear()
        thread=threading.Thread(target=worker,args=(self.store,stop),daemon=True);thread.start()
        try:
            self.assertTrue(ready.wait(1))
            self.store.create_task(self.key,{'name':'立即提醒'})
            self.assertTrue(delivered.wait(1),'idle worker should wake without waiting for its 5-second poll')
        finally:stop.set();self.store.wakeup.set();thread.join(2)

    def test_dashboard_pagination_includes_all_retained_tasks(self):
        task=self.store.create_task(self.key,{'name':'分页实验'})
        with self.store.db() as c:
            row=c.execute('SELECT * FROM tasks WHERE id=?',(task['id'],)).fetchone()
            body=c.execute("SELECT body FROM notices WHERE task=? AND kind='started'",(task['id'],)).fetchone()[0]
            for i in range(201):
                c.execute("INSERT INTO tasks(id,owner,key_hash,name,status,created,heartbeat,config,finished) VALUES(?,?,?,?,?,?,?,?,?)",(f'{i:032x}',row['owner'],f'hash-{i}',f'历史实验 {i}','succeeded',self.now-i-1,self.now,row['config'],self.now))
        token=re.search(r'/dashboard/([A-Za-z0-9_-]{43})',body).group(1)
        first=self.store.dashboard(token);second=self.store.dashboard(token,200)
        self.assertEqual(first['total'],202)
        self.assertEqual(len(first['tasks']),200);self.assertTrue(first['has_more'])
        self.assertEqual(len(second['tasks']),2);self.assertFalse(second['has_more'])
        self.assertEqual(first['tasks'][0]['id'],task['id'])
        self.assertEqual(len({x['id'] for x in first['tasks']+second['tasks']}),202)
        with self.assertRaises(APIError):self.store.dashboard(token,-1)

    def test_dashboard_samples_are_bounded_and_survive_restart(self):
        task=self.store.create_task(self.key,{'name':'趋势测试'})
        for i in range(125):
            self.now+=31;self.event(task,'metric',event_id=str(i),metrics={'loss':1/(i+1),'epoch':i})
        with self.store.db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM samples WHERE task=?',(task['id'],)).fetchone()[0],120)
            body=c.execute("SELECT body FROM notices WHERE task=? AND kind='started'",(task['id'],)).fetchone()[0]
        token=re.search(r'/dashboard/([A-Za-z0-9_-]{43})',body).group(1)
        data=Store(self.cfg,clock=lambda:self.now).dashboard(token)['tasks'][0]
        self.assertEqual(len(data['trend']),60)
        self.assertEqual(data['metrics']['epoch'],124)
        self.assertEqual(data['trend'][-1]['value'],1/125)
        self.store.delete_task(self.key,task['id'])
        with self.store.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM samples').fetchone()[0],0)

    def test_signup_limits_prevent_repeated_mail(self):
        for _ in range(2): self.store.request_verification("a@example.com","1.2.3.4")
        with self.assertRaises(APIError) as e: self.store.request_verification("a@example.com","1.2.3.4")
        self.assertEqual(e.exception.status,429)
    def test_isolation_and_scoped_task_key(self):
        task=self.task()
        other=self.signup("b@example.com","5.6.7.8")
        with self.assertRaises(APIError) as e: self.store.task_detail(other,task["id"])
        self.assertEqual(e.exception.status,404)
        for action in [lambda:self.store.list_tasks(task["task_key"]),lambda:self.store.delete_task(task["task_key"],task["id"]),lambda:self.store.create_task(task["task_key"],{"name":"x"})]:
            with self.assertRaises(APIError): action()
        second=self.task()
        with self.assertRaises(APIError): self.store.event(task["task_key"],second["id"],{"event_id":"x","type":"failed"})
        self.assertTrue(self.event(task,"heartbeat")["ok"])
    def test_terminal_idempotency_and_immutable_completion(self):
        task=self.task()
        self.event(task,"failed",message="command failed")
        self.assertTrue(self.event(task,"failed")["duplicate"])
        self.assertEqual(self.count(task),1)
        with self.assertRaises(APIError) as e: self.event(task,"heartbeat",event_id="late")
        self.assertEqual(e.exception.status,409)
        self.assertEqual(self.store.task_detail(self.key,task["id"])["status"],"failed")
    def test_concurrent_terminal_events_send_once(self):
        task=self.task()
        def send(_):
            try: return self.event(task,"succeeded",event_id="same")
            except APIError as e: return e.status
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(send,range(8)))
        self.assertEqual(sum(isinstance(x,dict) and not x["duplicate"] for x in results),1)
        self.assertEqual(self.count(task),1)
    def test_heartbeat_outage_rearms_but_cools_down(self):
        task=self.task(heartbeat_timeout=30)
        self.now+=31;self.store.tick();self.store.tick()
        self.assertEqual(self.count(task,"heartbeat_timeout"),1)
        self.event(task,"heartbeat")
        self.now+=31;self.store.tick()
        self.assertEqual(self.count(task,"heartbeat_timeout"),1)
        self.now+=901;self.store.tick()
        self.assertEqual(self.count(task,"heartbeat_timeout"),2)
    def test_runtime_and_metrics_trigger_once(self):
        task=self.task(runtime_timeout=60,rules=[{"metric":"loss","op":"lt","value":.01}])
        self.event(task,"metric",metrics={"loss":.005})
        self.event(task,"metric",event_id="second",metrics={"loss":.004})
        self.assertEqual(self.count(task),1)
        self.now+=61;self.store.tick();self.store.tick()
        self.assertEqual(self.count(task,"runtime_timeout"),1)
    def test_mail_identifies_experiment_and_trigger_reason(self):
        for quick in [False,True]:
            task=self.store.quick_task({"email":"titles@example.com","name":"模型 seed42 第3次"},"7.7.7.7") if quick else self.store.create_task(self.key,{"name":"模型 seed42 第3次"})
            self.event(task,"succeeded")
            with self.store.db() as c:
                row=c.execute("SELECT subject,body FROM notices WHERE task=? AND kind!='started'",(task["id"],)).fetchone()
            self.assertEqual(row[0],"[endnote][成功] 模型 seed42 第3次 · #"+task["id"][:8])
            self.assertIn("发送原因：实验主动报告成功结束。",row[1])
            self.assertIn(task["id"],row[1])
            self.assertIn("创建时间：",row[1])
        task=self.task(heartbeat_timeout=30)
        # Existing stored default templates also adopt the new subject.
        with self.store.db() as c:
            cfg=json.loads(c.execute("SELECT config FROM tasks WHERE id=?",(task["id"],)).fetchone()[0])
            cfg['subject']='[endnote] $name · $reason'
            c.execute("UPDATE tasks SET config=? WHERE id=?",(json.dumps(cfg),task["id"]))
        self.now+=31;self.store.tick()
        with self.store.db() as c:
            row=c.execute("SELECT subject,body FROM notices WHERE task=?",(task["id"],)).fetchone()
        self.assertIn("[中断]",row[0])
        self.assertIn("超过 30 秒未收到新心跳",row[1])
        self.assertIn("最后心跳：",row[1])
        for kind,label,config in [('failed','失败',{}),('runtime_timeout','超时',{'runtime_timeout':30}),('metric','指标达标',{'rules':[{'metric':'loss','op':'lt','value':.01}]})]:
            task=self.task(**config)
            if kind=='runtime_timeout':self.now+=31;self.store.tick()
            else:self.event(task,kind,metrics={'loss':.005})
            with self.store.db() as c:
                row=c.execute("SELECT subject,body FROM notices WHERE task=? AND kind=?",(task["id"],'loss lt 0.01' if kind=='metric' else kind)).fetchone()
            self.assertIn('['+label+']',row[0])
            self.assertIn('发送原因：',row[1])

    def test_custom_mail_plain_text_and_header_safety(self):
        task=self.task(subject="$name $message",body="$reason $metrics")
        self.event(task,"succeeded",message="hello\nBcc: bad@example.com")
        with self.store.db() as c:
            row=c.execute("SELECT subject,recipient FROM notices WHERE task=?",(task["id"],)).fetchone()
            self.assertNotIn("\n",row[0]);self.assertEqual(row[1],"a@example.com")
        with self.assertRaises(APIError):self.task(subject="subject\nBcc: bad@example.com")
        with self.assertRaises(APIError):self.task(body="$invalid")
    def test_invalid_rules_and_nan_are_rejected(self):
        for rules in [[{"metric":"loss","op":"exec","value":1}],[{"metric":"x","op":"lt","value":float("nan")}],[{"metric":"x","op":[],"value":1}]]:
            with self.assertRaises(APIError): self.task(rules=rules)
        task=self.task()
        with self.assertRaises(APIError): self.event(task,"metric",metrics={"loss":float("inf")})
    def test_queue_survives_restart_and_retry(self):
        task=self.task()
        self.event(task,"succeeded")
        def failed(*args): raise RuntimeError("sensitive SMTP response")
        restarted=Store(self.cfg,failed,lambda:self.now)
        restarted.deliver_one()
        detail=restarted.task_detail(self.key,task["id"])
        self.assertEqual(detail["notifications"][0]["error"],"RuntimeError")
        self.assertEqual(detail["notifications"][0]["state"],"pending")
        self.now+=31
        restarted.sender=lambda *args:self.sent.append(args)
        restarted.deliver_one()
        self.assertEqual(restarted.task_detail(self.key,task["id"])["notifications"][0]["state"],"sent")
    def test_full_mail_quota_preserves_events_and_deferred_notifications(self):
        self.cfg.mail_per_user_day=1
        self.now+=86400  # First-binding mail consumed the initial daily slot.
        one=self.task();self.event(one,"succeeded")
        self.store.deliver_one()
        two=self.task();self.event(two,"failed")
        self.store.deliver_one()
        self.assertEqual(self.store.task_detail(self.key,two["id"])["status"],"failed")
        self.assertEqual(self.store.task_detail(self.key,two["id"])["notifications"][0]["state"],"pending")
        self.now+=86401;self.store.deliver_one()
        self.assertEqual(self.store.task_detail(self.key,two["id"])["notifications"][0]["state"],"sent")
    def test_queue_full_keeps_transient_metric_snapshot(self):
        task=self.task(rules=[{"metric":"loss","op":"lt","value":.01}])
        with self.store.db() as c:
            now=self.now
            c.executemany("INSERT INTO notices(id,recipient,subject,body,kind,next_at,created) VALUES(?,?,?,?,?,?,?)",[("filler"+str(i),"a@example.com","x","x","test",now,now) for i in range(2000)])
        self.event(task,"metric",metrics={"loss":.005})
        self.event(task,"metric",event_id="later",metrics={"loss":.5})
        self.assertEqual(len(self.store.task_detail(self.key,task["id"])["deferred_notifications"]),1)
        with self.store.db() as c:c.execute("DELETE FROM notices WHERE id LIKE 'filler%'")
        self.store.tick()
        self.assertEqual(self.count(task),1)
        with self.store.db() as c:
            body=c.execute("SELECT body FROM notices WHERE task=?",(task["id"],)).fetchone()[0]
            self.assertIn("0.005",body)
        self.assertEqual(self.store.task_detail(self.key,task["id"])["deferred_notifications"],[])

    def test_deletion_revokes_task_key_and_pending_mail(self):
        task=self.task();self.event(task,"succeeded")
        self.store.delete_task(self.key,task["id"])
        self.assertEqual(self.count(task),0)
        with self.assertRaises(APIError): self.event(task,"heartbeat")
    def test_rotate_revokes_previous_account_key(self):
        new=self.store.rotate(self.key)["api_key"]
        with self.assertRaises(APIError):self.store.list_tasks(self.key)
        self.assertEqual(self.store.list_tasks(new),{"tasks":[]})
    def test_http_auth_origin_body_and_static(self):
        server=Server(("127.0.0.1",0),self.store)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base="http://127.0.0.1:"+str(server.server_address[1])+"/endnote"
        def call(route,data=None,headers=None):
            req=Request(base+route,json.dumps(data).encode() if data is not None else None,headers or {})
            try:
                with urlopen(req,timeout=3) as r:return r.status,r.read()
            except HTTPError as e:return e.code,e.read()
        try:
            self.assertEqual(call("/")[0],200)
            self.assertEqual(call("/v1/tasks")[0],401)
            self.assertEqual(call("/v1/auth/request",{"email":"a@example.com"},{"Content-Type":"application/json","Origin":"https://evil.example"})[0],403)
            self.assertEqual(call("/v1/tasks",{"name":"x"*20000},{"Content-Type":"application/json"})[0],413)
            status,payload=call("/v1/quick/tasks",{"email":"httpquick@example.com","name":"HTTP测试"},{"Content-Type":"application/json"})
            self.assertEqual(status,201,payload)
            quick=json.loads(payload)
            self.assertEqual(call("/v1/tasks/"+quick["id"],headers={"Authorization":"Bearer "+quick["task_key"]})[0],200)
            with self.store.db() as c:
                token=c.execute("SELECT token FROM mail_preferences WHERE recipient_hash=?",(__import__('endnote.service',fromlist=['digest']).digest("httpquick@example.com"),)).fetchone()[0]
            self.assertEqual(call("/unsubscribe/"+token)[0],200)
            self.assertEqual(call("/v1/quick/tasks",{"email":"httpquick@example.com","name":"HTTP测试"},{"Content-Type":"application/json"})[0],403)
            public=Client(base)
            with public.experiment("SDK直接使用",email="sdkquick@example.com",heartbeat_timeout=30,heartbeat_interval=5) as public_exp:
                public_exp.metric(loss=.005)
            self.assertEqual(public.request("/v1/tasks/"+public_exp.task["id"],key=public_exp.task["task_key"])["status"],"succeeded")
            with self.store.db() as c:
                dashboard_body=c.execute("SELECT body FROM notices WHERE task=? AND kind='started'",(public_exp.task['id'],)).fetchone()[0]
            dashboard_token=re.search(r'/dashboard/([A-Za-z0-9_-]{43})',dashboard_body).group(1)
            self.assertEqual(call('/dashboard/'+dashboard_token)[0],200)
            status,payload=call('/v1/dashboard/'+dashboard_token)
            self.assertEqual(status,200)
            self.assertEqual(json.loads(payload)['tasks'][0]['id'],public_exp.task['id'])
            self.assertEqual(call('/v1/dashboard/'+'x'*43)[0],404)
            self.assertEqual(call('/v1/dashboard/'+dashboard_token+'?offset=bad')[0],400)
            self.assertEqual(call('/v1/dashboard/'+dashboard_token,headers={'Origin':'https://evil.example'})[0],403)
            for asset in ['/dashboard.js','/dashboard.css']:self.assertEqual(call(asset)[0],200)
            import gzip
            request=Request(base+'/dashboard.js',headers={'Accept-Encoding':'gzip'})
            with urlopen(request,timeout=3) as response:
                self.assertEqual(response.headers['Content-Encoding'],'gzip')
                self.assertIn(b'function render',gzip.decompress(response.read()))
            with urlopen(Request(base+'/dashboard.js',headers={'Accept-Encoding':'gzip;q=0'}),timeout=3) as response:self.assertIsNone(response.headers['Content-Encoding'])
            client=Client(base,self.key)
            with client.experiment("python",heartbeat_timeout=30,heartbeat_interval=5) as exp:
                exp.metric(loss=.005)
            self.assertEqual(client.request("/v1/tasks/"+exp.task["id"])["status"],"succeeded")
            env=dict(os.environ,ENDNOTE_URL=base,ENDNOTE_API_KEY=self.key)
            flags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0
            result=subprocess.run([sys.executable,"-m","endnote.client","run","--name","failed-command","--heartbeat-timeout","30","--heartbeat-interval","5","--",sys.executable,"-c","import sys;sys.exit(7)"],env=env,capture_output=True,text=True,creationflags=flags,timeout=15)
            self.assertEqual(result.returncode,7,result.stderr)
            tasks=client.request("/v1/tasks")["tasks"]
            self.assertEqual(next(x for x in tasks if x["name"]=="failed-command")["status"],"failed")
            self.assertNotIn("could not report completion",result.stderr)
            with self.assertRaises(ValueError):Client("http://untrusted.example",self.key)
        finally:server.shutdown();server.server_close();thread.join()

if __name__=="__main__":unittest.main()
