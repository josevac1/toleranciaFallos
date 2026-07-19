# Sistema de Reservas de Entradas con Kubernetes

Proyecto académico de **tolerancia a fallos en sistemas distribuidos**. Se implementó una arquitectura simplificada para la venta de entradas y se desplegó en un clúster Kubernetes de dos nodos.

## Integrantes

- José Vanegas
- Miguel Vanegas

---

## 1. Objetivo

Construir y desplegar un sistema de reservas formado por seis componentes:

1. API Gateway.
2. Servicio de Reservas.
3. Servicio de Inventario.
4. Servicio de Pagos simulado.
5. Servicio de Notificaciones simulado.
6. Base de datos PostgreSQL.

Los componentes críticos **Gateway**, **Reservas** e **Inventario** se ejecutan con dos réplicas distribuidas entre ambos nodos.

---

## 2. Arquitectura

El flujo principal es:

```text
Cliente
   |
   v
API Gateway
   |
   v
Servicio de Reservas
   |
   +----> Servicio de Inventario ----> PostgreSQL
   |
   +----> Servicio de Pagos
   |
   +----> Servicio de Notificaciones
   |
   +----> PostgreSQL
```

### Diagrama de despliegue

![Diagrama de arquitectura Kubernetes](evidencias/diagrama.png)

El clúster se distribuye así:

| Nodo | Etiqueta | Componentes |
|---|---|---|
| `tickets-cluster` | `sitio=nodo-a` | PostgreSQL, Notificaciones y una réplica de Gateway, Reservas e Inventario |
| `tickets-cluster-m02` | `sitio=nodo-b` | Pagos y una réplica de Gateway, Reservas e Inventario |

---

## 3. Tecnologías utilizadas

- Python 3.12.
- FastAPI.
- PostgreSQL 16.
- Docker Desktop.
- Kubernetes.
- Minikube multinodo.
- kubectl.
- PowerShell.
- Comunicación REST.

---

## 4. Estructura del proyecto

```text
sistema-entradas/
├── gateway/
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
├── reservations/
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
├── inventory/
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
├── payments/
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
├── notifications/
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
├── database/
│   └── init.sql
├── kubernetes/
│   ├── 00-namespace.yaml
│   ├── 01-postgres-configmap.yaml
│   ├── 02-postgres.yaml
│   ├── 03-inventory.yaml
│   ├── 04-payments.yaml
│   ├── 05-notifications.yaml
│   ├── 06-reservations.yaml
│   └── 07-gateway.yaml
├── chaos/
├── scripts/
│   └── verificar-cluster.ps1
├── evidencias/
├── README.md
└── .gitignore
```

---

## 5. Crear el clúster

```powershell
minikube start -p tickets-cluster --driver=docker --nodes=2 --cpus=2 --memory=3072 --container-runtime=containerd
kubectl config use-context tickets-cluster
kubectl get nodes -o wide
```

Etiquetar los nodos:

```powershell
kubectl label node tickets-cluster sitio=nodo-a --overwrite
kubectl label node tickets-cluster-m02 sitio=nodo-b --overwrite
kubectl get nodes -L sitio
```

---

## 6. Construir y cargar imágenes

Construir:

```powershell
docker build -t tickets-gateway:1.0.0 .\gateway
docker build -t tickets-reservations:1.0.0 .\reservations
docker build -t tickets-inventory:1.0.0 .\inventory
docker build -t tickets-payments:1.0.0 .\payments
docker build -t tickets-notifications:1.0.0 .\notifications
```

Cargar en Minikube:

```powershell
minikube image load tickets-gateway:1.0.0 -p tickets-cluster --daemon
minikube image load tickets-reservations:1.0.0 -p tickets-cluster --daemon
minikube image load tickets-inventory:1.0.0 -p tickets-cluster --daemon
minikube image load tickets-payments:1.0.0 -p tickets-cluster --daemon
minikube image load tickets-notifications:1.0.0 -p tickets-cluster --daemon
```

