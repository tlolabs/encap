import ctypes
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import ffmpeg_runtime as runtime


class CompatibilityRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='encap compatibility ü ')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'spec.json').write_text('{"source":{"version":"9.0.1"}}')

    def pair(self, version='9.0.1'):
        for name in ('ffmpeg', 'ffprobe'):
            path = self.root / name
            path.write_text('#!/bin/sh\nprintf \'%s\\n\' \'' + name + ' version ' + version + '\'\n')
            path.chmod(0o755)

    @unittest.skipIf(os.name == 'nt', 'Unix diagnostic script fixture')
    def test_unicode_absolute_pair_runs_with_empty_path_and_rejects_wrong_version(self):
        self.pair()
        runtime.validate_pair(self.root, self.root, 'macos-arm64')
        self.pair('different')
        with self.assertRaisesRegex(ValueError, 'version differs'):
            runtime.validate_pair(self.root, self.root, 'macos-arm64')

    @unittest.skipIf(os.name == 'nt', 'Unix diagnostic script fixture')
    def test_missing_and_oversized_tool_output_have_no_path_fallback(self):
        self.pair()
        (self.root / 'ffmpeg').unlink()
        with patch.dict(os.environ, PATH=str(self.root)):
            with self.assertRaises(FileNotFoundError):
                runtime.validate_pair(self.root, self.root, 'macos-arm64')
        self.pair()
        path = self.root / 'ffprobe'
        path.write_text('#!/bin/sh\nprintf \'%s\' \'' + 'x' * (64 * 1024 + 1) + '\'\n')
        with self.assertRaisesRegex(ValueError, 'output exceeded'):
            runtime.validate_pair(self.root, self.root, 'macos-arm64')

    def test_tool_timeout_is_explicit_and_does_not_invoke_an_engine(self):
        with patch.object(runtime.subprocess, 'run', side_effect=subprocess.TimeoutExpired('fixture', 10)) as call:
            with self.assertRaises(subprocess.TimeoutExpired):
                runtime.validate_pair(self.root, self.root, 'linux-arm64')
        self.assertEqual(call.call_args.kwargs['timeout'], 10)
        self.assertEqual(call.call_args.kwargs['env']['PATH'], '')
        self.assertEqual(call.call_args.args[0], [str((self.root / 'ffmpeg').resolve()), '-version'])

    def test_authentication_failure_prevents_pair_execution_and_destination_writes(self):
        output = self.root / 'output'
        with patch.object(runtime, 'verify', side_effect=ValueError('corrupt authenticated archive')), \
             patch.object(runtime, 'validate_pair') as pair:
            with self.assertRaisesRegex(ValueError, 'corrupt authenticated'):
                runtime.stage('macos-arm64', self.root, output)
        pair.assert_not_called()
        self.assertFalse(output.exists())

    def test_native_identity_checks_abi_copies_buffer_and_releases_all_handles(self):
        payload = json.dumps({'schema_version': 1, 'ok': True, 'result': {'encap_version': 'fixture'}}).encode()
        released = []

        class Function:
            def __init__(self, function):
                self.function = function
            def __call__(self, *args):
                return self.function(*args)

        class API:
            encap_app_abi_version = Function(lambda: 1)
            encap_app_schema_version = Function(lambda: 1)
            encap_app_create = Function(lambda: 11)
            encap_app_cancel_create = Function(lambda: 12)
            encap_app_execute_json = Function(lambda *args: 13)
            encap_app_buffer_len = Function(lambda handle: len(payload))
            encap_app_buffer_copy = Function(lambda handle, output, size: (ctypes.memmove(output, payload, size), size)[1])
            encap_app_release = Function(lambda handle: released.append(handle) or 0)

        with patch('linked_runtime.verify_stage') as verify, patch.object(runtime.ctypes, 'CDLL', return_value=API()):
            self.assertEqual(runtime.linked_identity(self.root, 'linux-arm64'), {'encap_version': 'fixture'})
        verify.assert_called_once()
        self.assertEqual(released, [13, 12, 11])
        released.clear()
        API.encap_app_buffer_len = Function(lambda handle: 64 * 1024 * 1024 + 1)
        with patch('linked_runtime.verify_stage'), patch.object(runtime.ctypes, 'CDLL', return_value=API()):
            with self.assertRaisesRegex(ValueError, 'result size'):
                runtime.linked_identity(self.root, 'linux-arm64')
        self.assertEqual(released, [13, 12, 11])


if __name__ == '__main__':
    unittest.main()
