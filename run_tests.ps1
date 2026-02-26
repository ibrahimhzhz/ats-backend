#!/usr/bin/env pwsh
<#
.SYNOPSIS
    ATS Backend test runner.

.DESCRIPTION
    Runs the test suite against a live server on localhost:8001.

USAGE
    .\run_tests.ps1               # everything except pipeline (fast, ~5s)
    .\run_tests.ps1 -All          # includes the end-to-end pipeline (hits Vertex AI)
    .\run_tests.ps1 -Unit         # scoring unit tests only (no server needed)
    .\run_tests.ps1 -Auth         # auth tests only
    .\run_tests.ps1 -Isolation    # multi-tenant isolation tests
    .\run_tests.ps1 -Pipeline     # pipeline tests only (slow, uses AI)
#>

param(
    [switch]$All,
    [switch]$Unit,
    [switch]$Auth,
    [switch]$Isolation,
    [switch]$Pipeline
)

$python = "D:/code/ats_backend/.venv/Scripts/python.exe"
$pytest  = "$python -m pytest"

# Check server is up (skip for unit-only run)
if (-not $Unit) {
    try {
        $health = Invoke-WebRequest -Uri "http://localhost:8001/api/health" `
                                    -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
        Write-Host "Server OK (200)" -ForegroundColor Green
    } catch {
        Write-Host "ERROR: Server not reachable at http://localhost:8001" -ForegroundColor Red
        Write-Host "Start it with:  uvicorn main:app --reload --port 8001" -ForegroundColor Yellow
        exit 1
    }
}

# Determine which tests to run
if ($Unit) {
    Write-Host "`n=== UNIT TESTS (no server) ===" -ForegroundColor Cyan
    Invoke-Expression "$pytest tests/test_unit_scoring.py -v"
}
elseif ($Auth) {
    Write-Host "`n=== AUTH TESTS ===" -ForegroundColor Cyan
    Invoke-Expression "$pytest tests/test_auth.py -v"
}
elseif ($Isolation) {
    Write-Host "`n=== TENANT ISOLATION TESTS ===" -ForegroundColor Cyan
    Invoke-Expression "$pytest tests/test_isolation.py -v"
}
elseif ($Pipeline) {
    Write-Host "`n=== END-TO-END PIPELINE TESTS (Vertex AI calls) ===" -ForegroundColor Yellow
    Invoke-Expression "$pytest tests/test_pipeline.py -v"
}
elseif ($All) {
    Write-Host "`n=== FULL SUITE (including Vertex AI pipeline tests) ===" -ForegroundColor Cyan
    Invoke-Expression "$pytest tests/ -v"
}
else {
    # Default: everything except the expensive pipeline tests
    Write-Host "`n=== FAST SUITE (unit + auth + isolation) ===" -ForegroundColor Cyan
    Invoke-Expression "$pytest tests/test_unit_scoring.py tests/test_auth.py tests/test_isolation.py -v"
}
