$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:OS -ne 'Windows_NT') { throw 'Teste exclusivo para Windows.' }
$AlmaRoot = Split-Path $PSScriptRoot -Parent
$AlmaInstallDir = Join-Path ([IO.Path]::GetTempPath()) ('ALMA teste ' + [Guid]::NewGuid().ToString('N'))
$AlmaReceipt = Join-Path $AlmaRoot 'release/windows/installation-check.json'
$AlmaSetup = Join-Path $AlmaRoot 'release/windows/ALMA-0.1.0-windows-x64-setup.exe'
$Install = Start-Process -FilePath $AlmaSetup -ArgumentList @('/S',("/D=" + $AlmaInstallDir)) -PassThru -Wait
if ($Install.ExitCode -ne 0) { throw "Instalador falhou: $($Install.ExitCode)" }
try {
    $AlmaApp = Join-Path $AlmaInstallDir 'alma-desktop.exe'
    if (-not (Test-Path $AlmaApp)) { throw 'Executavel principal nao encontrado na instalacao.' }
    $Probe = Start-Process -FilePath $AlmaApp -ArgumentList @('--package-smoke',('"' + $AlmaReceipt + '"')) -WorkingDirectory $AlmaInstallDir -PassThru -Wait
    if ($Probe.ExitCode -ne 0) { throw 'Motor instalado falhou na verificacao. Consulte installation-check.json.' }
    if (-not (Get-Content $AlmaReceipt -Raw | ConvertFrom-Json).ok) { throw 'Verificacao incompleta.' }
    & (Join-Path $AlmaRoot '.venv/Scripts/python.exe') (Join-Path $AlmaRoot 'scripts/smoke_packaged_worker.py') (Join-Path $AlmaInstallDir 'runtime/worker/alma-worker.exe') (Join-Path $AlmaInstallDir 'runtime/browsers')
    if ($LASTEXITCODE -ne 0) { throw 'Chromium instalado nao passou no teste.' }
    Write-Host 'PASS: instalacao, Rust, Python, documentos, SQLite e Chromium.'
} finally {
    $Uninstaller = Join-Path $AlmaInstallDir 'uninstall.exe'
    if (Test-Path $Uninstaller) { Start-Process $Uninstaller -ArgumentList '/S' -Wait }
}
