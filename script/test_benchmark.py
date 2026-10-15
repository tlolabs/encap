import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import benchmark


class BenchmarkTests(unittest.TestCase):
    def test_rejects_failed_commands_and_missing_metrics(self):
        with patch('benchmark.subprocess.run', return_value=subprocess.CompletedProcess([], 1, 'BENCH: fake', 'failed')):
            with self.assertRaises(RuntimeError):
                benchmark.run_command(['fake'])
        with self.assertRaises(ValueError):
            benchmark.parse_core('test result: ok. 0 tests')
        with self.assertRaises(ValueError):
            benchmark.parse_duration_to_us('garbage')

    def test_exact_unknown_command_fallback_only(self):
        old = "error: unrecognized subcommand 'startup'\nUsage: engine"
        self.assertTrue(benchmark.unknown_startup(subprocess.CompletedProcess([], 2, '', old)))
        for code, error in [(1, old), (-2, old), (2, 'damaged recovery'), (0, old)]:
            self.assertFalse(benchmark.unknown_startup(subprocess.CompletedProcess([], code, '', error)))

    def test_statistics_and_units(self):
        values = benchmark.stats([4, 1, 3, 2])
        self.assertEqual(values['median_ms'], 2.5)
        self.assertEqual(values['p95_ms'], 4)
        self.assertEqual(values['samples_ms'], [4, 1, 3, 2])
        self.assertEqual(benchmark.parse_duration_to_us('2.5ms'), 2500)
        with self.assertRaises(ValueError):
            benchmark.compare_results({'engine': {}}, {'engine': {}})

    def test_compare_does_not_run_or_build(self):
        with tempfile.TemporaryDirectory() as root:
            paths = [Path(root) / name for name in ['before.json', 'after.json']]
            for path in paths:
                path.write_text(json.dumps({'schema': 1}))
            with patch('sys.argv', ['benchmark.py', '--compare', *map(str, paths)]), patch('benchmark.run_command') as run:
                with self.assertRaises(ValueError):
                    benchmark.main()
                run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