---

## 7. Desplegar Kubernetes

```powershell
kubectl apply -f .\kubernetes\00-namespace.yaml
kubectl apply -f .\kubernetes\01-postgres-configmap.yaml
kubectl apply -f .\kubernetes\02-postgres.yaml
kubectl apply -f .\kubernetes\03-inventory.yaml
kubectl apply -f .\kubernetes\04-payments.yaml
kubectl apply -f .\kubernetes\05-notifications.yaml
kubectl apply -f .\kubernetes\06-reservations.yaml
kubectl apply -f .\kubernetes\07-gateway.yaml
```

Verificar:

```powershell
kubectl get deployments -n tickets
kubectl get pods -n tickets -o wide
kubectl get services -n tickets
kubectl get pvc -n tickets
```

### Verificación final del sistema

![Verificación completa del clúster](evidencias/verificacionsistemaReserva.png)

La evidencia confirma:

- Dos nodos en estado `Ready`.
- Seis Deployments.
- Nueve pods en estado `Running`.
- Gateway, Inventario y Reservas distribuidos entre los dos nodos.
- Seis Services.
- PVC de PostgreSQL en estado `Bound`.
- Endpoints asociados a los pods.

---

## 8. Acceso al API Gateway

```powershell
kubectl port-forward -n tickets service/gateway-service 18000:8000
```

Swagger:

```text
http://127.0.0.1:18000/docs
```

Salud:

```powershell
Invoke-RestMethod http://127.0.0.1:18000/health
```

Consultar inventario:

```powershell
Invoke-RestMethod http://127.0.0.1:18000/api/inventory/1
```

Crear una reserva:

```powershell
$body = @{
    user_id  = "usuario-k8s-001"
    event_id = 1
    email    = "usuario@example.com"
    amount   = 25.50
} | ConvertTo-Json

Invoke-RestMethod `
    -Uri "http://127.0.0.1:18000/api/reservations" `
    -Method Post `
    -ContentType "application/json" `
    -Body $body
```

---

## 9. Comportamiento simulado

### Pagos

```text
Latencia mínima: 500 ms
Latencia máxima: 2500 ms
Probabilidad de fallo: 15 %
```

### Notificaciones

```text
Latencia mínima: 200 ms
Latencia máxima: 1200 ms
Probabilidad de fallo: 10 %
```

Cuando Pagos falla, Reservas solicita liberar el asiento. Cuando Notificaciones falla, la reserva permanece confirmada con estado `CONFIRMED_NOTIFICATION_PENDING`.

---

## 10. Verificar PostgreSQL

```powershell
$postgresPod = kubectl get pod `
  -n tickets `
  -l app=postgres `
  -o jsonpath="{.items[0].metadata.name}"

kubectl exec -n tickets $postgresPod -- `
  psql -U tickets_user -d tickets_db -c "\dt"

kubectl exec -n tickets $postgresPod -- `
  psql -U tickets_user -d tickets_db `
  -c "SELECT id, user_id, event_id, amount, status, created_at FROM reservations;"

kubectl exec -n tickets $postgresPod -- `
  psql -U tickets_user -d tickets_db `
  -c "SELECT * FROM inventory;"
```

---

## 11. Evidencias principales

### Construcción y pruebas locales

| Evidencia | Resultado |
|---|---|
| ![Estructura del proyecto](evidencias/01_paso1_estructura_proyecto_y_dockerfile.png) | Estructura inicial del proyecto y Dockerfiles. |
| ![Pago aprobado](evidencias/03_paso1_pagos_aprobado_powershell.png) | Prueba local de un pago aprobado. |
| ![Reserva confirmada](evidencias/07_paso1_reserva_confirmada_local.png) | Reserva confirmada durante las pruebas locales. |
| ![Gateway funcionando](evidencias/10_paso1_gateway_reserva_exitosa_local.png) | Flujo completo mediante el API Gateway. |

