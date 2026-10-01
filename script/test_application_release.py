import copy
from pathlib import Path
import unittest
import application_release as release
from core_runtime import obj

class ApplicationReleaseControls(unittest.TestCase):
    def test_evidence_revision_cannot_change_application_inputs(self):
        self.assertTrue(release.qualification_only_path('runtime/updater-qualification.json'))
        for path in ('desktop/EnCap.Desktop/App.axaml', 'global.json', 'runtime/core-runtime.json', '.github/workflows/build-platforms.yml'):
            self.assertFalse(release.qualification_only_path(path))

    def test_candidate_can_never_publish(self):
        plan=obj(release.ROOT/'runtime/application-qualification.json');plan['application_revision']='a'*40
        with self.assertRaisesRegex(ValueError,'unpublished Core'):
            release.validate(plan,{'qualification_only':True},'a'*40)

    def test_missing_final_package_evidence_cannot_publish(self):
        plan=obj(release.ROOT/'runtime/application-qualification.json');plan['application_revision']='a'*40
        pin={'qualification_only':False,'release_revision':'b'*40,'manifest_sha256':'c'*64}
        with self.assertRaisesRegex(ValueError,'qualified target|incomplete'):
            release.validate(plan,pin,'a'*40)

    def test_matrix_cannot_silently_shrink(self):
        plan=obj(release.ROOT/'runtime/application-qualification.json');plan['application_revision']='a'*40
        plan['targets'].pop('windows-arm64')
        pin={'qualification_only':False,'release_revision':'b'*40,'manifest_sha256':'c'*64}
        with self.assertRaisesRegex(ValueError,'matrix'):
            release.validate(plan,pin,'a'*40)

if __name__=='__main__':unittest.main()
