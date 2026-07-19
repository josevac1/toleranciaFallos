Write-Host "========================================="
Write-Host " SISTEMA DE RESERVAS - VERIFICACION"
Write-Host "========================================="

Write-Host "`n1. Contexto activo:"
kubectl config current-context

Write-Host "`n2. Nodos del cluster:"
kubectl get nodes -L sitio

Write-Host "`n3. Deployments:"
kubectl get deployments -n tickets

Write-Host "`n4. Pods y distribucion:"
kubectl get pods -n tickets `
  -o custom-columns="POD:.metadata.name,COMPONENTE:.metadata.labels.app,READY:.status.containerStatuses[0].ready,ESTADO:.status.phase,NODO:.spec.nodeName"

Write-Host "`n5. Services:"
kubectl get services -n tickets

Write-Host "`n6. Almacenamiento:"
kubectl get pvc -n tickets

Write-Host "`n7. Endpoints:"
kubectl get endpoints -n tickets

Write-Host "`n========================================="
Write-Host " VERIFICACION FINALIZADA"
Write-Host "========================================="