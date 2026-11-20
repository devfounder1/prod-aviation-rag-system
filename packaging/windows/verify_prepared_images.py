"""CI checks of the exact delivered Linux amd64 image tars using synthetic input."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))

DOCUMENT_CHECK=r'''
from pathlib import Path
import hashlib,json,subprocess,sys
sys.path.insert(0,'/opt/butuz')
from docx import Document
from gost_formatter import format_docx
from standard_profiles import runtime_files
root=Path('/opt/butuz');h=hashlib.sha256()
for name in runtime_files():h.update(name.encode());h.update((root/name).read_bytes())
doc=Document();doc.add_paragraph('Synthetic delivery check')
doc.add_heading('Technical requirements',level=1)
doc.add_paragraph('Signal value 10 V is preserved.')
doc.save('/work/input.docx')
format_docx(Path('/work/input.docx'),Path('/work/output.docx'))
r=subprocess.run(['soffice','-env:UserInstallation=file:///tmp/lo-check','--headless','--convert-to','pdf','--outdir','/work','/work/output.docx'],capture_output=True,text=True,timeout=45)
assert r.returncode==0 and Path('/work/output.pdf').stat().st_size>1000,(r.stdout,r.stderr)
print(json.dumps({'kind':'document','runtime_fingerprint':h.hexdigest(),'exported_pdf_bytes':Path('/work/output.pdf').stat().st_size}))
'''

SANDBOX_CHECK=r'''
from pathlib import Path
import json,subprocess,sys
import numpy as np
assert np.array([1,2]).sum()==3
Path('/work/test_delivery.py').write_text('def test_delivery(): assert 2+2 == 4\n')
r=subprocess.run([sys.executable,'-m','pytest','-q','/work/test_delivery.py'],capture_output=True,text=True,timeout=20)
assert r.returncode==0,(r.stdout,r.stderr)
print(json.dumps({'kind':'sandbox','pytest_exit_code':r.returncode,'pytest_output':r.stdout}))
'''


def main() -> None:
    from document_runner import runtime_fingerprint
    rows=[]
    for tag,code,tar in (('butuz-documents:local',DOCUMENT_CHECK,'butuz-documents.tar'),
                         ('butuz-sandbox:local',SANDBOX_CHECK,'butuz-sandbox.tar')):
        metadata=json.loads(subprocess.check_output(['docker','image','inspect',tag],text=True))[0]
        if metadata['Architecture']!='amd64' or metadata['Os']!='linux':raise ValueError('Wrong delivered image platform')
        command=['docker','run','--rm','--pull=never','--platform','linux/amd64','--network=none',
                 '--read-only','--user','65534:65534','--cap-drop=ALL','--security-opt','no-new-privileges',
                 '--cpus','1','--memory','512m','--pids-limit','64','--tmpfs','/tmp:rw,size=192m,mode=1777',
                 '--tmpfs','/work:rw,size=64m,mode=1777','-e','HOME=/tmp','--entrypoint','python',metadata['Id'],'-c',code]
        result=subprocess.run(command,capture_output=True,text=True,timeout=65)
        if result.returncode:
            print(result.stdout[-16000:]);print(result.stderr[-16000:],file=sys.stderr)
            raise RuntimeError('Prepared image check failed: '+tag)
        report=json.loads(result.stdout.strip().splitlines()[-1])
        if report['kind']=='document' and report['runtime_fingerprint']!=runtime_fingerprint():
            raise ValueError('Document code fingerprint mismatch')
        path=ROOT/'dist/linux-images'/tar
        h=hashlib.sha256()
        with path.open('rb') as stream:
            while chunk:=stream.read(4*1024*1024):h.update(chunk)
        rows.append({'image_id':metadata['Id'],'tar_sha256':h.hexdigest(),**report})
    output=ROOT/'dist/offline-image-checks.json'
    output.write_text(json.dumps({'full_windows_gui_acceptance':'pending','checks':rows},indent=2))
    print(output.read_text())


if __name__=='__main__':main()
