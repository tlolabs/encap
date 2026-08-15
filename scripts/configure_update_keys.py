#!/usr/bin/env python3
"""Generate EnCap's update key and optionally configure the GitHub repository."""

from __future__ import annotations

import argparse
import base64
import os
import subprocess
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def load_or_create_seed(path: Path) -> bytes:
    if path.exists():
        seed = base64.b64decode(path.read_text(encoding="ascii").strip(), validate=True)
        if len(seed) != 32:
            raise SystemExit(f"{path} does not contain a 32-byte Ed25519 seed.")
        return seed
    seed = os.urandom(32)
    path.write_text(base64.b64encode(seed).decode("ascii") + "\n", encoding="ascii")
    path.chmod(0o600)
    return seed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="tlolabs/encap")
    parser.add_argument("--key-file", type=Path, default=Path(".encap-update-private-key"))
    parser.add_argument(
        "--public-key-file",
        type=Path,
        default=Path("src/encap/update_public_key.txt"),
    )
    parser.add_argument(
        "--configure-github",
        action="store_true",
        help="Set the GitHub Actions secret and repository variable with gh.",
    )
    args = parser.parse_args()

    seed = load_or_create_seed(args.key_file)
    private_key = Ed25519PrivateKey.from_private_bytes(seed)
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    private_value = base64.b64encode(seed).decode("ascii")
    public_value = base64.b64encode(public_key).decode("ascii")
    args.public_key_file.parent.mkdir(parents=True, exist_ok=True)
    args.public_key_file.write_text(public_value + "\n", encoding="ascii")

    if args.configure_github:
        subprocess.run(
            [
                "gh",
                "secret",
                "set",
                "ENCAP_UPDATE_PRIVATE_KEY",
                "--repo",
                args.repo,
            ],
            input=private_value,
            text=True,
            check=True,
        )
        subprocess.run(
            [
                "gh",
                "variable",
                "set",
                "ENCAP_UPDATE_PUBLIC_KEY",
                "--repo",
                args.repo,
                "--body",
                public_value,
            ],
            check=True,
        )
        print(f"Configured update signing for {args.repo}.")
    else:
        print("GitHub was not changed. Re-run with --configure-github after `gh auth login`.")

    print(f"Public key: {public_value}")
    print(f"Local public key file: {args.public_key_file}")
    print(f"Private recovery key: {args.key_file} (mode 0600; keep it backed up and secret)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
