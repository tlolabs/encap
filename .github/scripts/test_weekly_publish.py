import importlib.util, tempfile, unittest, json, hashlib
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('publisher',Path(__file__).with_name('weekly_publish.py')); m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class PublishTests(unittest.TestCase):
 def test_invalid_inputs(self):
  for tag,sha,target in [('../bad','a'*40,'linux-x64'),('v1.0.0','no','linux-x64'),('v1.0.0','a'*40,'macos-arm64')]:
   with self.assertRaises(ValueError):m.publish('tlolabs/encap',tag,sha,target,Path('/missing'))
 def test_moved_tag(self):
  with patch.object(m,'api',return_value={'object':{'type':'commit','sha':'b'*40}}),self.assertRaisesRegex(ValueError,'moved'):m.publish('tlolabs/encap','v1.0.0','a'*40,'linux-x64',Path('/missing'))
 def test_existing_identical_and_mismatch(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);name='EnCap-1.0.0-linux-x64.AppImage';(root/name).write_bytes(b'package');sha=hashlib.sha256(b'package').hexdigest();(root/(name+'.sha256')).write_text(sha+'  '+name+'\n')
   proof=dict(tag='v1.0.0',sha='a'*40,target='linux-x64',package=name,sha256=sha,status='passed');(root/'verification.json').write_text(json.dumps(proof));(root/(name+'.verification.json')).write_text(json.dumps(proof))
   assets=[dict(name=p.name,size=p.stat().st_size,digest='sha256:'+hashlib.sha256(p.read_bytes()).hexdigest()) for p in root.iterdir() if p.name!='verification.json']
   def api(path):return {'object':{'type':'commit','sha':'a'*40}} if '/git/ref/' in path else dict(draft=False,tag_name='v1.0.0',assets=assets)
   with patch.object(m,'api',side_effect=api),patch.object(m.subprocess,'run') as run:
    m.publish('tlolabs/encap','v1.0.0','a'*40,'linux-x64',root);run.assert_not_called()
    assets[0]['digest']='sha256:'+'0'*64
    with self.assertRaises(ValueError):m.publish('tlolabs/encap','v1.0.0','a'*40,'linux-x64',root)
if __name__=='__main__':unittest.main()
