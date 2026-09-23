# Sistema-RTP

Sistema de análisis y gestión de roles operativos RTP.

## Proyecto Python + PostgreSQL

Proyecto base para conectarse a PostgreSQL usando `psycopg` y variables de entorno.

## Requisitos

- Python 3.10 o superior
- PostgreSQL instalado y ejecutándose

## Configuración en Windows

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
FLASK_SECRET_KEY=cambia-esta-clave-por-una-segura
```

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
