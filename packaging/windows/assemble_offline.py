"""Explicit local assembly from prepared Windows artifacts and selected local data.

No downloads, host-code execution from the bundle, or publication to GitHub.
The resulting manifest deliberately leaves full native GUI acceptance pending.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from typing import Any
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(HERE))
sys.path.insert(0,str(ROOT))
from make_source_kit import build as build_source_kit
from verify_bundle import digest, verify

REPOS=('intfloat/multilingual-e5-small','BAAI/bge-reranker-v2-m3',
       'Systran/faster-whisper-base','Systran/faster-whisper-small')


def extract_zip(archive: Path, destination: Path) -> None:
    """Extract prepared vendor artifacts without links or path escapes."""
    with ZipFile(archive) as package:
        infos=package.infolist()
        if len(infos)>100_000 or sum(i.file_size for i in infos)>30*1024**3:
            raise ValueError('Unexpected component archive size')
        for item in infos:
            name=PurePosixPath(item.filename.replace('\\','/'))
            if (name.is_absolute() or '..' in name.parts or not name.parts or
                    any(':' in p for p in name.parts) or item.external_attr>>16&0o170000==0o120000):
                raise ValueError('Unsafe component archive member')
            target=destination.joinpath(*name.parts)
            if item.is_dir():target.mkdir(parents=True,exist_ok=True);continue
            target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists():raise ValueError('Duplicate component archive path')
            with package.open(item) as source,target.open('xb') as output:
                shutil.copyfileobj(source,output,4*1024*1024)


def copy_blob(source: Path, target: Path, expected: str, size: int) -> None:
    if not source.is_file() or source.is_symlink() or source.stat().st_size!=size:
        raise ValueError('Missing/changed model blob')
    h=hashlib.sha256();target.parent.mkdir(parents=True,exist_ok=True)
    with source.open('rb') as src,target.open('xb') as dest:
        while chunk:=src.read(4*1024*1024):dest.write(chunk);h.update(chunk)
    if h.hexdigest()!=expected:raise ValueError('Model blob digest mismatch')


def copy_ollama(models: Path, output: Path) -> list[dict[str, Any]]:
    copied: set[str]=set();records=[]
    for name,tag in (('qwen2.5','14b'),('qwen2.5vl','7b')):
        rel=Path('manifests/registry.ollama.ai/library')/name/tag
        source=models/rel
        if source.is_symlink():raise ValueError('Model manifest symlink rejected')
        raw=source.read_bytes();manifest=json.loads(raw)
        blobs=[manifest['config'],*manifest['layers']]
        for blob in blobs:
            value=blob['digest']
            if not re.fullmatch(r'sha256:[a-f0-9]{64}',value):raise ValueError('Unknown model blob digest')
            if value in copied:continue
            filename=value.replace(':','-')
            copy_blob(models/'blobs'/filename,output/'blobs'/filename,value[7:],int(blob['size']))
            copied.add(value)
        target=output/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        records.append({'model':name+':'+tag,'manifest_sha256':hashlib.sha256(raw).hexdigest(),
                        'bytes':sum(int(b['size']) for b in blobs)})
        print('Copied selected model',name+':'+tag,flush=True)
    return records


def copy_hf(cache: Path, output: Path) -> None:
    cache=cache.resolve()
    for repo in REPOS:
        folder=cache/('models--'+repo.replace('/','--'))
        if not (folder/'refs/main').is_file():raise ValueError('Missing model cache main reference: '+repo)
        revision=(folder/'refs/main').read_text().strip()
        if not re.fullmatch('[a-f0-9]{40,64}',revision) or not (folder/'snapshots'/revision).is_dir():
            raise ValueError('Missing model snapshot: '+repo)
        for path in folder.rglob('*'):
            if not path.resolve().is_relative_to(cache):raise ValueError('Model cache link leaves cache')
        shutil.copytree(folder,output/folder.name,symlinks=False,ignore=shutil.ignore_patterns('__pycache__','.locks'))
        print('Copied local cache',repo,flush=True)


def verify_image(path: Path, tag: str) -> dict[str, str]:
    with tarfile.open(path) as image:
        member=image.extractfile('manifest.json')
        if member is None:raise ValueError('Missing image manifest')
        entries=json.load(member)
        selected=[entry for entry in entries if tag in entry.get('RepoTags',[])]
        if len(selected)!=1:raise ValueError('Image tag mismatch')
        config_name=selected[0]['Config']
        config_stream=image.extractfile(config_name)
        if config_stream is None:raise ValueError('Missing image config')
        config=json.load(config_stream)
        if config.get('os')!='linux' or config.get('architecture')!='amd64':raise ValueError('Linux amd64 image required')
        return {'tag':tag,'os':'linux','architecture':'amd64','sha256':digest(path)}


def single_executable(root: Path, name: str) -> Path:
    matches=list(root.rglob(name))
    if len(matches)!=1:raise ValueError('Ambiguous vendor executable: '+name)
    return matches[0].parent


def vendor_asset(resources: Path, release: str, name: str) -> dict[str, Any]:
    data=json.loads((resources/(release+'-release.json')).read_text())
    matches=[a for a in data['assets'] if a['name']==name]
    if len(matches)!=1:raise ValueError('Missing pinned vendor asset')
    asset=matches[0];path=resources/name
    actual=digest(path)
    if path.stat().st_size!=asset['size']:raise ValueError('Incomplete vendor download: '+name)
    if asset.get('digest') and asset['digest']!='sha256:'+actual:raise ValueError('Vendor digest mismatch: '+name)
    return {'file':name,'release':data['tag_name'],'url':asset['browser_download_url'],
            'sha256':actual,'publisher_digest_available':bool(asset.get('digest'))}


def assemble(resources: Path, output: Path, models: Path, hf: Path, library: Path) -> None:
    if output.exists() or output.with_suffix('.zip').exists():raise ValueError('Fresh delivery directory required')
    # Vendor download checks finish before any large local copying.
    assets=[vendor_asset(resources,'ollama','ollama-windows-amd64.zip'),
            vendor_asset(resources,'flet','flet-windows.zip')]
    wsl=json.loads((resources/'wsl-release.json').read_text())
    installers=[a['name'] for a in wsl['assets'] if a['name'].endswith('.x64.msi')]
    if len(installers)!=1:raise ValueError('Ambiguous WSL installer')
    assets.append(vendor_asset(resources,'wsl',installers[0]))
    artifacts=json.loads((resources/'component-artifacts.json').read_text())
    for name in ('windows-runtime-components.zip','linux-amd64-images.zip'):
        expected=artifacts[name]['sha256']
        if not re.fullmatch('[a-f0-9]{64}',expected) or digest(resources/name)!=expected:
            raise ValueError('Prepared component artifact hash mismatch')
    docker=resources/'Docker-Desktop-Installer.exe'
    checksum=(resources/'docker-checksums.txt').read_text().split()[0]
    if not re.fullmatch('[a-f0-9]{64}',checksum) or digest(docker)!=checksum:raise ValueError('Docker installer checksum mismatch')
    assets.extend(({'file':docker.name,'url':'https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe',
                    'sha256':checksum,'publisher_digest_available':True},
                   {'file':'vc_redist.x64.exe','url':'https://aka.ms/vc14/vc_redist.x64.exe',
                    'sha256':digest(resources/'vc_redist.x64.exe'),'publisher_digest_available':False}))
    from standards_library import sources,load
    editions=sources()
    for source in editions:load(source,library)
    with tempfile.TemporaryDirectory(dir=resources,prefix='assemble-') as temp:
        tmp=Path(temp)
        for file,folder in (('windows-runtime-components.zip','runtime'),('linux-amd64-images.zip','images'),
                            ('flet-windows.zip','flet'),('ollama-windows-amd64.zip','ollama')):
            extract_zip(resources/file,tmp/folder)
        metadata=json.loads((tmp/'runtime/runtime-build.json').read_text())
        commit=metadata['source_commit']
        if not re.fullmatch('[a-f0-9]{40}',commit):raise ValueError('Unknown runtime source revision')
        old_lock=subprocess.check_output(['git','show',commit+':uv.lock'],cwd=ROOT)
        if old_lock!=(ROOT/'uv.lock').read_bytes():raise ValueError('Runtime dependencies are stale')
        from standard_profiles import runtime_files
        for name in (*runtime_files(),'document_runtime/Dockerfile','sandbox/Dockerfile'):
            source='document_runtime/worker.py' if name=='worker.py' else name
            if subprocess.check_output(['git','show',commit+':'+source],cwd=ROOT)!=(ROOT/source).read_bytes():
                raise ValueError('Prepared image source is stale: '+source)
        build_source_kit(tmp/'source')
        shutil.copytree(tmp/'source',output)
        (output/'ASSEMBLY_REQUIRED.txt').unlink()
        shutil.copytree(tmp/'runtime/Runtime',output/'Runtime')
        shutil.copyfile(tmp/'runtime/BUTUZIK.AI.exe',output/'BUTUZIK.AI.exe')
        shutil.copytree(single_executable(tmp/'flet','flet.exe'),output/'Flet')
        (output/'Flet/version.txt').write_text(metadata['packages']['flet-desktop'],encoding='utf-8')
        shutil.copytree(single_executable(tmp/'ollama','ollama.exe'),output/'Ollama')
        provenance=output/'Provenance';provenance.mkdir()
        shutil.copyfile(tmp/'runtime/runtime-build.json',provenance/'runtime-build.json')
        shutil.copyfile(tmp/'runtime/requirements.windows.txt',provenance/'requirements.windows.txt')
        shutil.copyfile(resources/'component-artifacts.json',provenance/'component-artifacts.json')
        image_records=[]
        (output/'Images').mkdir()
        for name,tag in (('butuz-documents.tar','butuz-documents:local'),('butuz-sandbox.tar','butuz-sandbox:local')):
            source_image=tmp/'images'/name
            image_records.append(verify_image(source_image,tag))
            shutil.copyfile(source_image,output/'Images'/name)
        shutil.copyfile(tmp/'images/image-build.json',provenance/'image-build.json')
    (output/'Models').mkdir()
    model_records=copy_ollama(models,output/'Models/ollama')
    copy_hf(hf,output/'Models/huggingface/hub')
    for source in editions:
        dest=output/'App/data/standards_library/v1'/source.sha256;dest.mkdir(parents=True)
        for name in ('source.pdf','catalog.json'):shutil.copyfile(library/source.sha256/name,dest/name)
    shutil.copyfile(output/'Tools/windows.env.example',output/'App/.env')
    shutil.copyfile(ROOT/'docs/offline-first-start-ru.txt',output/'СНАЧАЛА ПРОЧИТАЙТЕ.txt')
    (output/'Installers').mkdir()
    for name in (*installers,'Docker-Desktop-Installer.exe','vc_redist.x64.exe'):
        shutil.copyfile(resources/name,output/'Installers'/name)
    record={'schema':1,'native_full_gui_acceptance':'pending','models':model_records,'vendor_assets':assets,
            'image_records':image_records,'registered_standards':len(editions),
            'runtime_build_source':commit,'assembly_source':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()}
    (provenance/'offline-assembly.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Writing full immutable manifest',flush=True)
    verify(output,write=True)
    print('Offline directory assembled; GUI acceptance remains pending:',output,flush=True)


def archive(root: Path) -> Path:
    target=root.with_suffix('.zip')
    if target.exists():raise ValueError('Refusing to replace an archive')
    # Model weights are already dense binary data; storing avoids hours of compression.
    with ZipFile(target,'x',allowZip64=True) as package:
        for path in sorted(root.rglob('*')):
            if path.is_symlink():raise ValueError('Symlink in delivery')
            if path.is_file():
                rel=path.relative_to(root)
                stored=rel.parts[0] in {'Models','Installers'}
                package.write(path,root.name+'/'+rel.as_posix(),compress_type=ZIP_STORED if stored else ZIP_DEFLATED,compresslevel=None if stored else 1)
    checksum=digest(target)
    target.with_suffix('.zip.sha256').write_text(checksum+'  '+target.name+'\n',encoding='ascii')
    print('Archive ready:',target,'bytes',target.stat().st_size,'sha256',checksum,flush=True)
    return target


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument('--resources',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--models',type=Path,required=True);parser.add_argument('--hf',type=Path,required=True)
    parser.add_argument('--standards',type=Path,required=True);parser.add_argument('--archive',action='store_true')
    args=parser.parse_args()
    assemble(args.resources.resolve(),args.output.resolve(),args.models.resolve(),args.hf.resolve(),args.standards.resolve())
    if args.archive:archive(args.output.resolve())


if __name__=='__main__':main()
