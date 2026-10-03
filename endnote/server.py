"""Loopback HTTP server, bounded concurrency and one durable mail worker."""
import argparse
import gzip
import json
import os
import re
import socketserver
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from .service import APIError, Settings, Store, smtp_sender, digest

STATIC = Path(__file__).with_name("web")
MAX_BODY = 16384

class Server(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True
    request_queue_size = 32
    def __init__(self,address,store,prefix="/endnote",trusted_proxy=False):
        self.store,self.prefix,self.trusted_proxy=store,prefix.rstrip('/'),trusted_proxy
        self.slots=threading.BoundedSemaphore(32)
        super().__init__(address,Handler)
    def process_request(self,request,client_address):
        if not self.slots.acquire(False):
            request.close()
            return
        try: super().process_request(request,client_address)
        except BaseException:
            self.slots.release()
            raise
    def process_request_thread(self,request,client_address):
        try: super().process_request_thread(request,client_address)
        finally: self.slots.release()
    def handle_error(self,request,client_address):
        # Never dump request payloads, API keys or SMTP responses.
        print("request failed",flush=True)

class Handler(BaseHTTPRequestHandler):
    server_version = "endnote"
    protocol_version = "HTTP/1.0"
    def setup(self):
        super().setup()
        self.connection.settimeout(10)
    def log_message(self,*args):
        pass
    def reply(self,status,data,content_type="application/json; charset=utf-8"):
        payload=data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False).encode()
        compressed=len(payload)>4096 and any(p.strip().split(";")[0]=="gzip" and not re.search(r";\s*q=0(?:\.0*)?(?:\s*;|\s*$)",p) for p in self.headers.get("Accept-Encoding","").split(","))
        if compressed:payload=gzip.compress(payload,compresslevel=3,mtime=0)
        self.send_response(status)
        if compressed:self.send_header("Content-Encoding","gzip")
        self.send_header("Vary","Accept-Encoding")
        self.send_header("Content-Type",content_type)
        self.send_header("Content-Length",str(len(payload)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Referrer-Policy","no-referrer")
        self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.send_header("X-Frame-Options","DENY")
        self.send_header("Connection","close")
        self.end_headers()
        if self.command!="HEAD": self.wfile.write(payload)
    def do_GET(self): self.dispatch()
    def do_POST(self): self.dispatch()
    def do_DELETE(self): self.dispatch()
    def do_HEAD(self): self.dispatch()
    def dispatch(self):
        try:
            target=urlsplit(self.path).path
            prefix=self.server.prefix
            if target==prefix and self.command in {"GET","HEAD"}:
                self.send_response(308); self.send_header("Location",prefix+"/"); self.send_header("Content-Length","0"); self.end_headers(); return
            if prefix and not target.startswith(prefix+"/"): raise APIError(404,"not found")
            route=target[len(prefix):] if prefix else target
            unsub=re.fullmatch(r"/unsubscribe/([A-Za-z0-9_-]{43})",route)
            if unsub and self.command in {"GET","POST"}:
                self.server.store.unsubscribe(unsub.group(1))
                return self.reply(200,(STATIC/"blocked.html").read_bytes(),"text/html; charset=utf-8")
            origin=self.headers.get("Origin")
            allowed=urlsplit(self.server.store.settings.public_url)
            if origin and origin!=f"{allowed.scheme}://{allowed.netloc}":
                raise APIError(403,"cross-origin requests disabled")
            if route=="/health" and self.command in {"GET","HEAD"}:
                healthy=time.time()-self.server.store.worker_last<90
                return self.reply(200 if healthy else 503,{"ok":healthy,"mail_enabled":self.server.store.settings.mail_enabled,"signup_enabled":self.server.store.settings.signup_enabled})
            if route in {"/","/app.js","/style.css","/runner.py","/dashboard.js","/dashboard.css"} and self.command in {"GET","HEAD"}:
                name={"/":"index.html","/app.js":"app.js","/style.css":"style.css","/runner.py":"runner.py","/dashboard.js":"dashboard.js","/dashboard.css":"dashboard.css"}[route]
                mime={"index.html":"text/html; charset=utf-8","app.js":"text/javascript; charset=utf-8","style.css":"text/css; charset=utf-8","runner.py":"text/plain; charset=utf-8","dashboard.js":"text/javascript; charset=utf-8","dashboard.css":"text/css; charset=utf-8"}[name]
                return self.reply(200,(STATIC/name).read_bytes(),mime)
            ip=self.client_address[0]
            # Trust only the local cloudflared process; ignore caller-supplied forwarded-for.
            if self.server.trusted_proxy and ip in {"127.0.0.1","::1"}:
                ip=self.headers.get("CF-Connecting-IP",ip)
            with self.server.store.db() as c:
                self.server.store.limit(c,"http:"+digest(ip),600,60)
                self.server.store.limit(c,"http-global",6000,60)
            data={}
            if self.command=="POST":
                if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length",[]))!=1: raise APIError(400,"one Content-Length required; chunked bodies disabled")
                try: length=int(self.headers["Content-Length"])
                except (ValueError,TypeError): raise APIError(400,"invalid Content-Length")
                if length<0 or length>MAX_BODY: raise APIError(413,"request body too large")
                if self.headers.get_content_type()!="application/json": raise APIError(415,"application/json required")
                raw=self.rfile.read(length)
                if len(raw)!=length: raise APIError(400,"incomplete request body")
                try: data=json.loads(raw)
                except (ValueError,UnicodeDecodeError): raise APIError(400,"invalid JSON")
                if not isinstance(data,dict): raise APIError(400,"JSON object required")
            dashboard=re.fullmatch(r'/v1/dashboard/([A-Za-z0-9_-]{43})',route)
            dashboard_archive=re.fullmatch(r'/v1/dashboard/([A-Za-z0-9_-]{43})/archive',route)
            if dashboard_archive and self.command=='POST':return self.reply(200,self.server.store.archive_dashboard_task(dashboard_archive.group(1),data.get('task_id'),data.get('archived',True)))
            dashboard_page=re.fullmatch(r'/dashboard/([A-Za-z0-9_-]{43})',route)
            if dashboard and self.command=='GET':
                raw_offset=parse_qs(urlsplit(self.path).query).get('offset',['0'])[0]
                if not re.fullmatch(r'[0-9]{1,5}',raw_offset):raise APIError(400,'invalid page offset')
                archive_filter=parse_qs(urlsplit(self.path).query).get('archived',['0'])[0]
                if archive_filter not in {'0','1'}:raise APIError(400,'invalid archive filter')
                options=parse_qs(urlsplit(self.path).query)
                trend_filter=options.get('trends',['1'])[0]
                if trend_filter not in {'0','1'}:raise APIError(400,'invalid trend filter')
                return self.reply(200,self.server.store.dashboard(dashboard.group(1),int(raw_offset),archive_filter=='1',options.get('status',['all'])[0],options.get('q',[''])[0],trend_filter=='1',options.get('task',[None])[0]))
            if dashboard_page and self.command in {'GET','HEAD'}:return self.reply(200,(STATIC/'dashboard.html').read_bytes(),'text/html; charset=utf-8')
            auth=self.headers.get("Authorization","")
            key=auth[7:] if auth.startswith("Bearer ") else ""
            store=self.server.store
            if route=="/v1/quick/tasks" and self.command=="POST": return self.reply(201,store.quick_task(data,ip))
            elif route=="/v1/auth/request" and self.command=="POST": result=store.request_verification(data.get("email"),ip)
            elif route=="/v1/auth/verify" and self.command=="POST": result=store.verify(data.get("email"),data.get("code"),ip)
            elif route=="/v1/auth/rotate" and self.command=="POST": result=store.rotate(key)
            elif route=="/v1/tasks" and self.command=="POST": return self.reply(201,store.create_task(key,data))
            elif route=="/v1/tasks" and self.command=="GET": result=store.list_tasks(key)
            else:
                match=re.fullmatch(r"/v1/tasks/([0-9a-f]{32})(/events)?",route)
                if not match: raise APIError(404,"not found")
                task_id,events=match.groups()
                if events and self.command=="POST": result=store.event(key,task_id,data)
                elif not events and self.command=="GET": result=store.task_detail(key,task_id)
                elif not events and self.command=="DELETE": result=store.delete_task(key,task_id)
                else: raise APIError(405,"method not allowed")
            self.reply(200,result)
        except APIError as e: self.reply(e.status,{"error":str(e)})
        except (TimeoutError,ConnectionError): self.close_connection=True
        except Exception:
            self.reply(500,{"error":"internal error"})

def worker(store,stop):
    while not stop.is_set():
        store.wakeup.clear()
        try:
            store.tick()
            for _ in range(10):
                if stop.is_set() or not store.deliver_one(): break
                if stop.wait(1): break
        except Exception as e:
            print("worker error: "+type(e).__name__,flush=True)
        store.wakeup.wait(5)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--bind",default="127.0.0.1")
    parser.add_argument("--port",type=int,default=8380)
    parser.add_argument("--prefix",default="/endnote")
    parser.add_argument("--trusted-local-proxy",action="store_true")
    args=parser.parse_args()
    state=Path(os.getenv("ENDNOTE_STATE_DIR","state")).resolve()
    state.mkdir(parents=True,exist_ok=True)
    lock=open(state/"server.lock","a+b")
    if os.name=="nt":
        import msvcrt
        lock.seek(0); lock.write(b"0"); lock.flush(); lock.seek(0)
        msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    else:
        import fcntl
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    enabled=os.getenv("ENDNOTE_MAIL_ENABLED","false").lower() in {"true","1"}
    settings=Settings(str(state/"endnote.db"),
                      public_url=os.getenv("ENDNOTE_PUBLIC_URL",f"http://{args.bind}:{args.port}{args.prefix}"),
                      mail_enabled=enabled,
                      signup_enabled=os.getenv("ENDNOTE_SIGNUP_ENABLED","false").lower() in {"true","1"},
                      mail_per_day=int(os.getenv("ENDNOTE_MAIL_PER_DAY","300")),
                      mail_per_user_day=int(os.getenv("ENDNOTE_MAIL_PER_USER_DAY","30")),
                      verification_per_day=int(os.getenv("ENDNOTE_VERIFICATION_PER_DAY","60")))
    sender=None
    if enabled:
        credential=os.getenv("ENDNOTE_SMTP_FILE")
        if not credential and os.getenv("CREDENTIALS_DIRECTORY"):
            credential=str(Path(os.environ["CREDENTIALS_DIRECTORY"])/"smtp.json")
        if not credential: raise RuntimeError("SMTP credential file required")
        sender=smtp_sender(json.loads(Path(credential).read_text()))
    store=Store(settings,sender)
    stop=threading.Event()
    thread=threading.Thread(target=worker,args=(store,stop),daemon=True)
    thread.start()
    server=Server((args.bind,args.port),store,args.prefix,args.trusted_local_proxy)
    print(f"endnote listening on {args.bind}:{args.port}",flush=True)
    try: server.serve_forever()
    finally:
        stop.set(); store.wakeup.set(); server.server_close(); thread.join(25); lock.close()

if __name__=="__main__": main()
