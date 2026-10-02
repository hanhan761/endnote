"""Checksum-verified, no-build activation. Execute with sudo on the 4090 only."""
import argparse
import datetime
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path,PurePosixPath
import re
import shlex
import shutil
import socket
import subprocess
import tarfile
import time
from urllib.request import urlopen
from urllib.error import HTTPError

ROOT=Path("/opt/endnote")
TUNNEL=Path("/etc/cloudflared/config.yml")
UNIT=Path("/etc/systemd/system/endnote.service")
SOURCE=Path("/opt/matterswarm-workstation/shared/.env.production")
RULE="  - hostname: am.matterswarm.com\n    path: ^/endnote(?:/.*)?$\n    service: http://127.0.0.1:8380\n"
def command(*args):
    p=subprocess.run(args,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=45)
    if p.returncode: raise RuntimeError("command failed: "+args[0])
    return p.stdout
def health():
    with urlopen("http://127.0.0.1:8380/endnote/health",timeout=5) as r:
        obj=json.load(r)
        if not obj.get("ok"):raise RuntimeError("endnote health failed")
        return obj
def http_status(url):
    try:
        with urlopen(url,timeout=5) as r:return r.status
    except HTTPError as e:return e.code
def origin_baseline(config):
    values={}
    for url in re.findall(r"service:\s*(http://127\.0\.0\.1:\d+)",config):
        if ":8380" in url:continue
        values[url]=http_status(url)
        if values[url]>=500:raise RuntimeError("existing origin degraded: "+url)
    return values
def smtp_config():
    result={}
    for line in SOURCE.read_text().splitlines():
        if "=" not in line:continue
        key,value=line.split("=",1)
        if key not in {"SMTP_HOST","SMTP_PORT","SMTP_USERNAME","SMTP_PASSWORD","SMTP_FROM","SMTP_USE_SSL","SMTP_STARTTLS"}:continue
        tokens=shlex.split(value,comments=True)
        result[key]=tokens[0] if tokens else ""
    if any(not result.get(k) for k in ["SMTP_HOST","SMTP_USERNAME","SMTP_PASSWORD","SMTP_FROM"]):
        raise RuntimeError("missing existing SMTP configuration")
    return result
def record(path,obj):
    path.write_text(json.dumps(obj,indent=2));path.chmod(0o600)
