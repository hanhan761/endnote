"""Backward-compatible queued/started events without a database migration."""
def patch_service(source):
    text = source.decode("utf-8").replace("\r\n", "\n")
    changes = [
        ("{'heartbeat','metric','succeeded','failed','cancelled'}", "{'heartbeat','metric','queued','started','succeeded','failed','cancelled'}"),
        ("merged=json.loads(task['metrics']); merged.update(metrics)", "merged=json.loads(task['metrics']); merged.update(metrics)\n            if kind in {'queued','started'}: merged['endnote_queued']=int(kind=='queued')"),
        ('"all","active","running","waiting","outage"', '"all","active","running","waiting","queued","outage"'),
        ("elif status in {'running','waiting'}:", "elif status=='queued':\n                filter_clause+=\" AND t.status='running' AND COALESCE(json_extract(t.metrics,'$.endnote_queued'),0)=1 AND NOT \"+outage_sql;filter_args.append(self.clock())\n            elif status in {'running','waiting'}:"),
        ("filter_args.append(self.clock())\n            elif status=='ended'", "filter_args.append(self.clock())\n                filter_clause+=\" AND COALESCE(json_extract(t.metrics,'$.endnote_queued'),0)!=1\"\n            elif status=='ended'"),
        ("summary={'running':0,'waiting':0", "summary={'queued':0,'running':0,'waiting':0"),
        ("SELECT t.status,t.heartbeat,t.heartbeat_seq,t.config ", "SELECT t.status,t.heartbeat,t.heartbeat_seq,t.config,t.metrics "),
        ("else 'waiting' if info['heartbeat_seq']==0 else 'running'", "else 'queued' if json.loads(info['metrics']).get('endnote_queued')==1 else 'waiting' if info['heartbeat_seq']==0 else 'running'"),
    ]
    for before, after in changes:
        if text.count(before)!=1: raise ValueError("queue patch anchor mismatch: "+before)
        text=text.replace(before,after,1)
    return text.encode("utf-8")

def patch_client(source):
    text=source.decode("utf-8").replace("\r\n", "\n")
    before='    def heartbeat(self): return self.event("heartbeat")'
    if text.count(before)!=1: raise ValueError("client queue anchor mismatch")
    text=text.replace(before,before+'\n    def queued(self): return self.event("queued")\n    def started(self): return self.event("started")',1)
    text=text.replace('choices=["heartbeat","metric","succeeded","failed","cancelled"]','choices=["heartbeat","metric","queued","started","succeeded","failed","cancelled"]')
    return text.encode("utf-8")
