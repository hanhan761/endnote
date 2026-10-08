"""Off-host CSS-only release, based on a verified immutable production archive."""
import gzip,hashlib,io,json,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE='f5b31f9f7184513090dec6ffe4f68288040c5b0ba2af9cbf12aead3b3b6c7800'
raw=(ROOT/'dist/endnote-machines-20261007.tar.gz').read_bytes()
assert hashlib.sha256(raw).hexdigest()==BASE
with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as archive:
    files={m.name:archive.extractfile(m).read() for m in archive.getmembers()}
manifest=json.loads(files.pop('MANIFEST.json'))
assert manifest['files']=={n:hashlib.sha256(v).hexdigest() for n,v in sorted(files.items())}
files['endnote/web/dashboard.css']=(ROOT/'endnote/web/dashboard.css').read_bytes()
files['MANIFEST.json']=json.dumps({'format':1,'files':{n:hashlib.sha256(v).hexdigest() for n,v in sorted(files.items())}},sort_keys=True).encode()
output=ROOT/'dist/endnote-polish-20261008.tar.gz'
with output.open('wb') as dest,gzip.GzipFile(fileobj=dest,mode='wb',mtime=0) as gz,tarfile.open(fileobj=gz,mode='w') as archive:
    for name,value in sorted(files.items()):
        info=tarfile.TarInfo(name);info.size=len(value);info.mode=0o644;info.mtime=0
        archive.addfile(info,io.BytesIO(value))
print(json.dumps({'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'baseline':BASE,'changed':['endnote/web/dashboard.css'],'bytes':output.stat().st_size}))
