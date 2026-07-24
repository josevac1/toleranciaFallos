$ErrorActionPreference = "Stop"

$namespace = "tickets"
$deployment = "inventory"
$selector = "app=inventory"

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host " FALLO 1: INVENTARIO FANTASMA" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

Write-Host "`n1. Estado inicial de Inventario:" -ForegroundColor Yellow

kubectl get pods `
    -n $namespace `
    -l $selector `
    -o wide

Write-Host "`n2. Buscando una replica para eliminar..." -ForegroundColor Yellow

$inventoryPod = kubectl get pods `
    -n $namespace `
    -l $selector `
    -o jsonpath="{.items[0].metadata.name}"

if ([string]::IsNullOrWhiteSpace($inventoryPod)) {
    Write-Host "No se encontro ningun pod de Inventario." -ForegroundColor Red
    exit 1
}

Write-Host "Pod seleccionado: $inventoryPod" -ForegroundColor Magenta

Write-Host "`n3. Eliminando el pod..." -ForegroundColor Yellow

kubectl delete pod `
    -n $namespace `
    $inventoryPod `
    --wait=false

Write-Host "`n4. Estado inmediatamente despues del fallo:" -ForegroundColor Yellow

kubectl get pods `
    -n $namespace `
    -l $selector `
    -o wide

Write-Host "`n5. Esperando que Kubernetes restaure las dos replicas..." -ForegroundColor Yellow

kubectl rollout status `
    deployment/$deployment `
    -n $namespace `
    --timeout=180s

Write-Host "`n6. Estado final:" -ForegroundColor Yellow

kubectl get pods `
    -n $namespace `
    -l $selector `
    -o wide

$readyReplicas = kubectl get deployment $deployment `
    -n $namespace `
    -o jsonpath="{.status.readyReplicas}"

$desiredReplicas = kubectl get deployment $deployment `
    -n $namespace `
    -o jsonpath="{.spec.replicas}"

Write-Host "`nReplicas deseadas: $desiredReplicas"
Write-Host "Replicas disponibles: $readyReplicas"

if ($readyReplicas -eq $desiredReplicas) {
    Write-Host "`nPRUEBA EXITOSA:" -ForegroundColor Green
    Write-Host "Kubernetes reemplazo automaticamente el pod eliminado." -ForegroundColor Green
}
else {
    Write-Host "`nPRUEBA INCOMPLETA:" -ForegroundColor Red
    Write-Host "No se recuperaron todas las replicas." -ForegroundColor Red
    exit 1
}

Write-Host "`n=========================================" -ForegroundColor Cyan
Write-Host " FIN DEL EXPERIMENTO" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan