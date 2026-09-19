# bootstrap_env.ps1 -- zero-dependency bootstrap for a brand-new Windows machine.
#
# The main provisioning scripts (preflight_env_check.py / provision_env.py) are
# written in Python, which a fresh OS does not have. This script only relies on
# what a fresh Windows ships with (PowerShell 5.1; winget when present):
#   1. detect winget; when absent (LTSC/Server/group policy) fall back to
#      direct official downloads -- only network access is needed
#   2. install Python 3.12 (winget user scope, or python.org silent installer)
#   3. refresh PATH from the registry (new installs are invisible otherwise)
#   4. hand off to provision_env.py for the full pinned-toolchain install
#      (it auto-selects winget or direct-download mode)
#
# HARD RULE (environment-provisioning.md): PostgreSQL 16 and Redis are NEVER
# installed on the dev machine -- dev connects to the deployment server.
#
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\bootstrap_env.ps1
# Exit codes: 0 = provisioning finished ready; 2 = Python unobtainable via
#             winget AND direct download (usually no network -> halted-pending-user);
#             other = provision_env.py exit code.

$ErrorActionPreference = 'Continue'

function Refresh-PathFromRegistry {
    # Import registry env vars this process is missing (e.g. NVM_HOME) BEFORE
    # expanding PATH, because installers reference them as unexpanded %VARS%.
    $keys = @(
        @{ Hive = 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Environment' },
        @{ Hive = 'HKCU:\Environment' }
    )
    $rawPaths = @()
    foreach ($k in $keys) {
        try { $props = Get-ItemProperty -Path $k.Hive -ErrorAction Stop } catch { continue }
        foreach ($p in $props.PSObject.Properties) {
            if ($p.Name -match '^PS') { continue }
            if ($p.Value -isnot [string]) { continue }
            if ($p.Name -ieq 'Path') {
                $rawPaths += $p.Value
            } elseif (-not (Test-Path "Env:$($p.Name)")) {
                Set-Item -Path "Env:$($p.Name)" -Value ([Environment]::ExpandEnvironmentVariables($p.Value))
            }
        }
    }
    $merged = ($rawPaths | ForEach-Object { [Environment]::ExpandEnvironmentVariables($_) }) -join ';'
    $env:Path = $merged + ';' + $env:Path
}

function Test-RealPython312 {
    # A fresh Windows has a Microsoft Store stub named python.exe -- it opens
    # the Store instead of running. Only trust output that looks like a version.
    foreach ($probe in @(@('py', @('-3.12', '--version')), @('python', @('--version')))) {
        $exe = $probe[0]; $probeArgs = $probe[1]
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        try { $out = & $exe @probeArgs 2>&1 | Out-String } catch { continue }
        if ($out -match 'Python 3\.12\.\d+') { return $true }
    }
    return $false
}

# --- 1. detect winget (App Installer ships with Windows 10 1809+/11) ---
# Missing winget (LTSC / Server / group policy) is NOT a blocker: we fall back
# to direct official downloads, which only need network access.
$wingetAvailable = [bool](Get-Command winget -ErrorAction SilentlyContinue)
if (-not $wingetAvailable) {
    Write-Output 'winget not available -- falling back to direct official downloads (no package manager needed).'
}

# --- 2. bootstrap Python 3.12 (the provisioning scripts need it) ---
Refresh-PathFromRegistry
if (Test-RealPython312) {
    Write-Output 'Python 3.12 already available -- skipping bootstrap install.'
} else {
    if ($wingetAvailable) {
        Write-Output 'Installing Python 3.12 via winget (user scope, silent)...'
        winget install Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
        Refresh-PathFromRegistry
        if (-not (Test-RealPython312)) {
            # user-scope may be unsupported in some environments; retry default scope
            Write-Output 'User-scope install did not verify -- retrying default scope...'
            winget install Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
            Refresh-PathFromRegistry
        }
    }
    if (-not (Test-RealPython312)) {
        # Direct download from python.org: used when winget is absent, or as a
        # last resort when winget installs failed to verify.
        Write-Output 'Downloading Python 3.12 directly from python.org ...'
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        $pyUrl = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe'
        $pyExe = Join-Path $env:TEMP 'python-3.12.10-amd64.exe'
        try {
            Invoke-WebRequest -Uri $pyUrl -OutFile $pyExe -UseBasicParsing
            Start-Process -FilePath $pyExe -ArgumentList '/quiet','InstallAllUsers=0','PrependPath=1','Include_test=0' -Wait
            Refresh-PathFromRegistry
        } catch {
            Write-Output "Direct download failed: $($_.Exception.Message)"
        }
    }
    if (-not (Test-RealPython312)) {
        Write-Output 'BLOCKED: Python 3.12 unavailable after winget AND direct-download attempts (likely no network).'
        Write-Output 'Per environment-provisioning.md this is halted-pending-user. Do NOT change the tech stack.'
        exit 2
    }
    Write-Output 'Python 3.12 bootstrap complete.'
}

# --- 3. hand off to the full provisioner (Git/JDK/Node/Maven/Python) ---
$provision = Join-Path $PSScriptRoot 'provision_env.py'
Write-Output 'Handing off to provision_env.py ...'
if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3.12 $provision
} else {
    & python $provision
}
exit $LASTEXITCODE
