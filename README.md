# Sistema de Reservas de Entradas con Kubernetes

Proyecto académico de **tolerancia a fallos en sistemas distribuidos**. La solución implementa una arquitectura simplificada de venta de entradas mediante microservicios REST desplegados en un clúster Kubernetes de dos nodos.

## Integrantes

- José Vanegas
- Miguel Vanegas

---

## 1. Objetivo

Construir y desplegar los siguientes seis componentes:

1. API Gateway.
2. Servicio de Reservas.
3. Servicio de Inventario.
4. Servicio de Pagos simulado.
5. Servicio de Notificaciones simulado.
6. Base de datos PostgreSQL.

Los componentes críticos **Gateway**, **Reservas** e **Inventario** tienen dos réplicas distribuidas entre ambos nodos para evitar que la caída de un nodo elimine todas sus instancias.

---

## 2. Arquitectura

<p align="center">
  <img src="evidencias/diagrama.png" alt="Arquitectura del sistema de reservas desplegada en Kubernetes." width="950">
</p>
<p align="center"><em>Arquitectura del sistema de reservas desplegada en Kubernetes.</em></p>


### Flujo principal

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

### Flujo de una reserva

1. El cliente envía la solicitud al API Gateway.
2. El Gateway reenvía la petición al Servicio de Reservas.
3. Reservas solicita un asiento al Servicio de Inventario.
4. Inventario consulta y actualiza PostgreSQL.
5. Reservas solicita el cobro al Servicio de Pagos.
6. Si Pagos falla, Reservas libera el asiento.
7. Si el pago es aprobado, la reserva se guarda en PostgreSQL.
8. Reservas intenta enviar la confirmación mediante Notificaciones.
9. Si Notificaciones falla, la compra permanece confirmada con estado `CONFIRMED_NOTIFICATION_PENDING`.

---

## 3. Componentes y réplicas

| Componente | Responsabilidad | Réplicas |
|---|---|---:|
| API Gateway | Entrada del sistema y enrutamiento | 2 |
| Reservas | Coordina inventario, pago, persistencia y notificación | 2 |
| Inventario | Consulta, reserva y libera asientos | 2 |
| Pagos | Stub con latencia y fallos simulados | 1 |
| Notificaciones | Stub para envío simulado de correos | 1 |
| PostgreSQL | Persistencia de eventos, inventario y reservas | 1 |
| **Total** |  | **9 pods** |

### Distribución multinodo

| Nodo | Etiqueta | Componentes |
|---|---|---|
| `tickets-cluster` | `sitio=nodo-a` | PostgreSQL, Notificaciones y una réplica de Gateway, Reservas e Inventario |
| `tickets-cluster-m02` | `sitio=nodo-b` | Pagos y una réplica de Gateway, Reservas e Inventario |

---

## 4. Tecnologías utilizadas

- Python 3.12.
- FastAPI.
- PostgreSQL 16 Alpine.
- Docker Desktop.
- Kubernetes.
- Minikube multinodo.
- kubectl.
- PowerShell.
- Comunicación REST.

---

## 5. Estructura del proyecto

```text
sistema-entradas/
├── chaos/
├── database/
│   └── init.sql
├── evidencias/
│   ├── diagrama.png
│   ├── verificacionsistemaReserva.png
│   └── capturas del proceso
├── gateway/
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
├── inventory/
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
├── kubernetes/
│   ├── 00-namespace.yaml
│   ├── 01-postgres-configmap.yaml
│   ├── 02-postgres.yaml
│   ├── 03-inventory.yaml
│   ├── 04-payments.yaml
│   ├── 05-notifications.yaml
│   ├── 06-reservations.yaml
│   └── 07-gateway.yaml
├── notifications/
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
├── payments/
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
├── reservations/
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
├── scripts/
│   └── verificar-cluster.ps1
├── .gitignore
└── README.md
```

---

## 6. Requisitos previos

- Docker Desktop ejecutándose con contenedores Linux.
- Minikube.
- kubectl.
- PowerShell.
- Al menos 6 GB de memoria disponible.

