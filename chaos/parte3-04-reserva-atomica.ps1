param(
    [ValidateSet("preparar", "probar", "restaurar", "estado")]
    [string]$Accion = "estado",

    [int]$Puerto = 18000
)

$ErrorActionPreference = "Stop"

$Namespace = "tickets"
$EstadoArchivo = Join-Path $PSScriptRoot "estado-parte3-m4.json"
$Evidencias = Join-Path $PSScriptRoot "..\evidencias"

New-Item -ItemType Directory -Force -Path $Evidencias | Out-Null


# ============================================================
# FUNCIONES AUXILIARES
# ============================================================

function Wait-Deployment {

    param(
        [Parameter(Mandatory = $true)]
        [string]$Nombre
    )

    Write-Host "Esperando Deployment: $Nombre..." -ForegroundColor Cyan

    & kubectl rollout status `
        "deployment/$Nombre" `
        -n $Namespace `
        --timeout=180s

    if ($LASTEXITCODE -ne 0) {
        throw "El Deployment $Nombre no quedo disponible."
    }
}


function Get-PostgresPod {

    $Pod = & kubectl get pods `
        -n $Namespace `
        -l "app=postgres" `
        -o "jsonpath={.items[0].metadata.name}"

    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo consultar el pod de PostgreSQL."
    }

    if ([string]::IsNullOrWhiteSpace($Pod)) {
        throw "No se encontro el pod de PostgreSQL."
    }

    return $Pod.Trim()
}


function Invoke-DatabaseCommand {

    param(
        [Parameter(Mandatory = $true)]
        [string]$Sql
    )

    $PostgresPod = Get-PostgresPod

    & kubectl exec `
        -n $Namespace `
        $PostgresPod `
        -- psql `
        -U tickets_user `
        -d tickets_db `
        -c $Sql

    if ($LASTEXITCODE -ne 0) {
        throw "La instruccion SQL fallo: $Sql"
    }
}


function Get-DatabaseValue {

    param(
        [Parameter(Mandatory = $true)]
        [string]$Sql
    )

    $PostgresPod = Get-PostgresPod

    $Resultado = & kubectl exec `
        -n $Namespace `
        $PostgresPod `
        -- psql `
        -U tickets_user `
        -d tickets_db `
        -t `
        -A `
        -c $Sql

    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo obtener el valor desde PostgreSQL."
    }

    return (($Resultado | Out-String).Trim())
}