def restore(info):
    if info.get("tunnel_changed"):
        TUNNEL.write_text(Path(info["tunnel_backup"]).read_text())
        command("cloudflared","--config",str(TUNNEL),"tunnel","ingress","validate")
        command("systemctl","restart","cloudflared")
    if info["previous"]:
        link=ROOT/"current.rollback"
        if link.is_symlink():link.unlink()
        link.symlink_to(info["previous"]);os.replace(link,ROOT/"current")
        if info["unit_backup"]:shutil.copyfile(info["unit_backup"],UNIT)
        command("systemctl","daemon-reload");command("systemctl","restart","endnote")
        health()
    else:
        subprocess.run(["systemctl","disable","--now","endnote"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
        if (ROOT/"current").is_symlink():(ROOT/"current").unlink()
        if info.get("unit_backup"):shutil.copyfile(info["unit_backup"],UNIT)
        elif UNIT.exists():UNIT.unlink()
        command("systemctl","daemon-reload")
    command("systemctl","is-active","cloudflared")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("archive",nargs="?")
    parser.add_argument("sha256",nargs="?")
    parser.add_argument("--rollback")
    args=parser.parse_args()
    if os.geteuid()!=0:raise RuntimeError("root required")
    if socket.gethostname()!="ps":raise RuntimeError("4090 workstation identity required")
    lock=open("/var/lock/endnote-deploy.lock","w")
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    # Serialize against other edits to the same tunnel.
    tunnel_lock=open("/var/lock/cloudflared-config.lock","w")
    fcntl.flock(tunnel_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if args.rollback:
        info=json.loads(Path(args.rollback).read_text())
        if info.get("root")!=str(ROOT):raise RuntimeError("invalid rollback record")
        restore(info);print("ROLLBACK_OK");return
    if not args.archive or not re.fullmatch("[0-9a-f]{64}",args.sha256 or ""):raise RuntimeError("archive and SHA256 required")
    archive=Path(args.archive)
    if archive.stat().st_size>2_000_000:raise RuntimeError("archive too large")
    raw=archive.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=args.sha256:raise RuntimeError("archive checksum mismatch")
    data={}
    with tarfile.open(fileobj=io.BytesIO(raw),mode="r:gz") as t:
        members=t.getmembers()
        if len(members)>100 or sum(m.size for m in members)>2_000_000:raise RuntimeError("expanded artifact too large")
        for member in members:
            name=member.name
            p=PurePosixPath(name)
            if not member.isfile() or p.is_absolute() or ".." in p.parts or name in data:raise RuntimeError("unsafe archive member")
            if name!="MANIFEST.json" and not (name.startswith("endnote/") and p.suffix in {".py",".js",".html",".css"}):raise RuntimeError("unexpected archive member")
            data[name]=t.extractfile(member).read()
    manifest=json.loads(data.pop("MANIFEST.json"))
    if manifest.get("format")!=1 or manifest.get("files")!={k:hashlib.sha256(v).hexdigest() for k,v in sorted(data.items())}:raise RuntimeError("manifest mismatch")
    command("systemctl","is-active","cloudflared")
    cfg=TUNNEL.read_text()
    baseline=origin_baseline(cfg)
    if not re.search(r"^\s+- hostname: am\.matterswarm\.com\s*$",cfg,re.M):raise RuntimeError("existing hostname ingress missing")
    if not (ROOT/"current").exists():
        sock=socket.socket();sock.bind(("127.0.0.1",8380));sock.close()
    else:health()
    disk=shutil.disk_usage("/opt")
    if disk.free-sum(map(len,data.values()))*3<max(2*1024**3,disk.total*.15):raise RuntimeError("insufficient disk reserve")
    mem=int(re.search(r"MemAvailable:\s*(\d+)",Path("/proc/meminfo").read_text()).group(1))*1024
    if mem<1024**3:raise RuntimeError("insufficient memory reserve")
    # Avoid publication while the host is under sustained severe I/O or memory stalls.
    for file in ["/proc/pressure/io","/proc/pressure/memory"]:
        p=Path(file)
        if p.exists():
            full=re.search(r"full avg10=([\d.]+)",p.read_text())
            if full and float(full.group(1))>10:raise RuntimeError("host pressure too high")
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ops=ROOT/"ops"/stamp;ops.mkdir(parents=True,exist_ok=False);ops.chmod(0o700)
    prior=str((ROOT/"current").resolve()) if (ROOT/"current").is_symlink() else None
    if (ROOT/"current").exists() and not prior:raise RuntimeError("current must be a release symlink")
    tunnel_backup=ops/"cloudflared.yml";shutil.copyfile(TUNNEL,tunnel_backup);tunnel_backup.chmod(0o600)
    unit_backup=ops/"endnote.service"
    if UNIT.exists():shutil.copyfile(UNIT,unit_backup)
    info=dict(root=str(ROOT),release=args.sha256,previous=prior,tunnel_backup=str(tunnel_backup),
              unit_backup=str(unit_backup) if UNIT.exists() else None,tunnel_changed=False,
              baseline=baseline,activated_at=stamp)
    record_path=ops/"release.json";record(record_path,info)
    release=ROOT/"releases"/args.sha256
    if release.exists():
        actual={str(p.relative_to(release)):p.read_bytes() for p in release.rglob("*") if p.is_file()}
        if actual!=data:raise RuntimeError("retained immutable release differs from verified artifact")
    else:
        release.mkdir(parents=True)
        for name,content in data.items():
            dest=release/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(content);dest.chmod(0o644)
    credential=Path("/etc/endnote/smtp.json");credential.parent.mkdir(mode=0o700,exist_ok=True)
    if not credential.exists():
        credential.write_text(json.dumps(smtp_config()));credential.chmod(0o600)
    # Authenticate with the existing SMTP account; no email is sent by this check.
    import sys
    sys.path.insert(0,str(release))
    from endnote.service import smtp_sender
    c=json.loads(credential.read_text());smtp_sender(c)
    import ssl,smtplib
    if str(c.get("SMTP_USE_SSL","true")).lower() in {"true","1","yes"}:
        smtp=smtplib.SMTP_SSL(c["SMTP_HOST"],int(c.get("SMTP_PORT","465")),timeout=20,context=ssl.create_default_context())
    else:
        smtp=smtplib.SMTP(c["SMTP_HOST"],int(c.get("SMTP_PORT","587")),timeout=20);smtp.starttls(context=ssl.create_default_context())
    with smtp:
        smtp.login(c["SMTP_USERNAME"],c["SMTP_PASSWORD"])
        if smtp.noop()[0]!=250:raise RuntimeError("SMTP NOOP failed")
    print("SMTP_AUTH_NOOP_OK")
    unit="""[Unit]
Description=endnote experiment notification API
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
DynamicUser=yes
WorkingDirectory=/opt/endnote/current
ExecStart=/usr/bin/python3 -B -m endnote.server --bind 127.0.0.1 --port 8380 --prefix /endnote --trusted-local-proxy
Environment=PYTHONUNBUFFERED=1
Environment=ENDNOTE_STATE_DIR=/var/lib/endnote
Environment=ENDNOTE_PUBLIC_URL=https://am.matterswarm.com/endnote
Environment=ENDNOTE_MAIL_ENABLED=true
Environment=ENDNOTE_SIGNUP_ENABLED=true
StateDirectory=endnote
StateDirectoryMode=0700
LoadCredential=smtp.json:/etc/endnote/smtp.json
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
RestrictRealtime=true
CapabilityBoundingSet=
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
UMask=0077
MemoryMax=256M
TasksMax=64
CPUQuota=100%
LimitNOFILE=1024

[Install]
WantedBy=multi-user.target
"""
    try:
        UNIT.write_text(unit)
        command("systemd-analyze","verify",str(UNIT))
        link=ROOT/"current.candidate";link.symlink_to(release);os.replace(link,ROOT/"current")
        command("systemctl","daemon-reload");command("systemctl","enable","--now","endnote")
        if prior:command("systemctl","restart","endnote")
        for _ in range(15):
            try:health();break
            except Exception:time.sleep(1)
        else:raise RuntimeError("candidate origin did not start")
        if RULE not in cfg:
            candidate=cfg.replace("  - hostname: am.matterswarm.com\n",RULE+"  - hostname: am.matterswarm.com\n",1)
            candidate_file=ops/"cloudflared.candidate.yml";candidate_file.write_text(candidate);candidate_file.chmod(0o600)
            command("cloudflared","--config",str(candidate_file),"tunnel","ingress","validate")
            info["tunnel_changed"]=True;record(record_path,info)
            TUNNEL.write_text(candidate);TUNNEL.chmod(0o600)
            command("systemctl","restart","cloudflared")
        command("systemctl","is-active","endnote")
        command("systemctl","is-active","cloudflared")
        for url,status in baseline.items():
            if http_status(url)!=status:raise RuntimeError("existing origin changed: "+url)
        info["origin"]=health();record(record_path,info)
    except BaseException:
        restore(info)
        raise
    print(json.dumps({"release":args.sha256,"rollback_record":str(record_path),"origin":info["origin"]}))

if __name__=="__main__":
    try:main()
    except Exception as e:
        # Do not expose provider replies or secrets from exceptions.
        print("ACTIVATION_FAILED: "+type(e).__name__)
        raise SystemExit(1)
