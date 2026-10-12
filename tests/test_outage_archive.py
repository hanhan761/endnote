import tempfile,unittest
from pathlib import Path
from endnote.service import APIError,Settings,Store,digest
from scripts.enroll_owner import enroll_owner
class OutageArchiveTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.now=1700000000.
  self.store=Store(Settings(str(Path(self.tmp.name)/'test.db')),clock=lambda:self.now)
  self.key='archive-owner';enroll_owner(self.store,'archive@example.com',digest(self.key))
  self.task=self.store.create_task(self.key,{'name':'Project ongoing'})
  with self.store.db(read_only=True) as c:self.token=c.execute('SELECT token FROM dashboards WHERE recipient_hash=?',(digest('archive@example.com'),)).fetchone()[0]
 def test_outage_archive_preserves_task_notifications_and_restores_after_recovery(self):
  self.now+=301
  with self.store.db(read_only=True) as c:before=c.execute('SELECT count(*) FROM notices').fetchone()[0]
  self.store.archive_dashboard_task(self.token,self.task['id'])
  self.assertEqual(self.store.dashboard(self.token)['total'],0)
  archived=self.store.dashboard(self.token,archived=True)['tasks'][0]
  self.assertEqual(archived['status'],'running');self.assertTrue(archived['outage'])
  with self.store.db(read_only=True) as c:self.assertEqual(c.execute('SELECT count(*) FROM notices').fetchone()[0],before)
  self.store.event(self.task['task_key'],self.task['id'],{'type':'heartbeat','event_id':'recovered'})
  self.store.archive_dashboard_task(self.token,self.task['id'],False)
  self.assertFalse(self.store.dashboard(self.token)['tasks'][0]['outage'])
 def test_fresh_running_task_rejects_archive(self):
  with self.assertRaises(APIError) as ctx:self.store.archive_dashboard_task(self.token,self.task['id'])
  self.assertEqual(ctx.exception.status,409)
 def test_heartbeat_disabled_task_is_not_an_outage(self):
  task=self.store.create_task(self.key,{'name':'No heartbeat alarm','notify_on':['succeeded','failed']});self.now+=301
  with self.assertRaises(APIError):self.store.archive_dashboard_task(self.token,task['id'])
 def test_recipient_isolation_is_preserved(self):
  other='other-owner';enroll_owner(self.store,'other@example.com',digest(other));task=self.store.create_task(other,{'name':'Other task'});self.now+=301
  with self.assertRaises(APIError) as ctx:self.store.archive_dashboard_task(self.token,task['id'])
  self.assertEqual(ctx.exception.status,404)
