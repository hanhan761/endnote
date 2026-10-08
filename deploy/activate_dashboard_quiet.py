"""Dashboard-only no-build cutover, retaining all current production features."""
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import socket
import subprocess
import sys
import tarfile
import time
from urllib.request import Request, urlopen

ROOT = Path('/opt/endnote')
BASE = '9769f126b202b02af2f7e47f5f9dad7802f1aefcd3dd40a126b1ff57686a3999'
SHA = 'ed57d225f12d183dacde13b34bb6a4cb13941e410ed8a9365e2e54eab35c702a'

def run(*args): return subprocess.check_output(args, text=True, stderr=subprocess.PIPE, timeout=30)
def healthy(public=False):
    base = 'https://am.matterswarm.com' if public else 'http://127.0.0.1:8380'
    with urlopen(Request(base+'/endnote/health', headers={'User-Agent':'Mozilla/5.0 endnote-check'}), timeout=12) as response:
        assert response.status == 200 and json.load(response)['ok']
def ready():
    for _ in range(15):
        try: healthy(); return
        except OSError: time.sleep(1)
    raise RuntimeError('origin failed')
def pointer(path, name):
    link = ROOT/name; assert not link.exists() and not link.is_symlink()
    link.symlink_to(path); os.replace(link, ROOT/'current')
def main():
    assert os.geteuid() == 0 and socket.gethostname() == 'ps'
    lock = open('/var/lock/endnote-deploy.lock', 'w'); fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
    old = (ROOT/'current').resolve(); assert old.name == BASE
    raw = Path(sys.argv[1]).read_bytes(); assert len(raw) < 2_000_000 and hashlib.sha256(raw).hexdigest() == SHA
    data = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
        members = archive.getmembers(); assert len(members) < 128 and sum(m.size for m in members) < 2_000_000
        for item in members:
            path = PurePosixPath(item.name)
            assert item.isfile() and not path.is_absolute() and '..' not in path.parts and item.name not in data
            assert item.name == 'MANIFEST.json' or item.name.startswith('endnote/')
            data[item.name] = archive.extractfile(item).read()
    manifest = json.loads(data.pop('MANIFEST.json'))
    assert manifest['format'] == 1 and manifest['files'] == {n:hashlib.sha256(v).hexdigest() for n,v in sorted(data.items())}
    before = {str(p.relative_to(old)):p.read_bytes() for p in old.rglob('*') if p.is_file()}
    assert set(data) == set(before)
    assert {n for n in before if data[n] != before[n]} == {'endnote/web/dashboard.css'}
    usage = shutil.disk_usage(ROOT)
    # This flag requires the owner's explicit one-release capacity exception.
    exception = '--approved-capacity-exception' in sys.argv[2:]
    peak = len(raw)*2 + sum(len(v) for v in data.values())*3
    reserve = 2*1024**3 if exception else max(2*1024**3, usage.total*.15)
    assert usage.free-peak > reserve
    stat = os.statvfs(ROOT); assert stat.f_favail > 4096
    mem = int(Path('/proc/meminfo').read_text().split('MemAvailable:')[1].split()[0])*1024
    assert mem > 1024**3
    assert float(Path('/proc/pressure/io').read_text().split('full avg10=')[1].split()[0]) < 5
    assert run('systemctl','is-active','endnote','cloudflared').split() == ['active','active']
    healthy(); healthy(True)
    unchanged = run('systemctl','show','cloudflared','ppt-web','endnote-machine','-p','MainPID')
    unit_hash = hashlib.sha256(Path('/etc/systemd/system/endnote.service').read_bytes()).hexdigest()
    release = ROOT/'releases'/SHA; assert not release.exists(); release.mkdir()
    for name,value in data.items():
        path = release/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(value); path.chmod(0o644)
    ops = ROOT/'ops'/('quiet-20261008-'+SHA[:12]); ops.mkdir(mode=0o700)
    receipt = {'release':SHA, 'previous':str(old), 'scope':'Dashboard CSS only; no schema, JavaScript, credentials, collector, unit or ingress changes', 'capacity_exception':exception, 'free_bytes':usage.free, 'estimated_peak_bytes':peak}
    (ops/'release.json').write_text(json.dumps(receipt,indent=2))
    activated = False
    try:
        assert (ROOT/'current').resolve() == old
        pointer(release,'current.quiet-next'); activated = True
        run('systemctl','restart','endnote'); ready()
        started = time.monotonic(); samples = 0
        while True:
            healthy(); healthy(True)
            assert run('systemctl','show','cloudflared','ppt-web','endnote-machine','-p','MainPID') == unchanged
            assert hashlib.sha256(Path('/etc/systemd/system/endnote.service').read_bytes()).hexdigest() == unit_hash
            assert run('systemctl','show','endnote','-p','NRestarts','--value').strip() == '0'
            samples += 1
            if time.monotonic()-started >= 60: break
            time.sleep(20)
        receipt.update(status='verified', samples=samples, observation_seconds=round(time.monotonic()-started))
        (ops/'release.json').write_text(json.dumps(receipt,indent=2)); print(json.dumps(receipt),flush=True)
    except BaseException:
        if activated: pointer(old,'current.quiet-rollback'); run('systemctl','restart','endnote'); ready()
        raise

if __name__ == '__main__': main()