Comprobar las herramientas:

```powershell
docker version
docker info --format "{{.OSType}}"
minikube version
kubectl version --client
```

Docker debe responder:

```text
linux
```

---

## 7. Crear el clúster de dos nodos

```powershell
minikube start -p tickets-cluster `
  --driver=docker `
  --nodes=2 `
  --cpus=2 `
  --memory=3072 `
  --container-runtime=containerd
```

Seleccionar el contexto y comprobar los nodos:

```powershell
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

## 8. Construir las imágenes Docker

Desde la raíz del proyecto:

```powershell
docker build -t tickets-gateway:1.0.0 .\gateway
docker build -t tickets-reservations:1.0.0 .\reservations
docker build -t tickets-inventory:1.0.0 .\inventory
docker build -t tickets-payments:1.0.0 .\payments
docker build -t tickets-notifications:1.0.0 .\notifications
```

Comprobar:

```powershell
docker images --format "{{.Repository}}:{{.Tag}}" | findstr "tickets-"
```

---

## 9. Cargar las imágenes en Minikube

```powershell
minikube image load tickets-gateway:1.0.0 -p tickets-cluster --daemon
minikube image load tickets-reservations:1.0.0 -p tickets-cluster --daemon
minikube image load tickets-inventory:1.0.0 -p tickets-cluster --daemon
minikube image load tickets-payments:1.0.0 -p tickets-cluster --daemon
minikube image load tickets-notifications:1.0.0 -p tickets-cluster --daemon
```

Comprobar:

```powershell
minikube image ls -p tickets-cluster | findstr "tickets-"
```

---

## 10. Desplegar los manifiestos Kubernetes

Aplicar en orden:

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

---

## 11. Verificar el despliegue

Ejecutar el script:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\verificar-cluster.ps1
```

Verificación manual:

```powershell
kubectl get nodes -L sitio
kubectl get deployments -n tickets
kubectl get pods -n tickets -o wide
kubectl get services -n tickets
kubectl get pvc -n tickets
kubectl get endpoints -n tickets
```

Resultado esperado:

```text
gateway         2/2
inventory       2/2
notifications   1/1
payments        1/1
postgres        1/1
reservations    2/2
```

<p align="center">
  <img src="evidencias/verificacionsistemaReserva.png" alt="Verificación final del sistema desplegado." width="950">
</p>
<p align="center"><em>Verificación final del sistema desplegado.</em></p>


---

## 12. Probar el API Gateway

Crear el túnel local:

```powershell
kubectl port-forward -n tickets service/gateway-service 18000:8000
```

Swagger:

```text
http://127.0.0.1:18000/docs
```

Comprobar salud:

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

## 13. Comportamiento simulado

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

| Resultado | Significado |
|---|---|
| `CONFIRMED` | Reserva, pago y notificación completados |
| `CONFIRMED_NOTIFICATION_PENDING` | Compra confirmada, pero falló Notificaciones |
| `503 Service Unavailable` | Pagos falló y Reservas libera el asiento |

---

## 14. Verificar PostgreSQL

```powershell
$postgresPod = kubectl get pod `
  -n tickets `
  -l app=postgres `
  -o jsonpath="{.items[0].metadata.name}"
```

Listar tablas:

```powershell
kubectl exec -n tickets $postgresPod -- `
  psql -U tickets_user -d tickets_db -c "\dt"
```

Consultar reservas:

```powershell
kubectl exec -n tickets $postgresPod -- `
  psql -U tickets_user -d tickets_db `
  -c "SELECT id, user_id, event_id, amount, status, created_at FROM reservations;"
```

Consultar inventario:

```powershell
kubectl exec -n tickets $postgresPod -- `
  psql -U tickets_user -d tickets_db `
  -c "SELECT * FROM inventory;"
