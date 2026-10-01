import base64
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
from unittest.mock import patch
import zipfile
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from tlo_update_release import build, verify_assets, stable

class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.seed=bytes(range(32));self.public=Ed25519PrivateKey.from_private_bytes(self.seed).public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
        self.config=dict(application_id='com.tlolabs.ativ',repository='tlolabs/ativ',version='1.10.0',channel='stable',target='windows-x64',public_key=base64.b64encode(self.public).decode())
        self.artifact=self.root/'ATIV-1.10.0-windows-x64.zip';self.package()
    def package(self):
        with zipfile.ZipFile(self.artifact,'w') as archive: archive.writestr('update-config.json',json.dumps(self.config))
    def build(self): return build(self.root,'1.10.0','stable','v1.10.0',self.seed,self.public,published_at='2026-09-30T00:00:00Z')
    def verify(self): return verify_assets(self.root,self.public,'com.tlolabs.ativ','tlolabs/ativ','1.10.0')
    def test_generator_and_verifier_roundtrip(self): self.assertEqual(self.build(),self.verify())
    def test_deterministic_and_legacy_compatible(self):
        self.build();first=(self.root/'update-manifest.json').read_bytes();self.build();self.assertEqual(first,(self.root/'update-manifest.json').read_bytes())
        self.assertEqual(json.loads(base64.b64decode(json.loads((self.root/'latest.json').read_text())['payload']))['schema'],1)
    def test_wrong_packaged_version_identity_key_and_target(self):
        for field in ('version','application_id','public_key','target'):
            old=self.config[field];self.config[field]='wrong';self.package()
            with self.assertRaisesRegex(ValueError,'Packaged'):self.build()
            self.config[field]=old
    def test_corrupted_published_artifact(self):
        self.build();self.artifact.write_bytes(b'corrupted')
        with self.assertRaisesRegex(ValueError,'Manifest/artifact'):self.verify()
    def test_invalid_metadata_signature(self):
        self.build();p=self.root/'update-manifest.json';envelope=json.loads(p.read_text());envelope['signature']=base64.b64encode(bytes(64)).decode();p.write_text(json.dumps(envelope))
        with self.assertRaises(Exception):self.verify()
    def test_production_versions(self):
        for version in ('01.0.0','1.2','1.2.3.4','1.2.3-beta','1.2.3+build'):
            with self.assertRaises(ValueError):stable(version)
    def test_production_rust_reader_accepts_generated_signed_bytes(self):
        self.build()
        config=dict(self.config,version='1.9.0');path=self.root/'previous-config.json';path.write_text(json.dumps(config))
        output=subprocess.check_output(['cargo','run','--quiet','--locked','-p','tlo-updater','--bin','tlo-qualify','--',str(path),str(self.root)],text=True)
        result=json.loads(output)
        self.assertEqual(result['discovery_authentication_download'],'passed')
        self.assertEqual(result['installation'],'not_tested')
    def test_unperformed_native_installation_blocks_release(self):
        from qualify_updates import qualify
        self.build();(self.root/'runtime').mkdir();(self.root/'runtime/updater-qualification.json').write_text(json.dumps(dict(schema=1,targets={'windows-x64':{'status':'not_run'}})))
        with patch('qualify_updates.ROOT',self.root):
            with self.assertRaisesRegex(ValueError,'not qualified'):qualify(self.root)
    def test_retains_encap_object_envelope(self):
        self.artifact.unlink();self.artifact=self.root/'EnCap-1.10.0-windows-x64.zip'
        self.config.update(application_id='com.tlolabs.encap',repository='tlolabs/encap');self.package()
        build(self.root,'1.10.0','stable','v1.10.0',self.seed,self.public,app='com.tlolabs.encap',repo='tlolabs/encap',prefix='EnCap')
        old=json.loads((self.root/'latest.json').read_text());self.assertEqual(old['payload']['schema_version'],1)
        Ed25519PrivateKey.from_private_bytes(self.seed).public_key().verify(base64.b64decode(old['signature']),json.dumps(old['payload'],separators=(',',':'),ensure_ascii=False).encode())

if __name__=='__main__':unittest.main()
