# Run on Windows x64. Preparation only; runtime never downloads dependencies.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$PythonRuntime,
    [Parameter(Mandatory=$true)][string]$FletRuntime,
    [Parameter(Mandatory=$true)][string]$FletVersion,
    [Parameter(Mandatory=$true)][string]$OllamaRuntime,
    [Parameter(Mandatory=$true)][string]$HuggingFaceHub,
    [Parameter(Mandatory=$true)][string]$OllamaModels,
    [Parameter(Mandatory=$true)][string]$StandardsLibrary,
    [Parameter(Mandatory=$true)][string]$DocumentImageTar,
    [Parameter(Mandatory=$true)][string]$SandboxImageTar,
    [Parameter(Mandatory=$true)][string]$Output,
    [string]$Wheelhouse = ''
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
function Invoke-Checked([string]$Command, [string[]]$Arguments) {
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Command failed with exit code $LASTEXITCODE" }
}
if (-not [Environment]::Is64BitOperatingSystem -or $env:OS -ne 'Windows_NT') { throw 'Windows x64 required' }
$kit = Split-Path $PSScriptRoot -Parent
foreach ($pair in @(@($PythonRuntime,'python.exe'),@($FletRuntime,'flet.exe'),@($OllamaRuntime,'ollama.exe'))) {
    if (-not (Test-Path (Join-Path $pair[0] $pair[1]) -PathType Leaf)) { throw "Missing runtime: $($pair[0]) / $($pair[1])" }
}
if (Test-Path (Join-Path $PythonRuntime 'pyvenv.cfg')) { throw 'Supply a full portable CPython runtime, not a venv' }
foreach ($file in @($DocumentImageTar,$SandboxImageTar)) { if (-not (Test-Path $file -PathType Leaf)) { throw "Missing image tar: $file" } }
if (-not (Test-Path $HuggingFaceHub -PathType Container) -or -not (Test-Path $OllamaModels -PathType Container)) { throw 'Supply prepared local model directories' }
if (Test-Path $Output) { throw 'Output already exists. Choose a NEW empty destination; never overwrite user data.' }
$uv = (Get-Command uv -ErrorAction Stop).Source
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path $csc)) { throw 'C# compiler missing; prepare .NET Framework developer tools before building' }
New-Item $Output -ItemType Directory | Out-Null
$Output = (Resolve-Path $Output).Path
Copy-Item (Join-Path $kit 'App') (Join-Path $Output 'App') -Recurse
Copy-Item $PSScriptRoot (Join-Path $Output 'Tools') -Recurse
Copy-Item $PythonRuntime (Join-Path $Output 'Runtime') -Recurse
Copy-Item $FletRuntime (Join-Path $Output 'Flet') -Recurse
Copy-Item $OllamaRuntime (Join-Path $Output 'Ollama') -Recurse
$python = Join-Path $Output 'Runtime\python.exe'
Invoke-Checked $python @('-c',"import sys,platform; assert sys.platform=='win32' and sys.maxsize>2**32 and sys.version_info[:2]==(3,12), 'CPython 3.12 x64 required'")
$requirements = Join-Path $Output 'Tools\requirements.windows.txt'
Invoke-Checked $uv @('export','--project',(Join-Path $Output 'App'),'--frozen','--no-dev','--no-emit-project','--output-file',$requirements)
$install = @('pip','install','--python',$python,'--break-system-packages','--require-hashes','--only-binary',':all:','-r',$requirements)
if ($Wheelhouse) { $install += @('--offline','--no-index','--find-links',(Resolve-Path $Wheelhouse).Path) }
Invoke-Checked $uv $install
Invoke-Checked $python @('-c',"import importlib.metadata,pathlib,sys; assert importlib.metadata.version('flet-desktop')==sys.argv[2], 'Flet release mismatch'; pathlib.Path(sys.argv[1]).write_text(sys.argv[2],encoding='utf-8')",(Join-Path $Output 'Flet\version.txt'),$FletVersion)
# Client MUST be from that exact Flet release; confirm this manually before building.
New-Item (Join-Path $Output 'Models\huggingface') -ItemType Directory -Force | Out-Null
# copytree dereferences cache symlinks so no developer-home paths are required.
Invoke-Checked $python @('-c',"import shutil,sys; shutil.copytree(sys.argv[1],sys.argv[2],symlinks=False)",$HuggingFaceHub,(Join-Path $Output 'Models\huggingface\hub'))
Invoke-Checked $python @('-c',"import shutil,sys; shutil.copytree(sys.argv[1],sys.argv[2],symlinks=False)",$OllamaModels,(Join-Path $Output 'Models\ollama'))
New-Item (Join-Path $Output 'App\data\standards_library') -ItemType Directory -Force | Out-Null
Invoke-Checked $python @('-c',"import shutil,sys; shutil.copytree(sys.argv[1],sys.argv[2],symlinks=False)",$StandardsLibrary,(Join-Path $Output 'App\data\standards_library\v1'))
New-Item (Join-Path $Output 'Images') -ItemType Directory | Out-Null
Copy-Item $DocumentImageTar (Join-Path $Output 'Images\butuz-documents.tar')
Copy-Item $SandboxImageTar (Join-Path $Output 'Images\butuz-sandbox.tar')
Copy-Item (Join-Path $Output 'Tools\windows.env.example') (Join-Path $Output 'App\.env')
Get-ChildItem $kit -Filter '*.docx' | Copy-Item -Destination $Output
Copy-Item (Join-Path $kit 'README_FIRST.md') $Output
Invoke-Checked $csc @('/nologo','/target:winexe','/platform:x64','/reference:System.Windows.Forms.dll',('/out:'+(Join-Path $Output 'BUTUZIK.AI.exe')),(Join-Path $Output 'Tools\Launcher.cs'))
Invoke-Checked $python @((Join-Path $Output 'Tools\verify_bundle.py'),$Output,'--write-manifest')
Write-Host 'Assembly complete. This is NOT Windows acceptance. Run Tools\Check-Offline.ps1 and the GUI smoke tests on a disconnected target PC.'