### PostgreSQL en Kubernetes

| Evidencia | Resultado |
|---|---|
| ![PostgreSQL desplegado](evidencias/20_paso2_postgresql_pod_pvc_y_service.png) | Pod, PVC y Service de PostgreSQL. |
| ![Tablas verificadas](evidencias/24_paso2_postgresql_tablas_verificadas.png) | Tablas `events`, `inventory` y `reservations`. |
| ![Inventario inicial](evidencias/25_paso2_postgresql_inventario_inicial_10.png) | Inventario inicial con diez asientos. |
| ![Evento inicial](evidencias/26_paso2_postgresql_evento_inicial.png) | Evento cargado mediante `init.sql`. |

### Inventario replicado

| Evidencia | Resultado |
|---|---|
| ![Dos réplicas](evidencias/33_paso2_inventario_dos_replicas_y_service.png) | Deployment de Inventario con dos réplicas. |
| ![Réplicas en dos nodos](evidencias/41_paso2_inventario_replicas_en_dos_nodos.png) | Una réplica de Inventario en cada nodo. |
| ![Endpoints del Service](evidencias/43_paso2_inventory_service_endpoints_dos_replicas.png) | Service con dos endpoints. |
| ![Reserva de asiento](evidencias/51_paso2_inventory_reserva_por_port_forward.png) | Reserva de un asiento mediante port-forward. |

### Pagos y Notificaciones

| Evidencia | Resultado |
|---|---|
| ![Pagos desplegado](evidencias/55_paso2_pagos_despliegue_pod_service_y_logs.png) | Deployment, Service y logs de Pagos. |
| ![Pruebas de Pagos](evidencias/57_paso2_pagos_pruebas_fallo_y_exito.png) | Respuestas exitosas y fallos simulados. |
| ![Logs de Pagos](evidencias/58_paso2_pagos_logs_latencia_fallos_y_exitos.png) | Latencia y resultados registrados. |
| ![Notificaciones desplegado](evidencias/60_paso2_notificaciones_despliegue_creado.png) | Deployment del Servicio de Notificaciones. |

---

## 12. Galería completa de evidencias

Las siguientes imágenes documentan todo el proceso, incluidos los errores encontrados, las correcciones y las verificaciones finales.

<details>
<summary><strong>Paso 1 estructura proyecto y Dockerfile.</strong></summary>

<br>

![Paso 1 estructura proyecto y Dockerfile.](evidencias/01_paso1_estructura_proyecto_y_dockerfile.png)

</details>

<details>
<summary><strong>Paso 1 Pagos fallo simulado Swagger.</strong></summary>

<br>

![Paso 1 Pagos fallo simulado Swagger.](evidencias/02_paso1_pagos_fallo_simulado_swagger.png)

</details>

<details>
<summary><strong>Paso 1 Pagos aprobado PowerShell.</strong></summary>

<br>

![Paso 1 Pagos aprobado PowerShell.](evidencias/03_paso1_pagos_aprobado_powershell.png)

</details>

<details>
<summary><strong>Paso 1 Pagos logs fallos y éxitos local.</strong></summary>

<br>

![Paso 1 Pagos logs fallos y éxitos local.](evidencias/04_paso1_pagos_logs_fallos_y_exitos_local.png)

</details>

<details>
<summary><strong>Paso 1 PostgreSQL local tablas creadas.</strong></summary>

<br>

![Paso 1 PostgreSQL local tablas creadas.](evidencias/05_paso1_postgresql_local_tablas_creadas.png)

</details>

<details>
<summary><strong>Paso 1 Reservas error Inventario no disponible.</strong></summary>

<br>

![Paso 1 Reservas error Inventario no disponible.](evidencias/06_paso1_reservas_error_inventario_no_disponible.png)

</details>

<details>
<summary><strong>Paso 1 reserva confirmada local.</strong></summary>

<br>

