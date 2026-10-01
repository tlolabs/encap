#!/usr/bin/env python3
"""Exercise the real GIO MPRIS adapter on a private D-Bus session."""
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    library = ctypes.CDLL(str(Path(sys.argv[1]).resolve()))
    callback_type = ctypes.CFUNCTYPE(None, ctypes.c_int, ctypes.c_double)
    actions = []
    callback = callback_type(lambda action, value: actions.append((action, value)))
    library.encap_media_open.argtypes = [ctypes.c_void_p, callback_type]
    library.encap_media_update.argtypes = [ctypes.c_char_p, ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_int, ctypes.c_int, ctypes.c_double]
    assert library.encap_media_open(None, callback) == 0
    try:
        library.encap_media_update(b'Fixture', 4, 20, 1, 1, 1, 1)
        base = ['gdbus', 'call', '--session', '--dest', f'org.mpris.MediaPlayer2.encap.instance{os.getpid()}', '--object-path', '/org/mpris/MediaPlayer2']
        for _ in range(100):
            result = subprocess.run(base + ['--method', 'org.freedesktop.DBus.Properties.Get', 'org.mpris.MediaPlayer2.Player', 'PlaybackStatus'], capture_output=True, text=True)
            if result.returncode == 0:
                break
            time.sleep(.02)
        assert result.returncode == 0, result.stderr
        assert 'Playing' in result.stdout
        for method, code in [('Play', 1), ('Pause', 2), ('Stop', 3), ('Next', 4), ('Previous', 5), ('PlayPause', 10)]:
            subprocess.run(base + ['--method', 'org.mpris.MediaPlayer2.Player.' + method], check=True, capture_output=True)
            assert actions[-1][0] == code, (method, actions)
        subprocess.run(base + ['--method', 'org.mpris.MediaPlayer2.Player.Seek', '2000000'], check=True, capture_output=True)
        assert actions[-1] == (6, 6.0), actions
        metadata = subprocess.check_output(base + ['--method', 'org.freedesktop.DBus.Properties.Get', 'org.mpris.MediaPlayer2.Player', 'Metadata'], text=True)
        assert 'Fixture' in metadata and '20000000' in metadata
        before = len(actions)
        library.encap_media_update(b'Fixture', 4, 20, 1, 0, 0, 1)
        subprocess.run(base + ['--method', 'org.mpris.MediaPlayer2.Player.Play'], check=True, capture_output=True)
        assert len(actions) == before, 'Busy sessions must reject playback actions'
        print('Passed real MPRIS metadata, six transport commands, relative seek, and busy gating.')
    finally:
        library.encap_media_close()
    for _ in range(5):
        assert library.encap_media_open(None, callback) == 0
        library.encap_media_close()
    print('Passed repeated immediate media-session shutdown.')

if __name__ == '__main__':
    main()
