$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
& "$root\Runtime\python.exe" "$root\Tools\verify_bundle.py" $root
if ($LASTEXITCODE -ne 0) { throw 'Bundle file check failed' }
& "$root\Runtime\python.exe" "$root\App\windows_entry.py" --doctor
if ($LASTEXITCODE -ne 0) { throw 'Local models/runtime not ready; see doctor output' }
& "$root\Runtime\python.exe" -c "import torch,chromadb,ctranslate2,sounddevice,lxml.etree; print('Native imports OK')"
if ($LASTEXITCODE -ne 0) { throw 'Native DLL import failed' }
& "$root\Runtime\python.exe" -c "import sys,subprocess; sys.path.insert(0,sys.argv[1]); from sandbox_runner import docker_command; d=docker_command(); results=[subprocess.run(d+['image','inspect',n,'--format','{{.Os}}/{{.Architecture}}'],capture_output=True,text=True) for n in ('butuz-documents:local','butuz-sandbox:local')]; assert all(r.returncode==0 and r.stdout.strip()=='linux/amd64' for r in results), 'Wrong/missing local Linux amd64 images'" "$root\App"
if ($LASTEXITCODE -ne 0) { throw 'Local Docker images not ready' }
& "$root\Runtime\python.exe" -c "import sys; sys.path.insert(0,sys.argv[1]); from standards_library import sources,load; [load(s) for s in sources()]; print('Registered standard archives verified')" "$root\App"
if ($LASTEXITCODE -ne 0) { throw 'Standard library incomplete or changed' }
Write-Host 'Readiness checks passed. GUI acceptance still required.'
