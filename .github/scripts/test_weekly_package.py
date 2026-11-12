import ast, unittest
from pathlib import Path
class PackagePolicy(unittest.TestCase):
 def test_native_final_bytes(self):
  p=Path(__file__).with_name('weekly_package.py');text=p.read_text();ast.parse(text)
  for required in ['Native target mismatch','Tag/version/source mismatch','verify_authenticode.ps1','runtime.validate(target,binary','shutil.unpack_archive','--appimage-extract','test_native_startup.py','validate-tools']:
   self.assertIn(required,text)
 def test_permissions_and_schedule(self):
  text=(Path(__file__).parents[1]/'workflows/weekly-release-smoke.yml').read_text()
  self.assertEqual(text.count('contents: write'),1)
  self.assertIn("cron: '17 16 * * 0'",text)
  for event in ['  push:','  pull_request:','  workflow_dispatch:']:self.assertNotIn(event,text)
  self.assertIn("if: always() && github.run_attempt == 1 && needs.select.outputs.has_new == 'true'",text)
if __name__=='__main__':unittest.main()