![Paso 1 reserva confirmada local.](evidencias/07_paso1_reserva_confirmada_local.png)

</details>

<details>
<summary><strong>Paso 1 logs Inventario no disponible.</strong></summary>

<br>

![Paso 1 logs Inventario no disponible.](evidencias/08_paso1_logs_inventario_no_disponible.png)

</details>

<details>
<summary><strong>Paso 1 API Gateway Swagger esquema inicial.</strong></summary>

<br>

![Paso 1 API Gateway Swagger esquema inicial.](evidencias/09_paso1_gateway_swagger_esquema_inicial.png)

</details>

<details>
<summary><strong>Paso 1 API Gateway reserva exitosa local.</strong></summary>

<br>

![Paso 1 API Gateway reserva exitosa local.](evidencias/10_paso1_gateway_reserva_exitosa_local.png)

</details>

<details>
<summary><strong>Paso 1 PostgreSQL local Inventario 7 asientos.</strong></summary>

<br>

![Paso 1 PostgreSQL local Inventario 7 asientos.](evidencias/11_paso1_postgresql_local_inventario_7_asientos.png)

</details>

<details>
<summary><strong>Paso 2 versiones docker minikube kubectl.</strong></summary>

<br>

![Paso 2 versiones docker minikube kubectl.](evidencias/12_paso2_versiones_docker_minikube_kubectl.png)

</details>

<details>
<summary><strong>Paso 2 error minikube icacls ruta personalizada.</strong></summary>

<br>

![Paso 2 error minikube icacls ruta personalizada.](evidencias/13_paso2_error_minikube_icacls_ruta_personalizada.png)

</details>

<details>
<summary><strong>Paso 2 reintento minikube y error icacls.</strong></summary>

<br>

![Paso 2 reintento minikube y error icacls.](evidencias/14_paso2_reintento_minikube_y_error_icacls.png)

</details>

<details>
<summary><strong>Paso 2 manifiestos PostgreSQL en Visual Studio Code.</strong></summary>

<br>

![Paso 2 manifiestos PostgreSQL en Visual Studio Code.](evidencias/15_paso2_manifiestos_postgresql_en_vscode.png)

</details>

<details>
<summary><strong>Paso 2 aplicación ConfigMap PostgreSQL intento.</strong></summary>

<br>

![Paso 2 aplicación ConfigMap PostgreSQL intento.](evidencias/16_paso2_aplicacion_configmap_postgresql_intento.png)

</details>

<details>
<summary><strong>Paso 2 ConfigMap PostgreSQL creado.</strong></summary>

<br>

![Paso 2 ConfigMap PostgreSQL creado.](evidencias/17_paso2_configmap_postgresql_creado.png)

</details>

<details>
<summary><strong>Paso 2 recursos PostgreSQL Kubernetes creados.</strong></summary>

<br>

![Paso 2 recursos PostgreSQL Kubernetes creados.](evidencias/18_paso2_recursos_postgresql_kubernetes_creados.png)

</details>

<details>
<summary><strong>Paso 2 rollout PostgreSQL exitoso.</strong></summary>

<br>

![Paso 2 rollout PostgreSQL exitoso.](evidencias/19_paso2_rollout_postgresql_exitoso.png)

</details>

<details>
<summary><strong>Paso 2 PostgreSQL pod PVC y Service.</strong></summary>

<br>

![Paso 2 PostgreSQL pod PVC y Service.](evidencias/20_paso2_postgresql_pod_pvc_y_service.png)

</details>

<details>
<summary><strong>Paso 2 logs inicializacion PostgreSQL.</strong></summary>

<br>

![Paso 2 logs inicializacion PostgreSQL.](evidencias/21_paso2_logs_inicializacion_postgresql.png)

</details>

<details>
<summary><strong>Paso 2 PostgreSQL tablas Inventario y evento.</strong></summary>

<br>

![Paso 2 PostgreSQL tablas Inventario y evento.](evidencias/22_paso2_postgresql_tablas_inventario_y_evento.png)

