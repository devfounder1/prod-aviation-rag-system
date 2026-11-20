"""Build a reviewable source/assembly kit; never label it a tested Windows EXE."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from zipfile import ZipFile,ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[2]
GUIDE_NAME='Инструкция для запуска BUTUZIK AI.docx'
DIRECTORIES={'assets','standards','docs','ollama','sandbox','document_runtime','packaging','tools'}
ROOT_FILES={'pyproject.toml','uv.lock','README.md','AGENTS.md','.env.example','LICENSE','LICENSE.md','.dockerignore'}
DENY={'data','agent_workspace','eval-results','logs','.git','.venv','__pycache__','.pytest_cache','.mypy_cache'}
SUFFIXES={'.py','.json','.md','.svg','.png','.jpg','.jpeg','.ico','.toml','.lock','.ps1','.cmd','.cs','.yml','.docx','.txt'}


def allowed(name: str) -> bool:
    path=Path(name)
    if path.is_absolute() or '..' in path.parts or any(p in DENY for p in path.parts):return False
    if path.name.startswith('.') and name not in {'.env.example','.dockerignore'}:return False
    if path.suffix=='.docx' and path.name!=GUIDE_NAME:return False
    return (len(path.parts)==1 and (name in ROOT_FILES or path.suffix=='.py') or
            len(path.parts)>1 and path.parts[0] in DIRECTORIES and (path.suffix in SUFFIXES or path.name in {'Dockerfile','Modelfile.agent'}))


def build(destination: Path) -> Path:
    if destination.exists():raise ValueError('Choose a new output directory')
    names=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT).decode().split('\0')
    names=sorted(n for n in names if n and allowed(n))
    destination.mkdir(parents=True)
    for name in names:
        source=ROOT/name
        if source.is_symlink() or not source.is_file() or not source.resolve().is_relative_to(ROOT):raise ValueError('Unsafe source: '+name)
        target=destination/'App'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    shutil.copytree(ROOT/'packaging/windows',destination/'Tools',ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copyfile(ROOT/'docs/windows-quickstart.md',destination/'README_FIRST.md')
    guide=ROOT/'docs'/GUIDE_NAME
    if not guide.is_file():raise ValueError('Launch guide missing; generate it before building the kit')
    shutil.copyfile(guide,destination/guide.name)
    (destination/'ASSEMBLY_REQUIRED.txt').write_text('SOURCE AND ASSEMBLY KIT ONLY. No Windows executable/runtime/models included. Build on Windows x64 using Tools/Build-Windows.ps1; native disconnected acceptance is pending.\n',encoding='utf-8')
    records={p.relative_to(destination).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(destination.rglob('*')) if p.is_file()}
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    (destination/'source-manifest.json').write_text(json.dumps({'schema':1,'source_commit':commit,'native_windows_tested':False,'sha256':records},indent=2),encoding='utf-8')
    archive=destination.with_suffix('.zip')
    if archive.exists():raise ValueError('Archive already exists')
    with ZipFile(archive,'w',ZIP_DEFLATED) as z:
        for path in sorted(destination.rglob('*')):
            if path.is_file():z.write(path,destination.name+'/'+path.relative_to(destination).as_posix())
    print(str(archive.resolve()));return archive


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('destination',type=Path);build(p.parse_args().destination)
