import tempfile,unittest
from pathlib import Path
from endnote.service import APIError,Settings,Store,digest
from scripts.enroll_owner import enroll_owner
class ModuleGroupingTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.settings=Settings(str(Path(self.tmp.name)/'test.db'),mail_enabled=True,signup_enabled=True)
  self.store=Store(self.settings,sender=lambda *args:None)
  self.key='module-owner';enroll_owner(self.store,'module@example.com',digest(self.key))
 def dashboard(self):
  with self.store.db(read_only=True) as c:token=c.execute('SELECT token FROM dashboards WHERE recipient_hash=?',(digest('module@example.com'),)).fetchone()[0]
  return self.store.dashboard(token)
 def test_group_survives_name_change_events_and_store_restart(self):
  old=self.store.create_task(self.key,{'name':'Original round18','group':'beam-module'})
  new=self.store.create_task(self.key,{'name':'Renamed round19','group':'beam-module'})
  self.store.event(old['task_key'],old['id'],{'type':'failed','event_id':'ended'})
  self.store.event(new['task_key'],new['id'],{'type':'heartbeat','event_id':'beat'})
  self.store=Store(self.settings,sender=lambda *args:None)
  tasks=self.dashboard()['tasks'];self.assertEqual({t['group'] for t in tasks},{'beam-module'})
  self.assertEqual({t['status'] for t in tasks},{'running','failed'})
 def test_legacy_tasks_keep_optional_group_unknown(self):
  self.store.create_task(self.key,{'name':'Legacy round1'})
  self.assertIsNone(self.dashboard()['tasks'][0]['group'])
 def test_quick_entry_retains_declared_group(self):
  self.store.quick_task({'email':'module@example.com','name':'Public round2','group':'beam-module'},'fixture-ip')
  self.assertEqual(self.dashboard()['tasks'][0]['group'],'beam-module')
 def test_group_validation_is_bounded_and_plain_text(self):
  for group in ['', 'x'*61, 123, 'bad\nmodule']:
   with self.subTest(group=group),self.assertRaises(APIError):self.store.validate_config({'name':'test','group':group})
