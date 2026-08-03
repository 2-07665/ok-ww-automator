[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$WorkspaceRoot = (Resolve-Path (Join-Path $ProjectRoot "..")).Path
$PythonExe = Join-Path $WorkspaceRoot ".venv\Scripts\python.exe"
$IconPath = Join-Path $WorkspaceRoot "ok-wuthering-waves\icons\icon.ico"
$ManifestPath = Join-Path $PSScriptRoot "launcher.manifest"
$EntryPoint = Join-Path $PSScriptRoot "launcher_entry.py"
$OutputPath = Join-Path $ProjectRoot "dist\OKAutomatorLauncher.exe"

foreach ($RequiredPath in @($PythonExe, $IconPath, $ManifestPath, $EntryPoint)) {
    if (-not (Test-Path -LiteralPath $RequiredPath -PathType Leaf)) {
        throw "Required build input is missing: $RequiredPath"
    }
}

Push-Location $ProjectRoot
try {
    if (Test-Path -LiteralPath $OutputPath -PathType Leaf) {
        Remove-Item -LiteralPath $OutputPath -Force
    }
    $PyInstallerArgs = @(
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--uac-admin",
        "--name", "OKAutomatorLauncher",
        "--icon", "`"$IconPath`"",
        "--manifest", "`"$ManifestPath`"",
        "--paths", "`"$(Join-Path $ProjectRoot 'src')`"",
        "--distpath", "`"$(Join-Path $ProjectRoot 'dist')`"",
        "--workpath", "`"$(Join-Path $ProjectRoot 'build\launcher')`"",
        "--specpath", "`"$(Join-Path $ProjectRoot 'build\launcher')`"",
        "`"$EntryPoint`""
    )
    $BuildProcess = Start-Process -FilePath $PythonExe -ArgumentList $PyInstallerArgs -NoNewWindow -Wait -PassThru
    if ($BuildProcess.ExitCode -ne 0) {
        throw "PyInstaller failed with exit code $($BuildProcess.ExitCode)"
    }
} finally {
    Pop-Location
}

if (-not (Test-Path -LiteralPath $OutputPath -PathType Leaf)) {
    throw "Build completed without producing $OutputPath"
}
Write-Host "Built $OutputPath"
