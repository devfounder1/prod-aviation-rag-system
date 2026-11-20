"""Offline directory integrity check, not proof of Windows GUI/model quality."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path,PurePosixPath
import struct

MUTABLE={'data','agent_workspace','logs','__pycache__','.pytest_cache','.mypy_cache','.locks'}
REQUIRED=('Runtime/python.exe','Flet/flet.exe','Flet/version.txt','Ollama/ollama.exe',
          'BUTUZIK.AI.exe','App/prilozhenie.py','App/windows_entry.py','App/.env',
          'Images/butuz-documents.tar','Images/butuz-sandbox.tar')


def digest(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as stream:
        while block:=stream.read(1024*1024):h.update(block)
    return h.hexdigest()


def amd64_pe(path: Path) -> bool:
    with path.open('rb') as stream:
        start=stream.read(64)
        if len(start)<64 or start[:2]!=b'MZ':return False
        offset=struct.unpack_from('<I',start,60)[0]
        if not 64<=offset<=1024*1024:return False
        stream.seek(offset);return stream.read(6)==b'PE\0\0\x64\x86'


def files(root: Path) -> list[Path]:
    result=[]
    for path in root.rglob('*'):
        rel=path.relative_to(root)
        standards=rel.as_posix().startswith('App/data/standards_library/v1/')
        if (any(p.lower() in MUTABLE for p in rel.parts) and not standards) or path.name.startswith('~$') or path.name in {'.env','bundle-manifest.json'} or rel.as_posix()=='App/config.json':continue
        if path.is_symlink():raise ValueError('Bundle contains a symlink: '+str(rel))
        if path.is_file():result.append(path)
    return sorted(result)


def verify(root: Path,write: bool=False) -> None:
    root=root.resolve()
    for name in REQUIRED:
        p=root/name
        if not p.is_file() or p.is_symlink() or not p.resolve().is_relative_to(root):raise ValueError('Missing bundle file: '+name)
    for name in ('Runtime/python.exe','BUTUZIK.AI.exe','Flet/flet.exe','Ollama/ollama.exe'):
        if not amd64_pe(root/name):raise ValueError('Not Windows x64 PE: '+name)
    for name in ('Models/huggingface/hub/models--intfloat--multilingual-e5-small','Models/ollama/manifests','Models/ollama/blobs'):
        p=root/name
        if not p.is_dir() or not any(f.is_file() for f in p.rglob('*')):raise ValueError('Missing model directory contents: '+name)
    manifest=root/'bundle-manifest.json'
    if write:
        if manifest.exists():raise ValueError('Refusing to replace existing manifest')
        records={p.relative_to(root).as_posix():digest(p) for p in files(root)}
        manifest.write_text(json.dumps({'schema':1,'windows_acceptance':'pending','sha256':records},indent=2),encoding='utf-8')
    else:
        data=json.loads(manifest.read_text(encoding='utf-8'))
        if data.get('schema')!=1 or not isinstance(data.get('sha256'),dict):raise ValueError('Invalid bundle manifest')
        expected=data['sha256']
        actual={p.relative_to(root).as_posix() for p in files(root)}
        if actual!=set(expected):raise ValueError('Immutable file list changed; restore a clean bundle')
        for name,sha in expected.items():
            rel=PurePosixPath(name)
            if rel.is_absolute() or '..' in rel.parts or '\\' in name:raise ValueError('Unsafe manifest path')
            if digest(root/name)!=sha:raise ValueError('Hash mismatch: '+name)
    print('Bundle integrity checked. Native Windows and disconnected GUI tests still required.')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);parser.add_argument('--write-manifest',action='store_true')
    args=parser.parse_args();verify(args.root,args.write_manifest)
