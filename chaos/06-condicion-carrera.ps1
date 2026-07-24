param(
    [ValidateSet("preparar", "probar", "restaurar", "estado")]
    [string]$Accion = "estado",

    [int]$Puerto = 18000
)

$ErrorActionPreference = "Stop"

$namespace = "tickets"
$stateFile = Join-Path $PSScriptRoot "estado-fallo6.json"
$evidenceDir = Join-Path (Split-Path $PSScriptRoot -Parent) "evidencias"

function Obtener-PostgresPod {

    $pod = kubectl get pod `
        -n $namespace `
        -l app=postgres `
        -o jsonpath="{.items[0].metadata.name}"

    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($pod)) {
        throw "No se encontro el pod de PostgreSQL."
    }

    return "$pod".Trim()
}

function Ejecutar-Sql {

    param(
        [Parameter(Mandatory = $true)]
        [string]$Sql
    )

    $postgresPod = Obtener-PostgresPod

    $resultado = kubectl exec `
        -n $namespace `
        $postgresPod `
        -- psql `
        -U tickets_user `
        -d tickets_db `
        -t `
        -A `
        -c $Sql

    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo ejecutar la consulta SQL."
    }

    return "$resultado".Trim()
}

function Obtener-Inventario {

    $resultado = Ejecutar-Sql `
        "SELECT available_seats FROM inventory WHERE event_id=1;"

    return [int]$resultado
}

