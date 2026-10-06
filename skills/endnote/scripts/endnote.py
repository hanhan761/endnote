"""Zero-dependency client and experiment command wrapper."""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
import uuid
import warnings
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None

class NotificationError(RuntimeError):
    pass

class Client:
    def __init__(self,url=None,key=None):
        self.url=(url or os.getenv("ENDNOTE_URL","https://am.matterswarm.com/endnote")).rstrip("/")
        parsed=urlsplit(self.url)
        if parsed.scheme!="https" and not (parsed.scheme=="http" and parsed.hostname in {"127.0.0.1","localhost","::1"}):
            raise ValueError("HTTPS required except for loopback development")
        if parsed.username or parsed.password or parsed.query or parsed.fragment: raise ValueError("invalid service URL")
        self.key=key or os.getenv("ENDNOTE_API_KEY","")
        if not self.key:
            from pathlib import Path
            saved=Path.home()/".config"/"endnote"/"credentials.json"
            if saved.exists():
                config=json.loads(saved.read_text())
                if config.get("url", "").rstrip("/")==self.url:
                    self.key=config.get("api_key", "")
    def request(self,route,data=None,key=None,method=None,retries=0):
        payload=json.dumps(data,allow_nan=False).encode() if data is not None else None
        headers={"User-Agent":"endnote/0.1 (+https://github.com/hanhan761/endnote)","Content-Type":"application/json","Authorization":"Bearer "+(self.key if key is None else key)}
        for attempt in range(retries+1):
            req=Request(self.url+route,payload,headers,method=method)
            try:
                with build_opener(NoRedirect).open(req,timeout=10) as response: return json.load(response)
            except HTTPError as e:
                # Do not surface server payloads that might include private data.
                if e.code not in {429,500,502,503,504} or attempt==retries:
                    raise NotificationError(f"endnote API returned HTTP {e.code}") from None
            except (URLError,TimeoutError,OSError):
                if attempt==retries: raise NotificationError("endnote service unreachable") from None
            time.sleep(min(4,2**attempt))
    def experiment(self,name,heartbeat_timeout=300,heartbeat_interval=60,**config):
        return Experiment(self,name,heartbeat_timeout,heartbeat_interval,config)

class Experiment:
    def __init__(self,client,name,timeout,interval,config):
        if not 5<=interval<timeout/2: raise ValueError("heartbeat interval must be >=5 and less than half the timeout")
        self.client,self.name,self.timeout,self.interval,self.config=client,name,timeout,interval,config
        self.stop=threading.Event()
        self.finalized=False
        self.task=None
        self.thread=None
    def __enter__(self):
        payload=dict(name=self.name,heartbeat_timeout=self.timeout,**self.config)
        address=payload.pop("email",None)
        route="/v1/tasks"
        if not self.client.key or address:
            payload["email"]=address or saved_email()
            if not payload["email"]: raise ValueError("provide email or save a default email")
            route="/v1/quick/tasks"
        self.task=self.client.request(route,payload,key="" if route=="/v1/quick/tasks" else None)
        self.thread=threading.Thread(target=self._heartbeat,daemon=True)
        self.thread.start()
        return self
    def event(self,kind,metrics=None,message=""):
        if not self.task: raise RuntimeError("experiment has not started")
        result=self.client.request("/v1/tasks/"+self.task["id"]+"/events",
            {"event_id":uuid.uuid4().hex,"type":kind,"metrics":metrics or {},"message":message},
            key=self.task["task_key"],retries=3)
        if kind in {"succeeded","failed","cancelled"}: self.finalized=True
        return result
    def metric(self,**values): return self.event("metric",values)
    def heartbeat(self): return self.event("heartbeat")
    def queued(self): return self.event("queued")
    def started(self): return self.event("started")
    def _heartbeat(self):
        while not self.stop.wait(self.interval):
            try: self.heartbeat()
            except NotificationError:
                warnings.warn("endnote heartbeat unavailable; server may report heartbeat timeout",RuntimeWarning)
    def __exit__(self,kind,error,tb):
        self.stop.set()
        self.thread.join(45)
        if self.finalized: return False
        try:
            # Exception text may contain secrets: completion sends only its type by default.
            self.event("failed" if kind else "succeeded",message=kind.__name__ if kind else "experiment completed")
        except NotificationError:
            warnings.warn("endnote could not report completion; check notification service",RuntimeWarning)
        return False

def saved_email():
    from pathlib import Path
    directory=Path.home()/".config"/"endnote"
    for name in ["preferences.json","credentials.json"]:
        file=directory/name
        if file.exists():
            value=json.loads(file.read_text()).get("email")
            if value: return value
    return None

def main():
    parser=argparse.ArgumentParser(description="endnote: end, then note")
    parser.add_argument("--url",default=os.getenv("ENDNOTE_URL","https://am.matterswarm.com/endnote"))
    sub=parser.add_subparsers(dest="action",required=True)
    p=sub.add_parser("request-code"); p.add_argument("--email")
    p=sub.add_parser("verify"); p.add_argument("--email")
    p=sub.add_parser("list")
    p=sub.add_parser("run"); p.add_argument("--email"); p.add_argument("--name",required=True); p.add_argument("--heartbeat-timeout",type=int,default=300); p.add_argument("--heartbeat-interval",type=int,default=60); p.add_argument("--runtime-timeout",type=int); p.add_argument("--rules",help="JSON file of metric rules"); p.add_argument("command",nargs=argparse.REMAINDER)
    p=sub.add_parser("event"); p.add_argument("--task",required=True); p.add_argument("--type",required=True,choices=["heartbeat","metric","queued","started","succeeded","failed","cancelled"]); p.add_argument("--metrics",default="{}"); p.add_argument("--message",default="")
    args=parser.parse_args()
    client=Client(args.url)
    if args.action in {"request-code","verify"}:
        args.email=args.email or saved_email()
        if not args.email: parser.error("provide --email once, or save email in ~/.config/endnote/preferences.json")
    if args.action=="request-code":
        print(json.dumps(client.request("/v1/auth/request",{"email":args.email},key=""),ensure_ascii=False))
    elif args.action=="verify":
        import getpass
        code=getpass.getpass("Email verification code: ")
        result=client.request("/v1/auth/verify",{"email":args.email,"code":code},key="")
        # Save to a user-owned private file, never to logs/stdout.
        from pathlib import Path
        target=Path.home()/".config"/"endnote"/"credentials.json"
        target.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,"w") as f: json.dump({"url":client.url,"api_key":result["api_key"],"email":result["email"]},f)
        os.chmod(target,0o600)
        print("Saved account key to "+str(target)+"; load it into ENDNOTE_API_KEY privately.")
    elif args.action=="list": print(json.dumps(client.request("/v1/tasks"),ensure_ascii=False,indent=2))
    elif args.action=="event":
        key=os.getenv("ENDNOTE_TASK_KEY")
        if not key: parser.error("ENDNOTE_TASK_KEY required")
        result=client.request("/v1/tasks/"+args.task+"/events",{"event_id":uuid.uuid4().hex,"type":args.type,"metrics":json.loads(args.metrics),"message":args.message},key=key,retries=3)
        print(json.dumps(result))
    elif args.action=="run":
        command=args.command
        if command and command[0]=="--": command=command[1:]
        if not command: parser.error("command required after --")
        config={}
        if args.email: config["email"]=args.email
        if args.runtime_timeout: config["runtime_timeout"]=args.runtime_timeout
        if args.rules:
            from pathlib import Path
            config["rules"]=json.loads(Path(args.rules).read_text())
        code=1
        with client.experiment(args.name,args.heartbeat_timeout,args.heartbeat_interval,**config) as experiment:
            print("endnote tracking task "+experiment.task["id"],flush=True)
            flags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0
            try:
                process=subprocess.Popen(command,shell=False,creationflags=flags)
                code=process.wait()
            except BaseException:
                if "process" in locals() and process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=10)
                    except subprocess.TimeoutExpired: process.kill(); process.wait()
                raise
            if code:
                experiment.stop.set()
                experiment.thread.join(45)
                experiment.event("failed",message=f"command exited with code {code}")

        return code
    return 0

if __name__=="__main__":
    try: sys.exit(main())
    except NotificationError as e: print(str(e),file=sys.stderr); sys.exit(2)
