"""Build a module-group release locally over the verified live baseline."""
import gzip,hashlib,io,json,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE='2e0210e2599f533a02eb57e6dc8883d67c859362f16b9fa3567f776ca39dad41'
ARCHIVE_SHA='28cae34e360c12bc88e88100c17e1c84ebdcf212020ebd37217edc49eb92c1cc'
SERVICE_SHA='29b84235da76d49583bc4eed1b3f98ac641ca8e8120071504ada4b08784c8dae'
raw=(ROOT/'dist/endnote-task-capacity-20261011.tar.gz').read_bytes()
assert hashlib.sha256(raw).hexdigest()==ARCHIVE_SHA
with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as archive:files={m.name:archive.extractfile(m).read() for m in archive.getmembers()}
manifest=json.loads(files.pop('MANIFEST.json'));assert manifest['files']=={n:hashlib.sha256(v).hexdigest() for n,v in sorted(files.items())}
service=(ROOT/'dist/module-baseline/service.py').read_bytes();assert hashlib.sha256(service).hexdigest()==SERVICE_SHA
files['endnote/service.py']=service
# The candidate service is produced by the same narrow patch applied to Git.
updated=(ROOT/'dist/module-baseline/service-group.py').read_bytes()
assert len(updated)-len(service)<2000 and len(updated)>len(service)
files['endnote/service.py']=updated
client=files['endnote/client.py'].decode().replace('p.add_argument("--name",required=True);','p.add_argument("--name",required=True); p.add_argument("--group",help="Stable module name shared by all rounds");').replace('        if args.email: config["email"]=args.email','        if args.group: config["group"]=args.group\n        if args.email: config["email"]=args.email')
files['endnote/client.py']=client.encode();files['endnote/web/dashboard.js']=(ROOT/'endnote/web/dashboard.js').read_bytes()
files['MANIFEST.json']=json.dumps({'format':1,'files':{n:hashlib.sha256(v).hexdigest() for n,v in sorted(files.items())}},sort_keys=True).encode()
output=ROOT/'dist/endnote-module-20261011.tar.gz'
with output.open('wb') as dest,gzip.GzipFile(fileobj=dest,mode='wb',mtime=0) as gz,tarfile.open(fileobj=gz,mode='w') as archive:
 for name,value in sorted(files.items()):
  info=tarfile.TarInfo(name);info.size=len(value);info.mode=0o644;info.mtime=0;archive.addfile(info,io.BytesIO(value))
print(json.dumps({'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'baseline':BASE,'bytes':output.stat().st_size}))
