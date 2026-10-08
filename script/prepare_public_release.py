#!/usr/bin/env python3
"""Verify the six same-run packages and write checksums for a manual-download release."""
import argparse
import base64
import os
from pathlib import Path
import tomllib

from tlo_update_release import SPECS, checksums, verify_package


ROOT = Path(__file__).resolve().parents[1]


def prepare(assets):
    version = tomllib.loads((ROOT / 'Cargo.toml').read_text())['workspace']['package']['version']
    public = base64.b64decode(os.environ['ENCAP_UPDATE_PUBLIC_KEY'], validate=True)
    if len(public) != 32:
        raise ValueError('Expected the deployed 32-byte update public key')
    expected = {f'EnCap-{version}-{target.rsplit("-appimage", 1)[0]}.{extension}': target
                for target, (_, _, extension, _) in SPECS.items()}
    actual = {path.name for path in assets.iterdir() if path.is_file()}
    if actual != set(expected):
        raise ValueError(f'Release packages differ from six-target matrix: missing={sorted(set(expected) - actual)}, extra={sorted(actual - set(expected))}')
    for name, target in expected.items():
        path = assets / name
        if not 0 < path.stat().st_size <= 2 * 1024**3:
            raise ValueError(f'Invalid package size: {name}')
        verify_package(path, target, 'com.tlolabs.encap', 'tlolabs/encap', version, public)
    checksums(assets)
    print(f'Verified {len(expected)} package identities and wrote SHA256SUMS for EnCap {version}.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', type=Path, required=True)
    prepare(parser.parse_args().assets)
