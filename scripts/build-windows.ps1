param([switch]$SkipChecks)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitOperatingSystem) {
    throw 'Execute este script em Windows 10/11 de 64 bits.'
}
$AlmaRoot = Split-Path $PSScriptRoot -Parent
Set-Location $AlmaRoot
function Invoke-Checked {
    param([string]$Tool, [string[]]$CommandArgs)
    & $Tool @CommandArgs
    if ($LASTEXITCODE -ne 0) { throw "Falha em $Tool (exit $LASTEXITCODE). Instalador nao aprovado." }
}
foreach ($Tool in @('python', 'node', 'npm.cmd', 'cargo')) {
    if (-not (Get-Command $Tool -ErrorAction SilentlyContinue)) {
        throw "Falta $Tool na maquina de compilacao. Consulte docs/WINDOWS.md."
    }
}
$AlmaPython = Join-Path $AlmaRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $AlmaPython)) { Invoke-Checked 'python' @('-m','venv','.venv') }
Invoke-Checked $AlmaPython @('-c','import sys,struct; assert sys.version_info >= (3,11) and struct.calcsize(chr(80))==8')
Invoke-Checked $AlmaPython @('-m','pip','install','-r','requirements.lock','-r','packaging/requirements-build.lock')
Invoke-Checked $AlmaPython @('-m','pip','install','--no-deps','-e','.')
Invoke-Checked 'npm.cmd' @('--prefix','apps/desktop','ci')
if (-not $SkipChecks) {
    Invoke-Checked $AlmaPython @('-m','pytest','tests/unit','tests/pdf','tests/integration/test_ipc.py','-q')
    Invoke-Checked 'cargo' @('test','--locked')
}
Invoke-Checked $AlmaPython @('scripts/build_worker.py','--destination','apps/desktop/src-tauri/bundled-runtime','--require-windows')
Push-Location 'apps/desktop'
try {
    Invoke-Checked 'npm.cmd' @('run','tauri','--','build','--config','src-tauri/tauri.installer.conf.json','--bundles','nsis','--target','x86_64-pc-windows-msvc')
} finally { Pop-Location }
$AlmaBundle = Join-Path $AlmaRoot 'apps/desktop/src-tauri/target/x86_64-pc-windows-msvc/release/bundle/nsis'
$AlmaInstallers = @(Get-ChildItem $AlmaBundle -Filter '*-setup.exe')
if ($AlmaInstallers.Count -ne 1) { throw 'Esperado exatamente um instalador. Limpe builds antigos e execute novamente.' }
$AlmaRelease = Join-Path $AlmaRoot 'release/windows'
New-Item -ItemType Directory -Force $AlmaRelease | Out-Null
$AlmaInstaller = Join-Path $AlmaRelease 'ALMA-0.1.0-windows-x64-setup.exe'
Copy-Item $AlmaInstallers[0].FullName $AlmaInstaller -Force
$AlmaHash = (Get-FileHash $AlmaInstaller -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText((Join-Path $AlmaRelease 'SHA256SUMS.txt'), "$AlmaHash  ALMA-0.1.0-windows-x64-setup.exe`n")
Copy-Item 'packaging/windows/LEIA-ME.txt' $AlmaRelease -Force
Write-Host "Instalador gerado: $AlmaInstaller"
Write-Host 'Antes de distribuir: execute scripts/test-windows-install.ps1 e confira a janela no Windows.'
