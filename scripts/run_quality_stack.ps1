param(
    [switch]$InstallTools,
    [int]$CoverageFailUnder = 75
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$backendDir = Join-Path $repoRoot "backend"

if (-not (Test-Path $backendDir)) {
    throw "backend directory not found: $backendDir"
}

if ($InstallTools) {
    Push-Location $backendDir
    try {
        python -m pip install --upgrade pip
        python -m pip install -r requirements.txt
        python -m pip install bandit pip-audit
        try {
            python -m pip install semgrep
        }
        catch {
            Write-Warning "Semgrep installation failed in local Python env. Docker fallback will be used if available."
        }
    }
    finally {
        Pop-Location
    }
}

Push-Location $backendDir
try {
    python -m coverage run manage.py test --noinput
    python -m coverage report --fail-under=$CoverageFailUnder
    python -m coverage xml

    python -m bandit -q -r . -x tests -ll -ii
    python -m pip_audit -r requirements.txt --progress-spinner off
}
finally {
    Pop-Location
}

Push-Location $repoRoot
try {
    $semgrepAvailable = $false
    try {
        python -m semgrep --version | Out-Null
        $semgrepAvailable = $true
    }
    catch {
        $semgrepAvailable = $false
    }

    if ($semgrepAvailable) {
        python -m semgrep scan --config p/security-audit --config p/secrets --severity ERROR --error --metrics=off backend
    }
    else {
        $dockerAvailable = $false
        try {
            docker --version | Out-Null
            $dockerAvailable = $true
        }
        catch {
            $dockerAvailable = $false
        }

        if (-not $dockerAvailable) {
            throw "Semgrep is unavailable in local Python environment and Docker is not available."
        }

        $repoPath = (Resolve-Path $repoRoot).Path
        docker run --rm -v "${repoPath}:/src" returntocorp/semgrep semgrep scan --config p/security-audit --config p/secrets --severity ERROR --error --metrics=off backend
    }
}
finally {
    Pop-Location
}
