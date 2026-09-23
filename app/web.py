import json
import hashlib
import os
import secrets
import smtplib
from calendar import monthrange
from copy import copy
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from email.message import EmailMessage

from flask import Flask, flash, g, jsonify, redirect, render_template, request, session, send_file, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from app.config import settings
from app.db import (
    MAX_MODULES,
    authenticate_user,
    complete_password_reset,
    create_catalog_item,
    create_controller,
    create_history_entry,
    create_password_reset_token,
    create_route,
    create_user,
    create_module,
    delete_controller,
    delete_route,
    delete_catalog_item,
    delete_user,
    delete_module,
    fetch_catalog_items,
    fetch_controllers,
    fetch_controller_by_credential,
    fetch_records,
    fetch_external_routes,
    fetch_routes,
    fetch_shared_modules,
    get_monthly_role_activation,
    fetch_turno_modules_map,
    fetch_users,
    fetch_admin_users,
    fetch_modules,
    fetch_history_entries,
    fetch_analysis_metrics,
    fetch_password_reset_token,
    get_connection,
    initialize_schema,
    normalize_display_text,
    update_admin_route,
    update_catalog_item,
    update_controller,
    update_controller_status,
    update_shift_status,
    update_route,
    update_route_status,
    update_user,
    update_module,
    link_route_to_module,
    update_module_route_status,
    unlink_route_from_module,
    upsert_record,
    save_month_records,
    set_monthly_role_activation,
    set_turno_modules,
)
from app.excel_export import build_turnos_excel


app = Flask(__name__, template_folder="../templates", static_folder="../static")
app.config["SECRET_KEY"] = settings.secret_key
app.config["ENVIRONMENT"] = settings.environment
memory_records: list[dict] = []
memory_controllers: list[dict] = []


def request_modules() -> list[dict]:
    modules = g.get("admin_modules")
    if modules is None:
        initialize_schema()
        modules = fetch_modules()
        g.admin_modules = modules
    return modules


@app.context_processor
def inject_module_name():
    module_number = request.view_args.get("module_number") if request.view_args else None
    module_name = None
    modules = []
    if module_number is not None:
        try:
            modules = request_modules()
            module = next((item for item in modules if item["id"] == module_number), None)
            module_name = module["nombre"] if module else None
        except Exception:
            module_name = None
    return {
        "module_name": module_name,
        "modules": modules,
        "module_names": {str(item["id"]): item["nombre"] for item in modules},
    }


def hydrate_record_identity(record: dict) -> dict:
    if not isinstance(record, dict):
        return record
    credential = str(record.get("credential", "")).strip()
    if not credential:
        return record
    controller = next(
        (
            item for item in memory_controllers
            if str(item.get("credencial", "")).strip() == credential
        ),
        None,
    )
    if controller is None:
        return record
    record["name"] = str(controller.get("nombre") or record.get("name") or "").strip()
    record["credential"] = str(controller.get("credencial") or credential).strip()
    return record


def records_for(month: int, year: int, module_number: int) -> list[dict]:
    try:
        initialize_schema()
        return fetch_records(month, year, module_number)
    except Exception:
        records = [
            record for record in memory_records
            if record["month"] == month
            and record["year"] == year
            and record.get("module_number") == module_number
        ]
        return [hydrate_record_identity(record) for record in records]


def monthly_role_is_closed(month: int, year: int, module_number: int | None = None) -> bool:
    current_month = date.today().year * 12 + date.today().month
    selected_month = year * 12 + month
    if selected_month >= current_month or module_number is None:
        return selected_month < current_month
    try:
        initialize_schema()
        return not get_monthly_role_activation(module_number, month, year)
    except Exception:
        return True


def requested_module_number(account: dict, payload: dict | None = None) -> int | None:
    if not account.get("is_admin"):
        return account.get("module_number")
    source = payload or request.args
    value = source.get("module_number") if hasattr(source, "get") else None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def record_history(
    account: dict,
    description: str,
    module_number: int | None = None,
    action: str = "registro",
    detail: str | None = None,
) -> None:
    try:
        initialize_schema()
        create_history_entry(account.get("username", "desconocido"), module_number, description, action, detail)
    except Exception:
        app.logger.exception("No fue posible registrar una entrada del historial")


def record_code_map(record: dict | None) -> dict[str, list[int]]:
    if not record:
        return {}
    assignments = record.get("daily_assignments") or {}
    if isinstance(assignments, str):
        try:
            assignments = json.loads(assignments)
        except (TypeError, ValueError):
            assignments = {}
    code_days: dict[str, list[int]] = {}
    for raw_day, raw_code in assignments.items():
        code = str(raw_code).strip().upper()
        if not code or code == "V":
            continue
        try:
            day = int(raw_day)
        except (TypeError, ValueError):
            continue
        code_days.setdefault(code, []).append(day)
    return {code: sorted(days) for code, days in code_days.items()}


def format_code_changes(previous: dict | None, current: dict | None) -> str:
    previous_codes = record_code_map(previous)
    current_codes = record_code_map(current)
    added = {
        code: sorted(set(current_codes.get(code, [])) - set(previous_codes.get(code, [])))
        for code in set(current_codes) | set(previous_codes)
    }
    removed = {
        code: sorted(set(previous_codes.get(code, [])) - set(current_codes.get(code, [])))
        for code in set(current_codes) | set(previous_codes)
    }
    added = {code: days for code, days in added.items() if days}
    removed = {code: days for code, days in removed.items() if days}

    def format_codes(source: dict[str, list[int]]) -> str:
        values = []
        for code in sorted(source):
            days = source[code]
            day_label = "día" if len(days) == 1 else "días"
            values.append(f"{code} ({day_label} {', '.join(map(str, days))})")
        return ", ".join(values)

    changes = []
    if added:
        changes.append(f"Agregó: {format_codes(added)}")
    if removed:
        changes.append(f"Eliminó: {format_codes(removed)}")
    return " | ".join(changes) or "Sin cambios de códigos"


@app.route("/", methods=["GET", "POST"])
def connection_status():
    if request.method == "POST":
        try:
            initialize_schema()
            account = authenticate_user(request.form.get("username", "").strip().lower(), request.form.get("password", ""))
        except Exception:
            account = None
        if account:
            record_history(
                account,
                "Inicio de sesión",
                account.get("module_number"),
                "inicio_sesion",
            )
            session["account"] = account
            if account.get("is_admin"):
                return redirect(url_for("admin_dashboard"))
            return redirect(url_for("schedule_dashboard", module_number=account["module_number"]))
        return render_template("inicio_de_sesion.html", login_error="Credenciales inválidas o acceso no permitido."), 401
    return render_template("inicio_de_sesion.html")


def send_password_reset_email(recipient: str, reset_url: str) -> None:
    mail_user = os.environ["MAIL_USER"]
    message = EmailMessage()
    message["Subject"] = "Recuperación de contraseña - Residencias Profesionales"
    message["From"] = f'{os.getenv("MAIL_FROM_NAME", "Residencias Profesionales")} <{mail_user}>'
    message["To"] = recipient
    message.set_content(
        "Solicitaste cambiar tu contraseña. Abre este enlace antes de 15 minutos:\n\n"
        f"{reset_url}\n\n"
        "Si no solicitaste este cambio, ignora este correo."
    )
    with smtplib.SMTP(
        os.getenv("MAIL_HOST", "smtp.gmail.com"),
        int(os.getenv("MAIL_PORT", "587")),
    ) as server:
        server.starttls()
        server.login(mail_user, os.environ["MAIL_PASS"])
        server.send_message(message)


@app.route("/recuperar-contrasena", methods=["GET", "POST"])
def recover_password():
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        recovery_message = "Si los datos corresponden a una cuenta activa, recibirás un enlace de recuperación en su correo electrónico."
        try:
            initialize_schema()
            token = secrets.token_urlsafe(32)
            token_record = create_password_reset_token(
                identifier,
                hashlib.sha256(token.encode()).hexdigest(),
                datetime.now(timezone.utc) + timedelta(minutes=15),
            )
            if token_record:
                send_password_reset_email(
                    token_record["correo"],
                    url_for("reset_password", token=token, _external=True),
                )
        except Exception:
            app.logger.exception("No fue posible procesar la recuperación de contraseña")
            pass
        return render_template("recuperar_contrasena.html", recovery_message=recovery_message)
    return render_template("recuperar_contrasena.html")


