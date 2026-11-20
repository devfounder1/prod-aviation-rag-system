from pathlib import Path
import hashlib
import importlib.util
import io
import json
import tarfile
from zipfile import ZipFile
from typing import Any

import pytest


@pytest.fixture
def assembly() -> Any:
    path=Path(__file__).resolve().parents[1]/'packaging/windows/assemble_offline.py'
    spec=importlib.util.spec_from_file_location('offline_assembly',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_component_zip_rejects_escape_before_writing_outside(tmp_path: Path,assembly: Any) -> None:
    archive=tmp_path/'bad.zip'
    with ZipFile(archive,'w') as z:z.writestr('../outside.txt','private')
    with pytest.raises(ValueError,match='Unsafe'):assembly.extract_zip(archive,tmp_path/'out')
    assert not (tmp_path/'outside.txt').exists()


def test_selected_model_copy_deduplicates_blobs_and_ignores_other_models(tmp_path: Path,assembly: Any) -> None:
    src=tmp_path/'models';(src/'blobs').mkdir(parents=True)
    raw=b'synthetic weights';sha=hashlib.sha256(raw).hexdigest()
    (src/'blobs'/('sha256-'+sha)).write_bytes(raw)
    (src/'blobs/other-private-model').write_bytes(b'do not copy')
    blob={'digest':'sha256:'+sha,'size':len(raw)}
    for name,tag in (('qwen2.5','14b'),('qwen2.5vl','7b')):
        p=src/'manifests/registry.ollama.ai/library'/name/tag;p.parent.mkdir(parents=True)
        p.write_text(json.dumps({'config':blob,'layers':[blob]}))
    out=tmp_path/'out';records=assembly.copy_ollama(src,out)
    assert len(records)==2 and len(list((out/'blobs').iterdir()))==1
    assert not (out/'blobs/other-private-model').exists()
    (src/'blobs'/('sha256-'+sha)).write_bytes(b'wrong same length')
    with pytest.raises(ValueError):assembly.copy_ollama(src,tmp_path/'second')


def test_hf_cache_external_link_is_rejected(tmp_path: Path,assembly: Any,monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(assembly,'REPOS',('test/model',))
    src=tmp_path/'cache/models--test--model'
    (src/'refs').mkdir(parents=True);(src/'refs/main').write_text('a'*40)
    (src/'snapshots'/('a'*40)).mkdir(parents=True)
    secret=tmp_path/'secret';secret.write_text('private')
    (src/'snapshots'/('a'*40)/'weights').symlink_to(secret)
    with pytest.raises(ValueError,match='leaves cache'):assembly.copy_hf(tmp_path/'cache',tmp_path/'out')


def test_image_requires_exact_local_tag_and_linux_amd64(tmp_path: Path,assembly: Any) -> None:
    archive=tmp_path/'image.tar'
    with tarfile.open(archive,'w') as t:
        for name,data in [('manifest.json',[{'Config':'config.json','RepoTags':['butuz-sandbox:local']}]),
                          ('config.json',{'os':'linux','architecture':'arm64'})]:
            raw=json.dumps(data).encode();member=tarfile.TarInfo(name);member.size=len(raw);t.addfile(member,io.BytesIO(raw))
    with pytest.raises(ValueError,match='amd64'):assembly.verify_image(archive,'butuz-sandbox:local')
    with pytest.raises(ValueError,match='tag mismatch'):assembly.verify_image(archive,'butuz-documents:local')
