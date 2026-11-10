from pathlib import Path
import os
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

import sandbox_runner
from sandbox_runner import ExecutionResult, execute, snapshot
from file_tools import create_file_tools
from ai_agent import LocalAgent


def test_snapshot_excludes_secrets_and_symlinks(tmp_path: Path) -> None:
    root, out = tmp_path/'root', tmp_path/'out'
    root.mkdir(); out.mkdir()
    (root/'code.py').write_text('print(1)')
    (root/'.env').write_text('SECRET=private')
    (root/'link.py').symlink_to(root/'code.py')
    snapshot(root,out)
    assert [p.name for p in out.iterdir()]==['code.py']


def test_unavailable_runtime_never_falls_back_to_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path/'code.py').write_text('print(1)')
    def unavailable() -> list[str]:
        raise RuntimeError('Docker unavailable')
    monkeypatch.setattr(sandbox_runner,'docker_command',unavailable)
    with pytest.raises(RuntimeError,match='Docker unavailable'):
        execute(tmp_path,'code.py')
    with pytest.raises(ValueError):
        execute(tmp_path,'../outside.py')


def test_agent_shows_actual_execution_instead_of_model_claim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import file_tools
    monkeypatch.setattr(file_tools,'WORKSPACE',tmp_path)
    monkeypatch.setattr(sandbox_runner,'execute',lambda *a,**k: ExecutionResult('ошибка выполнения',1,'','AssertionError',0.1))
    model=MagicMock()
    model.bind_tools.return_value.invoke.side_effect=[
        AIMessage(content='',tool_calls=[{'name':'run_pytest','id':'1','args':{'file_path':'test_x.py'}}]),
        AIMessage(content='Все тесты прошли'),
    ]
    answer=LocalAgent(model).run('Проверь тесты',tools=create_file_tools('a'))
    assert 'AssertionError' in answer and 'код завершения: 1' in answer
    assert 'Все тесты прошли' not in answer


@pytest.mark.skipif(os.environ.get('BUTUZ_SANDBOX_LIVE')!='1',reason='Requires prepared local Docker image')
def test_real_container_boundaries(tmp_path: Path) -> None:
    (tmp_path/'check.py').write_text('''from pathlib import Path
import socket
import numpy as np
assert np.array([1,2]).sum()==3
Path('only_inside.txt').write_text('temporary')
try:
    Path('/input/check.py').write_text('bad')
except OSError: print('READ_ONLY')
try:
    socket.create_connection(('1.1.1.1',80),timeout=1)
except OSError: print('NO_NETWORK')
''')
    result=execute(tmp_path,'check.py')
    assert result.exit_code==0 and 'READ_ONLY' in result.stdout and 'NO_NETWORK' in result.stdout
    assert not (tmp_path/'only_inside.txt').exists()
    (tmp_path/'test_ok.py').write_text('def test_ok(): assert 2+2==4')
    assert execute(tmp_path,'test_ok.py',tests=True).exit_code==0
    (tmp_path/'test_bad.py').write_text('def test_bad(): assert False')
    assert execute(tmp_path,'test_bad.py',tests=True).exit_code==1
    (tmp_path/'hang.py').write_text('while True: pass')
    assert 'время' in execute(tmp_path,'hang.py',timeout=2).status
    (tmp_path/'flood.py').write_text('while True: print("x"*10000)')
    assert 'лимит вывода' in execute(tmp_path,'flood.py').status
