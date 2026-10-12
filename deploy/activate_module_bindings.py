"""Dashboard-only no-build cutover, retaining all current production features."""
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import socket
import sqlite3
import subprocess
import sys
import tarfile
import time
from urllib.request import Request, urlopen

ROOT = Path('/opt/endnote')
BASE = 'd6e4d5342bfd8377440b58bbd0767551743da79f3b67067b3cea0323f43da475'
SHA = '9f90eab485f3877769ad39ae9de8343002c1e62d1842fbe8f6186bd8031673e5'

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
    assert set(data) == set(before)|{'endnote/grouping.py'}
    assert {n for n in before if data[n] != before[n]} == {'endnote/service.py'}
    usage = shutil.disk_usage(ROOT)
    # This flag requires the owner's explicit one-release capacity exception.
    exception = '--approved-capacity-exception' in sys.argv[2:]
    peak = len(raw)*2 + sum(len(v) for v in data.values())*3 + Path('/var/lib/endnote/endnote.db').stat().st_size*2 + 32*1024**2
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
    ops = ROOT/'ops'/('module-bindings-20261013-'+SHA[:12]); ops.mkdir(mode=0o700)
    expected_js = hashlib.sha256(data['endnote/web/dashboard.js']).hexdigest()
    def asset(public=False):
        base = 'https://am.matterswarm.com' if public else 'http://127.0.0.1:8380'
        with urlopen(Request(base+'/endnote/dashboard.js', headers={'User-Agent':'Mozilla/5.0 endnote-check'}), timeout=12) as response:
            assert response.status == 200 and hashlib.sha256(response.read()).hexdigest() == expected_js
    receipt = {'release':SHA, 'previous':str(old), 'scope':'Recipient-scoped module namespace binding; additive table; Numerai grouping only', 'capacity_exception':exception, 'free_bytes':usage.free, 'estimated_peak_bytes':peak}
    (ops/'release.json').write_text(json.dumps(receipt,indent=2))
    assignment=json.loads(Path(sys.argv[2]).read_text())
    anchor=assignment['anchor_task_id'];prefix=assignment['prefix'];module=assignment['module']
    assert len(anchor)==32 and all(ch in '0123456789abcdef' for ch in anchor)
    assert prefix=='numerai' and module=='Numerai'
    database='/var/lib/endnote/endnote.db'
    source=sqlite3.connect('file:'+database+'?mode=ro',uri=True)
    import hashlib as _hash
    source.create_function('recipient_hash',1,lambda value:_hash.sha256(value.lower().encode()).hexdigest())
    owner=source.execute('SELECT recipient_hash(COALESCE(g.recipient,a.email)) FROM tasks t JOIN accounts a ON a.id=t.owner LEFT JOIN guest_accounts g ON g.id=a.id WHERE t.id=?',(anchor,)).fetchone()[0]
    token=source.execute('SELECT token FROM dashboards WHERE recipient_hash=?',(owner,)).fetchone()[0]
    destination=sqlite3.connect(str(ops/'database-before.sqlite'));source.backup(destination);destination.close();source.close();(ops/'database-before.sqlite').chmod(0o600)
    prior_binding=[None]
    def bind():
        with sqlite3.connect(database,timeout=5) as c:
            existing=c.execute('SELECT module FROM dashboard_module_bindings WHERE recipient_hash=? AND prefix=?',(owner,prefix)).fetchone()
            assert existing is None or existing[0]==module
            prior_binding[0]=existing[0] if existing else None
            c.execute('INSERT INTO dashboard_module_bindings VALUES(?,?,?) ON CONFLICT(recipient_hash,prefix) DO UPDATE SET module=excluded.module',(owner,prefix,module))
    def grouped():
        url='http://127.0.0.1:8380/endnote/v1/dashboard/'+token+'?q=Numerai&archived=1&trends=0'
        with urlopen(url,timeout=8) as response:result=json.load(response)
        assert result['tasks'] and all(t['group']==module for t in result['tasks'])
    bound=False
    activated = False
    try:
        assert (ROOT/'current').resolve() == old
        pointer(release,'current.module-bindings-next'); activated = True
        run('systemctl','restart','endnote'); ready()
        bind();bound=True;grouped()
        started = time.monotonic(); samples = 0
        while True:
            healthy(); healthy(True); asset(); asset(True); grouped()
            assert run('systemctl','show','cloudflared','ppt-web','endnote-machine','-p','MainPID') == unchanged
            assert hashlib.sha256(Path('/etc/systemd/system/endnote.service').read_bytes()).hexdigest() == unit_hash
            assert run('systemctl','show','endnote','-p','NRestarts','--value').strip() == '0'
            samples += 1
            if time.monotonic()-started >= 60: break
            time.sleep(20)
        receipt.update(status='verified', samples=samples, observation_seconds=round(time.monotonic()-started))
        (ops/'release.json').write_text(json.dumps(receipt,indent=2)); print(json.dumps(receipt),flush=True)
    except BaseException:
        if bound:
            with sqlite3.connect(database,timeout=5) as c:
                if prior_binding[0] is None:c.execute('DELETE FROM dashboard_module_bindings WHERE recipient_hash=? AND prefix=?',(owner,prefix))
                else:c.execute('UPDATE dashboard_module_bindings SET module=? WHERE recipient_hash=? AND prefix=?',(prior_binding[0],owner,prefix))
        if activated: pointer(old,'current.module-bindings-rollback'); run('systemctl','restart','endnote'); ready()
        raise

if __name__ == '__main__': main()
