"""Off-host Group attention ordering release, based on a verified immutable production archive."""
import gzip,hashlib,io,json,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE='d6e4d5342bfd8377440b58bbd0767551743da79f3b67067b3cea0323f43da475'
BASE_ARCHIVE_SHA=BASE
raw=(ROOT/'dist/endnote-outage-archive-20261012.tar.gz').read_bytes()
assert hashlib.sha256(raw).hexdigest()==BASE_ARCHIVE_SHA
with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as archive:
    files={m.name:archive.extractfile(m).read() for m in archive.getmembers()}
manifest=json.loads(files.pop('MANIFEST.json'))
assert manifest['files']=={n:hashlib.sha256(v).hexdigest() for n,v in sorted(files.items())}
service=files['endnote/service.py'].decode()
service=service.replace('            CREATE TABLE IF NOT EXISTS dashboard_archives(', '            CREATE TABLE IF NOT EXISTS dashboard_module_bindings(recipient_hash TEXT NOT NULL,prefix TEXT NOT NULL,module TEXT NOT NULL,PRIMARY KEY(recipient_hash,prefix));\n            CREATE TABLE IF NOT EXISTS dashboard_archives(')
service=service.replace('            scope="FROM tasks t WHERE t.owner','            bindings=c.execute("SELECT prefix,module FROM dashboard_module_bindings WHERE recipient_hash=?",(access[0],)).fetchall()\n            scope="FROM tasks t WHERE t.owner')
service=service.replace("                item['group']=config.get('group')","                from .grouping import canonical_group\n                item['group']=canonical_group(row['name'],config.get('group'),bindings)")
files['endnote/service.py']=service.encode()
files['endnote/grouping.py']=(ROOT/'endnote/grouping.py').read_bytes()

files['MANIFEST.json']=json.dumps({'format':1,'files':{n:hashlib.sha256(v).hexdigest() for n,v in sorted(files.items())}},sort_keys=True).encode()
output=ROOT/'dist/endnote-bindings-20261013.tar.gz'
with output.open('wb') as dest,gzip.GzipFile(fileobj=dest,mode='wb',mtime=0) as gz,tarfile.open(fileobj=gz,mode='w') as archive:
    for name,value in sorted(files.items()):
        info=tarfile.TarInfo(name);info.size=len(value);info.mode=0o644;info.mtime=0
        archive.addfile(info,io.BytesIO(value))
print(json.dumps({'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'baseline':BASE,'changed':['endnote/service.py','endnote/grouping.py'],'bytes':output.stat().st_size}))