@app.route("/nueva-contrasena/<token>", methods=["GET", "POST"])
def reset_password(token: str):
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    try:
        initialize_schema()
        token_record = fetch_password_reset_token(token_hash)
    except Exception:
        token_record = None
    if token_record is None:
        return render_template("nueva_contrasena.html", reset_error="El enlace no es válido o ya expiró."), 400
    if request.method == "POST":
        password = request.form.get("password", "")
        confirmation = request.form.get("password_confirmation", "")
        if len(password) < 8:
            return render_template("nueva_contrasena.html", reset_error="La contraseña debe tener al menos 8 caracteres."), 400
        if password != confirmation:
            return render_template("nueva_contrasena.html", reset_error="Las contraseñas no coinciden."), 400
        try:
            updated = complete_password_reset(
                token_hash,
                token_record["user_id"],
                generate_password_hash(password),
            )
        except Exception:
            updated = False
        if updated:
            record_history(
                {
                    "username": token_record["username"],
                },
                "Cambió su contraseña mediante recuperación",
                token_record["module_number"],
                "contrasena",
            )
            return render_template("nueva_contrasena.html", reset_success="Tu contraseña fue actualizada. Ya puedes iniciar sesión.")
        return render_template("nueva_contrasena.html", reset_error="No fue posible actualizar la contraseña."), 400
    return render_template("nueva_contrasena.html")


@app.get("/administrador")
def admin_dashboard():
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    try:
        initialize_schema()
        modules = request_modules()
        controllers = fetch_controllers()
        grouped_controllers = [
            {
                "module_number": module["id"],
                "module_name": module["nombre"],
                "controllers": [controller for controller in controllers if controller["mod1"] == module["id"]],
            }
            for module in modules
        ]
    except Exception:
        modules = []
        grouped_controllers = []

    return render_template(
        "admin/dashboard.html",
        account=account,
        modules=modules,
        grouped_controllers=grouped_controllers,
    )


@app.get("/administrador/rol-mensual")
def admin_monthly_role_page():
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    try:
        initialize_schema()
        modules = request_modules()
    except Exception:
        modules = []
    return render_template("admin/rol_mensual.html", account=account, modules=modules)


@app.get("/administrador/historial")
def admin_history_page():
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    try:
        initialize_schema()
        entries = fetch_history_entries()
    except Exception:
        entries = []
    return render_template("admin/historial.html", account=account, entries=entries)


@app.route("/administrador/rol-mensual/<int:module_number>/estado", methods=["GET", "POST"])
def admin_monthly_role_status(module_number: int):
    account = session.get("account")
    if not account or module_number not in range(1, MAX_MODULES + 1):
        return jsonify(error="No autorizado."), 403
    if request.method == "POST" and not account.get("is_admin"):
        return jsonify(error="No autorizado."), 403
    if request.method == "GET" and not account.get("is_admin") and account.get("module_number") != module_number:
        return jsonify(error="No autorizado."), 403
    source = request.args if request.method == "GET" else request.form
    month = source.get("month", type=int)
    year = source.get("year", type=int)
    if not month or not year or not 1 <= month <= 12 or year < 1:
        return jsonify(error="El mes o el año no son válidos."), 400
    if request.method == "GET":
        return jsonify({"activo": get_monthly_role_activation(module_number, month, year)})
    active = request.form.get("activo") == "true"
    try:
        initialize_schema()
        result = set_monthly_role_activation(module_number, month, year, active)
        record_history(
            account,
            f"{'Activó' if active else 'Desactivó'} el mes {month:02d}/{year}",
            module_number,
            "activacion",
        )
        return jsonify({"activo": result})
    except Exception as error:
        return jsonify(error=f"No se pudo cambiar el estado del mes: {error}"), 400


@app.get("/administrador/controladores")
def admin_controllers_page():
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    edit_controller_id = request.args.get("edit_id", type=int)
    try:
        initialize_schema()
        modules = request_modules()
        controllers = fetch_controllers()
        grouped_controllers = [
            {
                "module_number": module["id"],
                "module_name": module["nombre"],
                "controllers": [controller for controller in controllers if controller["mod1"] == module["id"]],
            }
            for module in modules
        ]
    except Exception:
        modules = []
        grouped_controllers = []

    editing_controller = None
    if edit_controller_id:
        for group in grouped_controllers:
            for controller in group["controllers"]:
                if controller.get("id") == edit_controller_id:
                    editing_controller = controller
                    break
            if editing_controller:
                break

    return render_template(
        "admin/dashboard.html",
        account=account,
        modules=modules,
        grouped_controllers=grouped_controllers,
        editing_controller=editing_controller,
    )


@app.get("/administrador/usuarios")
def admin_users_page():
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    edit_user_id = request.args.get("edit_user_id", type=int)
    try:
        initialize_schema()
        modules = request_modules()
        users = fetch_users()
        users_by_module = {}
        for user in users:
            users_by_module.setdefault(user.get("module_number"), []).append(user)
        grouped_users = [
            {
                "module_number": module["id"],
                "module_name": module["nombre"],
                "users": users_by_module.get(module["id"], []),
            }
            for module in modules
        ]
        try:
            admin_users = fetch_admin_users()
        except Exception:
            app.logger.exception("No fue posible cargar los usuarios administradores")
            admin_users = []
    except Exception:
        app.logger.exception("No fue posible cargar los usuarios y módulos")
        modules = []
        grouped_users = []
        admin_users = []

    editing_user = None
    if edit_user_id:
        for group in grouped_users:
            for user in group["users"]:
                if user.get("id") == edit_user_id:
                    editing_user = user
                    break
            if editing_user:
                break
        if editing_user is None:
            editing_user = next((user for user in admin_users if user.get("id") == edit_user_id), None)

    return render_template(
        "admin/usuarios.html",
        account=account,
        grouped_users=grouped_users,
        modules=modules,
        editing_user=editing_user,
        admin_users=admin_users,
    )


@app.get("/administrador/modulos")
def admin_modules_page():
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    try:
        initialize_schema()
        modules = request_modules()
    except Exception:
        app.logger.exception("No fue posible cargar los módulos")
        modules = []
    return render_template("admin/modulos.html", account=account, modules=modules)


@app.post("/administrador/modulos")
def admin_create_module():
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    module_id = request.form.get("module_id")
    nombre = str(request.form.get("nombre", "")).strip()
    direccion = str(request.form.get("direccion", "")).strip()
    latitud = str(request.form.get("latitud", "")).strip()
    longitud = str(request.form.get("longitud", "")).strip()
    if not nombre or not direccion or not latitud or not longitud:
        flash("Nombre, dirección, latitud y longitud son obligatorios.", "error")
        return redirect(url_for("admin_modules_page"))
    try:
        latitud_value = float(latitud)
        longitud_value = float(longitud)
    except ValueError:
        flash("La latitud y la longitud deben ser valores numéricos.", "error")
        return redirect(url_for("admin_modules_page"))
    if not -90 <= latitud_value <= 90 or not -180 <= longitud_value <= 180:
        flash("La latitud debe estar entre -90 y 90, y la longitud entre -180 y 180.", "error")
        return redirect(url_for("admin_modules_page"))
    try:
        initialize_schema()
        if module_id:
            if update_module(int(module_id), nombre, direccion, latitud, longitud) is None:
                flash("No se encontró el módulo para actualizar.", "error")
            else:
                flash("Módulo actualizado correctamente.", "success")
        elif create_module(nombre, direccion, latitud, longitud) is None:
            flash("Ya existen los veinte módulos disponibles.", "error")
        else:
            flash("Módulo creado correctamente.", "success")
    except Exception:
        flash("No se pudo guardar el módulo. Verifica que el nombre no esté repetido.", "error")
    return redirect(url_for("admin_modules_page"))


@app.post("/administrador/modulos/<int:module_id>/eliminar")
def admin_delete_module(module_id: int):
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    try:
        initialize_schema()
        result = delete_module(module_id)
        if result == "in_use":
            flash("No se puede eliminar un módulo que tiene datos asociados.", "error")
        elif result == "deleted":
            flash("Módulo eliminado correctamente.", "success")
        else:
            flash("No se encontró el módulo para eliminar.", "error")
    except Exception:
        flash("No se pudo eliminar el módulo.", "error")
    return redirect(url_for("admin_modules_page"))


