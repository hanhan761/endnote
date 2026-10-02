"""Trusted owner enrollment through an authorized administrator console, never HTTP.

The owner explicitly chooses the recipient. Public callers use isolated quick tasks.
Generate the plaintext API key on the client; this helper accepts only its SHA-256 hash.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys

def enroll_owner(store,address,key_hash):
    from endnote.service import email
    address=email(address)
    if not isinstance(key_hash,str) or not re.fullmatch(r"[0-9a-f]{64}",key_hash):
        raise ValueError("SHA-256 key digest required")
    with store.db() as c:
        row=c.execute("SELECT id FROM accounts WHERE email=?",(address,)).fetchone()
        account_id=row["id"] if row else secrets.token_hex(16)
        if row:
            c.execute("UPDATE accounts SET key_hash=? WHERE id=?",(key_hash,account_id))
        else:
            c.execute("INSERT INTO accounts VALUES(?,?,?,?)",(account_id,address,key_hash,store.clock()))
        already=c.execute("SELECT 1 FROM notices WHERE owner=? AND kind='binding'",(account_id,)).fetchone()
        if not already:
            store.queue(c,account_id,None,address,"[endnote] 邮箱绑定成功",
                        "你的邮箱已成功绑定 endnote。\n\n这是一封绑定成功测试邮件。本机已保存通知配置，以后复用 endnote 无需重复输入邮箱或绑定。\n\n实验完成、失败、失联或满足你选择的提醒条件时，会向这个邮箱发送通知。正常心跳不会定期发邮件。\n\n管理实验："+store.settings.public_url+"/","binding")
        c.execute("DELETE FROM challenges WHERE email=?",(address,))
        c.execute("UPDATE notices SET state='cancelled',body='' WHERE recipient=? AND kind='verification' AND state='pending'",(address,))
    return {"ok":True,"account_id":account_id,"binding_test":"already_requested" if already else "queued"}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--payload",required=True)
    p.add_argument("--sha256",required=True)
    args=p.parse_args()
    if os.name=="nt" or os.geteuid()!=0:raise RuntimeError("authorized root console required")
    raw=Path(args.payload).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=args.sha256:raise RuntimeError("enrollment payload checksum mismatch")
    payload=json.loads(raw)
    sys.path.insert(0,"/opt/endnote/current")
    from endnote.service import Settings,Store
    store=Store(Settings("/var/lib/endnote/endnote.db",public_url="https://am.matterswarm.com/endnote"))
    result=enroll_owner(store,payload["email"],payload["key_hash"])
    print(json.dumps(result))

if __name__=="__main__":main()
