"""Optional, recipient-scoped machine telemetry. Never executes caller input."""
import json
import math
import re
import secrets
from .service import APIError, digest, text

class Machines:
    def __init__(self, store):
        self.store=store
        with store.db() as c:
            c.execute('CREATE TABLE IF NOT EXISTS machines(id TEXT PRIMARY KEY,recipient_hash TEXT NOT NULL,name TEXT NOT NULL,key_hash TEXT UNIQUE NOT NULL,created REAL NOT NULL,received REAL,payload TEXT NOT NULL DEFAULT "{}",enabled INTEGER NOT NULL DEFAULT 1)')
            c.execute('CREATE INDEX IF NOT EXISTS machine_recipient ON machines(recipient_hash,created)')
    def access(self,c,token):
        if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):raise APIError(404,'dashboard not found')
        row=c.execute('SELECT recipient_hash FROM dashboards WHERE token=?',(token,)).fetchone()
        if not row:raise APIError(404,'dashboard not found')
        return row[0]
    def create(self,token,data):
        if set(data)!={'name'}:raise APIError(400,'only a machine name is accepted')
        name=text(data.get('name'),60,'machine name').strip()
        if not name or any(ord(ch)<32 for ch in name):raise APIError(400,'invalid machine name')
        with self.store.db() as c:
            owner=self.access(c,token)
            self.store.limit(c,'machine-create:'+owner,6,3600)
            existing=c.execute('SELECT id FROM machines WHERE recipient_hash=? AND name=?',(owner,name)).fetchone()
            if existing:raise APIError(409,'此名称已经接入，请使用不同名称，或先停用原采集器。')
            if c.execute('SELECT count(*) FROM machines WHERE recipient_hash=?',(owner,)).fetchone()[0]>=12:raise APIError(429,'每个邮箱最多接入 12 台机器')
            if c.execute('SELECT count(*) FROM machines').fetchone()[0]>=2000:raise APIError(429,'machine capacity reached')
            key='en_machine_'+secrets.token_urlsafe(32);machine_id=secrets.token_hex(16)
            c.execute('INSERT INTO machines(id,recipient_hash,name,key_hash,created) VALUES(?,?,?,?,?)',(machine_id,owner,name,digest(key),self.store.clock()))
        return {'id':machine_id,'name':name,'machine_key':key,'interval':15}
    def list(self,token):
        with self.store.db(read_only=True) as c:
            owner=self.access(c,token);now=self.store.clock()
            rows=c.execute('SELECT id,name,created,received,payload,enabled FROM machines WHERE recipient_hash=? ORDER BY created,id LIMIT 12',(owner,)).fetchall()
            return [{ 'id':r['id'],'name':r['name'],'received':r['received'],'state':'disabled' if not r['enabled'] else 'waiting' if r['received'] is None else 'online' if now-r['received']<90 else 'offline','metrics':json.loads(r['payload'])} for r in rows]
    def enable(self,token,machine_id,enabled):
        if not isinstance(enabled,bool):raise APIError(400,'enabled must be boolean')
        with self.store.db() as c:
            owner=self.access(c,token)
            self.store.limit(c,'machine-manage:'+owner,30,60)
            row=c.execute('SELECT id FROM machines WHERE id=? AND recipient_hash=?',(machine_id,owner)).fetchone()
            if not row:raise APIError(404,'machine not found')
            c.execute('UPDATE machines SET enabled=? WHERE id=?',(int(enabled),machine_id))
        return {'ok':True,'enabled':enabled}
    @staticmethod
    def validate(data):
        fields={'cpu_percent','cpu_temperature','memory_total','memory_used','disk_total','disk_used','gpus'}
        if not isinstance(data,dict) or set(data)-fields:raise APIError(400,'unsupported telemetry fields')
        def number(value,lo,hi):
            if value is None:return None
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not lo<=value<=hi:raise APIError(400,'invalid telemetry number')
            return value
        result={k:number(data.get(k),-20 if k=='cpu_temperature' else 0,150 if k=='cpu_temperature' else 100 if k=='cpu_percent' else 2**60) for k in fields-{'gpus'}}
        for prefix in ['memory','disk']:
            used,total=result[prefix+'_used'],result[prefix+'_total']
            if used is not None and total is not None and used>total:raise APIError(400,'used capacity exceeds total')
        gpus=data.get('gpus',[])
        if not isinstance(gpus,list) or len(gpus)>8:raise APIError(400,'at most eight GPUs')
        result['gpus']=[];indices=set()
        for gpu in gpus:
            if not isinstance(gpu,dict) or set(gpu)-{'index','name','percent','temperature','memory_used','memory_total','power'}:raise APIError(400,'invalid GPU telemetry')
            index=gpu.get('index')
            if isinstance(index,bool) or not isinstance(index,int) or not 0<=index<256 or index in indices:raise APIError(400,'invalid GPU index')
            indices.add(index);name=text(gpu.get('name'),80,'GPU name')
            item={'index':index,'name':name,'percent':number(gpu.get('percent'),0,100),'temperature':number(gpu.get('temperature'),-20,150),'memory_used':number(gpu.get('memory_used'),0,2**60),'memory_total':number(gpu.get('memory_total'),0,2**60),'power':number(gpu.get('power'),0,10000)}
            if item['memory_used'] is not None and item['memory_total'] is not None and item['memory_used']>item['memory_total']:raise APIError(400,'GPU used memory exceeds total')
            result['gpus'].append(item)
        return result
    def ingest(self,key,machine_id,data):
        if not isinstance(key,str) or not key.startswith('en_machine_'):raise APIError(401,'machine credential required')
        payload=self.validate(data)
        with self.store.db() as c:
            row=c.execute('SELECT enabled FROM machines WHERE id=? AND key_hash=?',(machine_id,digest(key))).fetchone()
            if not row:raise APIError(401,'invalid machine credential')
            if not row[0]:raise APIError(403,'machine reporting disabled')
            self.store.limit(c,'machine-report:'+machine_id,12,60)
            c.execute('UPDATE machines SET received=?,payload=? WHERE id=?',(self.store.clock(),json.dumps(payload,allow_nan=False),machine_id))
        return {'ok':True}

    def dashboard(self,token,*args,**kwargs):
        result=self.store.dashboard(token,*args,**kwargs)
        result['machines']=self.list(token)
        return result
