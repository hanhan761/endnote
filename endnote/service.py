"""Bounded, durable experiment notifications. Python 3.10+, no dependencies."""
import contextlib
import hashlib
import hmac
import json
import math
import re
import secrets
import smtplib
import sqlite3
import ssl
import time
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from string import Template

EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_\x60{|}~-]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?\.[A-Za-z]{2,63}")
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,63}")
OPERATORS = {"gt": lambda a,b:a>b, "gte": lambda a,b:a>=b,
             "lt": lambda a,b:a<b, "lte": lambda a,b:a<=b, "eq": lambda a,b:a==b}
DEFAULT_SUBJECT = "[endnote][$reason] $name · #$task_id"
LEGACY_SUBJECT = "[endnote] $name · $reason"
REASON_LABELS = {"succeeded":"成功", "failed":"失败", "heartbeat_timeout":"中断", "runtime_timeout":"超时"}

NOTIFY = {"succeeded", "failed", "heartbeat_timeout", "runtime_timeout"}
TERMINAL = {"succeeded", "failed", "cancelled"}

class APIError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

def text(value, limit, label, empty=False):
    if not isinstance(value, str) or len(value)>limit or (not empty and not value.strip()):
        raise APIError(400, f"invalid {label}")
    if any(ord(x)<32 and x not in '\n\t' for x in value):
        raise APIError(400, f"invalid {label}")
    return value

def number(value, low, high, label):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not low<=value<=high:
        raise APIError(400, f"invalid {label}")
    return value

def email(value):
    if not isinstance(value,str) or len(value)>254 or not EMAIL.fullmatch(value):
        raise APIError(400,"invalid email")
    return value.lower()

@dataclass
class Settings:
    database: str
    public_url: str = "http://127.0.0.1:8380/endnote"
    mail_enabled: bool = False
    signup_enabled: bool = False
    mail_per_day: int = 300
    mail_per_user_day: int = 30
    verification_per_day: int = 60
    max_accounts: int = 500
    max_tasks: int = 10000

