import tempfile,unittest
from pathlib import Path
from endnote.service import Store,Settings,digest
from scripts.enroll_owner import enroll_owner
class ModuleBindingTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.settings=Settings(str(Path(self.tmp.name)/'test.db'));self.store=Store(self.settings)
  self.key='owner';enroll_owner(self.store,'owner@example.com',digest(self.key))
  self.store.create_task(self.key,{'name':'Numerai old round','group':'Numerai-PlanA'})
  with self.store.db() as c:
   self.token=c.execute('SELECT token FROM dashboards WHERE recipient_hash=?',(digest('owner@example.com'),)).fetchone()[0]
   c.execute('INSERT INTO dashboard_module_bindings VALUES(?,?,?)',(digest('owner@example.com'),'numerai','Numerai'))
 def test_existing_future_and_legacy_rounds_share_module_after_restart(self):
  self.store.create_task(self.key,{'name':'Renamed round','group':'Numerai-PlanB'})
  self.store.create_task(self.key,{'name':'Numerai legacy round'})
  self.store=Store(self.settings)
  self.assertEqual({t['group'] for t in self.store.dashboard(self.token)['tasks']},{'Numerai'})
 def test_module_binding_is_recipient_scoped(self):
  enroll_owner(self.store,'other@example.com',digest('other'))
  self.store.create_task('other',{'name':'Numerai other','group':'Numerai-PlanA'})
  with self.store.db(read_only=True) as c:token=c.execute('SELECT token FROM dashboards WHERE recipient_hash=?',(digest('other@example.com'),)).fetchone()[0]
  self.assertEqual(self.store.dashboard(token)['tasks'][0]['group'],'Numerai-PlanA')
 def test_prefix_boundaries_do_not_merge_unrelated_module(self):
  self.store.create_task(self.key,{'name':'NumeraiOther round','group':'NumeraiOther'})
  self.assertEqual(next(t for t in self.store.dashboard(self.token)['tasks'] if t['name']=='NumeraiOther round')['group'],'NumeraiOther')
