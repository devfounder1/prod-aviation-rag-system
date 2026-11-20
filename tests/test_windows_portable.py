from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest
import sandbox_runner


def test_windows_docker_uses_only_fixed_local_linux_pipes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sandbox_runner.sys,'platform','win32')
    monkeypatch.setattr(sandbox_runner.shutil,'which',lambda _: 'docker.exe')
    seen=[]
    def run(command,**kwargs):
        seen.append(command)
        return SimpleNamespace(returncode=0,stdout='windows' if len(seen)==1 else 'linux')
    monkeypatch.setattr(sandbox_runner.subprocess,'run',run)
    result=sandbox_runner.docker_command()
    assert result==['docker.exe','--host','npipe:////./pipe/docker_engine']
    assert all(c[2].startswith('npipe:////./pipe/') for c in seen)


def test_windows_missing_engine_never_runs_host_python(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sandbox_runner.sys,'platform','win32')
    monkeypatch.setattr(sandbox_runner.shutil,'which',lambda _: 'docker.exe')
    def run(command,**kwargs):raise subprocess.TimeoutExpired(command,5)
    monkeypatch.setattr(sandbox_runner.subprocess,'run',run)
    with pytest.raises(RuntimeError,match='Linux engine'):sandbox_runner.docker_command()


def test_portable_bootstrap_sets_own_paths_without_using_shell_cwd(tmp_path: Path,monkeypatch: pytest.MonkeyPatch) -> None:
    import windows_entry
    app=tmp_path/'App';app.mkdir();(app/'prilozhenie.py').touch()
    flet=tmp_path/'Flet';flet.mkdir();(flet/'flet.exe').touch();(flet/'version.txt').write_text('0.28.3')
    monkeypatch.setattr(windows_entry.importlib.metadata,'version',lambda _: '0.28.3')
    monkeypatch.chdir(tmp_path)
    # monkeypatch restores cwd and environment after the test.
    for key in ('FLET_VIEW_PATH','HF_HOME','HF_HUB_CACHE','HF_HUB_OFFLINE','TRANSFORMERS_OFFLINE','LANGSMITH_TRACING','LANGCHAIN_TRACING_V2','HF_HUB_DISABLE_TELEMETRY','OLLAMA_MODELS'):
        monkeypatch.setenv(key,'before')
    assert windows_entry.configure(app)==tmp_path
    assert Path.cwd()==app
    assert windows_entry.os.environ['HF_HOME']==str(tmp_path/'Models'/'huggingface')
    assert windows_entry.os.environ['FLET_VIEW_PATH']==str(flet)
    (flet/'version.txt').write_text('wrong')
    with pytest.raises(RuntimeError,match='Версия'):windows_entry.configure(app)


def test_source_kit_filter_excludes_private_runtime_and_unapproved_docx() -> None:
    import importlib.util
    path=Path(__file__).resolve().parents[1]/'packaging/windows/make_source_kit.py'
    spec=importlib.util.spec_from_file_location('source_kit',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    for name in ('data/chats.sqlite3','agent_workspace/chats/private.py','.env','docs/private.docx','docs/BUTUZIK_AI_User_Guide_RU.docx','../leak.py','documents_ae/manual.pdf'):
        assert not module.allowed(name),name
    for name in ('prilozhenie.py','.dockerignore','.env.example','standards/library.json','ollama/Modelfile.agent','tools/build_user_guide.py','docs/Инструкция для запуска BUTUZIK AI.docx'):
        assert module.allowed(name),name


def test_bundle_manifest_detects_changed_file_and_keeps_user_data_mutable(tmp_path: Path) -> None:
    import importlib.util,struct
    path=Path(__file__).resolve().parents[1]/'packaging/windows/verify_bundle.py'
    spec=importlib.util.spec_from_file_location('verify_bundle',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    pe=bytearray(70);pe[:2]=b'MZ';struct.pack_into('<I',pe,60,64);pe[64:70]=b'PE\0\0\x64\x86'
    for name in module.REQUIRED:
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(bytes(pe) if name.endswith('.exe') else b'fixture')
    for name in ('Models/huggingface/hub/models--intfloat--multilingual-e5-small/weights','Models/ollama/manifests/test','Models/ollama/blobs/test'):
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'fixture')
    module.verify(tmp_path,write=True);module.verify(tmp_path)
    data=tmp_path/'App/data';data.mkdir();(data/'chats.sqlite3').write_bytes(b'new runtime')
    module.verify(tmp_path)
    (tmp_path/'App/config.json').write_text('{"user_setting":true}')
    (tmp_path/'~$launch-guide.docx').write_text('Word owner lock')
    logs=tmp_path/'Logs';logs.mkdir();(logs/'launcher.log').write_text('startup')
    module.verify(tmp_path)
    (tmp_path/'App/prilozhenie.py').write_bytes(b'tampered')
    with pytest.raises(ValueError,match='Hash mismatch'):module.verify(tmp_path)
