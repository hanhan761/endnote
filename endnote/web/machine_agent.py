"""Read-only local resource collector; Python standard library, outbound HTTPS only."""
import argparse
import csv
import ctypes
import io
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError
from urllib.parse import urlsplit

CONFIG = None  # Filled only in the private downloaded copy.

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def numeric(value,scale=1):
    try:
        result=float(value)*scale
        return result if math.isfinite(result) else None
    except (ValueError,TypeError):return None

def gpu_metrics():
    command=shutil.which('nvidia-smi')
    if not command:return []
    try:
        result=subprocess.run([command,'--query-gpu=index,name,utilization.gpu,temperature.gpu,memory.used,memory.total,power.draw','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=4,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        if result.returncode:return []
        rows=[]
        for parts in list(csv.reader(io.StringIO(result.stdout)))[:8]:
            if len(parts)!=7:continue
            rows.append(dict(index=int(parts[0]),name=parts[1].strip()[:80],percent=numeric(parts[2]),temperature=numeric(parts[3]),memory_used=numeric(parts[4],1024**2),memory_total=numeric(parts[5],1024**2),power=numeric(parts[6])))
        return rows
    except (OSError,ValueError,subprocess.TimeoutExpired):return []

class Collector:
    def __init__(self):self.previous=self.cpu_times()
    def cpu_times(self):
        if sys.platform.startswith('linux'):
            try:
                values=list(map(int,Path('/proc/stat').read_text().splitlines()[0].split()[1:9]))
                return values[3]+values[4],sum(values)
            except (OSError,ValueError,IndexError):return None
        if os.name=='nt':
            from ctypes import wintypes
            idle,kernel,user=wintypes.FILETIME(),wintypes.FILETIME(),wintypes.FILETIME()
            if ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle),ctypes.byref(kernel),ctypes.byref(user)):
                integer=lambda f:(f.dwHighDateTime<<32)|f.dwLowDateTime
                return integer(idle),integer(kernel)+integer(user)
        return None
    def memory(self):
        if sys.platform.startswith('linux'):
            try:
                values={p[0].rstrip(':'):int(p[1])*1024 for p in (line.split() for line in Path('/proc/meminfo').read_text().splitlines()) if len(p)>=2 and p[1].isdigit()}
                total=values['MemTotal'];return total,total-values.get('MemAvailable',values.get('MemFree',0))
            except (OSError,ValueError,KeyError):return None,None
        if os.name=='nt':
            class Memory(ctypes.Structure):
                _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(name,ctypes.c_ulonglong) for name in ['total','available','total_page','available_page','total_virtual','available_virtual','extended']]
            result=Memory();result.length=ctypes.sizeof(result)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(result)):return result.total,result.total-result.available
        return None,None
    def temperature(self):
        if not sys.platform.startswith('linux'):return None
        values=[]
        try:
            for chip in list(Path('/sys/class/hwmon').glob('hwmon*'))[:64]:
                try:
                    if (chip/'name').read_text().strip() not in {'coretemp','k10temp','zenpower','cpu_thermal'}:continue
                    for sensor in list(chip.glob('temp*_input'))[:64]:
                        value=numeric(sensor.read_text(),.001)
                        if value is not None and -20<=value<=150:values.append(value)
                except OSError:continue
        except OSError:pass
        return max(values) if values else None
    def sample(self):
        current=self.cpu_times();cpu=None
        if current and self.previous:
            idle,total=current[0]-self.previous[0],current[1]-self.previous[1]
            if total>0:cpu=max(0,min(100,100*(1-idle/total)))
        self.previous=current
        total,used=self.memory()
        try:disk=shutil.disk_usage(Path.home().anchor);disk_total,disk_used=disk.total,disk.used
        except OSError:disk_total,disk_used=None,None
        return dict(cpu_percent=cpu,cpu_temperature=self.temperature(),memory_total=total,memory_used=used,disk_total=disk_total,disk_used=disk_used,gpus=gpu_metrics())

def main(config=None):
    parser=argparse.ArgumentParser(description='endnote optional machine monitor')
    parser.add_argument('--config',type=Path,help='private JSON configuration')
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--sample',action='store_true',help='show local metrics without uploading')
    args=parser.parse_args()
    if args.config:config=json.loads(args.config.read_text())
    collector=Collector();time.sleep(1)
    if args.sample:print(json.dumps(collector.sample(),allow_nan=False));return
    if not config:parser.error('use the private downloaded script or --config')
    base=config.get('url','').rstrip('/');url=urlsplit(base)
    if url.scheme!='https' and not(url.scheme=='http' and url.hostname in {'127.0.0.1','localhost','::1'}):parser.error('HTTPS required')
    if url.username or url.password or url.query or url.fragment:parser.error('invalid URL')
    machine=config.get('id','');key=config.get('machine_key','')
    import re
    if not re.fullmatch(r'[0-9a-f]{32}',machine) or not key.startswith('en_machine_'):parser.error('invalid private configuration')
    opener=build_opener(NoRedirect);delay=15
    while True:
        started=time.monotonic()
        try:
            payload=json.dumps(collector.sample(),allow_nan=False).encode()
            request=Request(base+'/v1/machines/'+machine+'/telemetry',payload,{'Content-Type':'application/json','Authorization':'Bearer '+key,'User-Agent':'endnote-machine/1'},method='POST')
            with opener.open(request,timeout=8) as response:
                if response.status!=200:raise OSError('report refused')
            delay=15
        except HTTPError as error:
            if error.code in {401,404}:print('Machine reporting stopped: credential invalid.',file=sys.stderr);return 2
            if error.code==403:
                delay=30
                print('Machine reporting paused; waiting for permission.',file=sys.stderr)
            else:
                delay=min(120,delay*2)
                print('Machine reporting temporarily unavailable; retrying.',file=sys.stderr)
        except (OSError,ValueError):
            delay=min(120,delay*2)
            print('Machine reporting temporarily unavailable; retrying.',file=sys.stderr)
        if args.once:return 0
        time.sleep(max(1,delay-(time.monotonic()-started)))

if __name__=='__main__':
    try:sys.exit(main(CONFIG))
    except KeyboardInterrupt:sys.exit(0)
