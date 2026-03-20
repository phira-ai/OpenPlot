$ErrorActionPreference = 'Stop'

$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $root

if ($env:OS -ne 'Windows_NT') {
    throw 'Windows build script must run on Windows'
}

Write-Host '[1/4] Syncing Python dependencies'
uv sync --group dev --group packaging --extra desktop

Write-Host '[2/4] Building frontend assets'
npm ci --prefix frontend
npm run build --prefix frontend

Write-Host '[3/4] Building OpenPlot bundle'
uv run pyinstaller --noconfirm --clean packaging/pyinstaller/OpenPlot.spec

Write-Host '[4/4] Building Windows installer'
$iscc = $null
foreach ($candidate in @(
    'iscc',
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
    'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
)) {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) {
        $iscc = $candidate
        break
    }
    if (Test-Path $candidate) {
        $iscc = $candidate
        break
    }
}

if (-not $iscc) {
    Write-Host 'WARNING: Inno Setup not found. Skipping installer creation.'
    Write-Host 'Install Inno Setup 6 from https://jrsoftware.org/isinfo.php or run:'
    Write-Host '  choco install innosetup -y'
    Write-Host ''
    Write-Host 'Falling back to zip archive.'
    Compress-Archive -Path dist/OpenPlot -DestinationPath dist/OpenPlot-windows-x64.zip -Force
    Write-Host 'Built dist/OpenPlot-windows-x64.zip'
} else {
    & $iscc packaging/windows/openplot.iss
    Write-Host 'Built dist/OpenPlot-windows-x64-setup.exe'
}