function Show-SystemState {

    Write-Host ""
    Write-Host "Deployments:" -ForegroundColor Yellow

    & kubectl get deployments -n $Namespace

    Write-Host ""
    Write-Host "Pods de Inventario:" -ForegroundColor Yellow

    & kubectl get pods `
        -n $Namespace `
        -l "app=inventory" `
        -o wide

    Write-Host ""
    Write-Host "Configuracion de Inventario:" -ForegroundColor Yellow

    & kubectl set env `
        deployment/inventory `
        -n $Namespace `
        --list |
        Select-String -Pattern "RACE_DELAY_MS"

    Write-Host ""
    Write-Host "Inventario actual:" -ForegroundColor Yellow

    Invoke-DatabaseCommand `
        -Sql "SELECT event_id, available_seats, updated_at FROM inventory WHERE event_id = 1;"
}


function Test-GatewayPort {

    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    $Disponible = Test-NetConnection `
        -ComputerName "127.0.0.1" `
        -Port $Port `
        -InformationLevel Quiet `
        -WarningAction SilentlyContinue

    return $Disponible
}


# ============================================================
# ENCABEZADO
# ============================================================

Write-Host "================================================" -ForegroundColor Cyan
Write-Host " PARTE III - RESERVA ATOMICA DE INVENTARIO" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan


# ============================================================
# ACCIONES
# ============================================================

switch ($Accion) {

    "preparar" {

        Write-Host ""
        Write-Host "1. Guardando el inventario original..." `
            -ForegroundColor Yellow

        if (-not (Test-Path $EstadoArchivo)) {

            $InventarioOriginal = Get-DatabaseValue `
                -Sql "SELECT available_seats FROM inventory WHERE event_id = 1;"

            if ($InventarioOriginal -notmatch "^\d+$") {
                throw "No se pudo determinar el inventario original."
            }

            $Estado = @{
                event_id        = 1
                available_seats = [int]$InventarioOriginal
                saved_at        = (Get-Date).ToString("o")
            }

            $Estado |
                ConvertTo-Json |
                Set-Content `
                    -Path $EstadoArchivo `
                    -Encoding UTF8

            Write-Host `
                "Inventario original guardado: $InventarioOriginal" `
                -ForegroundColor Green
        }
        else {
            Write-Host `
                "Ya existe un inventario original guardado." `
                -ForegroundColor Yellow
        }


        Write-Host ""
        Write-Host "2. Restaurando Notificaciones..." `
            -ForegroundColor Yellow

        & kubectl scale `
            deployment/notifications `
            -n $Namespace `
            --replicas=1

        if ($LASTEXITCODE -ne 0) {
            throw "No se pudo restaurar Notificaciones."
        }

        Wait-Deployment -Nombre "notifications"


        Write-Host ""
        Write-Host "3. Desactivando fallos aleatorios de Pagos..." `
            -ForegroundColor Yellow

        & kubectl set env `
            deployment/payments `
            -n $Namespace `
            MIN_DELAY_MS=100 `
            MAX_DELAY_MS=100 `
            FAILURE_RATE=0

        if ($LASTEXITCODE -ne 0) {
            throw "No se pudo configurar Pagos."
        }

        Wait-Deployment -Nombre "payments"


        Write-Host ""
        Write-Host "4. Desactivando fallos de Notificaciones..." `
            -ForegroundColor Yellow

        & kubectl set env `
            deployment/notifications `
            -n $Namespace `
            MIN_DELAY_MS=50 `
            MAX_DELAY_MS=50 `
            FAILURE_RATE=0

        if ($LASTEXITCODE -ne 0) {
            throw "No se pudo configurar Notificaciones."
        }

        Wait-Deployment -Nombre "notifications"


        Write-Host ""
        Write-Host "5. Configurando la ventana de concurrencia..." `
            -ForegroundColor Yellow

        & kubectl set env `
            deployment/inventory `
            -n $Namespace `
            RACE_DELAY_MS=1500

        if ($LASTEXITCODE -ne 0) {
            throw "No se pudo configurar Inventario."
        }

        Wait-Deployment -Nombre "inventory"


        Write-Host ""
        Write-Host "6. Reiniciando Reservas..." `
            -ForegroundColor Yellow

        & kubectl rollout restart `
            deployment/reservations `
            -n $Namespace

        if ($LASTEXITCODE -ne 0) {
            throw "No se pudo reiniciar Reservas."
        }

        Wait-Deployment -Nombre "reservations"


        Write-Host ""
        Write-Host "7. Preparando exactamente un asiento..." `
            -ForegroundColor Yellow

        Invoke-DatabaseCommand `
            -Sql "DELETE FROM reservations WHERE user_id LIKE 'usuario-atomico-%';"

        Invoke-DatabaseCommand `
            -Sql "UPDATE inventory SET available_seats = 1, updated_at = CURRENT_TIMESTAMP WHERE event_id = 1;"


        Show-SystemState


        Write-Host ""
        Write-Host "EXPERIMENTO PREPARADO." -ForegroundColor Green
        Write-Host "Hay exactamente un asiento disponible." `
            -ForegroundColor Green
        Write-Host "Se enviaran dos compras simultaneas." `
            -ForegroundColor Green
    }


    "probar" {

        Write-Host ""
        Write-Host "1. Comprobando el port-forward del Gateway..." `
            -ForegroundColor Yellow

        $GatewayDisponible = Test-GatewayPort -Port $Puerto

        if (-not $GatewayDisponible) {
            throw "No existe un port-forward en el puerto $Puerto. Ejecuta: kubectl port-forward -n tickets service/gateway-service ${Puerto}:8000"
        }


        $RunId = Get-Date -Format "yyyyMMddHHmmss"

        Write-Host ""
        Write-Host "2. Restaurando un asiento antes de la prueba..." `
            -ForegroundColor Yellow

        Invoke-DatabaseCommand `
            -Sql "DELETE FROM reservations WHERE user_id LIKE 'usuario-atomico-$RunId-%';"

        Invoke-DatabaseCommand `
            -Sql "UPDATE inventory SET available_seats = 1, updated_at = CURRENT_TIMESTAMP WHERE event_id = 1;"


        Write-Host ""
        Write-Host "3. Preparando dos clientes concurrentes..." `
            -ForegroundColor Yellow

        $MomentoInicioUtc = [DateTime]::UtcNow.AddSeconds(6)
        $MomentoInicioTicks = $MomentoInicioUtc.Ticks

        Write-Host `
            "Las solicitudes se enviaran a las $($MomentoInicioUtc.ToLocalTime())" `
            -ForegroundColor Cyan


        $Jobs = 1..2 | ForEach-Object {

            $Numero = $_

            $Payload = @{
                user_id  = "usuario-atomico-$RunId-$Numero"
                event_id = 1
                email    = "atomico$Numero-$RunId@example.com"
                amount   = 25.50
            } | ConvertTo-Json -Compress


            Start-Job `
                -ScriptBlock {

                    param(
                        [int]$PuertoTrabajo,
                        [string]$Body,
                        [int]$NumeroSolicitud,
                        [long]$InicioTicks
                    )

                    while ([DateTime]::UtcNow.Ticks -lt $InicioTicks) {
                        Start-Sleep -Milliseconds 10
                    }

                    $Inicio = Get-Date

                    try {

                        $Respuesta = Invoke-RestMethod `
                            -Uri "http://127.0.0.1:$PuertoTrabajo/api/reservations" `
                            -Method Post `
                            -ContentType "application/json" `
                            -Body $Body

                        $Duracion = ((Get-Date) - $Inicio).TotalSeconds

                        [PSCustomObject]@{
                            solicitud     = $NumeroSolicitud
                            exitosa       = $true
                            http          = 200
                            estado        = $Respuesta.status
                            reservationId = $Respuesta.reservation_id
                            segundos      = [math]::Round($Duracion, 3)
                            error         = ""
                        }
                    }
                    catch {

                        $Duracion = ((Get-Date) - $Inicio).TotalSeconds
                        $HttpStatus = 0
                        $Estado = "ERROR"
                        $Detalle = $_.Exception.Message

                        if ($null -ne $_.Exception.Response) {
                            $HttpStatus = [int]$_.Exception.Response.StatusCode
                        }

                        if ($_.ErrorDetails.Message) {

                            $Detalle = $_.ErrorDetails.Message

                            try {
                                $ErrorJson = $_.ErrorDetails.Message |
                                    ConvertFrom-Json

                                if ($null -ne $ErrorJson.status) {
                                    $Estado = $ErrorJson.status
                                }

                                if ($null -ne $ErrorJson.detail) {
                                    $Detalle = $ErrorJson.detail
                                }
                            }
                            catch {
                                # Se conserva el mensaje original.
                            }
                        }

                        [PSCustomObject]@{
                            solicitud     = $NumeroSolicitud
                            exitosa       = $false
                            http          = $HttpStatus
                            estado        = $Estado
                            reservationId = ""
                            segundos      = [math]::Round($Duracion, 3)
                            error         = $Detalle
                        }
                    }

                } `
                -ArgumentList `
                    $Puerto, `
                    $Payload, `
                    $Numero, `
                    $MomentoInicioTicks
        }


        Write-Host ""
        Write-Host "4. Enviando dos compras simultaneas..." `
            -ForegroundColor Yellow

        $Jobs | Wait-Job | Out-Null
        $Resultados = $Jobs | Receive-Job
        $Jobs | Remove-Job


        Write-Host ""
        Write-Host "5. Resultados de las solicitudes:" `
            -ForegroundColor Yellow

        $Resultados |
            Sort-Object solicitud |
            Format-Table `
                solicitud, `
                exitosa, `
                http, `
                estado, `
                reservationId, `
                segundos, `
                error `
                -AutoSize


        $ArchivoResultado = Join-Path `
            $Evidencias `
            "parte3-m4-resultados-$RunId.json"

        $Resultados |
            ConvertTo-Json -Depth 10 |
            Set-Content `
                -Path $ArchivoResultado `
                -Encoding UTF8


        Write-Host ""
        Write-Host "6. Verificando PostgreSQL..." `
            -ForegroundColor Yellow

        $ReservasConfirmadas = Get-DatabaseValue `
            -Sql "SELECT COUNT(*) FROM reservations WHERE user_id LIKE 'usuario-atomico-$RunId-%' AND status LIKE 'CONFIRMED%';"

        $AsientosDisponibles = Get-DatabaseValue `
            -Sql "SELECT available_seats FROM inventory WHERE event_id = 1;"


        Write-Host `
            "Reservas confirmadas: $ReservasConfirmadas" `
            -ForegroundColor Cyan

        Write-Host `
            "Asientos disponibles: $AsientosDisponibles" `
            -ForegroundColor Cyan


        Write-Host ""
        Write-Host "Reservas registradas:" `
            -ForegroundColor Yellow

        Invoke-DatabaseCommand `
            -Sql "SELECT user_id, event_id, status, created_at FROM reservations WHERE user_id LIKE 'usuario-atomico-$RunId-%' ORDER BY created_at;"


        if (
            ($ReservasConfirmadas -eq "1") -and
            ($AsientosDisponibles -eq "0")
        ) {
            Write-Host ""
            Write-Host `
                "PRUEBA EXITOSA: CONDICION DE CARRERA CONTROLADA." `
                -ForegroundColor Green

            Write-Host `
                "Solo una compra obtuvo el ultimo asiento." `
                -ForegroundColor Green

            Write-Host `
                "La segunda solicitud fue rechazada de forma controlada." `
                -ForegroundColor Green
        }
        else {
            Write-Host ""
            Write-Host "RESULTADO INESPERADO." `
                -ForegroundColor Red

            Write-Host `
                "Debe existir una reserva confirmada y cero asientos." `
                -ForegroundColor Red
        }


        Write-Host ""
        Write-Host "Resultados guardados en:" `
            -ForegroundColor Green

        Write-Host $ArchivoResultado
    }


    "restaurar" {

        Write-Host ""
        Write-Host "1. Leyendo el inventario original..." `
            -ForegroundColor Yellow

        if (-not (Test-Path $EstadoArchivo)) {
            throw "No existe el archivo de estado original."
        }

        $Estado = Get-Content `
            -Path $EstadoArchivo `
            -Raw |
            ConvertFrom-Json

        $InventarioOriginal = [int]$Estado.available_seats


        Write-Host ""
        Write-Host "2. Restaurando Inventario..." `
            -ForegroundColor Yellow

        & kubectl set env `
            deployment/inventory `
            -n $Namespace `
            RACE_DELAY_MS=0

        if ($LASTEXITCODE -ne 0) {
            throw "No se pudo restaurar Inventario."
        }

        Wait-Deployment -Nombre "inventory"


        Write-Host ""
        Write-Host "3. Restaurando Pagos..." `
            -ForegroundColor Yellow

        & kubectl set env `
            deployment/payments `
            -n $Namespace `
            MIN_DELAY_MS=500 `
            MAX_DELAY_MS=2500 `
            FAILURE_RATE=0.15

        if ($LASTEXITCODE -ne 0) {
            throw "No se pudo restaurar Pagos."
        }

        Wait-Deployment -Nombre "payments"


        Write-Host ""
        Write-Host "4. Restaurando Notificaciones..." `
            -ForegroundColor Yellow

        & kubectl scale `
            deployment/notifications `
            -n $Namespace `
            --replicas=1

        if ($LASTEXITCODE -ne 0) {
            throw "No se pudo escalar Notificaciones."
        }

        & kubectl set env `
            deployment/notifications `
            -n $Namespace `
            MIN_DELAY_MS=200 `
            MAX_DELAY_MS=1200 `
            FAILURE_RATE=0.10

        if ($LASTEXITCODE -ne 0) {
            throw "No se pudo restaurar Notificaciones."
        }

        Wait-Deployment -Nombre "notifications"


        Write-Host ""
        Write-Host "5. Reiniciando Reservas..." `
            -ForegroundColor Yellow

        & kubectl rollout restart `
            deployment/reservations `
            -n $Namespace

        if ($LASTEXITCODE -ne 0) {
            throw "No se pudo reiniciar Reservas."
        }

        Wait-Deployment -Nombre "reservations"


        Write-Host ""
        Write-Host "6. Restaurando datos originales..." `
            -ForegroundColor Yellow

        Invoke-DatabaseCommand `
            -Sql "DELETE FROM reservations WHERE user_id LIKE 'usuario-atomico-%';"

        Invoke-DatabaseCommand `
            -Sql "UPDATE inventory SET available_seats = $InventarioOriginal, updated_at = CURRENT_TIMESTAMP WHERE event_id = 1;"


        Remove-Item `
            -Path $EstadoArchivo `
            -Force


        Show-SystemState


        Write-Host ""
        Write-Host "SISTEMA RESTAURADO." `
            -ForegroundColor Green

        Write-Host `
            "Inventario restaurado a $InventarioOriginal asientos." `
            -ForegroundColor Green
    }


    "estado" {

        Show-SystemState
    }
}