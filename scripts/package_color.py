"""Package dashboard grouping atop the exact production release, off-host."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]

BASE = '7b7bf4743985ad7547d107eb9e0e3f5f7710111ba87ead690b9636ea1071296a'
raw = (ROOT / 'dist/endnote-grouping-20261006.tar.gz').read_bytes()
assert hashlib.sha256(raw).hexdigest() == BASE
with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
    files = {m.name: archive.extractfile(m).read() for m in archive.getmembers()}
manifest = json.loads(files.pop('MANIFEST.json'))
assert manifest['files'] == {n:hashlib.sha256(v).hexdigest() for n,v in sorted(files.items())}
for name in ['endnote/web/dashboard.js', 'endnote/web/dashboard.css']:
    files[name] = (ROOT / name).read_bytes()
files['MANIFEST.json'] = json.dumps({'format':1,'files':{n:hashlib.sha256(v).hexdigest() for n,v in sorted(files.items())}}, sort_keys=True).encode()
candidate = ROOT / 'dist/color-candidate'
for name, value in files.items():
    path = candidate / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(value)
output = ROOT / 'dist/endnote-color-20261006.tar.gz'
with output.open('wb') as dest, gzip.GzipFile(fileobj=dest, mode='wb', mtime=0) as gz, tarfile.open(fileobj=gz, mode='w') as archive:
    for name,value in sorted(files.items()):
        info = tarfile.TarInfo(name); info.size = len(value); info.mode = 0o644; info.mtime = 0
        archive.addfile(info, io.BytesIO(value))
print(json.dumps({'sha256':hashlib.sha256(output.read_bytes()).hexdigest(), 'baseline':BASE, 'changed':['endnote/web/dashboard.js','endnote/web/dashboard.css']}))
