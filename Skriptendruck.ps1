#Requires -Version 5.1
<#
.SYNOPSIS
    Skriptendruck - Druckaufträge verarbeiten
.DESCRIPTION
    Startet die Verarbeitung der Druckaufträge.
    Einfach per Doppelklick oder Rechtsklick > "Mit PowerShell ausführen" starten.
#>

# UTF-8 Ausgabe
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# Ins Verzeichnis des Skripts wechseln (dort liegt pyproject.toml)
Set-Location -Path $PSScriptRoot

Write-Host ""
Write-Host "  ╔══════════════════════════════════════════╗" -ForegroundColor Blue
Write-Host "  ║   Skriptendruck - Fachschaft MB          ║" -ForegroundColor Blue
Write-Host "  ║   Druckaufträge verarbeiten               ║" -ForegroundColor Blue
Write-Host "  ╚══════════════════════════════════════════╝" -ForegroundColor Blue
Write-Host ""

# Poetry prüfen
try {
    $poetryVersion = poetry --version 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Poetry nicht gefunden" }
} catch {
    Write-Host "[FEHLER] Poetry wurde nicht gefunden!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Bitte zuerst einrichten:" -ForegroundColor Yellow
    Write-Host "  1. Python installieren: https://www.python.org/downloads/"
    Write-Host "  2. Poetry installieren: pip install poetry"
    Write-Host "  3. Skriptendruck_Setup.ps1 ausführen"
    Write-Host ""
    Read-Host "Enter zum Beenden"
    exit 1
}

# Verarbeitung starten
Write-Host "Starte Verarbeitung..." -ForegroundColor Cyan
Write-Host ""

poetry run skriptendruck process
$exitCode = $LASTEXITCODE

Write-Host ""
if ($exitCode -eq 0) {
    Write-Host "Verarbeitung abgeschlossen." -ForegroundColor Green
} else {
    Write-Host "Verarbeitung mit Fehlern beendet (Code: $exitCode)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Fenster schliesst sich in 10 Sekunden" -ForegroundColor DarkGray
Start-Sleep -Seconds 10