```

---

## 15. Evidencias principales

<p align="center">
  <img src="evidencias/diagrama.png" alt="Arquitectura del sistema desplegado en Kubernetes." width="950">
</p>
<p align="center"><em>Arquitectura del sistema desplegado en Kubernetes.</em></p>

<p align="center">
  <img src="evidencias/verificacionsistemaReserva.png" alt="Verificación final: nodos, Deployments, pods, Services, almacenamiento y endpoints." width="950">
</p>
<p align="center"><em>Verificación final: nodos, Deployments, pods, Services, almacenamiento y endpoints.</em></p>

<p align="center">
  <img src="evidencias/01_paso1_estructura_proyecto_y_dockerfile.png" alt="Estructura inicial del proyecto y Dockerfiles." width="950">
</p>
<p align="center"><em>Estructura inicial del proyecto y Dockerfiles.</em></p>

<p align="center">
  <img src="evidencias/10_paso1_gateway_reserva_exitosa_local.png" alt="Flujo completo de una reserva mediante el API Gateway." width="950">
</p>
<p align="center"><em>Flujo completo de una reserva mediante el API Gateway.</em></p>

<p align="center">
  <img src="evidencias/24_paso2_postgresql_tablas_verificadas.png" alt="Tablas de PostgreSQL verificadas dentro del clúster." width="950">
</p>
<p align="center"><em>Tablas de PostgreSQL verificadas dentro del clúster.</em></p>

<p align="center">
  <img src="evidencias/30_paso2_cluster_dos_nodos_etiquetados.png" alt="Clúster de dos nodos con las etiquetas nodo-a y nodo-b." width="950">
</p>
<p align="center"><em>Clúster de dos nodos con las etiquetas nodo-a y nodo-b.</em></p>

<p align="center">
  <img src="evidencias/41_paso2_inventario_replicas_en_dos_nodos.png" alt="Inventario con una réplica en cada nodo." width="950">
</p>
<p align="center"><em>Inventario con una réplica en cada nodo.</em></p>

<p align="center">
  <img src="evidencias/43_paso2_inventory_service_endpoints_dos_replicas.png" alt="Service de Inventario con dos endpoints disponibles." width="950">
</p>
<p align="center"><em>Service de Inventario con dos endpoints disponibles.</em></p>

<p align="center">
  <img src="evidencias/57_paso2_pagos_pruebas_fallo_y_exito.png" alt="Servicio de Pagos con respuestas exitosas y fallos simulados." width="950">
</p>
<p align="center"><em>Servicio de Pagos con respuestas exitosas y fallos simulados.</em></p>

<p align="center">
  <img src="evidencias/60_paso2_notificaciones_despliegue_creado.png" alt="Despliegue del Servicio de Notificaciones." width="950">
</p>
<p align="center"><em>Despliegue del Servicio de Notificaciones.</em></p>

<p align="center">
  <img src="evidencias/61_paso2_distribucion_pods_postgres_inventory_payments_notifications.png" alt="Distribución de componentes entre los nodos." width="950">
</p>
<p align="center"><em>Distribución de componentes entre los nodos.</em></p>

<p align="center">
  <img src="evidencias/62_paso2_services_postgres_inventory_payments_notifications.png" alt="Services internos desplegados en el namespace tickets." width="950">
</p>
<p align="center"><em>Services internos desplegados en el namespace tickets.</em></p>


---

## 16. Galería completa

Todas las capturas incluidas en la carpeta `evidencias` se muestran en las secciones desplegables siguientes.

<details>
<summary><strong>Pruebas locales y construcción inicial (11 imágenes)</strong></summary>

<br>

### Paso 1 estructura proyecto y Dockerfile

<p align="center">
  <img src="evidencias/01_paso1_estructura_proyecto_y_dockerfile.png" alt="Paso 1 estructura proyecto y Dockerfile" width="950">
</p>
### Paso 1 Pagos fallo simulado Swagger

<p align="center">
  <img src="evidencias/02_paso1_pagos_fallo_simulado_swagger.png" alt="Paso 1 Pagos fallo simulado Swagger" width="950">
</p>
### Paso 1 Pagos aprobado PowerShell

<p align="center">
  <img src="evidencias/03_paso1_pagos_aprobado_powershell.png" alt="Paso 1 Pagos aprobado PowerShell" width="950">
</p>
### Paso 1 Pagos logs fallos y éxitos local

<p align="center">
  <img src="evidencias/04_paso1_pagos_logs_fallos_y_exitos_local.png" alt="Paso 1 Pagos logs fallos y éxitos local" width="950">
</p>
### Paso 1 PostgreSQL local tablas creadas

<p align="center">
  <img src="evidencias/05_paso1_postgresql_local_tablas_creadas.png" alt="Paso 1 PostgreSQL local tablas creadas" width="950">
</p>
### Paso 1 Reservas error Inventario no disponible

<p align="center">
  <img src="evidencias/06_paso1_reservas_error_inventario_no_disponible.png" alt="Paso 1 Reservas error Inventario no disponible" width="950">
</p>
### Paso 1 reserva confirmada local

<p align="center">
  <img src="evidencias/07_paso1_reserva_confirmada_local.png" alt="Paso 1 reserva confirmada local" width="950">
</p>
### Paso 1 logs Inventario no disponible

<p align="center">
  <img src="evidencias/08_paso1_logs_inventario_no_disponible.png" alt="Paso 1 logs Inventario no disponible" width="950">
</p>
### Paso 1 Gateway Swagger esquema inicial

<p align="center">
  <img src="evidencias/09_paso1_gateway_swagger_esquema_inicial.png" alt="Paso 1 Gateway Swagger esquema inicial" width="950">
</p>
### Paso 1 Gateway reserva exitosa local

<p align="center">
  <img src="evidencias/10_paso1_gateway_reserva_exitosa_local.png" alt="Paso 1 Gateway reserva exitosa local" width="950">
</p>
### Paso 1 PostgreSQL local Inventario 7 asientos

<p align="center">
  <img src="evidencias/11_paso1_postgresql_local_inventario_7_asientos.png" alt="Paso 1 PostgreSQL local Inventario 7 asientos" width="950">
</p>

</details>

<details>
<summary><strong>PostgreSQL y almacenamiento en Kubernetes (19 imágenes)</strong></summary>

<br>

### Paso 2 versiones docker minikube kubectl

<p align="center">
  <img src="evidencias/12_paso2_versiones_docker_minikube_kubectl.png" alt="Paso 2 versiones docker minikube kubectl" width="950">
</p>
### Paso 2 error minikube icacls ruta personalizada

<p align="center">
  <img src="evidencias/13_paso2_error_minikube_icacls_ruta_personalizada.png" alt="Paso 2 error minikube icacls ruta personalizada" width="950">
</p>
### Paso 2 reintento minikube y error icacls

<p align="center">
  <img src="evidencias/14_paso2_reintento_minikube_y_error_icacls.png" alt="Paso 2 reintento minikube y error icacls" width="950">
</p>
### Paso 2 manifiestos PostgreSQL en Visual Studio Code

<p align="center">
  <img src="evidencias/15_paso2_manifiestos_postgresql_en_vscode.png" alt="Paso 2 manifiestos PostgreSQL en Visual Studio Code" width="950">
</p>
### Paso 2 aplicación ConfigMap PostgreSQL intento

<p align="center">
  <img src="evidencias/16_paso2_aplicacion_configmap_postgresql_intento.png" alt="Paso 2 aplicación ConfigMap PostgreSQL intento" width="950">
</p>
### Paso 2 ConfigMap PostgreSQL creado

<p align="center">
  <img src="evidencias/17_paso2_configmap_postgresql_creado.png" alt="Paso 2 ConfigMap PostgreSQL creado" width="950">
</p>
### Paso 2 recursos PostgreSQL Kubernetes creados

<p align="center">
  <img src="evidencias/18_paso2_recursos_postgresql_kubernetes_creados.png" alt="Paso 2 recursos PostgreSQL Kubernetes creados" width="950">
</p>
### Paso 2 rollout PostgreSQL exitoso

<p align="center">
  <img src="evidencias/19_paso2_rollout_postgresql_exitoso.png" alt="Paso 2 rollout PostgreSQL exitoso" width="950">
</p>
### Paso 2 PostgreSQL pod PVC y Service

<p align="center">
  <img src="evidencias/20_paso2_postgresql_pod_pvc_y_service.png" alt="Paso 2 PostgreSQL pod PVC y Service" width="950">
</p>
### Paso 2 logs inicializacion PostgreSQL

<p align="center">
  <img src="evidencias/21_paso2_logs_inicializacion_postgresql.png" alt="Paso 2 logs inicializacion PostgreSQL" width="950">
</p>
### Paso 2 PostgreSQL tablas Inventario y evento

<p align="center">
  <img src="evidencias/22_paso2_postgresql_tablas_inventario_y_evento.png" alt="Paso 2 PostgreSQL tablas Inventario y evento" width="950">
</p>
### Paso 2 variable postgres pod configurada

<p align="center">
  <img src="evidencias/23_paso2_variable_postgres_pod_configurada.png" alt="Paso 2 variable postgres pod configurada" width="950">
</p>
### Paso 2 PostgreSQL tablas verificadas

<p align="center">
  <img src="evidencias/24_paso2_postgresql_tablas_verificadas.png" alt="Paso 2 PostgreSQL tablas verificadas" width="950">
</p>
### Paso 2 PostgreSQL Inventario inicial 10

<p align="center">
  <img src="evidencias/25_paso2_postgresql_inventario_inicial_10.png" alt="Paso 2 PostgreSQL Inventario inicial 10" width="950">
</p>
### Paso 2 PostgreSQL evento inicial

<p align="center">
  <img src="evidencias/26_paso2_postgresql_evento_inicial.png" alt="Paso 2 PostgreSQL evento inicial" width="950">
</p>
### Paso 2 PostgreSQL pod en nodo a

<p align="center">
  <img src="evidencias/27_paso2_postgresql_pod_en_nodo_a.png" alt="Paso 2 PostgreSQL pod en nodo a" width="950">
</p>
### Paso 2 PostgreSQL PVC y Service detalle

<p align="center">
  <img src="evidencias/28_paso2_postgresql_pvc_y_service_detalle.png" alt="Paso 2 PostgreSQL PVC y Service detalle" width="950">
</p>
### Paso 2 PostgreSQL recursos completos

<p align="center">
  <img src="evidencias/29_paso2_postgresql_recursos_completos.png" alt="Paso 2 PostgreSQL recursos completos" width="950">
</p>
### Paso 2 cluster dos nodos etiquetados

<p align="center">
  <img src="evidencias/30_paso2_cluster_dos_nodos_etiquetados.png" alt="Paso 2 cluster dos nodos etiquetados" width="950">
</p>

</details>

<details>
<summary><strong>Inventario replicado y comunicación interna (24 imágenes)</strong></summary>

<br>

### Paso 2 manifiesto Inventario en Visual Studio Code

<p align="center">
  <img src="evidencias/31_paso2_manifiesto_inventario_en_vscode.png" alt="Paso 2 manifiesto Inventario en Visual Studio Code" width="950">
</p>
### Paso 2 despliegue Inventario creado

<p align="center">
  <img src="evidencias/32_paso2_despliegue_inventario_creado.png" alt="Paso 2 despliegue Inventario creado" width="950">
</p>
### Paso 2 Inventario dos réplicas y Service

<p align="center">
  <img src="evidencias/33_paso2_inventario_dos_replicas_y_service.png" alt="Paso 2 Inventario dos réplicas y Service" width="950">
</p>
### Paso 2 port forward Inventario 01

<p align="center">
  <img src="evidencias/34_paso2_port_forward_inventario_01.png" alt="Paso 2 port forward Inventario 01" width="950">
</p>
### Paso 2 port forward Inventario 02

<p align="center">
  <img src="evidencias/35_paso2_port_forward_inventario_02.png" alt="Paso 2 port forward Inventario 02" width="950">
</p>
### Paso 2 Inventario salud Kubernetes

<p align="center">
  <img src="evidencias/36_paso2_inventario_health_kubernetes.png" alt="Paso 2 Inventario salud Kubernetes" width="950">
</p>
### Paso 2 Inventario consulta 10 asientos

<p align="center">
  <img src="evidencias/37_paso2_inventario_consulta_10_asientos.png" alt="Paso 2 Inventario consulta 10 asientos" width="950">
</p>
### Paso 2 Inventario reserva asiento 9 disponibles

<p align="center">
  <img src="evidencias/38_paso2_inventario_reserva_asiento_9_disponibles.png" alt="Paso 2 Inventario reserva asiento 9 disponibles" width="950">
</p>
### Paso 2 PostgreSQL confirma Inventario 9

<p align="center">
  <img src="evidencias/39_paso2_postgresql_confirma_inventario_9.png" alt="Paso 2 PostgreSQL confirma Inventario 9" width="950">
</p>
### Paso 2 Inventario libera asiento 10

<p align="center">
  <img src="evidencias/40_paso2_inventario_libera_asiento_10.png" alt="Paso 2 Inventario libera asiento 10" width="950">
</p>
### Paso 2 Inventario réplicas en dos nodos

<p align="center">
  <img src="evidencias/41_paso2_inventario_replicas_en_dos_nodos.png" alt="Paso 2 Inventario réplicas en dos nodos" width="950">
</p>
### Paso 2 Inventario Service ClusterIP

<p align="center">
  <img src="evidencias/42_paso2_inventory_service_clusterip.png" alt="Paso 2 Inventario Service ClusterIP" width="950">
</p>
### Paso 2 Inventario Service endpoints dos réplicas

<p align="center">
  <img src="evidencias/43_paso2_inventory_service_endpoints_dos_replicas.png" alt="Paso 2 Inventario Service endpoints dos réplicas" width="950">
</p>
### Paso 2 Inventario Service EndpointSlice

<p align="center">
  <img src="evidencias/44_paso2_inventory_service_endpointslice.png" alt="Paso 2 Inventario Service EndpointSlice" width="950">
</p>
### Paso 2 prueba interna Inventario salud

<p align="center">
  <img src="evidencias/45_paso2_prueba_interna_inventory_health.png" alt="Paso 2 prueba interna Inventario salud" width="950">
</p>
### Paso 2 prueba interna Inventario consulta

<p align="center">
  <img src="evidencias/46_paso2_prueba_interna_inventory_consulta.png" alt="Paso 2 prueba interna Inventario consulta" width="950">
</p>
### Paso 2 Inventario port forward y endpoints

<p align="center">
  <img src="evidencias/47_paso2_inventory_port_forward_y_endpoints.png" alt="Paso 2 Inventario port forward y endpoints" width="950">
</p>
### Paso 2 prueba interna Inventario salud 02

<p align="center">
  <img src="evidencias/48_paso2_prueba_interna_inventory_health_02.png" alt="Paso 2 prueba interna Inventario salud 02" width="950">
</p>
### Paso 2 Inventario salud por port forward

<p align="center">
  <img src="evidencias/49_paso2_inventory_health_por_port_forward.png" alt="Paso 2 Inventario salud por port forward" width="950">
</p>
### Paso 2 Inventario consulta por port forward

<p align="center">
  <img src="evidencias/50_paso2_inventory_consulta_por_port_forward.png" alt="Paso 2 Inventario consulta por port forward" width="950">
</p>
### Paso 2 Inventario reserva por port forward

<p align="center">
  <img src="evidencias/51_paso2_inventory_reserva_por_port_forward.png" alt="Paso 2 Inventario reserva por port forward" width="950">
</p>
### Paso 2 PostgreSQL verifica Inventario 9

<p align="center">
  <img src="evidencias/52_paso2_postgresql_verifica_inventario_9.png" alt="Paso 2 PostgreSQL verifica Inventario 9" width="950">
</p>
### Paso 2 Inventario liberación por port forward

<p align="center">
  <img src="evidencias/53_paso2_inventory_liberacion_por_port_forward.png" alt="Paso 2 Inventario liberación por port forward" width="950">
</p>
### Paso 2 Inventario Service descripcion endpoints

<p align="center">
  <img src="evidencias/54_paso2_inventory_service_descripcion_endpoints.png" alt="Paso 2 Inventario Service descripcion endpoints" width="950">
</p>

</details>

<details>
<summary><strong>Pagos y Notificaciones (8 imágenes)</strong></summary>

<br>

### Paso 2 Pagos despliegue pod Service y logs

<p align="center">
  <img src="evidencias/55_paso2_pagos_despliegue_pod_service_y_logs.png" alt="Paso 2 Pagos despliegue pod Service y logs" width="950">
</p>
### Paso 2 Pagos port forward activo

<p align="center">
  <img src="evidencias/56_paso2_pagos_port_forward_activo.png" alt="Paso 2 Pagos port forward activo" width="950">
</p>
### Paso 2 Pagos pruebas fallo y éxito

<p align="center">
  <img src="evidencias/57_paso2_pagos_pruebas_fallo_y_exito.png" alt="Paso 2 Pagos pruebas fallo y éxito" width="950">
</p>
### Paso 2 Pagos logs latencia fallos y éxitos

<p align="center">
  <img src="evidencias/58_paso2_pagos_logs_latencia_fallos_y_exitos.png" alt="Paso 2 Pagos logs latencia fallos y éxitos" width="950">
</p>
### Paso 2 Pagos logs en tiempo real

<p align="center">
  <img src="evidencias/59_paso2_pagos_logs_en_tiempo_real.png" alt="Paso 2 Pagos logs en tiempo real" width="950">
</p>
### Paso 2 Notificaciones despliegue creado

<p align="center">
  <img src="evidencias/60_paso2_notificaciones_despliegue_creado.png" alt="Paso 2 Notificaciones despliegue creado" width="950">
</p>
### Paso 2 distribución pods postgres Inventario Pagos Notificaciones

<p align="center">
  <img src="evidencias/61_paso2_distribucion_pods_postgres_inventory_payments_notifications.png" alt="Paso 2 distribución pods postgres Inventario Pagos Notificaciones" width="950">
</p>
### Paso 2 Services postgres Inventario Pagos Notificaciones

<p align="center">
  <img src="evidencias/62_paso2_services_postgres_inventory_payments_notifications.png" alt="Paso 2 Services postgres Inventario Pagos Notificaciones" width="950">
</p>

</details>

<details>
<summary><strong>Arquitectura y verificación final (2 imágenes)</strong></summary>

<br>

### Diagrama

<p align="center">
  <img src="evidencias/diagrama.png" alt="Diagrama" width="950">
</p>
### VerificacionsistemaReserva

<p align="center">
  <img src="evidencias/verificacionsistemaReserva.png" alt="VerificacionsistemaReserva" width="950">
</p>

</details>


---

## 17. Logs

```powershell
kubectl logs -n tickets deployment/gateway --tail=50 --prefix
kubectl logs -n tickets deployment/reservations --tail=50 --prefix
kubectl logs -n tickets deployment/inventory --tail=50 --prefix
kubectl logs -n tickets deployment/payments --tail=50
kubectl logs -n tickets deployment/notifications --tail=50
kubectl logs -n tickets deployment/postgres --tail=50
```

---

## 18. Solución de problemas

### `ImagePullBackOff`

```powershell
minikube image ls -p tickets-cluster | findstr "tickets-"
minikube image load tickets-inventory:1.0.0 -p tickets-cluster --daemon
kubectl rollout restart deployment/inventory -n tickets
```

### Pod en estado `Pending`

```powershell
kubectl describe pod -n tickets NOMBRE_DEL_POD
kubectl get nodes -L sitio
```

### Service sin endpoints

```powershell
kubectl describe service inventory-service -n tickets
kubectl get pods -n tickets -l app=inventory
```

### Puerto local ocupado

```powershell
kubectl port-forward -n tickets service/gateway-service 18010:8000
```

---

## 19. Detener o eliminar el entorno

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

> Las credenciales incluidas en los manifiestos se utilizan únicamente en un entorno académico local.
