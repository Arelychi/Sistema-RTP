# Sistema-RTP

Sistema de análisis y gestión de roles operativos RTP.

## Proyecto Python + PostgreSQL

Proyecto base para conectarse a PostgreSQL usando `psycopg` y variables de entorno.

## Requisitos

- Python 3.10 o superior
- PostgreSQL instalado y ejecutándose

## Configuración local en Windows

Desde esta carpeta, ejecuta. En este workspace, el entorno está ubicado en `c:\xampp\htdocs\xampp\.venv`:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
..\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edita `.env` con los datos reales de tu base de datos:

```dotenv
PGHOST=localhost
PGPORT=5432
PGDATABASE=mi_base_de_datos
PGUSER=postgres
PGPASSWORD=tu_contraseña
SECRET_KEY=cambia-esta-clave-por-una-segura
```

La aplicación carga `.env` automáticamente mediante `app/config.py`. Usa `SECRET_KEY` como nombre principal; `FLASK_SECRET_KEY` se mantiene solo para compatibilidad. Para PostgreSQL local puedes usar las variables `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER` y `PGPASSWORD`.

También puedes usar una URL completa:

```dotenv
DATABASE_URL=postgresql://usuario:contraseña@localhost:5432/ProgramacionDeControladores
```

Cuando existe `DATABASE_URL`, tiene prioridad sobre las variables `PG*`.

## Despliegue en Render

Configura estas variables en **Render > Service > Environment**:

```dotenv
APP_ENV=production
SECRET_KEY=una-clave-larga-y-aleatoria
DATABASE_URL=postgresql://...
```

Si enlazas una base de datos PostgreSQL de Render con el servicio web, Render puede proporcionar `DATABASE_URL` automáticamente. No subas `.env` a GitHub ni guardes credenciales reales en `.env.example`.

El `Procfile` ya configura Gunicorn:

```text
web: gunicorn --bind 0.0.0.0:$PORT app.web:app
```

Render define `PORT`; por eso Gunicorn escucha en `0.0.0.0:$PORT`. En desarrollo se ejecuta Flask en `127.0.0.1:5000` con `debug=True`; en producción se usa Gunicorn, no el servidor de desarrollo de Flask, y el modo debug queda desactivado.

## Probar la conexión

```powershell
..\.venv\Scripts\python.exe -m app.main
```

## Abrir la interfaz gráfica

Instala las dependencias y ejecuta el servidor web:

```powershell
..\.venv\Scripts\python.exe -m pip install -r requirements.txt
..\.venv\Scripts\python.exe -m app.web
```

Después abre [http://127.0.0.1:5000](http://127.0.0.1:5000) en el navegador. La aplicación crea automáticamente el esquema `seguridad`, la tabla `seguridad.usuarios` y la tabla `schedule_records`.

## Acceso inicial

La primera ejecución crea estas cuentas si todavía no existen:

- `user1` / `user1` hasta `user7` / `user7`: cada cuenta solo entra a su módulo correspondiente.
- `administrador` / `administrador`: acceso exclusivo a **Más Ajustes**.

Cambia estas contraseñas antes de usar el sistema en producción. Las contraseñas se almacenan como hashes, no en texto plano.

- Registro de nombre, credencial, ruta, turno y nomenclatura.
- Calendario del mes actual con navegación entre meses.
- Días de trabajo y descanso alternables con clic.
- Tabla mensual estilo rol, con el código combinado de nomenclatura y turno, por ejemplo `A` + `1` = `A1`.

Si PostgreSQL no está disponible, la pantalla funciona en modo local temporal para poder probar la interfaz; esos registros se conservan mientras el proceso del servidor siga activo.

El archivo `.env` está excluido de Git para evitar publicar credenciales.
