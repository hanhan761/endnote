"""Bounded recipient-scoped module binding update; no service restart."""
import fcntl,hashlib,json,os,re,shutil,socket,sqlite3,subprocess,sys,time,unicodedata
from pathlib import Path
from urllib.request import build_opener,ProxyHandler
from urllib.parse import urlencode
open_url=build_opener(ProxyHandler({})).open
DB=Path('/var/lib/endnote/endnote.db')
def main():
 assert os.geteuid()==0 and socket.gethostname()=='ps'
 lock=open('/var/lock/endnote-deploy.lock','w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 bundle=json.loads(Path(sys.argv[1]).read_text());anchor=bundle['anchor_task_id'];prefixes=bundle['prefixes'];module=bundle['module']
 assert isinstance(anchor,str) and re.fullmatch('[0-9a-f]{32}',anchor)
 assert isinstance(prefixes,list) and 1<=len(prefixes)<=16 and len(prefixes)==len(set(prefixes))
 assert all(isinstance(p,str) and re.fullmatch('[a-z0-9_-]{1,60}',p) for p in prefixes)
 assert isinstance(bundle['query'],str) and re.fullmatch('[A-Za-z0-9_ -]{1,60}',bundle['query'])
 assert isinstance(module,str) and 0<len(module.strip())<=60 and not any(ord(ch)<32 for ch in module)
 def state():return subprocess.check_output(['systemctl','show','endnote','cloudflared','endnote-machine','-p','MainPID','-p','NRestarts'],text=True)
 before_state=state()
 def health():
  for origin in ['http://127.0.0.1:8380','https://am.matterswarm.com']:
   with open_url(origin+'/endnote/health',timeout=12) as r:assert r.status==200 and json.load(r)['ok']
 health()
 usage=shutil.disk_usage(DB.parent);peak=DB.stat().st_size*2+32*1024**2
 reserve=2*1024**3 if '--approved-capacity-exception' in sys.argv[2:] else max(2*1024**3,usage.total*.15)
 assert usage.free-peak>reserve
 assert float(Path('/proc/pressure/io').read_text().split('full avg10=')[1].split()[0])<5
 with sqlite3.connect('file:'+str(DB)+'?mode=ro',uri=True) as c:
  c.create_function('recipient_hash',1,lambda value:hashlib.sha256(value.lower().encode()).hexdigest())
  row=c.execute('SELECT recipient_hash(COALESCE(g.recipient,a.email)) FROM tasks t JOIN accounts a ON a.id=t.owner LEFT JOIN guest_accounts g ON g.id=a.id WHERE t.id=?',(anchor,)).fetchone();assert row
  owner=row[0];token=c.execute('SELECT token FROM dashboards WHERE recipient_hash=?',(owner,)).fetchone()[0]
  previous={p:c.execute('SELECT module FROM dashboard_module_bindings WHERE recipient_hash=? AND prefix=?',(owner,p)).fetchone() for p in prefixes}
  ops=Path('/opt/endnote/ops')/('binding-'+str(time.time_ns()));ops.mkdir(mode=0o700)
  dest=sqlite3.connect(str(ops/'database-before.sqlite'));c.backup(dest);dest.close();(ops/'database-before.sqlite').chmod(0o600)
 (ops/'previous.json').write_text(json.dumps(previous));(ops/'previous.json').chmod(0o600)
 applied=False
 try:
  with sqlite3.connect(DB,timeout=5) as c:
   c.execute('BEGIN IMMEDIATE')
   for prefix in prefixes:
    assert c.execute('SELECT module FROM dashboard_module_bindings WHERE recipient_hash=? AND prefix=?',(owner,prefix)).fetchone()==previous[prefix]
    c.execute('INSERT INTO dashboard_module_bindings VALUES(?,?,?) ON CONFLICT(recipient_hash,prefix) DO UPDATE SET module=excluded.module',(owner,prefix,module))
  applied=True
  counts=[]
  for archived in ['0','1']:
   url='http://127.0.0.1:8380/endnote/v1/dashboard/'+token+'?'+urlencode({'q':bundle['query'],'trends':'0','archived':archived})
   with open_url(url,timeout=8) as r:data=json.load(r)
   assert data['total']<=200 and all(t['group']==module for t in data['tasks'])
   counts.append(data['total'])
  health();assert state()==before_state
  receipt={'module':module,'prefixes':prefixes,'unarchived':counts[0],'archived':counts[1],'service_restart':False,'verified':True}
  (ops/'receipt.json').write_text(json.dumps(receipt));print(json.dumps(receipt))
 except BaseException:
  if applied:
   with sqlite3.connect(DB,timeout=5) as c:
    c.execute('BEGIN IMMEDIATE')
    for prefix,value in previous.items():
     assert c.execute('SELECT module FROM dashboard_module_bindings WHERE recipient_hash=? AND prefix=?',(owner,prefix)).fetchone()==(module,)
     if value is None:c.execute('DELETE FROM dashboard_module_bindings WHERE recipient_hash=? AND prefix=?',(owner,prefix))
     else:c.execute('UPDATE dashboard_module_bindings SET module=? WHERE recipient_hash=? AND prefix=?',(value[0],owner,prefix))
  raise
if __name__=='__main__':main()
