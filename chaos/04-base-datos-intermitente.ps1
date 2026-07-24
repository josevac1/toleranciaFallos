param(
    [ValidateSet("activar", "restaurar", "estado")]
    [string]$Accion = "estado"
)

$ErrorActionPreference = "Stop"

$namespace = "tickets"
$service = "postgres-service"

function Obtener-Direcciones {

    $resultado = kubectl get endpointslice `
        -n $namespace `
        -l "kubernetes.io/service-name=$service" `
        -o jsonpath="{.items[*].endpoints[*].addresses[*]}"

    return "$resultado".Trim()
}

function Mostrar-Estado {

    Write-Host "`nService PostgreSQL:" -ForegroundColor Yellow

    kubectl get service $service `
        -n $namespace `
        -o wide

    Write-Host "`nSelector actual:" -ForegroundColor Yellow

    $selector = kubectl get service $service `
        -n $namespace `
        -o jsonpath="{.spec.selector.app}"

    Write-Host "app=$selector"

    Write-Host "`nEndpointSlices:" -ForegroundColor Yellow

    kubectl get endpointslice `
        -n $namespace `
        -l "kubernetes.io/service-name=$service" `
        -o wide

    Write-Host "`nDirecciones disponibles:" -ForegroundColor Yellow

    $direcciones = Obtener-Direcciones

    if ([string]::IsNullOrWhiteSpace($direcciones)) {
        Write-Host "No existen endpoints disponibles." `
            -ForegroundColor Red
    }
    else {
        Write-Host $direcciones -ForegroundColor Green
    }

    Write-Host "`nPod de PostgreSQL:" -ForegroundColor Yellow

    kubectl get pods `
        -n $namespace `
        -l app=postgres `
        -o wide
}

Write-Host "==============================================" `
    -ForegroundColor Cyan

Write-Host " FALLO 4: BASE DE DATOS INTERMITENTE" `
    -ForegroundColor Cyan

Write-Host "==============================================" `
    -ForegroundColor Cyan

switch ($Accion) {

    "activar" {

        Write-Host "`n1. Cambiando el selector de postgres-service..." `
            -ForegroundColor Yellow

        kubectl set selector `
            service/$service `
            app=postgres-disabled `
            -n $namespace

        if ($LASTEXITCODE -ne 0) {
            Write-Host "No se pudo modificar el Service." `
                -ForegroundColor Red
            exit 1
        }

        Write-Host "`n2. Esperando que desaparezcan los endpoints..." `
            -ForegroundColor Yellow

        $sinEndpoints = $false

        for ($intento = 1; $intento -le 20; $intento++) {

            $direcciones = Obtener-Direcciones

            if ([string]::IsNullOrWhiteSpace($direcciones)) {
                $sinEndpoints = $true
                break
            }

            Start-Sleep -Seconds 1
        }

        Mostrar-Estado

        if ($sinEndpoints) {
            Write-Host "`nFALLO ACTIVADO:" -ForegroundColor Green
            Write-Host `
                "PostgreSQL sigue encendido, pero su Service no tiene endpoints." `
                -ForegroundColor Green
        }
        else {
            Write-Host "`nLos endpoints no desaparecieron a tiempo." `
                -ForegroundColor Red
            exit 1
        }
    }

    "restaurar" {

        Write-Host "`n1. Restaurando el selector correcto..." `
            -ForegroundColor Yellow

        kubectl set selector `
            service/$service `
            app=postgres `
            -n $namespace

        if ($LASTEXITCODE -ne 0) {
            Write-Host "No se pudo restaurar el Service." `
                -ForegroundColor Red
            exit 1
        }

        Write-Host "`n2. Esperando que PostgreSQL recupere su endpoint..." `
            -ForegroundColor Yellow

        $recuperado = $false

        for ($intento = 1; $intento -le 30; $intento++) {

            $direcciones = Obtener-Direcciones

            if (-not [string]::IsNullOrWhiteSpace($direcciones)) {
                $recuperado = $true
                break
            }

            Start-Sleep -Seconds 1
        }

        Mostrar-Estado

        if ($recuperado) {
            Write-Host "`nSISTEMA RESTAURADO:" -ForegroundColor Green
            Write-Host `
                "postgres-service vuelve a dirigir trafico hacia PostgreSQL." `
                -ForegroundColor Green
        }
        else {
            Write-Host "`nPostgreSQL no recupero su endpoint a tiempo." `
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