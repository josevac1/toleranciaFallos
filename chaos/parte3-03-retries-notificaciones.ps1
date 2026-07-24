param(
    [ValidateSet(
        "activar",
        "probar",
        "restaurar",
        "estado"
    )]
    [string]$Accion = "estado",

    [int]$Puerto = 18000
)

$ErrorActionPreference = "Stop"

$namespace = "tickets"

$evidencias = Join-Path $PSScriptRoot "..\evidencias"

New-Item `
    -ItemType Directory `
    -Force `
    -Path $evidencias |
    Out-Null


# ============================================================
# FUNCIONES
# ============================================================

function Get-CantidadPods {

    param(
        [Parameter(Mandatory = $true)]
        [string]$Selector
    )

    $podsJson = kubectl get pods `
        -n $namespace `
        -l $Selector `
        -o json `
        2>$null

    if ($LASTEXITCODE -ne 0) {
        throw "No se pudieron consultar los pods de Kubernetes."
    }

    $podsTexto = $podsJson | Out-String
    $listaPods = $podsTexto | ConvertFrom-Json

    return @($listaPods.items).Count
}


function Mostrar-Estado {

    Write-Host ""
    Write-Host "Deployments:" -ForegroundColor Yellow

    kubectl get deployment `
        payments `
        notifications `
        reservations `
        -n $namespace

    Write-Host ""
    Write-Host "Pods de Notificaciones:" -ForegroundColor Yellow

    $cantidadPods = Get-CantidadPods `
        -Selector "app=notifications"

    Write-Host "Cantidad de pods: $cantidadPods"

    Write-Host ""
    Write-Host "Configuracion de Pagos:" -ForegroundColor Yellow

    kubectl set env `
        deployment/payments `
        -n $namespace `
        --list |
        Select-String `
            -Pattern "MIN_DELAY_MS|MAX_DELAY_MS|FAILURE_RATE"

    Write-Host ""
    Write-Host "Configuracion de Retries:" -ForegroundColor Yellow

    kubectl set env `
        deployment/reservations `
        -n $namespace `
        --list |
        Select-String `
            -Pattern "NOTIFICATION_"
}


