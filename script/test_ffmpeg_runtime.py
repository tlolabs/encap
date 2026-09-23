#!/usr/bin/env python3
"""ENCAP-owned source-runtime tests: real media, manifest rejection and no PATH fallback."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from ffmpeg_build import ROOT
from ffmpeg_runtime import stage, finish, validate


def test(engine,runtime,target):
    with tempfile.TemporaryDirectory(prefix='encap-managed-') as temporary:
        staged=Path(temporary)/'bundle';staged.mkdir()
        suffix='.exe' if target.startswith('windows-') else ''
        executable=staged/('encap-engine'+suffix);shutil.copy2(engine,executable)
        stage(target, runtime, staged)
        finish(target, staged, staged / 'ffmpeg-runtime')
        validate(target, staged, staged / 'ffmpeg-runtime', runtime)
        env=dict(os.environ,PATH=str(runtime)+os.pathsep+os.environ.get('PATH',''))
        # These edits must fail before any media invocation. Provenance cannot merely be present.
        for name, mutate in [
            ('encap-runtime.json', lambda data: data.replace(b'"architecture": "', b'"architecture": "wrong-')),
            ('encap-runtime.json', lambda data: data.replace(b'"encap_version": "', b'"encap_version": "wrong-')),
            ('encap-runtime.json', lambda data: data.replace(b'"revision": "', b'"revision": "wrong-')),
            ('build.json', lambda data: data + b' '),
            ('signed-payload.json', lambda data: data.replace(b'"target": "', b'"target": "wrong-')),
        ]:
            path = staged/'ffmpeg-runtime'/name
            original = path.read_bytes()
            try:
                path.write_bytes(mutate(original))
                try:
                    validate(target, staged, staged / 'ffmpeg-runtime', runtime)
                except ValueError:
                    pass
                else:
                    raise AssertionError('Accepted changed provenance: ' + name)
                result=subprocess.run([str(executable),'validate-tools'],env=env,capture_output=True,timeout=60)
                assert result.returncode!=0,(name,'engine accepted changed provenance')
            finally:
                path.write_bytes(original)
        # A usable fallback pair exists on PATH throughout every negative check.
        for name in ['dependency.json','build.json','payload.json','signed-payload.json','encap-runtime.json','ffmpeg'+suffix,'ffprobe'+suffix]:
            path=(staged/name if name in ['ffmpeg'+suffix, 'ffprobe'+suffix] else staged/'ffmpeg-runtime'/name);original=path.read_bytes();mode=path.stat().st_mode
            path.unlink()
            p=subprocess.run([str(executable),'validate-tools'],env=env,capture_output=True,timeout=60)
            assert p.returncode!=0,(name,'missing bundle silently fell back to PATH')
            assert 'error' in json.loads(p.stdout)
            path.write_bytes(b'damaged')
            path.chmod(mode)
            p=subprocess.run([str(executable),'validate-tools'],env=env,capture_output=True,timeout=60)
            assert p.returncode!=0,(name,'damaged bundle silently fell back to PATH')
            path.write_bytes(original);path.chmod(mode)
        # Release builds ignore environment overrides, including poisoned paths.
        result = subprocess.run([str(executable), 'validate-tools'],
            env=dict(env, ENCAP_FFMPEG='/missing', ENCAP_FFPROBE='/missing'), capture_output=True, timeout=60)
        assert result.returncode == 0, result.stdout
        print('Normal packaged engine: identity, relocation, missing/damaged tools and no PATH fallback passed')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--engine',type=Path,required=True);p.add_argument('--runtime',type=Path,required=True);p.add_argument('--target',required=True);a=p.parse_args();test(a.engine.resolve(),a.runtime.resolve(),a.target)
