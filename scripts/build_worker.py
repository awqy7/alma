"""Build a relocatable worker and its Chromium, never an OS-disguised binary."""
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]

def build(destination,require_windows=False):
    if require_windows and (sys.platform!='win32' or platform.machine().lower() not in {'amd64','x86_64'}):
        raise SystemExit('O instalador Windows x64 deve ser gerado no Windows x64.')
    destination=Path(destination).resolve()
    destination.mkdir(parents=True,exist_ok=True)
    env={**os.environ,'PLAYWRIGHT_BROWSERS_PATH':str(destination/'browsers'),'PYTHONUTF8':'1'}
    subprocess.run([sys.executable,'-m','playwright','install','chromium'],env=env,check=True)
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean',
                    '--distpath',str(destination),'--workpath',str(ROOT/'.packaging/pyinstaller'),
                    str(ROOT/'packaging/worker.spec')],env=env,cwd=ROOT,check=True)
    (destination/'build-info.json').write_text(json.dumps({'platform':sys.platform,'architecture':platform.machine(),
        'python':platform.python_version(),'worker_version':'0.1.0','ocr_bundled':False},indent=2),encoding='utf-8')
    worker=destination/'worker'/('alma-worker.exe' if sys.platform=='win32' else 'alma-worker')
    subprocess.run([sys.executable,str(ROOT/'scripts/smoke_packaged_worker.py'),str(worker),str(destination/'browsers')],check=True)
    print(f'Runtime verificado: {destination}')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--destination',required=True);parser.add_argument('--require-windows',action='store_true')
    args=parser.parse_args();build(args.destination,args.require_windows)
