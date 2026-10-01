#!/usr/bin/env python3
"""Native launch smoke only, after real media and lifecycle integration checks."""
import argparse,subprocess,time
from pathlib import Path
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('executable',type=Path);a=p.parse_args()
    process=subprocess.Popen([str(a.executable.resolve())],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        time.sleep(5)
        if process.poll() is not None:raise SystemExit('Native application exited during startup smoke')
        print('Native application started and remained running; manual UI/accessibility not tested')
    finally:
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=20)
            except subprocess.TimeoutExpired:process.kill();process.wait()

if __name__ == "__main__":
    main()
