"""Read-only macOS release eligibility; no attempt ledger writes."""
import unittest
from unittest.mock import patch
import weekly_release_smoke as m


class ReleaseEligibility(unittest.TestCase):
    def setUp(self):
        self.gate = m.Gate(m.GitHub('tlolabs/encap'))
        self.matrix = {'include': [dict(tag='v1.2.3', sha='a' * 40, target=t)
                                  for t in ('linux-x64', 'windows-arm64')]}
        self.name = 'EnCap-1.2.3-macos-arm64-signed.zip'
        self.release = dict(tag_name='v1.2.3', draft=False, prerelease=False,
                            published_at='2026-11-13T09:00:00Z', assets=[
                                dict(name=self.name, state='uploaded', size=123),
                                dict(name=self.name + '.sha256', state='uploaded', size=100)])

    def check(self, releases):
        with patch.object(self.gate.api, 'pages', return_value=iter(releases)), \
             patch.object(self.gate, 'mark') as mark:
            result = self.gate.released_macos_only(self.matrix)
            mark.assert_not_called()
            return result

    def test_matching_release_preserves_exact_matrix(self):
        self.assertEqual(self.check([self.release]), (self.matrix, 0))

    def test_missing_or_unpublished_release_is_deferred(self):
        variants = [[], [dict(self.release, draft=True)],
                    [dict(self.release, prerelease=True)],
                    [dict(self.release, published_at=None)],
                    [dict(self.release, tag_name='v1.2.4')]]
        for releases in variants:
            with self.subTest(releases=releases):
                self.assertEqual(self.check(releases), ({'include': []}, 2))

    def test_incomplete_or_wrong_macos_assets_are_deferred(self):
        for assets in [[], self.release['assets'][:1],
                       [dict(a, size=0) for a in self.release['assets']],
                       [dict(a, state='new') for a in self.release['assets']],
                       [dict(a, name=a['name'].replace('1.2.3', '1.2.4')) for a in self.release['assets']]]:
            with self.subTest(assets=assets):
                self.assertEqual(self.check([dict(self.release, assets=assets)]), ({'include': []}, 2))

    def test_api_failure_is_not_treated_as_no_release(self):
        with patch.object(self.gate.api, 'pages', side_effect=m.GateError('API unavailable')):
            with self.assertRaises(m.GateError):
                self.gate.released_macos_only(self.matrix)

    def test_empty_matrix_does_not_call_api(self):
        with patch.object(self.gate.api, 'pages') as pages:
            self.assertEqual(self.gate.released_macos_only({'include': []}), ({'include': []}, 0))
            pages.assert_not_called()

    def test_cli_filters_before_any_claim(self):
        args = ['select', '--repo', 'tlolabs/encap', '--pattern', r'v\d+\.\d+\.\d+',
                '--targets', 'linux-x64', '--require-macos-release', '--claim']
        with patch.object(m.Gate, 'select', return_value=(self.matrix, {'new': 2})), \
             patch.object(m.Gate, 'released_macos_only', return_value=({'include': []}, 2)), \
             patch.object(m.Gate, 'claim') as claim, patch.object(m, 'emit_outputs') as output:
            self.assertEqual(m.main(args), 0)
            claim.assert_not_called()
            output.assert_called_once_with({'include': []}, {'new': 0, 'deferred_release': 2})


class PublicationOutcomes(unittest.TestCase):
    def test_publication_is_required_for_target_success(self):
        from test_weekly_release_smoke import FakeAPI, item, URL
        smoke=dict(name='Smoke v1.2.3 (linux-x64)',status='completed',conclusion='success')
        publisher=dict(name='Publish v1.2.3 (linux-x64)',status='completed',conclusion='success')
        for jobs, expected in [([publisher],'success'),([],'error'),([publisher,publisher],'error'),
                ([dict(publisher,conclusion='failure')],'failure'),
                ([dict(publisher,conclusion='skipped')],'error'),
                ([dict(publisher,status='in_progress')],'error')]:
            api=FakeAPI(jobs=[smoke]+jobs)
            result=m.Gate(api).finalize({'include':[item()]},123,1,URL,require_publication=True)
            self.assertEqual(result[expected],1)
            self.assertEqual(api.writes[0][1]['state'],expected)

if __name__ == '__main__':
    unittest.main()