</details>

<details>
<summary><strong>Paso 2 variable postgres pod configurada.</strong></summary>

<br>

![Paso 2 variable postgres pod configurada.](evidencias/23_paso2_variable_postgres_pod_configurada.png)

</details>

<details>
<summary><strong>Paso 2 PostgreSQL tablas verificadas.</strong></summary>

<br>

![Paso 2 PostgreSQL tablas verificadas.](evidencias/24_paso2_postgresql_tablas_verificadas.png)

</details>

<details>
<summary><strong>Paso 2 PostgreSQL Inventario inicial 10.</strong></summary>

<br>

![Paso 2 PostgreSQL Inventario inicial 10.](evidencias/25_paso2_postgresql_inventario_inicial_10.png)

</details>

<details>
<summary><strong>Paso 2 PostgreSQL evento inicial.</strong></summary>

<br>

![Paso 2 PostgreSQL evento inicial.](evidencias/26_paso2_postgresql_evento_inicial.png)

</details>

<details>
<summary><strong>Paso 2 PostgreSQL pod en nodo a.</strong></summary>

<br>

![Paso 2 PostgreSQL pod en nodo a.](evidencias/27_paso2_postgresql_pod_en_nodo_a.png)

</details>

<details>
<summary><strong>Paso 2 PostgreSQL PVC y Service detalle.</strong></summary>

<br>

![Paso 2 PostgreSQL PVC y Service detalle.](evidencias/28_paso2_postgresql_pvc_y_service_detalle.png)

</details>

<details>
<summary><strong>Paso 2 PostgreSQL recursos completos.</strong></summary>

<br>

![Paso 2 PostgreSQL recursos completos.](evidencias/29_paso2_postgresql_recursos_completos.png)

</details>

<details>
<summary><strong>Paso 2 cluster dos nodos etiquetados.</strong></summary>

<br>

![Paso 2 cluster dos nodos etiquetados.](evidencias/30_paso2_cluster_dos_nodos_etiquetados.png)

</details>

<details>
<summary><strong>Paso 2 manifiesto Inventario en Visual Studio Code.</strong></summary>

<br>

![Paso 2 manifiesto Inventario en Visual Studio Code.](evidencias/31_paso2_manifiesto_inventario_en_vscode.png)

</details>

<details>
<summary><strong>Paso 2 despliegue Inventario creado.</strong></summary>

<br>

![Paso 2 despliegue Inventario creado.](evidencias/32_paso2_despliegue_inventario_creado.png)

</details>

<details>
<summary><strong>Paso 2 Inventario dos réplicas y Service.</strong></summary>

<br>

![Paso 2 Inventario dos réplicas y Service.](evidencias/33_paso2_inventario_dos_replicas_y_service.png)

</details>

<details>
<summary><strong>Paso 2 port forward Inventario 01.</strong></summary>

<br>

![Paso 2 port forward Inventario 01.](evidencias/34_paso2_port_forward_inventario_01.png)

</details>

<details>
<summary><strong>Paso 2 port forward Inventario 02.</strong></summary>

<br>

![Paso 2 port forward Inventario 02.](evidencias/35_paso2_port_forward_inventario_02.png)

</details>

<details>
<summary><strong>Paso 2 Inventario health Kubernetes.</strong></summary>

<br>

![Paso 2 Inventario health Kubernetes.](evidencias/36_paso2_inventario_health_kubernetes.png)

</details>

<details>
<summary><strong>Paso 2 Inventario consulta 10 asientos.</strong></summary>

<br>

![Paso 2 Inventario consulta 10 asientos.](evidencias/37_paso2_inventario_consulta_10_asientos.png)

</details>

<details>
<summary><strong>Paso 2 Inventario reserva asiento 9 disponibles.</strong></summary>

<br>

![Paso 2 Inventario reserva asiento 9 disponibles.](evidencias/38_paso2_inventario_reserva_asiento_9_disponibles.png)

