param(
    [ValidateSet("activar", "restaurar", "estado")]
    [string]$Accion = "estado"
)

$ErrorActionPreference = "Stop"

$namespace = "tickets"
$deployment = "notifications"
$service = "notifications-service"

function Obtener-Endpoints {

    $resultado = kubectl get endpointslice `
        -n $namespace `
        -l "kubernetes.io/service-name=$service" `
        -o jsonpath="{.items[*].endpoints[*].addresses[*]}" `
        2>$null

    return "$resultado".Trim()
}

function Mostrar-Estado {

    Write-Host "`nDeployment de Notificaciones:" `
        -ForegroundColor Yellow

    kubectl get deployment $deployment `
        -n $namespace
    Write-Host "`nPods de Notificaciones:" `
        -ForegroundColor Yellow

    $podsJson = kubectl get pods `
        -n $namespace `
        -l app=notifications `
        -o json `
        2>$null

    $listaPods = $podsJson | ConvertFrom-Json
    $cantidadPods = @($listaPods.items).Count

    if ($cantidadPods -eq 0) {
        Write-Host "No existen pods de Notificaciones." `
            -ForegroundColor Red
    }
    else {
        kubectl get pods `
            -n $namespace `
            -l app=notifications `
            -o wide
    }


    Write-Host "`nService:" `
        -ForegroundColor Yellow

    kubectl get service $service `
        -n $namespace `
        -o wide

    Write-Host "`nEndpointSlices:" `
        -ForegroundColor Yellow

    kubectl get endpointslice `
        -n $namespace `
        -l "kubernetes.io/service-name=$service" `
        -o wide

    $endpoints = Obtener-Endpoints

    Write-Host "`nDirecciones disponibles:" `
        -ForegroundColor Yellow

    if ([string]::IsNullOrWhiteSpace($endpoints)) {
        Write-Host "No existen endpoints disponibles." `
            -ForegroundColor Red
    }
    else {
        Write-Host $endpoints `
            -ForegroundColor Green
    }
}

Write-Host "==============================================" `
    -ForegroundColor Cyan

Write-Host " FALLO 5: EL CORREO PERDIDO" `
    -ForegroundColor Cyan

Write-Host "==============================================" `
    -ForegroundColor Cyan

switch ($Accion) {

    "activar" {

        Write-Host "`n1. Deteniendo Notificaciones..." `
            -ForegroundColor Yellow

        kubectl scale deployment/$deployment `
            -n $namespace `
            --replicas=0

        if ($LASTEXITCODE -ne 0) {
            Write-Host "No se pudo escalar Notificaciones." `
                -ForegroundColor Red
            exit 1
        }

        Write-Host "`n2. Esperando que desaparezcan los pods..." `
            -ForegroundColor Yellow

        $detenido = $false

        for ($intento = 1; $intento -le 30; $intento++) {

            $cantidadPods = kubectl get pods `
                -n $namespace `
                -l app=notifications `
                --no-headers `
                2>$null |
                Measure-Object |
                Select-Object -ExpandProperty Count

            if ($cantidadPods -eq 0) {
                $detenido = $true
                break
            }

            Start-Sleep -Seconds 1
        }

        Mostrar-Estado

        if ($detenido) {
            Write-Host "`nFALLO ACTIVADO:" `
                -ForegroundColor Green

            Write-Host `
                "Notificaciones esta fuera de servicio y no tiene pods." `
                -ForegroundColor Green
        }
        else {
            Write-Host `
                "`nLos pods de Notificaciones no desaparecieron a tiempo." `
                -ForegroundColor Red

            exit 1
        }
    }

    "restaurar" {

        Write-Host "`n1. Restaurando Notificaciones..." `
            -ForegroundColor Yellow

        kubectl scale deployment/$deployment `
            -n $namespace `
            --replicas=1

        if ($LASTEXITCODE -ne 0) {
            Write-Host "No se pudo restaurar Notificaciones." `
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
            Write-Host `
                "Notificaciones no estuvo disponible a tiempo." `
                -ForegroundColor Red

            exit 1
        }

        $recuperado = $false

        for ($intento = 1; $intento -le 30; $intento++) {

            $endpoints = Obtener-Endpoints

            if (-not [string]::IsNullOrWhiteSpace($endpoints)) {
                $recuperado = $true
                break
            }

            Start-Sleep -Seconds 1
        }

        Mostrar-Estado

        if ($recuperado) {
            Write-Host "`nSISTEMA RESTAURADO:" `
                -ForegroundColor Green

            Write-Host `
                "Notificaciones vuelve a tener un pod y un endpoint." `
                -ForegroundColor Green
        }
        else {
            Write-Host `
                "`nEl Service no recupero su endpoint a tiempo." `
                -ForegroundColor Red

            exit 1
        }
    }

    "estado" {
        Mostrar-Estado
    }
}

Write-Host "`n==============================================" `
    -ForegroundColor Cyan

Write-Host " FIN DEL SCRIPT" `
    -ForegroundColor Cyan

Write-Host "==============================================" `
    -ForegroundColor Cyan