@app.get("/administrador/rutas")
def admin_routes_page():
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    edit_route_id = request.args.get("edit_id", type=int)
    try:
        initialize_schema()
        modules = request_modules()
        grouped_routes = [
            {
                "module_number": module["id"],
                "module_name": module["nombre"],
                "routes": fetch_routes(module["id"]),
            }
            for module in modules
        ]
        tipos_rutas = fetch_catalog_items("tipos_rutas")
        servicios = fetch_catalog_items("servicio")
    except Exception:
        modules = []
        grouped_routes = []
        tipos_rutas = []
        servicios = []
    editing_route = None
    if edit_route_id:
        for group in grouped_routes:
            for route in group["routes"]:
                if route.get("id") == edit_route_id and not route.get("is_external"):
                    editing_route = route
                    break
            if editing_route:
                break
    shared_modules = []
    if editing_route:
        try:
            shared_modules = fetch_shared_modules(editing_route["id"])
        except Exception:
            shared_modules = []
    return render_template(
        "admin/rutas.html",
        account=account,
        modules=modules,
        grouped_routes=grouped_routes,
        editing_route=editing_route,
        shared_modules=shared_modules,
        tipos_rutas=tipos_rutas,
        servicios=servicios,
    )


@app.get("/administrador/analisis")
def admin_analysis_page():
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    try:
        initialize_schema()
        modules = request_modules()
        metrics = fetch_analysis_metrics()
    except Exception:
        app.logger.exception("No fue posible cargar las métricas de análisis")
        metrics = {
            "users": 0,
            "admins": 0,
            "controllers": 0,
            "active_controllers": 0,
            "routes": 0,
            "active_routes": 0,
            "inactive_routes": 0,
            "gender_distribution": [],
            "route_usage": [],
            "shared_routes": [],
            "controller_days": [],
            "shift_usage": [],
            "most_controllers": None,
        }
    return render_template("admin/analisis.html", account=account, modules=modules, metrics=metrics)


@app.post("/administrador/rutas")
def admin_create_route():
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))

    payload = {field: str(request.form.get(field, "")).strip() for field in ("ruta", "origen", "destino", "servicio", "estado")}
    route_id = request.form.get("route_id")
    tipos_raw = str(request.form.get("tipos", "")).strip()
    try:
        payload["tipos"] = int(tipos_raw) if tipos_raw else None
    except (TypeError, ValueError):
        flash("Selecciona un tipo de ruta válido.", "error")
        return redirect(url_for("admin_routes_page"))
    try:
        module_number = int(request.form.get("mod1", "1"))
    except (TypeError, ValueError):
        flash("Selecciona un módulo válido.", "error")
        return redirect(url_for("admin_routes_page"))
    if module_number not in range(1, MAX_MODULES + 1) or any(not payload[field] for field in ("ruta", "origen", "destino", "servicio")):
        flash("Completa los datos de la ruta y selecciona un módulo válido.", "error")
        return redirect(url_for("admin_routes_page"))
    try:
        shared_modules = sorted({int(value) for value in request.form.getlist("shared_modules")})
    except (TypeError, ValueError):
        flash("Los módulos compartidos no son válidos.", "error")
        return redirect(url_for("admin_routes_page"))
    if any(shared_module not in range(1, MAX_MODULES + 1) for shared_module in shared_modules):
        flash("Los módulos compartidos no son válidos.", "error")
        return redirect(url_for("admin_routes_page"))
    shared_modules = [shared_module for shared_module in shared_modules if shared_module != module_number]

    try:
        initialize_schema()
        if route_id:
            previously_shared = set(fetch_shared_modules(int(route_id)))
            saved = update_admin_route(int(route_id), {**payload, "mod1": module_number})
            if saved is None:
                flash("No se encontró la ruta para actualizar.", "error")
                return redirect(url_for("admin_routes_page"))
            else:
                flash("Ruta actualizada correctamente.", "success")
            for shared_module in previously_shared - set(shared_modules):
                unlink_route_from_module(int(saved["id"]), shared_module)
        else:
            saved = create_route(payload, module_number)
            record_history(
                account,
                f"Registró ruta {saved.get('ruta', payload['ruta'])} (de Rutas)",
                module_number,
                "registro",
                f"Ruta: {saved.get('ruta', payload['ruta'])}; Origen: {saved.get('origen', payload['origen'])}; Destino: {saved.get('destino', payload['destino'])}; Servicio: {saved.get('servicio', payload['servicio'])}",
            )
            flash("Ruta creada correctamente.", "success")
        for shared_module in shared_modules:
            link_route_to_module(int(saved["id"]), shared_module)
    except Exception:
        flash("No se pudo guardar la ruta. Verifica los datos.", "error")
    return redirect(url_for("admin_routes_page"))


@app.post("/administrador/rutas/<int:route_id>/eliminar")
def admin_delete_route(route_id: int):
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    try:
        initialize_schema()
        flash("Ruta eliminada correctamente." if delete_route(route_id) else "No se encontró la ruta para eliminar.", "success")
    except Exception:
        flash("No se pudo eliminar la ruta.", "error")
    return redirect(url_for("admin_routes_page"))


@app.post("/administrador/rutas/<int:route_id>/estado")
def admin_toggle_route_status(route_id: int):
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))

    requested_status = str(request.form.get("estado", "")).strip()
    if requested_status not in {"Activo", "Inactivo"}:
        flash("El estado de la ruta no es válido.", "error")
        return redirect(url_for("admin_routes_page"))

    try:
        initialize_schema()
        updated_route = update_route_status(route_id, requested_status)
        if updated_route is None:
            flash("No se encontró la ruta para actualizar.", "error")
        else:
            flash(f"Ruta {requested_status.lower()} correctamente.", "success")
    except Exception:
        flash("No se pudo cambiar el estado de la ruta.", "error")
    return redirect(url_for("admin_routes_page"))


@app.post("/administrador/rutas/<int:route_id>/modulo/<int:module_number>/estado")
def admin_toggle_shared_route_status(route_id: int, module_number: int):
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    requested_status = str(request.form.get("estado", "")).strip()
    if module_number not in range(1, MAX_MODULES + 1) or requested_status not in {"Activo", "Inactivo"}:
        flash("Los datos de la ruta compartida no son válidos.", "error")
        return redirect(url_for("admin_routes_page"))
    try:
        initialize_schema()
        updated_route = update_module_route_status(route_id, module_number, requested_status)
        if updated_route is None:
            flash("No se encontró la ruta compartida.", "error")
        else:
            flash(f"Ruta compartida {requested_status.lower()} correctamente.", "success")
    except Exception:
        flash("No se pudo cambiar el estado de la ruta compartida.", "error")
    return redirect(url_for("admin_routes_page"))


@app.post("/administrador/rutas/<int:route_id>/modulo/<int:module_number>/desvincular")
def admin_unlink_shared_route(route_id: int, module_number: int):
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    if module_number not in range(1, MAX_MODULES + 1):
        flash("El módulo de la ruta compartida no es válido.", "error")
        return redirect(url_for("admin_routes_page"))
    try:
        initialize_schema()
        if unlink_route_from_module(route_id, module_number):
            flash("Ruta desvinculada del módulo correctamente.", "success")
        else:
            flash("No se encontró la ruta compartida.", "error")
    except Exception:
        flash("No se pudo desvincular la ruta.", "error")
    return redirect(url_for("admin_routes_page"))


@app.get("/administrador/turnos")
def admin_turnos_page():
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    edit_turno_id = request.args.get("edit_id", type=int)
    try:
        initialize_schema()
        modules = request_modules()
        turnos = fetch_catalog_items("turnos")
        module_names = {module["id"]: module["nombre"] for module in modules}
        turno_modules = fetch_turno_modules_map([turno["id"] for turno in turnos])
        for turno in turnos:
            turno["modules"] = [
                module_names.get(module_id, f"Módulo {module_id}")
                for module_id in turno_modules.get(turno["id"], [])
            ]
    except Exception:
        modules = []
        turnos = []
        turno_modules = {}
    editing_turno = next((turno for turno in turnos if turno.get("id") == edit_turno_id), None) if edit_turno_id else None
    selected_turno_modules = turno_modules.get(edit_turno_id, []) if editing_turno else []
    return render_template(
        "admin/turnos.html",
        account=account,
        turnos=turnos,
        editing_turno=editing_turno,
        modules=modules,
        selected_turno_modules=selected_turno_modules,
    )


