"""Package dashboard grouping atop the exact production release, off-host."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"deploy"))
from machine_patch import patch_service,patch_server,patch_html

BASE = 'c4504b2e4aa79d5b10d051827ee52a4d184891473494bf2f114dedfc26e021ac'
raw = (ROOT / 'dist/endnote-color-20261006.tar.gz').read_bytes()
assert hashlib.sha256(raw).hexdigest() == BASE
with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
    files = {m.name: archive.extractfile(m).read() for m in archive.getmembers()}
manifest = json.loads(files.pop('MANIFEST.json'))
assert manifest['files'] == {n:hashlib.sha256(v).hexdigest() for n,v in sorted(files.items())}
for name in ['endnote/web/dashboard.js', 'endnote/web/dashboard.css']:
    files[name] = (ROOT / name).read_bytes()
for name,patch in [('endnote/service.py',patch_service),('endnote/server.py',patch_server),('endnote/web/dashboard.html',patch_html)]:
    files[name] = patch(files[name])
for name in ['endnote/machines.py','endnote/web/machine_agent.py']:
    files[name] = (ROOT/name).read_bytes()
files['MANIFEST.json'] = json.dumps({'format':1,'files':{n:hashlib.sha256(v).hexdigest() for n,v in sorted(files.items())}}, sort_keys=True).encode()
candidate = ROOT / 'dist/machine-candidate'
for name, value in files.items():
    path = candidate / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(value)
output = ROOT / 'dist/endnote-machines-20261007.tar.gz'
with output.open('wb') as dest, gzip.GzipFile(fileobj=dest, mode='wb', mtime=0) as gz, tarfile.open(fileobj=gz, mode='w') as archive:
    for name,value in sorted(files.items()):
        info = tarfile.TarInfo(name); info.size = len(value); info.mode = 0o644; info.mtime = 0
        archive.addfile(info, io.BytesIO(value))
print(json.dumps({'sha256':hashlib.sha256(output.read_bytes()).hexdigest(), 'baseline':BASE, 'changed':['endnote/web/dashboard.js','endnote/web/dashboard.css','endnote/web/dashboard.html','endnote/server.py','endnote/service.py'],'added':['endnote/machines.py','endnote/web/machine_agent.py']}))
