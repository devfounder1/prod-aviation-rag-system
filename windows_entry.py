"""Fixed entry point for the portable Windows directory, no runtime downloads."""
from __future__ import annotations

import importlib.metadata
import json
import os
from pathlib import Path
import runpy
import sys


def configure(app: Path) -> Path:
    app=app.resolve();root=app.parent
    if not (app/'prilozhenie.py').is_file():raise RuntimeError('App/prilozhenie.py отсутствует')
    executable=root/'Flet'/'flet.exe'
    if not executable.is_file():raise RuntimeError('Нет локального Flet/flet.exe; комплект неполный')
    version=(root/'Flet'/'version.txt').read_text(encoding='utf-8').strip()
    if version!=importlib.metadata.version('flet-desktop'):
        raise RuntimeError('Версия Flet клиента не совпадает с Python-пакетом')
    os.chdir(app)
    os.environ.update(FLET_VIEW_PATH=str(executable.parent),HF_HOME=str(root/'Models'/'huggingface'),
        HF_HUB_CACHE=str(root/'Models'/'huggingface'/'hub'),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',
        LANGSMITH_TRACING='false',LANGCHAIN_TRACING_V2='false',HF_HUB_DISABLE_TELEMETRY='1')
    if str(app) not in sys.path:sys.path.insert(0,str(app))
    # Only this trusted local CLI directory; no new remote provider.
    if (root/'Ollama'/'ollama.exe').is_file():
        os.environ['PATH']=str(root/'Ollama')+os.pathsep+os.environ.get('PATH','')
    os.environ['OLLAMA_MODELS']=str(root/'Models'/'ollama')
    return root


def main() -> None:
    configure(Path(__file__).resolve().parent)
    if '--doctor' in sys.argv:
        from doctor import check
        report=check();print(json.dumps(report,ensure_ascii=False,indent=2))
        raise SystemExit(0 if report['ready'] else 1)
    runpy.run_module('prilozhenie',run_name='__main__')


if __name__=='__main__':
    main()