function Esperar-Deployment {

    param(
        [Parameter(Mandatory = $true)]
        [string]$Deployment
    )

    kubectl rollout status `
        "deployment/$Deployment" `
        -n $namespace `
        --timeout=180s

    if ($LASTEXITCODE -ne 0) {
        throw "El Deployment $Deployment no quedo disponible."
    }
}


# ============================================================
# ENCABEZADO
# ============================================================

Write-Host "================================================" `
    -ForegroundColor Cyan

Write-Host " PARTE III - RETRIES Y FALLBACK DE NOTIFICACIONES" `
    -ForegroundColor Cyan

Write-Host "================================================" `
    -ForegroundColor Cyan


# ============================================================
# ACCIONES
# ============================================================

switch ($Accion) {

    "activar" {

        Write-Host ""
        Write-Host `
            "1. Desactivando fallos aleatorios de Pagos..." `
            -ForegroundColor Yellow

        kubectl set env `
            deployment/payments `
            -n $namespace `
            MIN_DELAY_MS=100 `
            MAX_DELAY_MS=200 `
            FAILURE_RATE=0

        if ($LASTEXITCODE -ne 0) {
            throw "No se pudo configurar el Servicio de Pagos."
        }

        Esperar-Deployment `
            -Deployment "payments"


        Write-Host ""
        Write-Host `
            "2. Escalando Notificaciones a cero replicas..." `
            -ForegroundColor Yellow

        kubectl scale `
            deployment/notifications `
            -n $namespace `
            --replicas=0

        if ($LASTEXITCODE -ne 0) {
            throw "No se pudo detener el Servicio de Notificaciones."
        }


        Write-Host ""
        Write-Host `
            "3. Esperando que desaparezcan los pods..." `
            -ForegroundColor Yellow

        $limite = (Get-Date).AddSeconds(120)
        $cantidadPods = -1

        do {

            $cantidadPods = Get-CantidadPods `
                -Selector "app=notifications"

            Write-Host "Pods restantes: $cantidadPods"

            if ($cantidadPods -eq 0) {
                break
            }

            Start-Sleep -Seconds 2

        } while ((Get-Date) -lt $limite)


        if ($cantidadPods -ne 0) {
            throw "Los pods de Notificaciones no desaparecieron a tiempo."
        }


        Write-Host ""
        Write-Host `
            "4. Reiniciando Reservas para iniciar una prueba limpia..." `
            -ForegroundColor Yellow

        kubectl rollout restart `
            deployment/reservations `
            -n $namespace

        if ($LASTEXITCODE -ne 0) {
            throw "No se pudo reiniciar el Servicio de Reservas."
        }

        Esperar-Deployment `
            -Deployment "reservations"


        Mostrar-Estado


        Write-Host ""
        Write-Host "FALLO ACTIVADO." -ForegroundColor Green
        Write-Host `
            "Notificaciones no tiene pods disponibles." `
            -ForegroundColor Green

        Write-Host `
            "Reservas realizara tres intentos y aplicara fallback." `
            -ForegroundColor Green
    }


    "probar" {

        Write-Host ""
        Write-Host `
            "1. Verificando el port-forward del Gateway..." `
            -ForegroundColor Yellow

        $puertoDisponible = Test-NetConnection `
            -ComputerName "127.0.0.1" `
            -Port $Puerto `
            -InformationLevel Quiet `
            -WarningAction SilentlyContinue

        if (-not $puertoDisponible) {
            throw "No existe un port-forward disponible en el puerto $Puerto. Ejecuta kubectl port-forward -n tickets service/gateway-service ${Puerto}:8000"
        }


        $marcaTiempo = Get-Date `
            -Format "yyyyMMddHHmmss"

        $userId = "usuario-retry-$marcaTiempo"
        $email = "retry-$marcaTiempo@example.com"

        $body = @{
            user_id  = $userId
            event_id = 1
            email    = $email
            amount   = 25.50
        } | ConvertTo-Json


        Write-Host ""
        Write-Host `
            "2. Ejecutando una reserva..." `
            -ForegroundColor Yellow

        Write-Host "Usuario: $userId" `
            -ForegroundColor Cyan

        Write-Host "Correo: $email" `
            -ForegroundColor Cyan


        $inicio = Get-Date

        try {

            $respuesta = Invoke-RestMethod `
                -Uri "http://127.0.0.1:${Puerto}/api/reservations" `
                -Method Post `
                -ContentType "application/json" `
                -Body $body

        }
        catch {

            Write-Host ""
            Write-Host `
                "La solicitud devolvio un error:" `
                -ForegroundColor Red

            if ($_.ErrorDetails.Message) {
                Write-Host $_.ErrorDetails.Message
            }
            else {
                Write-Host $_.Exception.Message
            }

            throw
        }


        $fin = Get-Date

        $duracion = (
            $fin - $inicio
        ).TotalSeconds


        Write-Host ""
        Write-Host "3. Resultado:" `
            -ForegroundColor Yellow

        $respuesta |
        Format-List


        Write-Host (
            "Duracion total: {0} segundos" -f `
            [math]::Round($duracion, 3)
        ) -ForegroundColor Cyan


        $archivoResultado = Join-Path `
            $evidencias `
            "parte3-m3-resultado-$marcaTiempo.json"

        $respuesta |
        ConvertTo-Json -Depth 10 |
        Set-Content `
            -Path $archivoResultado `
            -Encoding UTF8


        Write-Host ""
        Write-Host "Resultado guardado en:" `
            -ForegroundColor Green

        Write-Host $archivoResultado


        Write-Host ""
        Write-Host "4. Logs de los reintentos:" `
            -ForegroundColor Yellow

        $logsReservas = kubectl logs `
            -n $namespace `
            -l app=reservations `
            --tail=250 `
            --prefix=true `
            2>&1

        $logsFiltrados = $logsReservas |
            Select-String `
                -Pattern "notification_retry|notification_fallback"

        if ($logsFiltrados) {
            $logsFiltrados
        }
        else {
            Write-Host `
                "No se encontraron logs de retry en esta consulta." `
                -ForegroundColor Yellow

            Write-Host `
                "Consulta manualmente cada pod de Reservas." `
                -ForegroundColor Yellow
        }


        Write-Host ""
        Write-Host "5. Reserva guardada en PostgreSQL:" `
            -ForegroundColor Yellow

        $postgresPod = kubectl get pod `
            -n $namespace `
            -l app=postgres `
            -o jsonpath="{.items[0].metadata.name}"

        if ([string]::IsNullOrWhiteSpace($postgresPod)) {
            throw "No se encontro el pod de PostgreSQL."
        }

        $sql = "SELECT user_id, event_id, status, created_at FROM reservations WHERE user_id = '$userId';"

        kubectl exec `
            -n $namespace `
            $postgresPod `
            -- psql `
            -U tickets_user `
            -d tickets_db `
            -c $sql


        Write-Host ""
        Write-Host "PRUEBA FINALIZADA." `
            -ForegroundColor Green

        Write-Host "Resultado esperado:" `
            -ForegroundColor Green

        Write-Host `
            "status: CONFIRMED_NOTIFICATION_PENDING"

        Write-Host `
            "notification_sent: False"

        Write-Host `
            "notification_attempts: 3"

        Write-Host `
            "notification_fallback_used: True"
    }


    "restaurar" {

        Write-Host ""
        Write-Host `
            "1. Restaurando Notificaciones..." `
            -ForegroundColor Yellow

        kubectl scale `
            deployment/notifications `
            -n $namespace `
            --replicas=1

        if ($LASTEXITCODE -ne 0) {
            throw "No se pudo restaurar Notificaciones."
        }

        Esperar-Deployment `
            -Deployment "notifications"


        Write-Host ""
        Write-Host `
            "2. Restaurando la configuracion normal de Pagos..." `
            -ForegroundColor Yellow

        kubectl set env `
            deployment/payments `
            -n $namespace `
            MIN_DELAY_MS=500 `
            MAX_DELAY_MS=2500 `
            FAILURE_RATE=0.15

        if ($LASTEXITCODE -ne 0) {
            throw "No se pudo restaurar Pagos."
        }

        Esperar-Deployment `
            -Deployment "payments"


        Write-Host ""
        Write-Host `
            "3. Reiniciando Reservas..." `
            -ForegroundColor Yellow

        kubectl rollout restart `
            deployment/reservations `
            -n $namespace

        if ($LASTEXITCODE -ne 0) {
            throw "No se pudo reiniciar Reservas."
        }

        Esperar-Deployment `
            -Deployment "reservations"


        Mostrar-Estado


        Write-Host ""
        Write-Host "SISTEMA RESTAURADO." `
            -ForegroundColor Green
    }


    "estado" {

        Mostrar-Estado
    }
}