</details>

<details>
<summary><strong>Paso 2 PostgreSQL confirma Inventario 9.</strong></summary>

<br>

![Paso 2 PostgreSQL confirma Inventario 9.](evidencias/39_paso2_postgresql_confirma_inventario_9.png)

</details>

<details>
<summary><strong>Paso 2 Inventario libera asiento 10.</strong></summary>

<br>

![Paso 2 Inventario libera asiento 10.](evidencias/40_paso2_inventario_libera_asiento_10.png)

</details>

<details>
<summary><strong>Paso 2 Inventario réplicas en dos nodos.</strong></summary>

<br>

![Paso 2 Inventario réplicas en dos nodos.](evidencias/41_paso2_inventario_replicas_en_dos_nodos.png)

</details>

<details>
<summary><strong>Paso 2 Inventario Service ClusterIP.</strong></summary>

<br>

![Paso 2 Inventario Service ClusterIP.](evidencias/42_paso2_inventory_service_clusterip.png)

</details>

<details>
<summary><strong>Paso 2 Inventario Service endpoints dos réplicas.</strong></summary>

<br>

![Paso 2 Inventario Service endpoints dos réplicas.](evidencias/43_paso2_inventory_service_endpoints_dos_replicas.png)

</details>

<details>
<summary><strong>Paso 2 Inventario Service EndpointSlice.</strong></summary>

<br>

![Paso 2 Inventario Service EndpointSlice.](evidencias/44_paso2_inventory_service_endpointslice.png)

</details>

<details>
<summary><strong>Paso 2 prueba interna Inventario health.</strong></summary>

<br>

![Paso 2 prueba interna Inventario health.](evidencias/45_paso2_prueba_interna_inventory_health.png)

</details>

<details>
<summary><strong>Paso 2 prueba interna Inventario consulta.</strong></summary>

<br>

![Paso 2 prueba interna Inventario consulta.](evidencias/46_paso2_prueba_interna_inventory_consulta.png)

</details>

<details>
<summary><strong>Paso 2 Inventario port forward y endpoints.</strong></summary>

<br>

![Paso 2 Inventario port forward y endpoints.](evidencias/47_paso2_inventory_port_forward_y_endpoints.png)

</details>

<details>
<summary><strong>Paso 2 prueba interna Inventario health 02.</strong></summary>

<br>

![Paso 2 prueba interna Inventario health 02.](evidencias/48_paso2_prueba_interna_inventory_health_02.png)

</details>

<details>
<summary><strong>Paso 2 Inventario health por port forward.</strong></summary>

<br>

![Paso 2 Inventario health por port forward.](evidencias/49_paso2_inventory_health_por_port_forward.png)

</details>

<details>
<summary><strong>Paso 2 Inventario consulta por port forward.</strong></summary>

<br>

![Paso 2 Inventario consulta por port forward.](evidencias/50_paso2_inventory_consulta_por_port_forward.png)

</details>

<details>
<summary><strong>Paso 2 Inventario reserva por port forward.</strong></summary>

<br>

![Paso 2 Inventario reserva por port forward.](evidencias/51_paso2_inventory_reserva_por_port_forward.png)

</details>

<details>
<summary><strong>Paso 2 PostgreSQL verifica Inventario 9.</strong></summary>

<br>

![Paso 2 PostgreSQL verifica Inventario 9.](evidencias/52_paso2_postgresql_verifica_inventario_9.png)

</details>

<details>
<summary><strong>Paso 2 Inventario liberación por port forward.</strong></summary>

<br>

![Paso 2 Inventario liberación por port forward.](evidencias/53_paso2_inventory_liberacion_por_port_forward.png)

</details>

<details>
<summary><strong>Paso 2 Inventario Service descripcion endpoints.</strong></summary>

<br>

![Paso 2 Inventario Service descripcion endpoints.](evidencias/54_paso2_inventory_service_descripcion_endpoints.png)

