"""Install only the owner-authorized workstation collector, after verified activation."""
import fcntl
import json
import os
from pathlib import Path
import pwd
import socket
import subprocess
import sys
import time

SHA='f5b31f9f7184513090dec6ffe4f68288040c5b0ba2af9cbf12aead3b3b6c7800'
UNIT=Path('/etc/systemd/system/endnote-machine.service')
CONFIG=Path('/home/codex-admin/.config/endnote/workstation-machine.json')
UNIT_TEXT='''[Unit]
Description=Endnote optional workstation resource collector
After=network-online.target endnote.service
Wants=network-online.target

[Service]
Type=simple
User=codex-admin
Group=codex-admin
ExecStart=/usr/bin/python3 /opt/endnote/current/endnote/web/machine_agent.py --config /home/codex-admin/.config/endnote/workstation-machine.json
Restart=on-failure
RestartSec=20
RestartPreventExitStatus=2
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
LockPersonality=yes
CapabilityBoundingSet=
MemoryMax=96M
CPUQuota=10%
TasksMax=32
UMask=0077

[Install]
WantedBy=multi-user.target
'''
def run(*args):return subprocess.check_output(args,text=True,stderr=subprocess.PIPE,timeout=30)
def main():
    assert os.geteuid()==0 and socket.gethostname()=='ps'
    lock=open('/var/lock/endnote-deploy.lock','w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    assert Path('/opt/endnote/current').resolve().name==SHA
    assert not UNIT.exists() and not CONFIG.exists()
    raw=Path(sys.argv[1]).read_bytes();assert len(raw)<2000
    config=json.loads(raw)
    assert set(config)=={'url','id','machine_key'} and config['url']=='https://am.matterswarm.com/endnote'
    import re
    assert re.fullmatch(r'[0-9a-f]{32}',config['id']) and re.fullmatch(r'en_machine_[A-Za-z0-9_-]{43}',config['machine_key'])
    account=pwd.getpwnam('codex-admin')
    if not CONFIG.parent.exists():
        CONFIG.parent.mkdir(mode=0o700,parents=True)
        os.chown(CONFIG.parent,account.pw_uid,account.pw_gid)
    CONFIG.write_bytes(raw);CONFIG.chmod(0o600);os.chown(CONFIG,account.pw_uid,account.pw_gid)
    UNIT.write_text(UNIT_TEXT);UNIT.chmod(0o644)
    try:
        run('systemd-analyze','verify',str(UNIT))
        run('systemctl','daemon-reload');run('systemctl','enable','--now','endnote-machine')
        for _ in range(3):
            time.sleep(5)
            assert run('systemctl','is-active','endnote-machine').strip()=='active'
        assert run('systemctl','show','endnote-machine','-p','NRestarts','--value').strip()=='0'
        print(json.dumps({'collector':'active','machine_id':config['id'],'sample_interval':15,'config_mode':'0600','user':'codex-admin'}))
    except BaseException:
        run('systemctl','disable','--now','endnote-machine')
        raise
if __name__=='__main__':main()
