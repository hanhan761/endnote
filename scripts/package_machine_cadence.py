"""Off-host CSS-only release, based on a verified immutable production archive."""
import gzip,hashlib,io,json,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE='ed57d225f12d183dacde13b34bb6a4cb13941e410ed8a9365e2e54eab35c702a'
raw=(ROOT/'dist/endnote-quiet-20261008.tar.gz').read_bytes()
assert hashlib.sha256(raw).hexdigest()==BASE
with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as archive:
    files={m.name:archive.extractfile(m).read() for m in archive.getmembers()}
manifest=json.loads(files.pop('MANIFEST.json'))
assert manifest['files']=={n:hashlib.sha256(v).hexdigest() for n,v in sorted(files.items())}
for name in ['endnote/machines.py','endnote/web/machine_agent.py','endnote/web/dashboard.js']:
    files[name]=(ROOT/name).read_bytes()
files['MANIFEST.json']=json.dumps({'format':1,'files':{n:hashlib.sha256(v).hexdigest() for n,v in sorted(files.items())}},sort_keys=True).encode()
output=ROOT/'dist/endnote-cadence-20261009.tar.gz'
with output.open('wb') as dest,gzip.GzipFile(fileobj=dest,mode='wb',mtime=0) as gz,tarfile.open(fileobj=gz,mode='w') as archive:
    for name,value in sorted(files.items()):
        info=tarfile.TarInfo(name);info.size=len(value);info.mode=0o644;info.mtime=0
        archive.addfile(info,io.BytesIO(value))
print(json.dumps({'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'baseline':BASE,'changed':['endnote/machines.py','endnote/web/machine_agent.py','endnote/web/dashboard.js'],'bytes':output.stat().st_size}))
