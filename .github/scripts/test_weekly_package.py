import ast, json, os, subprocess, sys, tempfile, textwrap, unittest
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
 def test_signer_authority_is_windows_only(self):
  text=(Path(__file__).parents[1]/'workflows/weekly-release-smoke.yml').read_text()
  linux=text.split('  smoke_linux:\n',1)[1].split('  smoke_windows:\n',1)[0]
  windows=text.split('  smoke_windows:\n',1)[1].split('  publish:\n',1)[0]
  self.assertEqual(text.count('id-token: write'),1)
  self.assertIn('id-token: write',windows)
  for forbidden in ['id-token:','AZURE_', 'secrets.', 'azure/login', 'artifact-signing-action']:
   self.assertNotIn(forbidden,linux)
  self.assertIn('needs: [select, smoke_linux, smoke_windows]',text)
  self.assertIn('fromJSON(needs.select.outputs.linux_matrix)',linux)
  self.assertIn('fromJSON(needs.select.outputs.windows_matrix)',windows)
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