@app.post("/administrador/turnos")
def admin_create_turno():
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))

    turno_id = request.form.get("turno_id")
    numero = str(request.form.get("numero", "")).strip()
    hora_inicio = str(request.form.get("hora_inicio", "")).strip()
    hora_fin = str(request.form.get("hora_fin", "")).strip()
    activo = request.form.get("activo") == "on"
    selected_modules = sorted({int(value) for value in request.form.getlist("turno_modules") if value.isdigit()})
    if any(module_number not in range(1, MAX_MODULES + 1) for module_number in selected_modules):
        flash("Selecciona módulos válidos para el turno.", "error")
        return redirect(url_for("admin_turnos_page"))

    if not numero.isdigit() or not hora_inicio or not hora_fin:
        flash("Completa el número de turno y ambas horas.", "error")
        return redirect(url_for("admin_turnos_page"))

    payload = {"numero": int(numero), "hora_inicio": hora_inicio, "hora_fin": hora_fin, "activo": activo}

    try:
        initialize_schema()
        if turno_id:
            updated_turno = update_catalog_item("turnos", int(turno_id), payload)
            if updated_turno is None:
                flash("No se encontró el turno para actualizar.", "error")
                return redirect(url_for("admin_turnos_page"))
            set_turno_modules(int(turno_id), selected_modules)
            flash("Turno actualizado correctamente.", "success")
        else:
            created_turno = create_catalog_item("turnos", payload)
            set_turno_modules(created_turno["id"], selected_modules)
            flash("Turno registrado correctamente.", "success")
    except Exception:
        flash("No se pudo guardar el turno. Verifica que el número no esté repetido.", "error")

    return redirect(url_for("admin_turnos_page"))


@app.post("/administrador/turnos/<int:turno_id>/eliminar")
def admin_delete_turno(turno_id: int):
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    try:
        initialize_schema()
        if delete_catalog_item("turnos", turno_id):
            flash("Turno eliminado correctamente.", "success")
        else:
            flash("No se encontró el turno para eliminar.", "error")
    except Exception:
        flash("No se pudo eliminar el turno.", "error")
    return redirect(url_for("admin_turnos_page"))


@app.post("/administrador/turnos/<int:turno_id>/estado")
def admin_toggle_turno_status(turno_id: int):
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    requested_status = str(request.form.get("estado", "")).strip()
    if requested_status not in {"Activo", "Inactivo"}:
        flash("El estado del turno no es válido.", "error")
        return redirect(url_for("admin_turnos_page"))
    try:
        initialize_schema()
        updated_shift = update_shift_status(turno_id, requested_status == "Activo")
        if updated_shift is None:
            flash("No se encontró el turno para actualizar.", "error")
        else:
            flash(f"Turno {requested_status.lower()} correctamente.", "success")
    except Exception:
        flash("No se pudo cambiar el estado del turno.", "error")
    return redirect(url_for("admin_turnos_page"))


@app.get("/administrador/tipos-rutas")
def admin_tipos_rutas_page():
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    edit_tipo_id = request.args.get("edit_id", type=int)
    try:
        initialize_schema()
        modules = request_modules()
        tipos_rutas = fetch_catalog_items("tipos_rutas")
        estados_especiales = fetch_catalog_items("estados_especiales")
        servicios = fetch_catalog_items("servicio")
    except Exception:
        modules = []
        tipos_rutas = []
        estados_especiales = []
        servicios = []
    editing_tipo_ruta = next((tipo for tipo in tipos_rutas if tipo.get("id") == edit_tipo_id), None) if edit_tipo_id else None
    edit_estado_id = request.args.get("edit_estado_id", type=int)
    editing_estado_especial = next((item for item in estados_especiales if item.get("id") == edit_estado_id), None) if edit_estado_id else None
    edit_servicio_id = request.args.get("edit_servicio_id", type=int)
    editing_servicio = next((item for item in servicios if item.get("id") == edit_servicio_id), None) if edit_servicio_id else None
    return render_template(
        "admin/tipos_rutas.html",
        account=account,
        modules=modules,
        tipos_rutas=tipos_rutas,
        editing_tipo_ruta=editing_tipo_ruta,
        estados_especiales=estados_especiales,
        editing_estado_especial=editing_estado_especial,
        servicios=servicios,
        editing_servicio=editing_servicio,
    )


@app.post("/administrador/tipos-rutas")
def admin_create_tipo_ruta():
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))

    catalog = request.form.get("catalog", "tipos_rutas")
    if catalog == "estados_especiales":
        estado_id = request.form.get("estado_id")
        codigo = str(request.form.get("codigo", "")).strip().upper()
        descripcion = str(request.form.get("descripcion", "")).strip()
        activo = request.form.get("activo") == "on"
        if not codigo or not descripcion:
            flash("El código y la descripción del estado especial son obligatorios.", "error")
            return redirect(url_for("admin_tipos_rutas_page"))
        payload = {"codigo": codigo, "descripcion": descripcion, "activo": activo}
        try:
            initialize_schema()
            if estado_id:
                update_catalog_item("estados_especiales", int(estado_id), payload)
                flash("Estado especial actualizado correctamente.", "success")
            else:
                create_catalog_item("estados_especiales", payload)
                flash("Estado especial registrado correctamente.", "success")
        except Exception:
            flash("No se pudo guardar el estado especial. Verifica que el código no esté repetido.", "error")
        return redirect(url_for("admin_tipos_rutas_page"))

    if catalog == "servicio":
        servicio_id = request.form.get("servicio_id")
        nombre = str(request.form.get("nombre", "")).strip()
        if not nombre:
            flash("El nombre del servicio es obligatorio.", "error")
            return redirect(url_for("admin_tipos_rutas_page"))
        try:
            initialize_schema()
            if servicio_id:
                updated_servicio = update_catalog_item("servicio", int(servicio_id), {"nombre": nombre})
                if updated_servicio is None:
                    flash("No se encontró el servicio para actualizar.", "error")
                else:
                    flash("Servicio actualizado correctamente.", "success")
            else:
                create_catalog_item("servicio", {"nombre": nombre})
                flash("Servicio registrado correctamente.", "success")
        except Exception:
            flash("No se pudo guardar el servicio. Verifica que el nombre no esté repetido.", "error")
        return redirect(url_for("admin_tipos_rutas_page"))

    tipo_id = request.form.get("tipo_id")
    descripcion = str(request.form.get("descripcion", "")).strip()

    if not descripcion:
        flash("La descripción del tipo de ruta es obligatoria.", "error")
        return redirect(url_for("admin_tipos_rutas_page"))

    payload = {"descripcion": descripcion}

    try:
        initialize_schema()
        if tipo_id:
            updated_tipo = update_catalog_item("tipos_rutas", int(tipo_id), payload)
            if updated_tipo is None:
                flash("No se encontró el tipo de ruta para actualizar.", "error")
                return redirect(url_for("admin_tipos_rutas_page"))
            flash("Tipo de ruta actualizado correctamente.", "success")
        else:
            create_catalog_item("tipos_rutas", payload)
            flash("Tipo de ruta registrado correctamente.", "success")
    except Exception:
        flash("No se pudo guardar el tipo de ruta. Verifica que la descripción no esté repetida.", "error")

    return redirect(url_for("admin_tipos_rutas_page"))


@app.post("/administrador/tipos-rutas/<int:tipo_id>/eliminar")
def admin_delete_tipo_ruta(tipo_id: int):
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    try:
        initialize_schema()
        if delete_catalog_item("tipos_rutas", tipo_id):
            flash("Tipo de ruta eliminado correctamente.", "success")
        else:
            flash("No se encontró el tipo de ruta para eliminar.", "error")
    except Exception:
        flash("No se pudo eliminar el tipo de ruta.", "error")
    return redirect(url_for("admin_tipos_rutas_page"))


@app.post("/administrador/estados-especiales/<int:estado_id>/eliminar")
def admin_delete_estado_especial(estado_id: int):
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    try:
        initialize_schema()
        if delete_catalog_item("estados_especiales", estado_id):
            flash("Estado especial eliminado correctamente.", "success")
        else:
            flash("No se encontró el estado especial para eliminar.", "error")
    except Exception:
        flash("No se pudo eliminar el estado especial.", "error")
    return redirect(url_for("admin_tipos_rutas_page"))


@app.post("/administrador/servicios/<int:servicio_id>/eliminar")
def admin_delete_servicio(servicio_id: int):
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    try:
        initialize_schema()
        if delete_catalog_item("servicio", servicio_id):
            flash("Servicio eliminado correctamente.", "success")
        else:
            flash("No se encontró el servicio para eliminar.", "error")
    except Exception:
        flash("No se pudo eliminar el servicio.", "error")
    return redirect(url_for("admin_tipos_rutas_page"))


@app.post("/administrador/controladores")
def admin_create_controller():
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))


    payload = {
        "nombre": str(request.form.get("nombre", "")).strip(),
        "credencial": str(request.form.get("credencial", "")).strip(),
        "sexo": str(request.form.get("sexo", "")).strip(),
        "mod1": int(request.form.get("mod1", 1) or 1),
    }

    controller_id = request.form.get("controller_id")
    if any(not value for value in payload.values()):
        flash("Completa todos los campos del controlador.", "error")
        return redirect(url_for("admin_controllers_page"))

    try:
        initialize_schema()
        if controller_id:
            updated_controller = update_controller(int(controller_id), payload)
            if updated_controller is None:
                flash("No se encontró el controlador para actualizar.", "error")
                return redirect(url_for("admin_controllers_page"))
            record_history(
                account,
                f"Editó controlador {updated_controller['credencial']} (de Controladores)",
                updated_controller["mod1"],
                "edicion",
                f"Nombre: {updated_controller['nombre']}; Credencial: {updated_controller['credencial']}; Sexo: {updated_controller['sexo']}",
            )
            flash("Controlador actualizado correctamente.", "success")
        else:
            created_controller = create_controller(payload)
            record_history(
                account,
                f"Registró controlador {payload['credencial']} (de Controladores)",
                payload["mod1"],
                "registro",
                f"Nombre: {created_controller.get('nombre', payload['nombre'])}; Credencial: {payload['credencial']}; Sexo: {payload['sexo']}",
            )
            flash("Controlador registrado correctamente.", "success")
    except Exception:
        flash("No se pudo guardar el controlador. Verifica que la credencial no esté repetida.", "error")

    return redirect(url_for("admin_controllers_page"))


@app.post("/administrador/controladores/<int:controller_id>/eliminar")
def admin_delete_controller(controller_id: int):
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    try:
        initialize_schema()
        controller = None
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT nombre, credencial, sexo, mod1 FROM catalogos.controladores WHERE id = %s",
                    (controller_id,),
                )
                controller = cursor.fetchone()
        if delete_controller(controller_id):
            if controller:
                record_history(
                    account,
                    f"Eliminó controlador {controller[1]} (de Controladores)",
                    controller[3],
                    "eliminacion",
                    f"Nombre: {controller[0]}; Credencial: {controller[1]}; Sexo: {controller[2]}",
                )
            flash("Controlador eliminado correctamente.", "success")
        else:
            flash("No se encontró el controlador para eliminar.", "error")
    except Exception:
        flash("No se pudo eliminar el controlador.", "error")
    return redirect(url_for("admin_controllers_page"))


@app.post("/administrador/controladores/<int:controller_id>/estado")
def admin_toggle_controller_status(controller_id: int):
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    requested_status = str(request.form.get("estado", "")).strip()
    if requested_status not in {"Activo", "Inactivo"}:
        flash("El estado del controlador no es válido.", "error")
        return redirect(url_for("admin_controllers_page"))
    try:
        initialize_schema()
        updated_controller = update_controller_status(controller_id, requested_status == "Activo")
        if updated_controller is None:
            flash("No se encontró el controlador para actualizar.", "error")
        else:
            flash(f"Controlador {requested_status.lower()} correctamente.", "success")
    except Exception:
        flash("No se pudo cambiar el estado del controlador.", "error")
    return redirect(url_for("admin_controllers_page"))


@app.post("/administrador/usuarios")
def admin_create_user():
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))

    username = str(request.form.get("username", "")).strip().lower()
    password = str(request.form.get("password", "")).strip()
    correo = str(request.form.get("correo", "")).strip() or None
    telefono = str(request.form.get("telefono", "")).strip() or None
    tipo_usuario = str(request.form.get("tipo_usuario", "usuario")).strip().lower()
    if tipo_usuario not in {"usuario", "admin"}:
        flash("Selecciona un tipo de usuario válido.", "error")
        return redirect(url_for("admin_users_page"))
    module_number = None
    if tipo_usuario == "usuario":
        try:
            module_number = int(request.form.get("module_number", 1) or 1)
        except (TypeError, ValueError):
            flash("Selecciona un módulo válido.", "error")
            return redirect(url_for("admin_users_page"))
    user_id = request.form.get("user_id")

    if not username:
        flash("El nombre de usuario es obligatorio.", "error")
        return redirect(url_for("admin_users_page"))
    if tipo_usuario == "usuario" and module_number not in range(1, MAX_MODULES + 1):
        flash("Selecciona un módulo válido.", "error")
        return redirect(url_for("admin_users_page"))
    if not user_id and not password:
        flash("La contraseña es obligatoria para crear un usuario.", "error")
        return redirect(url_for("admin_users_page"))

    try:
        initialize_schema()
        payload = {
            "username": username,
            "correo": correo,
            "telefono": telefono,
            "module_number": module_number,
            "is_admin": tipo_usuario == "admin",
            "tipo_usuario": tipo_usuario,
        }
        if user_id:
            if password:
                payload["password_hash"] = generate_password_hash(password)
            updated_user = update_user(int(user_id), payload)
            if updated_user is None:
                flash("No se encontró el usuario para actualizar.", "error")
                return redirect(url_for("admin_users_page"))
            flash("Usuario actualizado correctamente.", "success")
        else:
            create_user({
                **payload,
                "password_hash": generate_password_hash(password),
            })
            flash("Usuario creado correctamente.", "success")
    except Exception:
        flash("No se pudo guardar el usuario. Verifica que los datos no estén repetidos.", "error")

    return redirect(url_for("admin_users_page"))


@app.post("/administrador/usuarios/<int:user_id>/eliminar")
def admin_delete_user(user_id: int):
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    try:
        initialize_schema()
        if delete_user(user_id):
            flash("Usuario eliminado correctamente.", "success")
        else:
            flash("No se encontró el usuario para eliminar.", "error")
    except Exception:
        flash("No se pudo eliminar el usuario.", "error")
    return redirect(url_for("admin_users_page"))


@app.get("/modulo/<int:module_number>")
def module_dashboard(module_number: int):
    account = session.get("account")
    if not account or (not account.get("is_admin") and account.get("module_number") != module_number):
        return redirect(url_for("connection_status"))
    try:
        initialize_schema()
        controllers = fetch_controllers(module_number, active_only=True)
    except Exception:
        controllers = []
    return render_template("creacion_de_controladores.html", module_number=module_number, controllers=controllers, account=account)


@app.get("/modulo/<int:module_number>/rutas")
def routes_dashboard(module_number: int):
    account = session.get("account")
    if not account or account.get("is_admin") or account.get("module_number") != module_number:
        return redirect(url_for("connection_status"))
    try:
        initialize_schema()
        routes = fetch_routes(module_number)
        tipos_rutas = fetch_catalog_items("tipos_rutas")
    except Exception:
        routes = []
        tipos_rutas = []
    return render_template("RUT.html", module_number=module_number, account=account, routes=routes)


@app.get("/api/modulos/<int:module_number>/controladores")
def module_controllers(module_number: int):
    if not module_authorized(module_number):
        return jsonify(error="No autorizado."), 403
    try:
        initialize_schema()
        return jsonify(fetch_controllers(module_number, active_only=True))
    except Exception as error:
        return jsonify(error=str(error)), 500


@app.get("/api/modulos/<int:module_number>/rutas-registradas")
def registered_module_routes(module_number: int):
    if not module_authorized(module_number):
        return jsonify(error="No autorizado."), 403
    try:
        initialize_schema()
        return jsonify(fetch_routes(module_number))
    except Exception as error:
        return jsonify(error=str(error)), 500


def module_authorized(module_number: int) -> bool:
    account = session.get("account")
    return bool(account and (account.get("is_admin") or account.get("module_number") == module_number))


@app.post("/modulo/<int:module_number>/rutas")
def add_route(module_number: int):
    if not module_authorized(module_number):
        return jsonify(error="No autorizado."), 403
    payload = request.get_json(silent=True) or {}
    required = ("ruta", "origen", "destino", "servicio")
    if any(not str(payload.get(field, "")).strip() for field in required):
        return jsonify(error="Completa todos los campos de la ruta."), 400
    try:
        tipos_value = payload.get("tipos")
        payload["tipos"] = int(tipos_value) if tipos_value not in (None, "") else None
    except (TypeError, ValueError):
        return jsonify(error="Selecciona un tipo de ruta válido."), 400
    try:
        initialize_schema()
        route = create_route({**payload, "nomenclatura": payload.get("nomenclatura", "R")}, module_number)
        return jsonify(route), 201
    except Exception as error:
        return jsonify(error=str(error)), 400


@app.route("/api/rutas/<int:route_id>", methods=["PUT", "PATCH", "DELETE"])
def route_item(route_id: int):
    account = session.get("account")
    if not account or account.get("is_admin"):
        return jsonify(error="No autorizado."), 403
    try:
        initialize_schema()
        if request.method == "DELETE":
            if not delete_route(route_id):
                return jsonify(error="Ruta no encontrada."), 404
            return jsonify(ok=True)
        payload = request.get_json(silent=True) or {}
        if request.method == "PATCH":
            result = update_route_status(route_id, payload.get("estado", "Activo"))
        else:
            required = ("ruta", "origen", "destino", "servicio")
            if any(not str(payload.get(field, "")).strip() for field in required):
                return jsonify(error="Completa todos los campos de la ruta."), 400
            try:
                tipos_value = payload.get("tipos")
                payload["tipos"] = int(tipos_value) if tipos_value not in (None, "") else None
            except (TypeError, ValueError):
                return jsonify(error="Selecciona un tipo de ruta válido."), 400
            result = update_route(route_id, {"id": route_id, **payload, "nomenclatura": payload.get("nomenclatura", "R")})
        if result is None:
            return jsonify(error="Ruta no encontrada."), 404
        return jsonify(result)
    except Exception as error:
        return jsonify(error=str(error)), 400


@app.get("/api/modulos/<int:module_number>/rutas-externas")
def external_routes(module_number: int):
    if not module_authorized(module_number):
        return jsonify(error="No autorizado."), 403
    try:
        initialize_schema()
        return jsonify(fetch_external_routes(module_number, request.args.get("q", "").strip(), request.args.get("origen_id", type=int)))
    except Exception as error:
        return jsonify(error=str(error)), 500


@app.post("/api/modulos/<int:module_number>/rutas/vincular")
def link_external_route(module_number: int):
    if not module_authorized(module_number):
        return jsonify(error="No autorizado."), 403
    payload = request.get_json(silent=True) or {}
    try:
        initialize_schema()
        return jsonify(link_route_to_module(int(payload["ruta_id"]), module_number)), 201
    except (KeyError, ValueError) as error:
        return jsonify(error=str(error)), 400
    except Exception as error:
        return jsonify(error=str(error)), 500


@app.patch("/api/modulos/<int:module_number>/rutas/<int:route_id>/estado")
def external_route_status(module_number: int, route_id: int):
    if not module_authorized(module_number):
        return jsonify(error="No autorizado."), 403
    payload = request.get_json(silent=True) or {}
    try:
        initialize_schema()
        result = update_module_route_status(route_id, module_number, payload.get("estado", "Activo"))
        return jsonify(result) if result else (jsonify(error="Ruta no vinculada."), 404)
    except Exception as error:
        return jsonify(error=str(error)), 400


@app.delete("/api/modulos/<int:module_number>/rutas/<int:route_id>/desvincular")
def unlink_external_route(module_number: int, route_id: int):
    if not module_authorized(module_number):
        return jsonify(error="No autorizado."), 403
    try:
        initialize_schema()
        if not unlink_route_from_module(route_id, module_number):
            return jsonify(error="Ruta no vinculada."), 404
        return jsonify(ok=True, deleted=True)
    except Exception as error:
        return jsonify(error=str(error)), 400


@app.get("/modulo/<int:module_number>/mas")
def more_dashboard(module_number: int):
    account = session.get("account")
    if not account or account.get("is_admin") or account.get("module_number") != module_number:
        return redirect(url_for("connection_status"))
    return render_template("turnos.html", module_number=module_number, account=account)


CATALOG_FIELDS = {
    "nomenclaturas": ("nomenclatura",),
    "turnos": ("numero", "hora_inicio", "hora_fin"),
    "estados_especiales": ("codigo", "descripcion"),
}
READ_ONLY_CATALOGS = {"estados_especiales"}


def catalog_authorized() -> bool:
    account = session.get("account")
    return bool(account and (account.get("is_admin") or account.get("module_number")))


@app.route("/api/catalogos/<string:catalog>", methods=["GET", "POST"])
def catalog_collection(catalog: str):
    account = session.get("account")
    if not catalog_authorized() or catalog not in CATALOG_FIELDS:
        return jsonify(error="No autorizado o catálogo no válido."), 403
    if request.method == "GET":
        try:
            initialize_schema()
            return jsonify(fetch_catalog_items(catalog, account.get("module_number") if catalog == "turnos" else None))
        except Exception as error:
            return jsonify(error=str(error)), 500
    if catalog in READ_ONLY_CATALOGS:
        return jsonify(error="Este catálogo es de solo lectura."), 405
    payload = request.get_json(silent=True) or {}
    missing = [field for field in CATALOG_FIELDS[catalog] if str(payload.get(field, "")).strip() == ""]
    if missing:
        return jsonify(error="Completa todos los campos requeridos."), 400
    try:
        initialize_schema()
        item = create_catalog_item(catalog, payload)
        return jsonify(item), 201
    except Exception as error:
        return jsonify(error=str(error)), 400


@app.route("/api/catalogos/<string:catalog>/<int:item_id>", methods=["PUT", "DELETE"])
def catalog_item(catalog: str, item_id: int):
    if not catalog_authorized() or catalog not in CATALOG_FIELDS:
        return jsonify(error="No autorizado o catálogo no válido."), 403
    if catalog in READ_ONLY_CATALOGS:
        return jsonify(error="Este catálogo es de solo lectura."), 405
    try:
        initialize_schema()
        if request.method == "DELETE":
            if not delete_catalog_item(catalog, item_id):
                return jsonify(error="Registro no encontrado."), 404
            return jsonify(ok=True)
        payload = request.get_json(silent=True) or {}
        missing = [field for field in CATALOG_FIELDS[catalog] if str(payload.get(field, "")).strip() == ""]
        if missing:
            return jsonify(error="Completa todos los campos requeridos."), 400
        item = update_catalog_item(catalog, item_id, payload)
        if item is None:
            return jsonify(error="Registro no encontrado."), 404
        return jsonify(item)
    except Exception as error:
        return jsonify(error=str(error)), 400


@app.get("/modulo/<int:module_number>/rol")
def schedule_dashboard(module_number: int):
    account = session.get("account")
    if not account or (not account.get("is_admin") and account.get("module_number") != module_number):
        return redirect(url_for("connection_status"))
    today = date.today()
    table_only = request.args.get("solo_tabla") == "1"
    admin_embed = request.args.get("admin_embed") == "1"
    month_activated = get_monthly_role_activation(module_number, today.month, today.year) if (table_only or admin_embed) else False
    return render_template(
        "rol_de_controladores.html",
        module_number=module_number,
        account=account,
        table_only=table_only,
        admin_embed=admin_embed,
        month_activated=month_activated,
        today={"year": today.year, "month": today.month, "day": today.day},
    )


@app.post("/modulo/<int:module_number>/controladores")
def add_controller(module_number: int):
    account = session.get("account")
    if not account or account.get("module_number") != module_number or account.get("is_admin"):
        return jsonify(error="No autorizado."), 403
    payload = {key: str(request.form.get(key, "")).strip() for key in ("nombre", "credencial", "sexo")}
    if any(not payload[key] for key in payload):
        return redirect(url_for("module_dashboard", module_number=module_number))
    payload["mod1"] = module_number
    created_controller = None
    existing_controller = None
    try:
        initialize_schema()
        existing_controller = fetch_controller_by_credential(payload["credencial"])
        if existing_controller:
            return redirect(url_for(
                "module_dashboard",
                module_number=module_number,
                controller_action="duplicate",
                controller_id=existing_controller["id"],
            ))
        created_controller = create_controller(payload)
        record_history(
            account,
            f"Registró controlador {created_controller['credencial']} (de Controladores)",
            module_number,
            "registro",
            f"Nombre: {created_controller['nombre']}; Credencial: {created_controller['credencial']}; Sexo: {created_controller['sexo']}",
        )
    except Exception:
        pass
    if created_controller:
        return redirect(url_for(
            "module_dashboard",
            module_number=module_number,
            controller_action="created",
            controller_id=created_controller["id"],
        ))
    return redirect(url_for("module_dashboard", module_number=module_number))


@app.route("/api/controladores/<int:controller_id>", methods=["PUT", "DELETE"])
def controller_item(controller_id: int):
    account = session.get("account")
    if not account or (not account.get("is_admin") and not account.get("module_number")):
        return jsonify(error="No autorizado."), 403
    try:
        initialize_schema()
        if request.method == "DELETE":
            controller = None
            try:
                with get_connection() as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT nombre, credencial, sexo, mod1 FROM catalogos.controladores WHERE id = %s",
                            (controller_id,),
                        )
                        controller = cursor.fetchone()
            except Exception:
                controller = None
            if not delete_controller(controller_id):
                return jsonify(error="Controlador no encontrado."), 404
            record_history(
                account,
                f"Eliminó controlador {controller[1] if controller else controller_id} (de Controladores)",
                controller[3] if controller else account.get("module_number"),
                "eliminacion",
                (
                    f"Nombre: {controller[0]}; Credencial: {controller[1]}; Sexo: {controller[2]}"
                    if controller
                    else f"ID del controlador: {controller_id}"
                ),
            )
            return jsonify(ok=True)

        payload = request.get_json(silent=True) or {}
        required = ("nombre", "credencial", "sexo")
        if any(not str(payload.get(field, "")).strip() for field in required):
            return jsonify(error="Completa todos los campos del controlador."), 400

        mod1 = int(payload.get("mod1", account.get("module_number", 1) or 1))
        if account.get("is_admin") and not payload.get("mod1"):
            mod1 = 1

        updated = update_controller(controller_id, {
            "nombre": str(payload["nombre"]).strip(),
            "credencial": str(payload["credencial"]).strip(),
            "sexo": str(payload["sexo"]).strip(),
            "mod1": mod1,
        })
        if updated is None:
            return jsonify(error="Controlador no encontrado."), 404
        record_history(
            account,
            f"Editó controlador {updated['credencial']} (de Controladores)",
            updated["mod1"],
            "edicion",
            f"Nombre: {updated['nombre']}; Credencial: {updated['credencial']}; Sexo: {updated['sexo']}",
        )
        return jsonify(updated)
    except Exception as error:
        return jsonify(error=str(error)), 400


@app.post("/logout")
def logout():
    account = session.get("account")
    if account:
        record_history(
            account,
            "Cierre de sesión",
            account.get("module_number"),
            "cierre_sesion",
        )
    session.clear()
    return redirect(url_for("connection_status"))


@app.get("/api/records")
def records():
    account = session.get("account")
    if not account:
        return jsonify(error="No autorizado."), 403
    today = date.today()
    month = request.args.get("month", today.month, type=int)
    year = request.args.get("year", today.year, type=int)
    module_number = requested_module_number(account)
    if not module_number:
        return jsonify(error="Falta el módulo del rol mensual."), 400
    return jsonify(records_for(month, year, module_number))


@app.post("/api/records/save-all")
def save_all_records():
    account = session.get("account")
    if not account:
        return jsonify(error="No autorizado."), 403
    payload = request.get_json(silent=True) or {}
    today = date.today()
    try:
        month = int(payload.get("month", today.month))
        year = int(payload.get("year", today.year))
    except (TypeError, ValueError):
        return jsonify(error="El mes o el año no son válidos."), 400
    module_number = requested_module_number(account, payload)
    if not module_number:
        return jsonify(error="Falta el módulo del rol mensual."), 400
    if monthly_role_is_closed(month, year, module_number):
        return jsonify(error="El mes seleccionado ya terminó y no permite modificaciones."), 409
    records = payload.get("records") or []
    if not isinstance(records, list):
        return jsonify(error="Los registros enviados no son válidos."), 400
    try:
        previous_records = records_for(month, year, module_number)
        initialize_schema()
        saved_count = save_month_records(records, module_number, month, year)
        previous_by_credential = {item.get("credential"): item for item in previous_records}
        changes = []
        for item in records:
            credential = str(item.get("credential", "")).strip()
            current = item
            detail = format_code_changes(previous_by_credential.get(credential), current)
            changes.append(f"{credential}: {detail}")
        current_credentials = {str(item.get("credential", "")).strip() for item in records}
        for credential, previous in previous_by_credential.items():
            if credential not in current_credentials:
                changes.append(f"{credential}: {format_code_changes(previous, None)}")
        history_action = "eliminacion" if not records and previous_records else (
            "edicion" if previous_records else "registro"
        )
        record_history(
            account,
            f"Guardó {saved_count} registro(s) del rol {month:02d}/{year} (de Asignación de Roles)",
            module_number,
            history_action,
            " | ".join(changes) if changes else "Sin registros con cambios de códigos",
        )
        return jsonify(ok=True, saved_count=saved_count)
    except Exception as error:
        return jsonify(error=f"No se pudieron guardar los registros: {error}"), 400


@app.post("/api/records")
def create_record():
    account = session.get("account")
    if not account:
        return jsonify(error="No autorizado."), 403
    payload = request.get_json(silent=True) or {}
    module_number = requested_module_number(account, payload)
    if not module_number:
        return jsonify(error="Falta el módulo del rol mensual."), 400
    required = ("name", "credential", "shift", "route", "nomenclature")
    if any(not str(payload.get(field, "")).strip() for field in required):
        return jsonify(error="Completa todos los datos del registro."), 400

    today = date.today()
    work_days = sorted({int(day) for day in payload.get("work_days", [])})
    rest_days = sorted({int(day) for day in payload.get("rest_days", [])})
    vacation_days = sorted({int(day) for day in payload.get("vacation_days", [])})
    vacation_days = [day for day in vacation_days if day not in work_days and day not in rest_days]
    daily_assignments = payload.get("daily_assignments") or {}
    if not isinstance(daily_assignments, dict):
        daily_assignments = {}
    normalized_assignments = {
        str(day): str(value).strip().upper() for day, value in daily_assignments.items()
    }
    month = int(payload.get("month", today.month))
    year = int(payload.get("year", today.year))
    if month < 1 or month > 12 or year < 1:
        return jsonify(error="El mes o el año no son válidos."), 400
    if monthly_role_is_closed(month, year, module_number):
        return jsonify(error="El mes seleccionado ya terminó y no permite agregar ni editar registros."), 409
    last_day = monthrange(year, month)[1]
    all_days = set(range(1, last_day + 1))
    if any(day not in all_days for day in (*work_days, *rest_days, *vacation_days)):
        return jsonify(error="Hay días que no pertenecen al mes seleccionado."), 400
    raw_details = payload.get("daily_details") or {}
    if not isinstance(raw_details, dict):
        raw_details = {}
    daily_details = {}
    for raw_day, detail in raw_details.items():
        try:
            day = int(raw_day)
        except (TypeError, ValueError):
            return jsonify(error="El detalle diario contiene un día inválido."), 400
        if day not in all_days or not isinstance(detail, dict):
            return jsonify(error="El detalle diario no es válido."), 400
        route = normalize_display_text(detail.get("route"))
        shift = str(detail.get("shift", "")).strip()
        nomenclature = str(detail.get("nomenclature", "")).strip().upper()
        if not route or not shift or not nomenclature:
            return jsonify(error="Completa ruta, turno y nomenclatura del día editado."), 400
        code = str(detail.get("code", f"{nomenclature}{shift}")).strip().upper()
        daily_details[str(day)] = {
            "route": route,
            "shift": shift,
            "nomenclature": nomenclature,
            "code": code,
        }
    try:
        deleted_days = sorted({int(day) for day in payload.get("deleted_days", [])})
    except (TypeError, ValueError):
        return jsonify(error="La lista de días eliminados no es válida."), 400
    if any(day not in all_days for day in deleted_days):
        return jsonify(error="Hay días eliminados que no pertenecen al mes seleccionado."), 400
    for day in deleted_days:
        normalized_assignments.pop(str(day), None)
        daily_details.pop(str(day), None)
    for day in vacation_days:
        normalized_assignments[str(day)] = "V"
    for day in [day for day in work_days if day not in deleted_days]:
        normalized_assignments.setdefault(str(day), f"{str(payload['nomenclature']).strip().upper()}{str(payload['shift']).strip()}")
    for day in rest_days:
        normalized_assignments.pop(str(day), None)
    final_work_days = [day for day in work_days if day not in vacation_days and day not in deleted_days]
    final_rest_days = [day for day in rest_days if day not in vacation_days and day not in deleted_days]
    record = {
        "name": normalize_display_text(payload["name"]),
        "credential": str(payload["credential"]).strip(),
        "shift": str(payload["shift"]).strip(),
        "route": normalize_display_text(payload["route"]),
        "nomenclature": str(payload["nomenclature"]).strip().upper(),
        "month": month,
        "year": year,
        "module_number": module_number,
        "work_days": json.dumps(final_work_days),
        "rest_days": json.dumps(final_rest_days),
        "daily_assignments": json.dumps(normalized_assignments),
        "daily_details": json.dumps(daily_details),
        "deleted_days": deleted_days,
    }
    existing_record = next(
        (
            item for item in memory_records
            if item["credential"] == record["credential"]
            and item["month"] == record["month"]
            and item["year"] == record["year"]
            and item.get("module_number") == record["module_number"]
        ),
        None,
    )
    previous_record = next(
        (item for item in records_for(month, year, module_number) if item.get("credential") == record["credential"]),
        None,
    )
    try:
        initialize_schema()
        saved = upsert_record(record)
    except Exception:
        if existing_record:
            existing_record.update({
                "name": record["name"],
                "shift": record["shift"],
                "route": record["route"],
                "nomenclature": record["nomenclature"],
                "month": record["month"],
                "year": record["year"],
                "module_number": record["module_number"],
                "work_days": [day for day in work_days if day not in vacation_days and day not in deleted_days],
                "rest_days": [day for day in rest_days if day not in vacation_days and day not in deleted_days],
                "daily_assignments": json.loads(record.get("daily_assignments") or "{}"),
                "daily_details": json.loads(record.get("daily_details") or "{}"),
            })
            for day in deleted_days:
                existing_record["daily_assignments"].pop(str(day), None)
                existing_record["daily_details"].pop(str(day), None)
            for day in rest_days:
                existing_record["daily_assignments"].pop(str(day), None)
            for day in vacation_days:
                existing_record["daily_assignments"][str(day)] = "V"
            for day in [item for item in work_days if item not in deleted_days]:
                existing_record["daily_assignments"].setdefault(str(day), f"{record['nomenclature']}{record['shift']}")
            saved = existing_record
        else:
            saved = next(
                (
                    item for item in memory_records
                    if item["credential"] == record["credential"]
                    and item["month"] == record["month"]
                    and item["year"] == record["year"]
                    and item.get("module_number") == record["module_number"]
                ),
                None,
            )
            if saved:
                merged_assignments = {
                    str(day): str(value).strip().upper()
                    for day, value in json.loads(record.get("daily_assignments", "{}") or "{}").items()
                    if int(day) not in set(record.get("deleted_days", []))
                }
                merged_details = {
                    str(day): value
                    for day, value in json.loads(record.get("daily_details", "{}") or "{}").items()
                    if int(day) not in set(record.get("deleted_days", []))
                }
                deleted_set = set(record.get("deleted_days", []))
                for day in deleted_set:
                    merged_assignments.pop(str(day), None)
                    merged_details.pop(str(day), None)
                for day in [item for item in work_days if item not in deleted_set]:
                    merged_assignments.setdefault(str(day), f"{record['nomenclature']}{record['shift']}")
                for day in rest_days:
                    merged_assignments.pop(str(day), None)
                for day in vacation_days:
                    merged_assignments[str(day)] = "V"
                saved.update({
                    "name": record["name"],
                    "shift": record["shift"],
                    "route": record["route"],
                    "nomenclature": record["nomenclature"],
                    "month": record["month"],
                    "year": record["year"],
                    "module_number": record["module_number"],
                    "work_days": [day for day in work_days if day not in vacation_days and day not in deleted_set],
                    "rest_days": [day for day in rest_days if day not in vacation_days and day not in deleted_set],
                    "daily_assignments": merged_assignments,
                    "daily_details": merged_details,
                })
            else:
                saved = {
                    key: value for key, value in record.items()
                    if key not in ("work_days", "rest_days", "daily_details", "deleted_days")
                }
                saved["id"] = len(memory_records) + 1
                saved["work_days"] = work_days
                saved["rest_days"] = rest_days
                saved["daily_assignments"] = json.loads(record.get("daily_assignments") or "{}")
                saved["daily_details"] = json.loads(record.get("daily_details") or "{}")
                saved["module_number"] = record["module_number"]
                memory_records.insert(0, saved)
    saved["updated_existing"] = previous_record is not None
    history_action = "edicion" if saved["updated_existing"] else "registro"
    record_history(
        account,
        f"{'Editó' if saved['updated_existing'] else 'Registró'} a {record['credential']} ({month:02d}/{year}) (de Asignación de Roles)",
        module_number,
        history_action,
        format_code_changes(previous_record, saved),
    )
    return jsonify(saved), 201


@app.post("/api/records/delete")
def delete_record_by_credential():
    account = session.get("account")
    if not account:
        return jsonify(error="No autorizado."), 403
    payload = request.get_json(silent=True) or {}
    credential = str(payload.get("credential", "")).strip()
    month = int(payload.get("month", date.today().month))
    year = int(payload.get("year", date.today().year))
    module_number = requested_module_number(account, payload)
    if not module_number:
        return jsonify(error="Falta el módulo del rol mensual."), 400
    if monthly_role_is_closed(month, year, module_number):
        return jsonify(error="El mes seleccionado ya terminó y no permite eliminar registros."), 409
    if not credential:
        return jsonify(error="Falta la credencial del registro."), 400
    previous_record = next(
        (item for item in records_for(month, year, module_number) if item.get("credential") == credential),
        None,
    )
    deleted = False
    try:
        initialize_schema()
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM schedule_records WHERE credential = %s AND month = %s AND year = %s AND module_number = %s",
                    (credential, month, year, module_number),
                )
                deleted = cursor.rowcount > 0
            connection.commit()
    except Exception:
        for item in list(memory_records):
            if item.get("credential") == credential and item.get("month") == month and item.get("year") == year and item.get("module_number") == module_number:
                memory_records.remove(item)
                deleted = True
    if deleted:
        record_history(
            account,
            f"Eliminó a {credential} ({month:02d}/{year}) (de Asignación de Roles)",
            module_number,
            "eliminacion",
            format_code_changes(previous_record, None),
        )
    return jsonify({"deleted": deleted, "credential": credential, "month": month, "year": year})


@app.get("/export/excel")
def export_excel():
    account = session.get("account")
    if not account:
        return jsonify(error="No autorizado."), 403
    month = request.args.get("month", type=int, default=date.today().month)
    year = request.args.get("year", type=int, default=date.today().year)
    module_number = requested_module_number(account)
    if not module_number:
        return jsonify(error="Falta el módulo del rol mensual."), 400
    records = records_for(month, year, module_number)
    try:
        initialize_schema()
        routes = fetch_routes(module_number)
    except Exception:
        routes = []
    output = build_turnos_excel(records, month, year, routes)
    filename = f"turnos_{month}_{year}.xlsx"
    record_history(account, f"Descargó Excel del rol {month:02d}/{year}", module_number, "descarga")
    return send_file(output, download_name=filename, as_attachment=True, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=not settings.is_production)