class Store:
    def __init__(self, settings, sender=None, clock=time.time):
        self.settings, self.sender, self.clock = settings, sender, clock
        self.worker_last = self.clock()
        Path(settings.database).parent.mkdir(parents=True,exist_ok=True)
        with self.db() as c:
            c.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY,email TEXT UNIQUE NOT NULL,key_hash TEXT UNIQUE NOT NULL,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS mail_preferences(recipient_hash TEXT PRIMARY KEY,token TEXT UNIQUE NOT NULL,blocked INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS guest_accounts(id TEXT PRIMARY KEY REFERENCES accounts(id),recipient TEXT NOT NULL,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS challenges(email TEXT PRIMARY KEY,token_hash TEXT NOT NULL,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,owner TEXT NOT NULL REFERENCES accounts(id),key_hash TEXT UNIQUE NOT NULL,name TEXT NOT NULL,status TEXT NOT NULL,created REAL NOT NULL,heartbeat REAL NOT NULL,heartbeat_seq INTEGER NOT NULL DEFAULT 0,config TEXT NOT NULL,message TEXT NOT NULL DEFAULT '',metrics TEXT NOT NULL DEFAULT '{}',finished REAL);
            CREATE INDEX IF NOT EXISTS task_owner ON tasks(owner,created);
            CREATE TABLE IF NOT EXISTS events(task TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,event_id TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(task,event_id));
            CREATE TABLE IF NOT EXISTS notices(id TEXT PRIMARY KEY,owner TEXT REFERENCES accounts(id),task TEXT REFERENCES tasks(id) ON DELETE CASCADE,recipient TEXT NOT NULL,subject TEXT NOT NULL,body TEXT NOT NULL,kind TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,next_at REAL NOT NULL,created REAL NOT NULL,sent REAL,error TEXT,expires REAL);
            CREATE INDEX IF NOT EXISTS notice_queue ON notices(state,next_at);
            CREATE TABLE IF NOT EXISTS triggers(task TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,reason TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(task,reason));
            CREATE TABLE IF NOT EXISTS deferred(id TEXT PRIMARY KEY,owner TEXT NOT NULL REFERENCES accounts(id),task TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,recipient TEXT NOT NULL,subject TEXT NOT NULL,body TEXT NOT NULL,kind TEXT NOT NULL,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS limits(bucket TEXT PRIMARY KEY,count INTEGER NOT NULL,expires REAL NOT NULL);
            """)

    @contextlib.contextmanager
    def db(self):
        c=sqlite3.connect(self.settings.database,timeout=5,isolation_level=None)
        c.row_factory=sqlite3.Row
        c.create_function("recipient_hash",1,lambda value:digest(value.lower()),deterministic=True)
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA synchronous=FULL")
        try:
            c.execute("BEGIN IMMEDIATE")
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def limit(self,c,key,maximum,period=86400):
        now=self.clock()
        bucket=f"{key}:{int(now//period)}"
        row=c.execute("SELECT count FROM limits WHERE bucket=?",(bucket,)).fetchone()
        if row and row[0]>=maximum: raise APIError(429,"quota exceeded; retry later")
        c.execute("INSERT INTO limits VALUES(?,1,?) ON CONFLICT(bucket) DO UPDATE SET count=count+1",(bucket,now+period*2))

    def auth(self,c,key,task_id=None):
        if not isinstance(key,str) or len(key)>128: raise APIError(401,"invalid API key")
        account=c.execute("SELECT * FROM accounts WHERE key_hash=?",(digest(key),)).fetchone()
        if account:
            self.limit(c,'api:'+account['id'],240,60)
            if task_id:
                task=c.execute("SELECT * FROM tasks WHERE id=? AND owner=?",(task_id,account['id'])).fetchone()
                if not task: raise APIError(404,"task not found")
                return account,task
            return account,None
        if task_id:
            task=c.execute("SELECT * FROM tasks WHERE id=? AND key_hash=?",(task_id,digest(key))).fetchone()
            if task:
                self.limit(c,'event:'+task['id'],120,60)
                return None,task
        raise APIError(401,"invalid API key")

    def blocked(self,c,address):
        row=c.execute('SELECT blocked FROM mail_preferences WHERE recipient_hash=?',(digest(address.lower()),)).fetchone()
        return bool(row and row[0])

    def unsubscribe(self,token):
        if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):raise APIError(404,'link not found')
        with self.db() as c:
            row=c.execute('SELECT recipient_hash FROM mail_preferences WHERE token=?',(token,)).fetchone()
            if not row:raise APIError(404,'link not found')
            target=row[0]
            c.execute('UPDATE mail_preferences SET blocked=1 WHERE recipient_hash=?',(target,))
            c.execute("UPDATE notices SET state='blocked',body='' WHERE recipient_hash(recipient)=? AND state='pending'",(target,))
            c.execute('DELETE FROM deferred WHERE recipient_hash(recipient)=?',(target,))
            c.execute('DELETE FROM challenges WHERE recipient_hash(email)=?',(target,))
            c.execute("UPDATE tasks SET status='cancelled',finished=? WHERE status='running' AND owner IN (SELECT a.id FROM accounts a LEFT JOIN guest_accounts g ON g.id=a.id WHERE recipient_hash(COALESCE(g.recipient,a.email))=?)",(self.clock(),target))
        return {'ok':True,'blocked':True}

    def request_verification(self,address,ip):
        address=email(address)
        if not self.settings.signup_enabled or not self.settings.mail_enabled:
            raise APIError(503,"registration temporarily disabled")
        with self.db() as c:
            if self.blocked(c,address):raise APIError(403,'此邮箱已停止接收通知')
            self.limit(c,'verify-ip:'+digest(ip),5,3600)
            self.limit(c,'verify-email:'+digest(address),3,3600)
            self.limit(c,'verify-global',self.settings.verification_per_day)
        with self.db() as c:
            if c.execute("SELECT count(*) FROM accounts").fetchone()[0]>=self.settings.max_accounts:
                raise APIError(503,"registration capacity reached")
            token=secrets.token_urlsafe(32)
            expires=self.clock()+900
            c.execute("INSERT INTO challenges VALUES(?,?,?) ON CONFLICT(email) DO UPDATE SET token_hash=excluded.token_hash,expires=excluded.expires",(address,digest(token),expires))
            c.execute("UPDATE notices SET state='cancelled',body='' WHERE recipient=? AND kind='verification' AND state='pending'",(address,))
            self.queue(c,None,None,address,"[endnote] 验证邮箱 / Verify email",
                       f"你的 endnote 验证码（15 分钟内有效）：\n\n{token}\n\n请在 {self.settings.public_url}/ 输入此验证码。\n若非你本人操作，请忽略。验证码不得交给他人。\n验证会创建或替换你的账号密钥。",'verification',expires=expires)
        return {"ok":True,"message":"check your mailbox; the latest code expires in 15 minutes"}

    def verify(self,address,token,ip):
        address=email(address)
        text(token,128,'verification code')
        with self.db() as c: self.limit(c,'verify-attempt:'+digest(ip),20,3600)
        with self.db() as c:
            row=c.execute("SELECT * FROM challenges WHERE email=?",(address,)).fetchone()
            if not row or row['expires']<self.clock() or not hmac.compare_digest(row['token_hash'],digest(token)):
                raise APIError(400,"invalid or expired verification code")
            key='en_account_'+secrets.token_urlsafe(32)
            account=c.execute("SELECT id FROM accounts WHERE email=?",(address,)).fetchone()
            if account: c.execute("UPDATE accounts SET key_hash=? WHERE id=?",(digest(key),account['id']))
            else:
                if c.execute("SELECT count(*) FROM accounts").fetchone()[0]>=self.settings.max_accounts: raise APIError(503,"registration capacity reached")
                account_id=secrets.token_hex(16)
                c.execute("INSERT INTO accounts VALUES(?,?,?,?)",(account_id,address,digest(key),self.clock()))
                self.queue(c,account_id,None,address,"[endnote] 邮箱绑定成功",
                           "你的邮箱已成功绑定 endnote。\n\n这是一封首次绑定测试邮件。以后实验完成、失败或满足你选择的提醒条件时，通知将发送到这个邮箱。\n\n复用账号无需再次绑定，正常心跳不会定期发邮件。\n\n管理实验："+self.settings.public_url+"/",'binding')
            c.execute("DELETE FROM challenges WHERE email=?",(address,))
            c.execute("UPDATE notices SET body='',state=CASE WHEN state='pending' THEN 'cancelled' ELSE state END WHERE recipient=? AND kind='verification'",(address,))
        return {"api_key":key,"email":address,"warning":"save this key; it is shown only once"}

    def validate_config(self,data):
        name=text(data.get('name'),100,'task name')
        notify=data.get('notify_on',sorted(NOTIFY))
        if not isinstance(notify,list) or len(notify)>4 or any(not isinstance(x,str) or x not in NOTIFY for x in notify): raise APIError(400,"invalid notify_on")
        hb=number(data.get('heartbeat_timeout',300),30,86400,'heartbeat_timeout')
        runtime=data.get('runtime_timeout')
        if runtime is not None: number(runtime,30,2592000,'runtime_timeout')
        rules=data.get('rules',[])
        if not isinstance(rules,list) or len(rules)>10: raise APIError(400,"at most 10 metric rules")
        checked=[]
        for rule in rules:
            if not isinstance(rule,dict): raise APIError(400,"invalid rule")
            metric=rule.get('metric')
            op=rule.get('op')
            if not isinstance(metric,str) or not NAME.fullmatch(metric) or not isinstance(op,str) or op not in OPERATORS: raise APIError(400,"invalid metric rule")
            value=number(rule.get('value'),-1e100,1e100,'metric threshold')
            checked.append({'metric':metric,'op':op,'value':value})
        subject=text(data.get('subject',DEFAULT_SUBJECT),160,'subject')
        if '\n' in subject or '\t' in subject: raise APIError(400,"subject must be one line")
        body=text(data.get('body','实验：$name\n状态：$status\n触发条件：$reason\n说明：$message\n指标：$metrics\n时间：$time'),4000,'body')
        # Validate templates at creation instead of crashing the background worker.
        for template in [subject,body]:
            try: Template(template).substitute({x:x for x in ['name','status','reason','message','metrics','time','task_id']})
            except (KeyError,ValueError): raise APIError(400,"invalid template; use $name $status $reason $message $metrics $time or $task_id or $")
        config=dict(notify_on=notify,heartbeat_timeout=hb,runtime_timeout=runtime,rules=checked,subject=subject,body=body)
        return name,config

    def create_task(self,key,data):
        name,config=self.validate_config(data)
        with self.db() as c:
            account,_=self.auth(c,key)
            if self.blocked(c,account["email"]):raise APIError(403,"此邮箱已停止接收通知")
            self.limit(c,'create:'+account['id'],100)
            if c.execute("SELECT count(*) FROM tasks WHERE owner=? AND status='running'",(account['id'],)).fetchone()[0]>=20: raise APIError(429,"at most 20 running tasks")
            if c.execute("SELECT count(*) FROM tasks WHERE owner=?",(account['id'],)).fetchone()[0]>=200: raise APIError(429,"delete old tasks before creating more")
            if c.execute("SELECT count(*) FROM tasks").fetchone()[0]>=self.settings.max_tasks: raise APIError(503,"task capacity reached")
            task_id=secrets.token_hex(16)
            task_key='en_task_'+secrets.token_urlsafe(32)
            now=self.clock()
            c.execute("INSERT INTO tasks(id,owner,key_hash,name,status,created,heartbeat,config) VALUES(?,?,?,?,?,?,?,?)",(task_id,account['id'],digest(task_key),name,'running',now,now,json.dumps(config)))
        return {'id':task_id,'task_key':task_key,'status':'running','heartbeat_timeout':config['heartbeat_timeout']}

    def quick_task(self,data,ip):
        if not self.settings.signup_enabled or not self.settings.mail_enabled:raise APIError(503,'service temporarily unavailable')
        address=email(data.get('email'))
        allowed={k:data[k] for k in ['name','notify_on','heartbeat_timeout','runtime_timeout','rules'] if k in data}
        allowed['subject']=DEFAULT_SUBJECT
        allowed['body']='任务：$name\n状态：$status\n触发条件：$reason\n指标：$metrics\n时间：$time'
        name,config=self.validate_config(allowed)
        if any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}',r['metric']) for r in config['rules']):raise APIError(400,'快捷入口指标名只能使用字母、数字和下划线')
        if not re.fullmatch(r'[\w\u4e00-\u9fff ()（）-]{1,60}',name):
            raise APIError(400,'任务名限 60 个字母、汉字、数字、空格或括号，不支持链接')
        with self.db() as c:
            if self.blocked(c,address):raise APIError(403,'此邮箱已停止接收通知')
            self.limit(c,'quick-ip:'+digest(ip),3,3600)
            self.limit(c,'quick-recipient:'+digest(address),3)
            self.limit(c,'quick-global',100)
            if c.execute('SELECT count(*) FROM accounts').fetchone()[0]>=self.settings.max_accounts:raise APIError(503,'service capacity reached')
            owner=secrets.token_hex(16);task_id=secrets.token_hex(16)
            task_key='en_task_'+secrets.token_urlsafe(32);now=self.clock()
            # Separate scopes for every task, including tasks using the same address.
            c.execute('INSERT INTO accounts VALUES(?,?,?,?)',(owner,owner+'@guest.endnote.invalid',digest(secrets.token_urlsafe(32)),now))
            c.execute('INSERT INTO guest_accounts VALUES(?,?,?)',(owner,address,now))
            c.execute('INSERT INTO tasks(id,owner,key_hash,name,status,created,heartbeat,config) VALUES(?,?,?,?,?,?,?,?)',(task_id,owner,digest(task_key),name,'running',now,now,json.dumps(config)))
            if not c.execute("SELECT 1 FROM notices WHERE recipient=? AND kind='binding'",(address,)).fetchone():
                self.queue(c,owner,None,address,'[endnote] 提醒已创建',
                           '这是 endnote 的首次接入测试邮件。有人为这个地址创建了实验提醒。\n\n以后任务完成、失败或满足已选条件时，将向这个地址发送通知。正常心跳不会定时发邮件。\n\n若非你本人操作，可忽略；公开入口限制同一邮箱每天最多 3 次发送尝试。','binding')
        return {'id':task_id,'task_key':task_key,'status':'running','heartbeat_timeout':config['heartbeat_timeout'],'notify_on':config['notify_on']}

    def rotate(self,key):
        with self.db() as c:
            account,_=self.auth(c,key)
            new='en_account_'+secrets.token_urlsafe(32)
            c.execute("UPDATE accounts SET key_hash=? WHERE id=?",(digest(new),account['id']))
        return {'api_key':new}

    def list_tasks(self,key):
        with self.db() as c:
            account,_=self.auth(c,key)
            return {'tasks':[dict(x) for x in c.execute("SELECT id,name,status,created,heartbeat,finished FROM tasks WHERE owner=? ORDER BY created DESC LIMIT 200",(account['id'],))]}

    def task_detail(self,key,task_id):
        with self.db() as c:
            account,task=self.auth(c,key,task_id)
            if not account and not c.execute("SELECT 1 FROM guest_accounts WHERE id=?",(task["owner"],)).fetchone(): raise APIError(403,"account key required")
            item={k:task[k] for k in ['id','name','status','created','heartbeat','message','finished']}
            item['metrics']=json.loads(task['metrics']); item['config']=json.loads(task['config'])
            item['notifications']=[dict(x) for x in c.execute("SELECT id,kind,state,attempts,created,sent,error FROM notices WHERE task=? ORDER BY created DESC LIMIT 50",(task_id,))]
            item['deferred_notifications']=[dict(x) for x in c.execute("SELECT kind,created FROM deferred WHERE task=? ORDER BY created LIMIT 50",(task_id,))]
            return item

    def delete_task(self,key,task_id):
        with self.db() as c:
            account,task=self.auth(c,key,task_id)
            if not account and not c.execute("SELECT 1 FROM guest_accounts WHERE id=?",(task["owner"],)).fetchone(): raise APIError(403,"account key required")
            c.execute("DELETE FROM tasks WHERE id=?",(task_id,))
        return {'ok':True}

    def event(self,key,task_id,data):
        event_id=text(data.get('event_id'),100,'event_id')
        kind=data.get('type')
        if not isinstance(kind,str) or kind not in {'heartbeat','metric','succeeded','failed','cancelled'}: raise APIError(400,"invalid event type")
        message=text(data.get('message',''),2000,'message',empty=True)
        metrics=data.get('metrics',{})
        if not isinstance(metrics,dict) or len(metrics)>30: raise APIError(400,"invalid metrics")
        for k,v in metrics.items():
            if not isinstance(k,str) or not NAME.fullmatch(k): raise APIError(400,"invalid metric name")
            number(v,-1e100,1e100,'metric value')
        with self.db() as c:
            _,task=self.auth(c,key,task_id)
            if c.execute('SELECT 1 FROM guest_accounts WHERE id=?',(task['owner'],)).fetchone():
                if any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}',k) for k in metrics):raise APIError(400,'invalid quick-entry metric name')
                message=''
            if c.execute("SELECT 1 FROM events WHERE task=? AND event_id=?",(task_id,event_id)).fetchone(): return {'ok':True,'duplicate':True,'status':task['status']}
            if task['status'] in TERMINAL: raise APIError(409,"task has already ended")
            now=self.clock()
            c.execute("INSERT INTO events VALUES(?,?,?)",(task_id,event_id,now))
            c.execute("DELETE FROM events WHERE task=? AND event_id NOT IN (SELECT event_id FROM events WHERE task=? ORDER BY created DESC,rowid DESC LIMIT 1000)",(task_id,task_id))
            status=kind if kind in TERMINAL else 'running'
            merged=json.loads(task['metrics']); merged.update(metrics)
            if len(merged)>30: raise APIError(400,"at most 30 distinct metrics per task")
            c.execute("UPDATE tasks SET status=?,heartbeat=?,heartbeat_seq=heartbeat_seq+1,message=?,metrics=?,finished=? WHERE id=?",(status,now,message,json.dumps(merged),now if status in TERMINAL else None,task_id))
            updated=c.execute("SELECT * FROM tasks WHERE id=?",(task_id,)).fetchone()
            config=json.loads(task['config'])
            if kind in config['notify_on']: self.trigger(c,updated,kind,kind)
            for i,rule in enumerate(config['rules']):
                if rule['metric'] in metrics and OPERATORS[rule['op']](metrics[rule['metric']],rule['value']):
                    self.trigger(c,updated,f'metric:{i}',f"{rule['metric']} {rule['op']} {rule['value']}")
            return {'ok':True,'duplicate':False,'status':status}

    def queue(self,c,owner,task,recipient,subject,body,kind,expires=None):
        target=digest(recipient.lower())
        preference=c.execute('SELECT token,blocked FROM mail_preferences WHERE recipient_hash=?',(target,)).fetchone()
        if preference and preference['blocked']:raise APIError(403,'此邮箱已停止接收通知')
        if not preference:
            token=secrets.token_urlsafe(32)
            c.execute('INSERT INTO mail_preferences VALUES(?,?,0,?)',(target,token,self.clock()))
        else:token=preference['token']
        # A recipient-held revocation link; never returned through the task API.
        footer='\n\n停止接收并屏蔽此邮箱（点击后取消待发邮件并停止相关提醒）：\n'+self.settings.public_url+'/unsubscribe/'+token
        body=body+footer
        if c.execute("SELECT count(*) FROM notices WHERE state='pending'").fetchone()[0]>=2000: raise APIError(429,"mail queue capacity reached")
        now=self.clock()
        c.execute("INSERT INTO notices(id,owner,task,recipient,subject,body,kind,next_at,created,expires) VALUES(?,?,?,?,?,?,?,?,?,?)",(secrets.token_hex(16),owner,task,recipient,subject,body,kind,now,now,expires))

    def trigger(self,c,task,identity,reason):
        if c.execute("SELECT 1 FROM triggers WHERE task=? AND reason=?",(task['id'],identity)).fetchone(): return False
        config=json.loads(task['config'])
        recipient=c.execute("SELECT COALESCE(g.recipient,a.email) FROM accounts a LEFT JOIN guest_accounts g ON g.id=a.id WHERE a.id=?",(task['owner'],)).fetchone()[0]
        if self.blocked(c,recipient):return False
        fields=dict(name=task['name'],status=task['status'],reason=reason,message=task['message'],metrics=task['metrics'],time=time.strftime('%Y-%m-%d %H:%M:%S UTC',time.gmtime(self.clock())))
        fields['task_id']=task['id'][:8]
        template=config['subject']
        if template in {DEFAULT_SUBJECT,LEGACY_SUBJECT}:
            template=DEFAULT_SUBJECT
            subject_fields=dict(fields,reason=REASON_LABELS.get(reason,'指标达标'))
        else: subject_fields=fields
        subject=Template(template).safe_substitute(subject_fields).replace('\n',' ').replace('\r',' ')[:200]
        body=Template(config['body']).safe_substitute(fields)[:10000]
        metric_reason=reason
        if reason not in REASON_LABELS:
            parts=reason.split(' ')
            if len(parts)==3:
                metric,op,threshold=parts
                operation={'gt':'大于','gte':'大于等于','lt':'小于','lte':'小于等于','eq':'等于'}.get(op,op)
                metric_reason=f"{metric} {operation} {threshold}（上报值：{json.loads(task['metrics']).get(metric)}）"
        explanation={'succeeded':'实验主动报告成功结束。','failed':'实验主动报告失败（例如命令非零退出或代码异常）。','heartbeat_timeout':f"超过 {config['heartbeat_timeout']:g} 秒未收到新心跳；最后心跳："+time.strftime('%Y-%m-%d %H:%M:%S UTC',time.gmtime(task['heartbeat']))+'。这表示上报失联，可能是进程退出、卡住或网络中断。','runtime_timeout':f"实验运行时长达到设定上限 {config['runtime_timeout']} 秒。"}.get(reason,'上报指标满足设定规则：'+metric_reason+'。')
        body='发送原因：'+explanation+'\n\n'+body
        body+='\n任务 ID：'+task['id']+'\n创建时间：'+time.strftime('%Y-%m-%d %H:%M:%S UTC',time.gmtime(task['created']))
        c.execute("SAVEPOINT enqueue")
        try:
            self.queue(c,task['owner'],task['id'],recipient,subject,body,reason)
        except APIError as e:
            c.execute("ROLLBACK TO enqueue")
            if e.status!=429: raise
            # Persist the rendered snapshot even when the hot mail queue is full.
            c.execute("INSERT INTO deferred VALUES(?,?,?,?,?,?,?,?)",(secrets.token_hex(16),task['owner'],task['id'],recipient,subject,body,reason,self.clock()))
        finally: c.execute("RELEASE enqueue")
        c.execute("INSERT INTO triggers VALUES(?,?,?)",(task['id'],identity,self.clock()))
        return True

    def tick(self):
        now=self.clock()
        with self.db() as c:
            tasks=c.execute("SELECT * FROM tasks WHERE status='running' OR (status IN ('succeeded','failed') AND finished>?) ORDER BY created LIMIT 10000",(now-86400,)).fetchall()
            for task in tasks:
                cfg=json.loads(task['config'])
                if task['status'] in {'succeeded','failed'} and task['status'] in cfg['notify_on']:
                    self.trigger(c,task,task['status'],task['status'])
                if task['status']!='running': continue
                if 'heartbeat_timeout' in cfg['notify_on'] and now-task['heartbeat']>=cfg['heartbeat_timeout']:
                    last=c.execute("SELECT max(created) FROM triggers WHERE task=? AND reason LIKE 'heartbeat:%'",(task['id'],)).fetchone()[0]
                    if last is None or now-last>=900:
                        self.trigger(c,task,f"heartbeat:{task['heartbeat_seq']}",'heartbeat_timeout')
                if 'runtime_timeout' in cfg['notify_on'] and cfg['runtime_timeout'] is not None and now-task['created']>=cfg['runtime_timeout']:
                    self.trigger(c,task,'runtime_timeout','runtime_timeout')
            for row in c.execute("SELECT * FROM deferred ORDER BY created LIMIT 100").fetchall():
                try:self.queue(c,row['owner'],row['task'],row['recipient'],row['subject'],row['body'],row['kind'])
                except APIError as e:
                    if e.status!=429:raise
                    break
                c.execute("DELETE FROM deferred WHERE id=?",(row['id'],))
            c.execute("DELETE FROM limits WHERE expires<?",(now,))
            c.execute("DELETE FROM challenges WHERE expires<?",(now,))
            c.execute("UPDATE notices SET state='expired',body='' WHERE state='pending' AND expires IS NOT NULL AND expires<?",(now,))
            c.execute("DELETE FROM notices WHERE created<? AND state!='pending'",(now-30*86400,))
            c.execute("DELETE FROM tasks WHERE finished IS NOT NULL AND finished<?",(now-30*86400,))
            for row in c.execute("SELECT id FROM guest_accounts WHERE created<? AND id NOT IN (SELECT owner FROM tasks)",(now-30*86400,)).fetchall():
                c.execute("DELETE FROM notices WHERE owner=?",(row[0],))
                c.execute("DELETE FROM guest_accounts WHERE id=?",(row[0],))
                c.execute("DELETE FROM accounts WHERE id=?",(row[0],))
        self.worker_last=now

    def deliver_one(self):
        if not self.settings.mail_enabled or not self.sender: return False
        with self.db() as c:
            row=c.execute("SELECT * FROM notices WHERE state='pending' AND next_at<=? ORDER BY created LIMIT 1",(self.clock(),)).fetchone()
            if not row: return False
            if self.blocked(c,row['recipient']):
                c.execute("UPDATE notices SET state='blocked',body='' WHERE id=?",(row['id'],))
                return True
            if row['expires'] and row['expires']<self.clock():
                c.execute("UPDATE notices SET state='expired',body='' WHERE id=?",(row['id'],))
                return True
        # Reserve quotas before contacting SMTP; retries also count as send attempts.
        try:
            with self.db() as c:
                self.limit(c,'mail-global',self.settings.mail_per_day)
                if row['owner']: self.limit(c,'mail-user:'+row['owner'],self.settings.mail_per_user_day)
                if c.execute('SELECT 1 FROM guest_accounts WHERE id=?',(row['owner'],)).fetchone():
                    self.limit(c,'guest-mail-recipient:'+digest(row['recipient']),3)
        except APIError:
            with self.db() as c:
                c.execute("UPDATE notices SET next_at=? WHERE id=?",(self.clock()+60,row['id']))
            return True
        try:
            self.sender(row['recipient'],row['subject'],row['body'],row['id'])
        except Exception as e:
            with self.db() as c:
                attempts=row['attempts']+1
                c.execute("UPDATE notices SET attempts=?,state=?,next_at=?,error=? WHERE id=?",(attempts,'dead' if attempts>=8 else 'pending',self.clock()+min(3600,15*2**attempts),type(e).__name__,row['id']))
        else:
            with self.db() as c:
                c.execute("UPDATE notices SET state='sent',sent=?,error=NULL,body=CASE WHEN kind='verification' THEN '' ELSE body END WHERE id=?",(self.clock(),row['id']))
        return True

def smtp_sender(config):
    if any(not config.get(k) for k in ['SMTP_HOST','SMTP_USERNAME','SMTP_PASSWORD','SMTP_FROM']): raise ValueError('incomplete SMTP configuration')
    email(config['SMTP_FROM'])
    def send(recipient,subject,body,notice_id):
        msg=EmailMessage()
        msg['From']=config['SMTP_FROM']; msg['To']=recipient; msg['Subject']=subject
        msg['Message-ID']=f"<{notice_id}@endnote.local>"
        links=re.findall(r'https?://[^\s]+/unsubscribe/[A-Za-z0-9_-]{43}',body)
        if links:
            msg['List-Unsubscribe']='<'+links[-1]+'>'
            msg['List-Unsubscribe-Post']='List-Unsubscribe=One-Click'
        msg.set_content(body+'\n\n— endnote · experiment notifications')
        context=ssl.create_default_context()
        use_ssl=str(config.get('SMTP_USE_SSL','true')).lower() in {'true','1','yes'}
        port=int(config.get('SMTP_PORT','465' if use_ssl else '587'))
        if use_ssl: client=smtplib.SMTP_SSL(config['SMTP_HOST'],port,timeout=20,context=context)
        else:
            client=smtplib.SMTP(config['SMTP_HOST'],port,timeout=20)
            client.starttls(context=context)
        with client:
            client.login(config['SMTP_USERNAME'],config['SMTP_PASSWORD'])
            client.send_message(msg,from_addr=config['SMTP_FROM'],to_addrs=[recipient])
    return send
