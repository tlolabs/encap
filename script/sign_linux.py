#!/usr/bin/env python3
# SPDX-FileCopyrightText: Thomas Lothian
# SPDX-License-Identifier: GPL-3.0-or-later
"""Sign final AppImage bytes with the pinned maintainer identity; fail closed."""
import argparse
import base64
import os
from pathlib import Path
import subprocess
import tempfile

FINGERPRINT='F7E74ED98DB485D03F2565B96B68B73FE752FD16'


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('image',type=Path);a=p.parse_args()
    if a.image.suffix != '.AppImage' or not a.image.is_file():raise SystemExit('Final AppImage required')
    if os.environ.get('LINUX_GPG_FINGERPRINT') != FINGERPRINT:raise SystemExit('Unapproved Linux signer')
    with tempfile.TemporaryDirectory(prefix='linux-signing-') as tmp:
        env=dict(os.environ,GNUPGHOME=tmp)
        key=base64.b64decode(os.environ['LINUX_GPG_PRIVATE_KEY_B64'],validate=True)
        subprocess.run(['gpg','--batch','--import'],env=env,input=key,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
        fingerprint=subprocess.check_output(['gpg','--batch','--with-colons','--fingerprint'],env=env,text=True)
        if 'fpr:::::::::'+FINGERPRINT+':' not in fingerprint:raise SystemExit('Private signing identity mismatch')
        signature=a.image.with_suffix('.AppImage.asc')
        if signature.exists():raise SystemExit('Refusing to replace existing signature')
        subprocess.run(['gpg','--batch','--pinentry-mode','loopback','--passphrase-fd','0','--local-user',FINGERPRINT,
                        '--armor','--output',str(signature),'--detach-sign',str(a.image)],env=env,
                       input=os.environ['LINUX_GPG_PASSPHRASE'].encode()+b'\n',stdout=subprocess.DEVNULL,check=True)
        verified=subprocess.run(['gpg','--batch','--status-fd','1','--verify',str(signature),str(a.image)],env=env,
                                stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True,text=True)
        if not any(line.startswith('[GNUPG:] VALIDSIG '+FINGERPRINT+' ') for line in verified.stdout.splitlines()):
            raise SystemExit('Final AppImage signature was not verified with the expected key')
    print('Verified final AppImage signature with maintainer '+FINGERPRINT)

if __name__=='__main__':main()
