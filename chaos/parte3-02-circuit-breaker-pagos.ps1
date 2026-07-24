param(
    [ValidateSet(
        "activar",
        "restaurar",
        "estado"
    )]
    [string]$Accion = "estado"
)

$ErrorActionPreference = "Stop"

$namespace = "tickets"


function Mostrar-Estado {

    Write-Host `
        "`nConfiguración de Pagos:" `
        -ForegroundColor Yellow

    kubectl set env `
        deployment/payments `
        -n $namespace `
        --list


    Write-Host `
        "`nConfiguración de Reservas:" `
        -ForegroundColor Yellow

    kubectl set env `
        deployment/reservations `
        -n $namespace `
        --list |
        Select-String "PAYMENT_"


    Write-Host `
        "`nPods de Pagos y Reservas:" `
        -ForegroundColor Yellow

    kubectl get pods `
        -n $namespace `
        -l "app in (payments,reservations)" `
        -o wide
}


Write-Host `
    "==============================================" `
    -ForegroundColor Cyan

Write-Host `
    " PARTE III - CIRCUIT BREAKER DE PAGOS" `
    -ForegroundColor Cyan

Write-Host `
    "==============================================" `
    -ForegroundColor Cyan


switch ($Accion) {

    "activar" {

        Write-Host `
            "`nConfigurando Pagos con 20 segundos de latencia..." `
            -ForegroundColor Yellow

        kubectl set env `
            deployment/payments `
            -n $namespace `
            MIN_DELAY_MS=20000 `
            MAX_DELAY_MS=20000 `
            FAILURE_RATE=0

        if ($LASTEXITCODE -ne 0) {
            throw "No se pudo configurar el Servicio de Pagos."
        }


        kubectl rollout status `
            deployment/payments `
            -n $namespace `
            --timeout=180s

        if ($LASTEXITCODE -ne 0) {
            throw "El Deployment de Pagos no quedó disponible."
        }


        Mostrar-Estado


        Write-Host `
            "`nFALLO ACTIVADO." `
            -ForegroundColor Green

        Write-Host `
            "Pagos tardará 20 segundos por solicitud." `
            -ForegroundColor Green

        Write-Host `
            "Reservas esperará solamente 3 segundos." `
            -ForegroundColor Green

        Write-Host `
            "Dos timeouts consecutivos abrirán el Circuit Breaker." `
            -ForegroundColor Green
    }


    "restaurar" {

        Write-Host `
            "`nRestaurando la configuración normal de Pagos..." `
            -ForegroundColor Yellow

        kubectl set env `
            deployment/payments `
            -n $namespace `
            MIN_DELAY_MS=500 `
            MAX_DELAY_MS=2500 `
            FAILURE_RATE=0.15

        if ($LASTEXITCODE -ne 0) {
            throw "No se pudo restaurar el Servicio de Pagos."
        }


        kubectl rollout status `
            deployment/payments `
            -n $namespace `
            --timeout=180s

        if ($LASTEXITCODE -ne 0) {
            throw "El Deployment de Pagos no quedó disponible."
        }


        Write-Host `
            "`nReiniciando Reservas para cerrar el Circuit Breaker..." `
            -ForegroundColor Yellow

        kubectl rollout restart `
            deployment/reservations `
            -n $namespace

        if ($LASTEXITCODE -ne 0) {
            throw "No se pudo reiniciar Reservas."
        }


        kubectl rollout status `
            deployment/reservations `
            -n $namespace `
            --timeout=180s

        if ($LASTEXITCODE -ne 0) {
            throw "Reservas no quedó disponible."
        }


        Mostrar-Estado


        Write-Host `
            "`nSISTEMA RESTAURADO." `
            -ForegroundColor Green
    }


    "estado" {
        Mostrar-Estado
    }
}
