"""Downloaded endnote task connector. Run: python endnote-task.py -- YOUR_COMMAND"""
import json
import subprocess
import sys
import os
import threading
import time
import uuid
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.error import HTTPError,URLError

TASK = None

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None

def report(kind,message=""):
    data=json.dumps({"event_id":uuid.uuid4().hex,"type":kind,"message":message}).encode()
    request=Request(TASK["url"]+"/v1/tasks/"+TASK["id"]+"/events",data,
                    {"Authorization":"Bearer "+TASK["task_key"],"Content-Type":"application/json","User-Agent":"endnote/0.1"})
    for attempt in range(4):
        try:
            with build_opener(NoRedirect).open(request,timeout=10) as r:return json.load(r)
        except HTTPError as e:
            if e.code not in {429,500,502,503,504}:break
        except (URLError,OSError,TimeoutError):pass
        if attempt<3:time.sleep(2**attempt)
    print("endnote: 暂时无法上报状态",file=sys.stderr)
    return None

def main():
    if not TASK:raise SystemExit("请从 endnote 页面下载接入文件")
    command=sys.argv[1:]
    if command and command[0]=="--":command=command[1:]
    if not command:raise SystemExit("用法：python endnote-task.py -- python train.py")
    stop=threading.Event()
    def heartbeat():
        interval=min(60,TASK.get("heartbeat_timeout",300)/3)
        while not stop.wait(interval):report("heartbeat")
    thread=None
    if "heartbeat_timeout" in TASK.get("notify_on",[]):
        thread=threading.Thread(target=heartbeat,daemon=True);thread.start()
    process=None
    try:
        flags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0
        process=subprocess.Popen(command,shell=False,creationflags=flags)
        code=process.wait()
    except BaseException:
        if process and process.poll() is None:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        stop.set()
        if thread:thread.join(45)
        report("failed","实验进程异常退出")
        raise
    stop.set()
    if thread:thread.join(45)
    report("succeeded" if code==0 else "failed",f"exit code {code}")
    return code

if __name__=="__main__":sys.exit(main())