</details>

<details>
<summary><strong>Paso 2 Pagos despliegue pod Service y logs.</strong></summary>

<br>

![Paso 2 Pagos despliegue pod Service y logs.](evidencias/55_paso2_pagos_despliegue_pod_service_y_logs.png)

</details>

<details>
<summary><strong>Paso 2 Pagos port forward activo.</strong></summary>

<br>

![Paso 2 Pagos port forward activo.](evidencias/56_paso2_pagos_port_forward_activo.png)

</details>

<details>
<summary><strong>Paso 2 Pagos pruebas fallo y éxito.</strong></summary>

<br>

![Paso 2 Pagos pruebas fallo y éxito.](evidencias/57_paso2_pagos_pruebas_fallo_y_exito.png)

</details>

<details>
<summary><strong>Paso 2 Pagos logs latencia fallos y éxitos.</strong></summary>

<br>

![Paso 2 Pagos logs latencia fallos y éxitos.](evidencias/58_paso2_pagos_logs_latencia_fallos_y_exitos.png)

</details>

<details>
<summary><strong>Paso 2 Pagos logs en tiempo real.</strong></summary>

<br>

![Paso 2 Pagos logs en tiempo real.](evidencias/59_paso2_pagos_logs_en_tiempo_real.png)

</details>

<details>
<summary><strong>Paso 2 Notificaciones despliegue creado.</strong></summary>

<br>

![Paso 2 Notificaciones despliegue creado.](evidencias/60_paso2_notificaciones_despliegue_creado.png)

</details>

<details>
<summary><strong>Paso 2 distribución pods postgres Inventario Pagos Notificaciones.</strong></summary>

<br>

![Paso 2 distribución pods postgres Inventario Pagos Notificaciones.](evidencias/61_paso2_distribucion_pods_postgres_inventory_payments_notifications.png)

</details>

<details>
<summary><strong>Paso 2 Services postgres Inventario Pagos Notificaciones.</strong></summary>

<br>

![Paso 2 Services postgres Inventario Pagos Notificaciones.](evidencias/62_paso2_services_postgres_inventory_payments_notifications.png)

</details>

---

## 13. Solución de problemas

### Imagen no encontrada


### `ImagePullBackOff`

```powershell
minikube image ls -p tickets-cluster | findstr "tickets-"
minikube image load tickets-inventory:1.0.0 -p tickets-cluster --daemon
kubectl rollout restart deployment/inventory -n tickets
```

### Pod en `Pending`

```powershell
kubectl describe pod -n tickets NOMBRE_DEL_POD
kubectl get nodes -L sitio
```

### Service sin endpoints

```powershell
kubectl describe service inventory-service -n tickets
kubectl get pods -n tickets -l app=inventory
```

### Puerto ocupado

```powershell
kubectl port-forward -n tickets service/gateway-service 18010:8000
```

---

## 14. Detener y eliminar

Detener:

```powershell
minikube stop -p tickets-cluster
```

Reanudar:

```powershell
minikube start -p tickets-cluster
```

Eliminar recursos:

```powershell
kubectl delete -f .\kubernetes
```

Eliminar el clúster:

```powershell
minikube delete -p tickets-cluster
```

---

## 15. Cumplimiento de la Parte I

| Requisito | Estado |
|---|---|
| Seis componentes | Cumplido |
| Comunicación REST | Cumplido |
| Pagos con latencia y fallos | Cumplido |
| Notificaciones con latencia y fallos | Cumplido |
| Clúster de dos nodos | Cumplido |
| Componentes críticos replicados | Cumplido |
| Réplicas distribuidas entre nodos | Cumplido |
| PostgreSQL con persistencia | Cumplido |
| Manifiestos YAML | Cumplido |
| Diagrama de arquitectura | Cumplido |
| Evidencias del despliegue | Cumplido |
| README reproducible | Cumplido |

> Las credenciales utilizadas son únicamente para un entorno académico local.
