# Comedor service

Servicio para registrar alumnos en el endpoint del comedor, ejecutarlo todos los dias a las 7:00 a. m. y administrarlo por HTTP o Telegram.

Importante: no subas tokens reales a GitHub. Si pegaste un token en un chat o repositorio, revocalo en BotFather y genera uno nuevo.

## Estructura

```text
server.py        Entrada principal
config.py        Variables, argumentos y zona horaria
store.py         SQLite y consultas
comedor_api.py   Cliente HTTP del comedor
runner.py        Scheduler y ejecucion idempotente por dia
telegram_bot.py  Bot, mensajes HTML y botones
http_api.py      API HTTP local
html_utils.py    Escape y formato HTML
```

## Despliegue con Docker

```bash
cp .env.example .env
nano .env
docker compose up -d --build
```

Variables en `.env`:

```env
COMEDOR_ADMIN_TOKEN=cambia-este-token-http
TELEGRAM_BOT_TOKEN=token-nuevo-del-bot
TELEGRAM_ADMIN_IDS=123456789
```

Para conocer tu `TELEGRAM_ADMIN_IDS`, inicia el servicio con el token del bot, escribe `/start` al bot y revisa la respuesta: mostrara tu ID si aun no estas autorizado. Luego pon ese ID en `.env` y reinicia:

```bash
docker compose restart
```

Por defecto:

- Base de datos: volumen Docker `comedor_data`, archivo interno `/data/comedor.db`
- Puerto HTTP con Docker: `8090`
- Hora objetivo: `07:00`
- Inicio automatico: `07:00`, en la hora objetivo exacta
- Fin de intentos: `07:01`, 1 minuto despues de la hora objetivo
- Zona horaria: `America/Lima`
- Reintentos: pausas Fibonacci `1, 1, 2, 3, 5...` segundos hasta el cierre
- Reporte final: se envia por Telegram a los IDs configurados en `TELEGRAM_ADMIN_IDS`

La ejecucion diaria empieza a intentar exactamente a las 7:00 a. m. y sigue hasta 1 minuto despues, con pausas Fibonacci (`1, 1, 2, 3, 5...` segundos) entre reintentos para evitar una rafaga fija de solicitudes. Si el servidor ya responde que no hay cupos (`t3_cupos <= 0`, `code: 500` sin ticket o mensajes como `SIN CUPOS DISPONIBLES`), el servicio marca el intento como `no_quota`, detiene la tanda y ya no sigue enviando solicitudes ese dia.

## Comandos de Telegram

```text
/add DNI CODIGO Nombre opcional
/list
/edit ID DNI CODIGO Nombre opcional
/delete ID
/disable ID
/enable ID
/run
/attempts
/tickets
/id
```

El bot tambien muestra botones inline:

- En `/start` y `/help`: `Ver alumnos`, `Ver tickets`, `Ejecutar faltantes`
- En `/list`: `Editar`, `Activar/Desactivar`, `Eliminar`, `Actualizar lista`, `Ver tickets`
- En `/tickets`: `Actualizar tickets`, `Ejecutar faltantes`, `Ver alumnos`

Los botones `Editar`, `Activar/Desactivar` y `Eliminar` piden primero el ID del alumno, asi la cantidad de botones no crece con la base de datos. El boton `Eliminar` pide confirmacion antes de borrar. El boton `Editar` envia una plantilla `/edit ...` para copiar, ajustar y enviar.

Ejemplo:

```text
/add 72423247 2023200631G Jhulio
```

Editar:

```text
/edit 1 72423247 2023200631G Jhulio Moran
```

Eliminar:

```text
/delete 1
```

Ver quienes tienen ticket hoy y quienes no:

```text
/tickets
```

## API HTTP

Agregar alumnos:

```bash
curl -X POST http://127.0.0.1:8090/students \
  -H 'Authorization: Bearer cambia-este-token-http' \
  -H 'Content-Type: application/json' \
  -d '{"dni":"72423247","codigo":"2023200631G","nombre":"Jhulio"}'
```

Ver alumnos:

```bash
curl http://127.0.0.1:8090/students \
  -H 'Authorization: Bearer cambia-este-token-http'
```

Editar alumno:

```bash
curl -X PATCH http://127.0.0.1:8090/students/1 \
  -H 'Authorization: Bearer cambia-este-token-http' \
  -H 'Content-Type: application/json' \
  -d '{"dni":"72423247","codigo":"2023200631G","nombre":"Jhulio Moran"}'
```

Eliminar alumno:

```bash
curl -X DELETE http://127.0.0.1:8090/students/1 \
  -H 'Authorization: Bearer cambia-este-token-http'
```

Desactivar o activar alumno:

```bash
curl -X POST http://127.0.0.1:8090/students/1/disable \
  -H 'Authorization: Bearer cambia-este-token-http'

curl -X POST http://127.0.0.1:8090/students/1/enable \
  -H 'Authorization: Bearer cambia-este-token-http'
```

Ejecutar manualmente:

```bash
curl -X POST http://127.0.0.1:8090/run \
  -H 'Authorization: Bearer cambia-este-token-http'
```

La ejecucion diaria y `/run` saltan automaticamente a los alumnos que ya tienen ticket registrado para el dia actual. Tambien dejan de insistir cuando el comedor informa que los cupos se agotaron.

Ver intentos recientes:

```bash
curl http://127.0.0.1:8090/attempts \
  -H 'Authorization: Bearer cambia-este-token-http'
```

## Ejecucion sin Docker

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
COMEDOR_ADMIN_TOKEN='cambia-este-token-http' \
TELEGRAM_BOT_TOKEN='token-nuevo-del-bot' \
TELEGRAM_ADMIN_IDS='123456789' \
./server.py --host 0.0.0.0 --port 8080
```
