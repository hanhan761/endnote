"""Off-host Outage archive release, based on a verified immutable production archive."""
import gzip,hashlib,io,json,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE='366efe7dd08feaf08f52caf4f137199557c5ffe2adbc5fd06b5aa1c397c9e52e'
BASE_ARCHIVE_SHA=BASE
raw=(ROOT/'dist/endnote-attention-20261012.tar.gz').read_bytes()
assert hashlib.sha256(raw).hexdigest()==BASE_ARCHIVE_SHA
with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as archive:
    files={m.name:archive.extractfile(m).read() for m in archive.getmembers()}
manifest=json.loads(files.pop('MANIFEST.json'))
assert manifest['files']=={n:hashlib.sha256(v).hexdigest() for n,v in sorted(files.items())}
service=files['endnote/service.py'].decode()
old="            if task['status'] not in TERMINAL:raise APIError(409,'只有已结束的任务可以归档')"
assert service.count(old)==1
service=service.replace("SELECT t.status FROM tasks t JOIN accounts a ON a.id=t.owner LEFT JOIN guest_accounts g ON g.id=a.id WHERE t.id=?","SELECT t.status,t.heartbeat,t.config FROM tasks t JOIN accounts a ON a.id=t.owner LEFT JOIN guest_accounts g ON g.id=a.id WHERE t.id=?")
service=service.replace(old,"            config=json.loads(task['config'])\n            outage=task['status']=='running' and 'heartbeat_timeout' in config['notify_on'] and self.clock()-task['heartbeat']>=config['heartbeat_timeout']\n            if archived and task['status'] not in TERMINAL and not outage:raise APIError(409,'只有已结束或心跳失联的任务可以归档；该任务可能已恢复心跳')")
files['endnote/service.py']=service.encode()
for name in ['endnote/web/dashboard.js']:
    files[name]=(ROOT/name).read_bytes()
files['MANIFEST.json']=json.dumps({'format':1,'files':{n:hashlib.sha256(v).hexdigest() for n,v in sorted(files.items())}},sort_keys=True).encode()
output=ROOT/'dist/endnote-outage-archive-20261012.tar.gz'
with output.open('wb') as dest,gzip.GzipFile(fileobj=dest,mode='wb',mtime=0) as gz,tarfile.open(fileobj=gz,mode='w') as archive:
    for name,value in sorted(files.items()):
        info=tarfile.TarInfo(name);info.size=len(value);info.mode=0o644;info.mtime=0
        archive.addfile(info,io.BytesIO(value))
print(json.dumps({'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'baseline':BASE,'changed':['endnote/service.py','endnote/web/dashboard.js'],'bytes':output.stat().st_size}))
