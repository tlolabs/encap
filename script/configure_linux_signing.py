#!/usr/bin/env python3
# SPDX-FileCopyrightText: Thomas Lothian
# SPDX-License-Identifier: GPL-3.0-or-later
"""Approved private-key transfer to the two named Actions stores, never to disk/logs."""
import argparse
import base64
import getpass
import json
import subprocess
import tempfile
from pathlib import Path

FINGERPRINT = 'F7E74ED98DB485D03F2565B96B68B73FE752FD16'
DESTINATIONS = ('tlolabs/ativ', 'tlolabs/encap')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--replace',action='store_true',help='Explicitly replace an existing signing secret')
    a=p.parse_args()
    for repo in DESTINATIONS:
        names=json.loads(subprocess.check_output(['gh','api',f'repos/{repo}/actions/secrets']))['secrets']
        if not a.replace and any(n['name'] in ('LINUX_GPG_PRIVATE_KEY_B64','LINUX_GPG_PASSPHRASE') for n in names):
            raise SystemExit('Existing Linux signing secret in '+repo+'; review before --replace')
    identity=subprocess.check_output(['gpg','--with-colons','--fingerprint',FINGERPRINT],text=True)
    if 'fpr:::::::::'+FINGERPRINT+':' not in identity or '153565009+tlolabs@users.noreply.github.com' not in identity:
        raise SystemExit('Maintainer signing identity does not match')
    password=getpass.getpass('Passphrase for the verified maintainer GPG key (sent only to the approved secret stores): ')
    private=subprocess.run(['gpg','--batch','--pinentry-mode','loopback','--passphrase-fd','0','--armor','--export-secret-keys',FINGERPRINT],
                           input=password.encode()+b'\n',stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
    if private.returncode or not private.stdout.startswith(b'-----BEGIN PGP PRIVATE KEY BLOCK-----'):
        raise SystemExit('GPG export failed; no material transferred')
    # Verify signing usability before making any remote changes, without logging secret data.
    with tempfile.TemporaryDirectory(prefix='release-preflight-') as directory:
        message = Path(directory) / 'public-preflight.txt'
        message.write_text('release-signing-preflight\n')
        signed=subprocess.run(['gpg','--batch','--pinentry-mode','loopback','--passphrase-fd','0','--local-user',FINGERPRINT,
                               '--armor','--detach-sign','--output','-',str(message)],input=password.encode()+b'\n',
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
        if signed.returncode:raise SystemExit('Private key cannot sign; no material transferred')
    public=subprocess.check_output(['gpg','--armor','--export',FINGERPRINT])
    for repo in DESTINATIONS:
        for name,value in [('LINUX_GPG_PRIVATE_KEY_B64',base64.b64encode(private.stdout)),('LINUX_GPG_PASSPHRASE',password.encode())]:
            subprocess.run(['gh','secret','set',name,'--repo',repo],input=value,check=True,stdout=subprocess.DEVNULL)
        for name,value in [('LINUX_GPG_PUBLIC_KEY_B64',base64.b64encode(public)),('LINUX_GPG_FINGERPRINT',FINGERPRINT.encode())]:
            subprocess.run(['gh','variable','set',name,'--repo',repo],input=value,check=True,stdout=subprocess.DEVNULL)
        print(repo+': Linux signing secrets configured; public maintainer identity verified')

if __name__=='__main__':main()
