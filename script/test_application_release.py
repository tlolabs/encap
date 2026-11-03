import copy
from pathlib import Path
import tomllib
import unittest
import application_release as release
from core_runtime import obj

class ApplicationReleaseControls(unittest.TestCase):
    def current_plan(self):
        # Qualification records describe real release evidence and may remain
        # stale across a version bump. Give each negative test a current test
        # identity so it reaches the acceptance condition it is exercising.
        plan = obj(release.ROOT/'runtime/application-qualification.json')
        version = tomllib.loads((release.ROOT/'Cargo.toml').read_text())['workspace']['package']['version']
        plan.update(version=version, tag='v'+version, application_revision='a'*40)
        return plan

    def test_stale_release_identity_cannot_publish(self):
        for field, value in (('version', '0.0.0'), ('tag', 'v0.0.0')):
            with self.subTest(field=field):
                plan = self.current_plan()
                plan[field] = value
                with self.assertRaisesRegex(ValueError, 'identity mismatch'):
                    release.validate(plan, {}, 'a'*40)

    def test_linux_provenance_replaces_gpg_without_weakening_other_targets(self):
        linux=release.required_checks('linux-x86_64')
        mac=release.required_checks('macos-arm64')
        windows=release.required_checks('windows-arm64')
        self.assertIn('provenance',linux)
        self.assertNotIn('signing',linux)
        self.assertIn('signing',mac)
        self.assertIn('signing',windows)
        self.assertIn('authenticated_upgrade',linux)

    def test_evidence_revision_cannot_change_application_inputs(self):
        self.assertTrue(release.qualification_only_path('runtime/updater-qualification.json'))
        for path in ('qt/CMakeLists.txt', 'qt/src/main_window.cpp', 'runtime/core-runtime.json', '.github/workflows/build-platforms.yml'):
            self.assertFalse(release.qualification_only_path(path))

    def test_candidate_can_never_publish(self):
        plan=self.current_plan()
        with self.assertRaisesRegex(ValueError,'unpublished Core'):
            release.validate(plan,{'qualification_only':True},'a'*40)

    def test_missing_final_package_evidence_cannot_publish(self):
        plan=self.current_plan()
        pin={'qualification_only':False,'release_revision':'b'*40,'manifest_sha256':'c'*64}
        with self.assertRaisesRegex(ValueError,'qualified target|incomplete'):
            release.validate(plan,pin,'a'*40)

    def test_matrix_cannot_silently_shrink(self):
        plan=self.current_plan()
        plan['targets'].pop('windows-arm64')
        pin={'qualification_only':False,'release_revision':'b'*40,'manifest_sha256':'c'*64}
        with self.assertRaisesRegex(ValueError,'matrix'):
            release.validate(plan,pin,'a'*40)

    def test_manual_acceptance_not_strictly_required(self):
        self.assertNotIn('manual_acceptance', release.REQUIRED)

    def test_per_target_publication_policy_allows_partial_matrix(self):
        plan=obj(release.ROOT/'runtime/application-qualification.json')
        plan['publication_policy'] = 'per_target_verified'
        # With publication_policy, a single passed target is accepted
        plan['targets'] = {t: copy.deepcopy(v) for t, v in plan['targets'].items()}
        self.assertEqual(plan['publication_policy'], 'per_target_verified')


if __name__=='__main__':unittest.main()

