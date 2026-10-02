"""Create a bounded immutable release on the development machine."""
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path

root=Path(__file__).resolve().parents[1]
files={str(p.relative_to(root)).replace("\\","/"):p.read_bytes()
       for p in (root/"endnote").rglob("*") if p.is_file() and p.suffix in {".py",".html",".js",".css"}}
manifest={"format":1,"files":{name:hashlib.sha256(data).hexdigest() for name,data in sorted(files.items())}}
files["MANIFEST.json"]=json.dumps(manifest,sort_keys=True).encode()
out=root/"dist"/"endnote-release.tar.gz";out.parent.mkdir(exist_ok=True)
with out.open("wb") as dest,gzip.GzipFile(fileobj=dest,mode="wb",mtime=0) as gz,tarfile.open(fileobj=gz,mode="w") as archive:
    for name,data in sorted(files.items()):
        item=tarfile.TarInfo(name);item.size=len(data);item.mode=0o644;item.mtime=0
        archive.addfile(item,io.BytesIO(data))
print(json.dumps({"archive":str(out),"sha256":hashlib.sha256(out.read_bytes()).hexdigest(),"expanded_bytes":sum(map(len,files.values()))}))
