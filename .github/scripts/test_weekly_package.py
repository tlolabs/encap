import ast, json, os, subprocess, sys, tempfile, textwrap, unittest
from pathlib import Path
class PackagePolicy(unittest.TestCase):
 def test_native_final_bytes(self):
  p=Path(__file__).with_name('weekly_package.py');text=p.read_text();ast.parse(text)
  for required in ['Native target mismatch','Tag/version/source mismatch','verify_weekly_windows.ps1','runtime.validate(target,binary','shutil.unpack_archive','--appimage-extract','test_native_startup.py','validate-tools']:
   self.assertIn(required,text)
 def test_permissions_and_schedule(self):
  text=(Path(__file__).parents[1]/'workflows/weekly-release-smoke.yml').read_text()
  self.assertEqual(text.count('contents: write'),1)
  self.assertIn("cron: '17 16 * * 0'",text)
  for event in ['  push:','  pull_request:','  workflow_dispatch:']:self.assertNotIn(event,text)
  self.assertIn("if: always() && github.run_attempt == 1 && needs.select.outputs.has_new == 'true'",text)
 def test_no_signing_authority_or_configuration_in_weekly_workflow(self):
  text=(Path(__file__).parents[1]/'workflows/weekly-release-smoke.yml').read_text()
  for forbidden in ['id-token:', 'AZURE_', 'secrets.', 'azure/login', 'artifact-signing-action']:
   self.assertNotIn(forbidden,text)
  self.assertIn('--windows-signing unsigned',text)
  self.assertIn('needs: [select, smoke_linux, smoke_windows, publish]',text)
  self.assertIn('--require-publication',text)
 def test_unsigned_identity_and_first_party_signatures_are_checked_twice(self):
  text=Path(__file__).with_name('weekly_package.py').read_text()
  self.assertIn("requires explicit unsigned mode",text)
  self.assertIn("run(*verify_args,'-Folder',stage)",text)
  self.assertIn("run(*verify_args,'-Folder',binary)",text)
  self.assertIn("label='-unsigned'",text)
  self.assertIn("authenticode=a.windows_signing",text)
  verifier=Path(__file__).with_name('verify_weekly_windows.ps1').read_text()
  for expected in ["$signature.Status -ne 'NotSigned'",'application_id','repository','channel','FileVersion','encap-portable-update.exe']:
   self.assertIn(expected,verifier)
 def test_native_matrix_partition(self):
  text=(Path(__file__).parents[1]/'workflows/weekly-release-smoke.yml').read_text()
  program=textwrap.dedent(text.split("python3 - <<'PYCODE'\n",1)[1].split('          PYCODE',1)[0])
  cases=[[],['linux-x64'],['windows-arm64'],['linux-x64','linux-arm64','windows-x64','windows-arm64']]
  for targets in cases:
   with self.subTest(targets=targets), tempfile.TemporaryDirectory() as tmp:
    rows=[dict(tag='v1.2.3',sha='a'*40,target=target) for target in targets]
    output=Path(tmp)/'output'
    env=dict(os.environ,SELECTED_MATRIX=json.dumps({'include':rows}),GITHUB_OUTPUT=str(output))
    subprocess.run([sys.executable,'-c',program],env=env,check=True)
    result=dict(line.split('=',1) for line in output.read_text().splitlines())
    for system in ['linux','windows']:
     expected=[row for row in rows if row['target'].startswith(system+'-')]
     self.assertEqual(json.loads(result[system+'_matrix']),{'include':expected})
     self.assertEqual(result['has_'+system],str(bool(expected)).lower())
if __name__=='__main__':unittest.main()
