import tempfile
import unittest
from pathlib import Path
from endnote.service import APIError, Settings, Store, digest
from scripts.enroll_owner import enroll_owner

class QueueStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now=1700000000.
        self.store=Store(Settings(str(Path(self.tmp.name)/"queue.db")),clock=lambda:self.now)
        self.key="queue-test-owner"
        enroll_owner(self.store,"queue@example.com",digest(self.key))
        self.task=self.store.create_task(self.key,{"name":"Project queued","notify_start":True})
        with self.store.db() as c: self.token=c.execute("SELECT token FROM dashboards").fetchone()[0]
    def event(self,kind,event_id=None,**data):
        return self.store.event(self.task["task_key"],self.task["id"],dict(type=kind,event_id=event_id or kind,**data))
    def test_queue_survives_heartbeat_and_metrics_until_started(self):
        self.event("queued")
        self.event("heartbeat")
        self.event("metric",metrics={"loss":.5})
        result=self.store.dashboard(self.token)
        self.assertEqual(result["summary"]["queued"],1)
        self.assertEqual(result["summary"]["running"],0)
        self.assertEqual(self.store.dashboard(self.token,status="queued")["total"],1)
        self.assertEqual(self.store.dashboard(self.token,status="running")["total"],0)
        self.assertEqual(self.store.dashboard(self.token,status="active")["total"],1)
        self.event("started")
        self.assertEqual(self.store.dashboard(self.token)["summary"]["running"],1)
        self.assertEqual(self.store.dashboard(self.token,status="queued")["total"],0)
        self.assertTrue(self.event("queued")["duplicate"])
        self.assertEqual(self.store.dashboard(self.token)["summary"]["running"],1)
    def test_queued_outage_and_terminal_status_take_precedence(self):
        self.event("queued");self.now+=301;self.store.tick()
        self.assertEqual(self.store.dashboard(self.token)["summary"]["outage"],1)
        self.assertEqual(self.store.dashboard(self.token,status="queued")["total"],0)
        self.event("succeeded")
        self.assertEqual(self.store.dashboard(self.token)["summary"]["succeeded"],1)
        with self.assertRaises(APIError):self.event("queued","after-end")
    def test_queue_events_do_not_send_additional_start_mail(self):
        self.event("queued");self.event("started")
        with self.store.db() as c:
            self.assertEqual(c.execute("SELECT count(*) FROM notices WHERE task=?",(self.task["id"],)).fetchone()[0],1)
