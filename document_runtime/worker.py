"""Fixed local converter/renderer; no model-generated programs or host execution."""
from __future__ import annotations

from dataclasses import asdict
import json
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import time

# -I omits the script directory. Add only this immutable image-owned code path.
sys.path.insert(0, '/opt/butuz')
from gost_formatter import format_docx  # noqa: E402
from document_inspection import inspect_docx  # noqa: E402
from document_layout import refresh_pagination  # noqa: E402
from standard_profiles import runtime_files  # noqa: E402
from pypdf import PdfReader  # noqa: E402


def convert(source: Path, destination: Path, kind: str) -> Path:
    destination.mkdir(exist_ok=True)
    profile = Path('/tmp/lo-profile/user')
    profile.mkdir(parents=True, exist_ok=True)
    config = profile / 'registrymodifications.xcu'
    if not config.exists():
        config.write_text('''<?xml version="1.0"?><oor:items xmlns:oor="http://openoffice.org/2001/registry"><item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item><item oor:path="/org.openoffice.Office.Writer/Content/Update"><prop oor:name="Link" oor:op="fuse"><value>2</value></prop></item></oor:items>''')
    command = ['soffice', '-env:UserInstallation=file:///tmp/lo-profile', '--headless',
               '--norestore', '--convert-to', kind, '--outdir', str(destination), str(source)]
    output = destination / (source.stem + '.' + kind.split(':', 1)[0])
    output.unlink(missing_ok=True)
    result = subprocess.run(command, capture_output=True, timeout=55)
    if result.returncode or not output.is_file():
        raise ValueError('Не удалось импортировать или отобразить документ. Возможно, он защищён или повреждён.')
    return output


def main() -> None:
    inputs = list(Path('/input').iterdir())
    if len(inputs) != 1 or inputs[0].suffix not in {'.doc', '.docx'}:
        raise ValueError('Нужен один документ DOC или DOCX')
    source = Path('/work') / ('source' + inputs[0].suffix)
    shutil.copyfile(inputs[0], source)
    original_format = source.suffix
    if source.suffix == '.doc':
        source = convert(source, Path('/work/imported'), 'docx:Office Open XML Text')
    # Validate before opening any OOXML in the renderer.
    before = inspect_docx(source)
    out = Path('/work/out'); out.mkdir()
    artifact = out / 'document.docx'
    report = asdict(format_docx(source, artifact))
    report['warnings'] = list(report['warnings'])
    pdf = convert(artifact, out, 'pdf:writer_pdf_Export')
    unresolved = 0
    for _ in range(3):
        changed, unresolved = refresh_pagination(artifact, pdf)
        if not changed:
            break
        pdf = convert(artifact, out, 'pdf:writer_pdf_Export')
    else:
        raise ValueError('Не удалось стабилизировать оглавление после изменения вёрстки')
    if unresolved:
        report['warnings'].append(f'Не удалось автоматически сверить ссылки оглавления: {unresolved}. Проверьте их вручную.')
    pages = len(PdfReader(pdf).pages)
    if not 1 <= pages <= 60:
        raise ValueError('Предпросмотр поддерживает от 1 до 60 страниц; документ не опубликован')
    subprocess.run(['pdftoppm', '-scale-to', '1100', '-png', str(pdf), str(out/'page')],
                   capture_output=True, check=True, timeout=55)
    report['page_count'] = pages
    digest = hashlib.sha256()
    for name in runtime_files():
        digest.update(name.encode()); digest.update((Path('/opt/butuz')/name).read_bytes())
    report['runtime_fingerprint'] = digest.hexdigest()
    report['changes'] = list(report['changes']) + [f'Предпросмотр подготовлен: {pages} страниц. Ссылки оглавления сверены: без совпадения — {unresolved}.']
    report['legacy_import'] = original_format == '.doc'
    report['input_features'] = {'sections': len(before.sections), 'tables': before.tables,
                                'textboxes': before.textboxes, 'images': before.image_parts,
                                'embedded_objects': before.embedded_objects}
    if original_format == '.doc':
        report['warnings'].append('Исходный DOC преобразован в DOCX. Внимательно проверьте сложные штампы и вертикальные надписи.')
    # Supply all Word text for review, not only Document.paragraphs.
    from zipfile import ZipFile
    from xml.etree import ElementTree as ET
    with ZipFile(artifact) as package:
        text = []
        for name in package.namelist():
            if name.startswith('word/') and name.endswith('.xml'):
                root = ET.fromstring(package.read(name))
                texts = [n.text or '' for n in root.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t')]
                if texts:
                    text.append(name + '\n' + '\n'.join(texts))
    (out/'text.txt').write_text('\n\n'.join(text))
    (out/'report.json').write_text(json.dumps(report, ensure_ascii=False))
    # Keep tmpfs alive until the caller exports the bounded, validated archive.
    print('BUTUZ_DOCUMENT_READY', flush=True)
    while True:
        time.sleep(1)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(type(exc).__name__ + ': ' + str(exc), file=sys.stderr, flush=True)
        raise SystemExit(1)
