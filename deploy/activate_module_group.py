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
BASE = '2e0210e2599f533a02eb57e6dc8883d67c859362f16b9fa3567f776ca39dad41'
SHA = '7d0e049a1b8de584536ba8d6d38faf15c269f326528287ed9a1d7afaf46a0c43'

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
    assert {n for n in before if data[n] != before[n]} == {'endnote/service.py','endnote/client.py','endnote/web/dashboard.js'}
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
    ops = ROOT/'ops'/('module-group-20261009-'+SHA[:12]); ops.mkdir(mode=0o700)
    expected_js = hashlib.sha256(data['endnote/web/dashboard.js']).hexdigest()
    def asset(public=False):
        base = 'https://am.matterswarm.com' if public else 'http://127.0.0.1:8380'
        with urlopen(Request(base+'/endnote/dashboard.js', headers={'User-Agent':'Mozilla/5.0 endnote-check'}), timeout=12) as response:
            assert response.status == 200 and hashlib.sha256(response.read()).hexdigest() == expected_js
    receipt = {'release':SHA, 'previous':str(old), 'scope':'Stable module config and row grouping; bounded two-task assignment; no status, credential, collector, unit or ingress changes', 'capacity_exception':exception, 'free_bytes':usage.free, 'estimated_peak_bytes':peak}
    (ops/'release.json').write_text(json.dumps(receipt,indent=2))
    assignment=json.loads(Path(sys.argv[2]).read_text())
    ids=assignment['task_ids'];group=assignment['group']
    assert len(ids)==2 and len(set(ids))==2 and all(isinstance(i,str) and len(i)==32 and all(ch in '0123456789abcdef' for ch in i) for i in ids)
    assert isinstance(group,str) and 0<len(group.strip())<=60 and not any(ord(ch)<32 for ch in group)
    database='/var/lib/endnote/endnote.db'
    with sqlite3.connect('file:'+database+'?mode=ro',uri=True) as c:
        records=[c.execute('SELECT t.config,COALESCE(g.recipient,a.email) FROM tasks t JOIN accounts a ON a.id=t.owner LEFT JOIN guest_accounts g ON g.id=a.id WHERE t.id=?',(i,)).fetchone() for i in ids]
        assert all(records) and len({hashlib.sha256(r[1].lower().encode()).hexdigest() for r in records})==1
        recipient=hashlib.sha256(records[0][1].lower().encode()).hexdigest()
        token=c.execute('SELECT token FROM dashboards WHERE recipient_hash=?',(recipient,)).fetchone()[0]
    previous_groups=[{'id':i,'present':'group' in json.loads(r[0]),'value':json.loads(r[0]).get('group')} for i,r in zip(ids,records)]
    backup=ops/'group-assignment.json';backup.write_text(json.dumps(previous_groups));backup.chmod(0o600)
    def assign(restore=False):
        with sqlite3.connect(database,timeout=5) as c:
            c.execute('BEGIN IMMEDIATE')
            for old_group in previous_groups:
                cfg=json.loads(c.execute('SELECT config FROM tasks WHERE id=?',(old_group['id'],)).fetchone()[0])
                if restore:
                    assert cfg.get('group')==group
                    if old_group['present']:cfg['group']=old_group['value']
                    else:cfg.pop('group',None)
                else:
                    assert ('group' in cfg)==old_group['present'] and cfg.get('group')==old_group['value']
                    cfg['group']=group
                c.execute('UPDATE tasks SET config=? WHERE id=?',(json.dumps(cfg),old_group['id']))
    def grouped():
        for i in ids:
            url='http://127.0.0.1:8380/endnote/v1/dashboard/'+token+'?task='+i+'&trends=0'
            with urlopen(url,timeout=8) as response:
                result=json.load(response)
                # Assignment never changes archive state; archived records are checked through the archive view.
                if not result['tasks']:
                    with urlopen(url+'&archived=1',timeout=8) as archived:result=json.load(archived)
                assert len(result['tasks'])==1 and result['tasks'][0]['group']==group
    assigned=False
    activated = False
    try:
        assert (ROOT/'current').resolve() == old
        pointer(release,'current.module-group-next'); activated = True
        run('systemctl','restart','endnote'); ready()
        assign(); assigned=True; grouped()
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
        if assigned:assign(restore=True)
        if activated: pointer(old,'current.module-group-rollback'); run('systemctl','restart','endnote'); ready()
        raise

if __name__ == '__main__': main()
