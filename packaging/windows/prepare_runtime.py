"""Explicit online preparation on Windows; no models or private files are uploaded."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main() -> None:
    if sys.platform != 'win32' or sys.maxsize <= 2**32:
        raise RuntimeError('Windows x64 preparation required')
    root=Path(__file__).resolve().parents[2]
    output=root/'dist/windows-runtime-components'
    if output.exists():raise RuntimeError('Fresh output required')
    output.mkdir(parents=True)
    uv=shutil.which('uv')
    if uv is None:raise RuntimeError('uv missing')
    subprocess.run([uv,'python','install','3.12'],check=True)
    python=Path(subprocess.check_output([uv,'python','find','--managed-python','3.12'],text=True).strip())
    shutil.copytree(python.parent,output/'Runtime',symlinks=False)
    target=output/'Runtime/python.exe'
    requirements=output/'requirements.windows.txt'
    subprocess.run([uv,'export','--project',str(root),'--python',str(target),'--no-python-downloads',
                    '--frozen','--no-dev','--no-emit-project','--output-file',str(requirements)],check=True)
    subprocess.run([uv,'pip','install','--python',str(target),'--break-system-packages',
                    '--require-hashes','--only-binary',':all:','-r',str(requirements)],check=True)
    # Import native DLL-bearing libraries on actual Windows, without loading models.
    env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONUTF8='1')
    code="""import sys,platform,json,importlib.metadata as m
import torch,chromadb,ctranslate2,sounddevice,lxml.etree,flet
assert sys.version_info[:2]==(3,12) and sys.maxsize>2**32
print(json.dumps({'python':sys.version,'machine':platform.machine(),'packages':{n:m.version(n) for n in ('torch','flet','flet-desktop','chromadb','ctranslate2','sounddevice','lxml')}},indent=2))
"""
    result=subprocess.run([str(target),'-c',code],env=env,check=True,capture_output=True,text=True,encoding='utf-8')
    print(result.stdout)
    metadata=json.loads(result.stdout)
    metadata['source_commit']=os.environ.get('GITHUB_SHA','unknown')
    metadata['full_windows_gui_acceptance']='pending'
    csc=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    subprocess.run([str(csc),'/nologo','/target:winexe','/platform:x64',
                    '/reference:System.Windows.Forms.dll','/out:'+str(output/'BUTUZIK.AI.exe'),
                    str(root/'packaging/windows/Launcher.cs')],check=True)
    metadata['launcher_sha256']=hashlib.sha256((output/'BUTUZIK.AI.exe').read_bytes()).hexdigest()
    (output/'runtime-build.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')


if __name__=='__main__':main()