function Mostrar-Estado {

    Write-Host "`nDeployments principales:" -ForegroundColor Yellow

    kubectl get deployment `
        inventory `
        payments `
        notifications `
        reservations `
        gateway `
        -n $namespace

    Write-Host "`nVariables de Inventario:" -ForegroundColor Yellow

    kubectl set env `
        deployment/inventory `
        -n $namespace `
        --list

    Write-Host "`nVariables de Pagos:" -ForegroundColor Yellow

    kubectl set env `
        deployment/payments `
        -n $namespace `
        --list

    Write-Host "`nVariables de Notificaciones:" -ForegroundColor Yellow

    kubectl set env `
        deployment/notifications `
        -n $namespace `
        --list

    Write-Host "`nInventario actual:" -ForegroundColor Yellow

    $inventario = Obtener-Inventario

    Write-Host "Asientos disponibles para el evento 1: $inventario" `
        -ForegroundColor Cyan
}

Write-Host "================================================" `
    -ForegroundColor Cyan

Write-Host " FALLO 6: CONDICION DE CARRERA" `
    -ForegroundColor Cyan

Write-Host "================================================" `
    -ForegroundColor Cyan

switch ($Accion) {

    "preparar" {

        Write-Host "`n1. Verificando PostgreSQL..." `
            -ForegroundColor Yellow

        $selectorPostgres = kubectl get service `
            postgres-service `
            -n $namespace `
            -o jsonpath="{.spec.selector.app}"

        if ("$selectorPostgres".Trim() -ne "postgres") {
            Write-Host `
                "postgres-service no tiene el selector correcto." `
                -ForegroundColor Red

            Write-Host `
                "Ejecuta primero la restauracion de la Falla 4." `
                -ForegroundColor Red

            exit 1
        }

        Write-Host "`n2. Guardando el inventario original..." `
            -ForegroundColor Yellow

        $inventarioOriginal = Obtener-Inventario

        $estado = [PSCustomObject]@{
            inventario_original = $inventarioOriginal
            preparado_en        = (Get-Date).ToString("s")
            ultimo_run_id       = ""
        }

        $estado |
            ConvertTo-Json |
            Set-Content `
                -Path $stateFile `
                -Encoding UTF8

        Write-Host `
            "Inventario original guardado: $inventarioOriginal" `
            -ForegroundColor Green

        Write-Host "`n3. Configurando Inventario para ampliar la carrera..." `
            -ForegroundColor Yellow

        kubectl set env `
            deployment/inventory `
            -n $namespace `
            RACE_DELAY_MS=1500

        Write-Host "`n4. Desactivando fallos aleatorios de Pagos..." `
            -ForegroundColor Yellow

        kubectl set env `
            deployment/payments `
            -n $namespace `
            MIN_DELAY_MS=100 `
            MAX_DELAY_MS=100 `
            FAILURE_RATE=0

        Write-Host "`n5. Desactivando fallos aleatorios de Notificaciones..." `
            -ForegroundColor Yellow

        kubectl set env `
            deployment/notifications `
            -n $namespace `
            MIN_DELAY_MS=50 `
            MAX_DELAY_MS=50 `
            FAILURE_RATE=0

        Write-Host "`n6. Esperando los nuevos pods..." `
            -ForegroundColor Yellow

        kubectl rollout status `
            deployment/inventory `
            -n $namespace `
            --timeout=180s

        kubectl rollout status `
            deployment/payments `
            -n $namespace `
            --timeout=180s

        kubectl rollout status `
            deployment/notifications `
            -n $namespace `
            --timeout=180s

        Write-Host "`n7. Eliminando datos de pruebas anteriores..." `
            -ForegroundColor Yellow

        Ejecutar-Sql `
            "DELETE FROM reservations WHERE user_id LIKE 'usuario-carrera-%';" |
            Out-Null

        Write-Host "`n8. Dejando un solo asiento disponible..." `
            -ForegroundColor Yellow

        Ejecutar-Sql `
            "UPDATE inventory
             SET available_seats=1,
                 updated_at=NOW()
             WHERE event_id=1;" |
            Out-Null

        Mostrar-Estado

        Write-Host "`nEXPERIMENTO PREPARADO:" `
            -ForegroundColor Green

        Write-Host `
            "Solo queda un asiento y existe una espera de 1500 ms en Inventario." `
            -ForegroundColor Green
    }

    "probar" {

        if (-not (Test-Path $stateFile)) {
            Write-Host `
                "Primero ejecuta el script con -Accion preparar." `
                -ForegroundColor Red

            exit 1
        }

        Write-Host "`n1. Comprobando el port-forward del Gateway..." `
            -ForegroundColor Yellow

        $puertoActivo = Test-NetConnection `
            -ComputerName 127.0.0.1 `
            -Port $Puerto `
            -InformationLevel Quiet

        if (-not $puertoActivo) {
            Write-Host `
                "No hay un port-forward activo en el puerto $Puerto." `
                -ForegroundColor Red

            Write-Host `
                "Abre otra terminal y ejecuta:" `
                -ForegroundColor Yellow

            Write-Host `
                "kubectl port-forward -n tickets service/gateway-service ${Puerto}:8000" `
                -ForegroundColor Cyan

            exit 1
        }

        Write-Host "`n2. Restaurando un asiento antes de la prueba..." `
            -ForegroundColor Yellow

        Ejecutar-Sql `
            "UPDATE inventory
             SET available_seats=1,
                 updated_at=NOW()
             WHERE event_id=1;" |
            Out-Null

        $runId = Get-Date -Format "yyyyMMddHHmmss"

        $estado = Get-Content $stateFile -Raw |
            ConvertFrom-Json

        $estado.ultimo_run_id = $runId

        $estado |
            ConvertTo-Json |
            Set-Content `
                -Path $stateFile `
                -Encoding UTF8

        Write-Host "`n3. Enviando dos compras simultaneas..." `
            -ForegroundColor Yellow

        $jobs = 1..2 | ForEach-Object {

            $numero = $_

            $body = @{
                user_id  = "usuario-carrera-$runId-$numero"
                event_id = 1
                email    = "carrera$numero@example.com"
                amount   = 25.50
            } | ConvertTo-Json -Compress

            Start-Job `
                -ScriptBlock {

                    param(
                        $PuertoTrabajo,
                        $Payload,
                        $NumeroSolicitud
                    )

                    $inicio = Get-Date

                    try {

                        $respuesta = Invoke-RestMethod `
                            -Uri "http://127.0.0.1:$PuertoTrabajo/api/reservations" `
                            -Method Post `
                            -ContentType "application/json" `
                            -Body $Payload

                        $fin = Get-Date

                        [PSCustomObject]@{
                            solicitud     = $NumeroSolicitud
                            exitosa       = $true
                            estado        = $respuesta.status
                            reservationId = $respuesta.reservation_id
                            segundos      = [math]::Round(
                                ($fin - $inicio).TotalSeconds,
                                3
                            )
                            error         = ""
                        }
                    }
                    catch {

                        $fin = Get-Date

                        [PSCustomObject]@{
                            solicitud     = $NumeroSolicitud
                            exitosa       = $false
                            estado        = "ERROR"
                            reservationId = ""
                            segundos      = [math]::Round(
                                ($fin - $inicio).TotalSeconds,
                                3
                            )
                            error         = $_.Exception.Message
                        }
                    }

                } `
                -ArgumentList $Puerto, $body, $numero
        }

        $jobs | Wait-Job | Out-Null

        $resultados = $jobs | Receive-Job

        $jobs | Remove-Job

        Write-Host "`n4. Resultados de las solicitudes:" `
            -ForegroundColor Yellow

        $resultados |
            Select-Object `
                solicitud,
                exitosa,
                estado,
                reservationId,
                segundos,
                error |
            Format-Table -AutoSize

        if (-not (Test-Path $evidenceDir)) {
            New-Item `
                -ItemType Directory `
                -Path $evidenceDir |
                Out-Null
        }

        $archivoResultados = Join-Path `
            $evidenceDir `
            "fallo6-resultados-$runId.json"

        $resultados |
            ConvertTo-Json -Depth 5 |
            Set-Content `
                -Path $archivoResultados `
                -Encoding UTF8

        Write-Host `
            "`nResultados guardados en: $archivoResultados" `
            -ForegroundColor Cyan

        Write-Host "`n5. Consultando PostgreSQL..." `
            -ForegroundColor Yellow

        $cantidadConfirmadas = Ejecutar-Sql `
            "SELECT COUNT(*)
             FROM reservations
             WHERE user_id LIKE 'usuario-carrera-$runId-%'
               AND status='CONFIRMED';"

        $inventarioFinal = Obtener-Inventario

        Write-Host `
            "Reservas confirmadas en esta prueba: $cantidadConfirmadas"

        Write-Host `
            "Asientos disponibles despues de la prueba: $inventarioFinal"

        Write-Host "`nReservas registradas:" `
            -ForegroundColor Yellow

        $postgresPod = Obtener-PostgresPod

        kubectl exec `
            -n $namespace `
            $postgresPod `
            -- psql `
            -U tickets_user `
            -d tickets_db `
            -c "SELECT user_id, event_id, amount, status, created_at
                FROM reservations
                WHERE user_id LIKE 'usuario-carrera-$runId-%'
                ORDER BY created_at;"

        if ([int]$cantidadConfirmadas -ge 2) {

            Write-Host "`nCONDICION DE CARRERA REPRODUCIDA:" `
                -ForegroundColor Green

            Write-Host `
                "Dos usuarios compraron cuando solo existia un asiento." `
                -ForegroundColor Green

            Write-Host `
                "Esto demuestra una inconsistencia por concurrencia." `
                -ForegroundColor Green
        }
        else {

            Write-Host "`nLA CARRERA NO SE REPRODUJO EN ESTE INTENTO." `
                -ForegroundColor Yellow

            Write-Host `
                "Ejecuta nuevamente -Accion probar. El script volvera a dejar un asiento." `
                -ForegroundColor Yellow
        }
    }

    "restaurar" {

        if (-not (Test-Path $stateFile)) {

            Write-Host `
                "No se encontro el archivo con el estado original." `
                -ForegroundColor Yellow

            Write-Host `
                "Se restauraran las variables, pero no se modificara el inventario." `
                -ForegroundColor Yellow

            $inventarioOriginal = $null
        }
        else {

            $estado = Get-Content $stateFile -Raw |
                ConvertFrom-Json

            $inventarioOriginal = [int]$estado.inventario_original
        }

        Write-Host "`n1. Restaurando Inventario..." `
            -ForegroundColor Yellow

        kubectl set env `
            deployment/inventory `
            -n $namespace `
            RACE_DELAY_MS=0

        Write-Host "`n2. Restaurando Pagos..." `
            -ForegroundColor Yellow

        kubectl set env `
            deployment/payments `
            -n $namespace `
            MIN_DELAY_MS=500 `
            MAX_DELAY_MS=2500 `
            FAILURE_RATE=0.15

        Write-Host "`n3. Restaurando Notificaciones..." `
            -ForegroundColor Yellow

        kubectl set env `
            deployment/notifications `
            -n $namespace `
            MIN_DELAY_MS=200 `
            MAX_DELAY_MS=1200 `
            FAILURE_RATE=0.10

        Write-Host "`n4. Esperando la restauracion..." `
            -ForegroundColor Yellow

        kubectl rollout status `
            deployment/inventory `
            -n $namespace `
            --timeout=180s

        kubectl rollout status `
            deployment/payments `
            -n $namespace `
            --timeout=180s

        kubectl rollout status `
            deployment/notifications `
            -n $namespace `
            --timeout=180s

        Write-Host "`n5. Eliminando las reservas de la prueba..." `
            -ForegroundColor Yellow

        Ejecutar-Sql `
            "DELETE FROM reservations
             WHERE user_id LIKE 'usuario-carrera-%';" |
            Out-Null

        if ($null -ne $inventarioOriginal) {

            Write-Host `
                "`n6. Restaurando el inventario original: $inventarioOriginal" `
                -ForegroundColor Yellow

            Ejecutar-Sql `
                "UPDATE inventory
                 SET available_seats=$inventarioOriginal,
                     updated_at=NOW()
                 WHERE event_id=1;" |
                Out-Null
        }

        if (Test-Path $stateFile) {
            Remove-Item $stateFile -Force
        }

        Mostrar-Estado

        Write-Host "`nSISTEMA RESTAURADO." `
            -ForegroundColor Green
    }

    "estado" {
        Mostrar-Estado
    }
}

Write-Host "`n================================================" `
    -ForegroundColor Cyan

Write-Host " FIN DEL SCRIPT" `
    -ForegroundColor Cyan

Write-Host "================================================" `
    -ForegroundColor Cyan