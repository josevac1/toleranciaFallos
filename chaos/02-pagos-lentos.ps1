param(
    [ValidateSet("activar", "restaurar", "estado")]
    [string]$Accion = "estado"
)

$ErrorActionPreference = "Stop"

$namespace = "tickets"
$deployment = "payments"

function Mostrar-Estado {
    Write-Host "`nEstado del Deployment de Pagos:" -ForegroundColor Yellow

    kubectl get deployment $deployment `
        -n $namespace

    Write-Host "`nPod de Pagos:" -ForegroundColor Yellow

    kubectl get pods `
        -n $namespace `
        -l app=payments `
        -o wide

    Write-Host "`nVariables actuales:" -ForegroundColor Yellow

    kubectl set env `
        deployment/$deployment `
        -n $namespace `
        --list
}

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host " FALLO 2: PASARELA DE PAGOS LENTA" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan

switch ($Accion) {

    "activar" {

        Write-Host "`n1. Configurando una latencia fija de 20 segundos..." `
            -ForegroundColor Yellow

        kubectl set env `
            deployment/$deployment `
            -n $namespace `
            MIN_DELAY_MS=20000 `
            MAX_DELAY_MS=20000 `
            FAILURE_RATE=0

        if ($LASTEXITCODE -ne 0) {
            Write-Host "No se pudo modificar el Deployment." `
                -ForegroundColor Red
            exit 1
        }

        Write-Host "`n2. Esperando el nuevo pod..." `
            -ForegroundColor Yellow

        kubectl rollout status `
            deployment/$deployment `
            -n $namespace `
            --timeout=180s

        if ($LASTEXITCODE -ne 0) {
            Write-Host "El nuevo pod no estuvo disponible a tiempo." `
                -ForegroundColor Red
            exit 1
        }

        Mostrar-Estado

        Write-Host "`nFALLO ACTIVADO:" -ForegroundColor Green
        Write-Host "Pagos tardara 20 segundos por solicitud." `
            -ForegroundColor Green
        Write-Host "La probabilidad de fallo aleatorio fue desactivada." `
            -ForegroundColor Green
    }

    "restaurar" {

        Write-Host "`n1. Restaurando la configuracion normal..." `
            -ForegroundColor Yellow

        kubectl set env `
            deployment/$deployment `
            -n $namespace `
            MIN_DELAY_MS=500 `
            MAX_DELAY_MS=2500 `
            FAILURE_RATE=0.15

        if ($LASTEXITCODE -ne 0) {
            Write-Host "No se pudo restaurar el Deployment." `
                -ForegroundColor Red
            exit 1
        }

        Write-Host "`n2. Esperando la restauracion..." `
            -ForegroundColor Yellow

        kubectl rollout status `
            deployment/$deployment `
            -n $namespace `
            --timeout=180s

        if ($LASTEXITCODE -ne 0) {
            Write-Host "El Deployment no se restauro a tiempo." `
                -ForegroundColor Red
            exit 1
        }

        Mostrar-Estado

        Write-Host "`nSISTEMA RESTAURADO:" -ForegroundColor Green
        Write-Host "Latencia: entre 500 y 2500 ms." `
            -ForegroundColor Green
        Write-Host "Probabilidad de fallo: 15 %." `
            -ForegroundColor Green
    }

    "estado" {
        Mostrar-Estado
    }
}

Write-Host "`n=============================================" -ForegroundColor Cyan
Write-Host " FIN DEL SCRIPT" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan