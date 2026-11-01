import importlib.util
from pathlib import Path
import tempfile
import unittest
spec=importlib.util.spec_from_file_location('ma_prepare',Path(__file__).with_name('prepare.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Tests(unittest.TestCase):
 def test_fresh_attempt_allowed(self):
  with tempfile.TemporaryDirectory() as d:m.guard_attempt(Path(d),'MA2305-2023-04-17')
 def test_all_partial_artifacts_block_retry(self):
  for suffix in ('.json','.jsonl','.parquet'):
   with self.subTest(suffix=suffix),tempfile.TemporaryDirectory() as d:
    p=Path(d);(p/('MA2305-2023-04-17'+suffix)).touch()
    with self.assertRaisesRegex(ValueError,'NO_AUTOMATIC_RETRY'):m.guard_attempt(p,'MA2305-2023-04-17')
 def test_bounds_and_budget(self):
  p=m.plan();self.assertEqual(len(p['jobs']),13);self.assertEqual(sum(j['expected_rows'] for j in p['jobs']),4365)
  self.assertTrue(all(j['contract'].startswith('MA') and j['frequency']=='1m' for j in p['jobs']))
  self.assertEqual(p['reserve_bytes'],128*1024**2)
if __name__=='__main__':unittest.main()
