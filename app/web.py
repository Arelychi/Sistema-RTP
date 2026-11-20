import json
import hashlib
import os
import re
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
    clear_history_for_module,
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
    delete_routes_from_module,
    delete_controllers_from_module,
    delete_users_by_ids,
    delete_turnos_by_ids,
    fetch_catalog_items,
    fetch_controllers,
    fetch_monthly_controller_workday_counts,
    fetch_controller_by_credential,
    fetch_records,
    fetch_external_routes,
    fetch_routes,
    fetch_shared_modules,
    fetch_shared_module_statuses,
    get_monthly_role_activation,
    fetch_turno_modules,
    fetch_turno_modules_map,
    fetch_turno_module_status_map,
    fetch_turno_module_statuses_map,
    get_next_turno_number,
    renumber_turnos_by_start,
    turno_start_exists,
    fetch_users,
    fetch_modules,
    fetch_history_entries,
    fetch_controller_analysis_dashboard,
    fetch_password_reset_token,
    get_connection,
    initialize_schema,
    manage_module_data,
    normalize_display_text,
    refresh_analysis_tables,
    update_admin_route,
    update_catalog_item,
    update_catalog_status,
    update_controller,
    update_controller_status,
    update_shift_status,
    update_turno_module_status,
    update_route,
    update_route_status,
    update_user,
    update_user_status,
    update_module,
    link_route_to_module,
    link_routes_to_module,
    update_module_route_status,
    unlink_route_from_module,
    upsert_record,
    upsert_records_atomically,
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
MONTH_NAMES_ES = (
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
)


def attach_monthly_workday_counts(
    grouped_controllers: list[dict],
    month: int,
    year: int,
) -> None:
    counts = fetch_monthly_controller_workday_counts(month, year)
    for group in grouped_controllers:
        module_number = int(group["module_number"])
        for controller in group["controllers"]:
            key = (str(controller["credencial"]), module_number)
            controller["monthly_assigned_days"] = counts.get(key, 0)


@app.errorhandler(500)
def handle_internal_server_error(error):
    if request.path.startswith("/api/"):
        original_error = getattr(error, "original_exception", None)
        if original_error is not None:
            app.logger.error(
                "Error interno no controlado en %s",
                request.path,
                exc_info=(
                    type(original_error),
                    original_error,
                    original_error.__traceback__,
                ),
            )
        return (
            jsonify(
                error=(
                    "Error interno del servidor al procesar la solicitud. "
                    "Revisa el registro de la aplicación."
                )
            ),
            500,
        )
    return error


def valid_controller_name(value: str) -> bool:
    return bool(re.fullmatch(r"[^\W\d_]+(?:\s+[^\W\d_]+)*", value, re.UNICODE))


def valid_controller_credential(value: str) -> bool:
    return bool(re.fullmatch(r"\d+", value))


def request_modules() -> list[dict]:
    modules = g.get("admin_modules")
    if modules is None:
        initialize_schema()
        modules = fetch_modules()
        g.admin_modules = modules
    return modules


def account_can_view_admin(account: dict | None) -> bool:
    """True for admins and for the read-only 'consultor' role."""
    if not account:
        return False
    return bool(account.get("is_admin")) or account.get("tipo_usuario") == "consultor"


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
    account = session.get("account")
    return {
        "module_name": module_name,
        "modules": modules,
        "module_names": {str(item["id"]): item["nombre"] for item in modules},
        "is_read_only_account": bool(account) and account.get("tipo_usuario") == "consultor",
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
    module_number: int | list[int] | None = None,
    action: str = "registro",
    detail: str | None = None,
    section: str = "general",
    before: dict | None = None,
    after: dict | None = None,
) -> bool:
    try:
        initialize_schema()
        create_history_entry(
            account.get("username", "desconocido"),
            module_number,
            description,
            action,
            detail,
            section,
            before,
            after,
        )
        return True
    except Exception:
        app.logger.exception("No fue posible registrar una entrada del historial")
        return False


def format_history_value(value, module_names: dict[str, str], field: str = "") -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "Activo" if value else "Inactivo"
    if isinstance(value, list):
        return ", ".join(
            format_history_value(item, module_names, field) for item in value
        ) or "—"
    if isinstance(value, dict):
        return "; ".join(
            f"{key}: {format_history_value(item, module_names, key)}"
            for key, item in value.items()
            if key != "_field_order"
        ) or "—"
    if isinstance(value, int) and field.startswith("Módulo") and str(value) in module_names:
        return module_names[str(value)]
    return str(value)


def format_history_route_lines(value: object) -> list[str] | None:
    if not isinstance(value, list):
        return None
    if not value:
        return ["—"]

    route_lines = []
    for route in value:
        if (
            not isinstance(route, dict)
            or route.get("Ruta") is None
            or route.get("Módulo de origen") is None
        ):
            return None
        route_lines.append(
            f"{route['Ruta']} - Módulo de origen {route['Módulo de origen']}"
        )
    return route_lines


def module_badge_number(module_id: int, module_name: str | None) -> str:
    if module_name:
        match = re.fullmatch(r"m[oó]dulo\s+(\d+)", module_name.strip(), re.IGNORECASE)
        if match:
            return str(int(match.group(1)))
    return str(module_id)


def history_snapshot(fields: dict[str, object]) -> dict:
    return {"_field_order": list(fields), **fields}


def history_user_type_label(user_type: str) -> str:
    return {
        "usuario": "Usuario",
        "admin": "Administrador",
        "consultor": "Consultor (solo lectura)",
    }.get(user_type, user_type)


def history_turno_snapshot(
    turno: dict,
    modules: list[int],
    module_statuses: dict[int, bool],
) -> dict:
    return history_snapshot({
        "Número": turno["numero"],
        "Tipo de turno": "General" if turno["alcance"] == "general" else "Específico",
        "Hora de inicio": str(turno["hora_inicio"]),
        "Hora de fin": str(turno["hora_fin"]),
        "Módulos disponibles": [
            {"Módulo": module_id, "Estado": module_statuses.get(module_id, True)}
            for module_id in modules
        ],
        "Estado": turno["activo"],
    })


def history_turno_time_label(turno: dict | None) -> str:
    if turno is None:
        return "turno"
    return f"turno de {turno['hora_inicio']} a {turno['hora_fin']}"


def history_snapshot_fields(
    snapshot: object,
    form_order: list[str] | None = None,
) -> list[tuple[str, object]]:
    if not isinstance(snapshot, dict):
        return []
    fields = {
        key: value
        for key, value in snapshot.items()
        if key not in {"_field_order", "_assignment_edited_days"}
    }
    order = snapshot.get("_field_order")
    if isinstance(order, list):
        field_names = [field for field in order if field in fields]
    elif form_order:
        field_names = [field for field in form_order if field in fields]
        field_names.extend(field for field in fields if field not in field_names)
    else:
        field_names = list(fields)
    return [(field, fields[field]) for field in field_names]


def history_form_field_order(description: str) -> list[str] | None:
    movement = description.casefold()
    if "estado especial" in movement:
        return ["Código", "Descripción", "Categoría", "Estado"]
    if "tipo de ruta" in movement:
        return ["Descripción", "Estado"]
    if "servicio" in movement:
        return ["Nombre", "Estado"]
    if "ruta" in movement:
        return [
            "Ruta",
            "Tipo",
            "Origen",
            "Destino",
            "Servicio",
            "Módulo de origen",
            "Módulos vinculados",
            "Módulos compartidos",
            "Módulos",
            "Estado",
        ]
    if "controlador" in movement:
        return ["Nombre", "Credencial", "Sexo", "Módulo", "Estado"]
    if "usuario" in movement:
        return [
            "Usuario",
            "Tipo de usuario",
            "Tipo",
            "Correo electrónico",
            "Correo",
            "Teléfono",
            "Módulo",
            "Estado",
        ]
    if "turno" in movement:
        return [
            "Número",
            "Tipo de turno",
            "Alcance",
            "Hora de inicio",
            "Hora de fin",
            "Módulos disponibles",
            "Módulos",
            "Estado",
        ]
    if "módulo" in movement:
        return ["Nombre del módulo", "Nombre", "Dirección", "Latitud", "Longitud"]
    return None


def display_history_movement(description: str) -> str:
    if description.endswith(")") and " (de " in description:
        return description.rsplit(" (de ", 1)[0]
    return description


def history_entry_category(description: str) -> str:
    if not description.endswith(")") or " (de " not in description:
        return ""
    section = description.rsplit(" (de ", 1)[1][:-1].casefold()
    return {
        "controladores": "controladores",
        "rutas": "rutas",
        "tipos de rutas": "tipos",
        "servicios": "servicios",
        "usuarios": "usuarios",
        "turnos": "turnos",
        "módulos": "modulos",
        "estados especiales": "estados_especiales",
    }.get(section, "")


def history_module_status_groups(
    field: str,
    value: object,
) -> list[dict[str, object]] | None:
    module_fields = {
        "Módulos vinculados",
        "Módulos disponibles",
        "Módulos compartidos",
    }
    if field not in module_fields:
        return None
    if not isinstance(value, list) or not value:
        return None

    modules_by_status: dict[str, list[str]] = {"Activo": [], "Inactivo": []}
    for item in value:
        if (
            not isinstance(item, dict)
            or item.get("Módulo") is None
            or "Estado" not in item
        ):
            return None

        module_value = item["Módulo"]
        if isinstance(module_value, bool) or not isinstance(module_value, (int, str)):
            return None
        module_number = str(module_value).strip()
        if not module_number.isdigit():
            return None

        status = item["Estado"]
        if isinstance(status, bool):
            status_label = "Activo" if status else "Inactivo"
        elif isinstance(status, str):
            normalized_status = status.strip().casefold()
            if normalized_status in {"activo", "active"}:
                status_label = "Activo"
            elif normalized_status in {"inactivo", "inactive"}:
                status_label = "Inactivo"
            else:
                return None
        else:
            return None

        modules_by_status[status_label].append(str(int(module_number)))

    return [
        {
            "status": status,
            "status_class": f"is-{status.casefold()}",
            "modules": modules_by_status[status],
        }
        for status in ("Activo", "Inactivo")
    ]


def _decode_assignment_snapshot_value(value: object, default: object) -> object:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return default
    return value if value is not None else default


def _assignment_snapshot_records(snapshot: object) -> list[dict]:
    if not isinstance(snapshot, dict):
        return []
    if "Asignaciones" in snapshot:
        records = _decode_assignment_snapshot_value(snapshot.get("Asignaciones"), [])
    elif "Credencial" in snapshot:
        records = [snapshot]
    else:
        return []
    if isinstance(records, dict):
        records = [records]
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, dict)]


def _assignment_history_period(
    movement: object,
    records: list[dict],
) -> tuple[int, int] | None:
    match = re.search(
        r"(?<!\d)(\d{1,2})\s*/\s*(\d{4})(?!\d)",
        str(movement or ""),
    )
    period_values = []
    if match:
        period_values.append((match.group(1), match.group(2)))
    period_values.extend(
        (
            record.get("month", record.get("Mes")),
            record.get("year", record.get("Año")),
        )
        for record in records
    )
    for raw_month, raw_year in period_values:
        try:
            month = int(raw_month)
            year = int(raw_year)
        except (TypeError, ValueError):
            continue
        if 1 <= month <= 12 and 1 <= year <= 9999:
            return month, year
    return None


def _assignment_snapshot_days(value: object, days_in_month: int) -> set[int]:
    raw_days = _decode_assignment_snapshot_value(value, [])
    if not isinstance(raw_days, (list, tuple, set)):
        return set()
    days = set()
    for raw_day in raw_days:
        try:
            day = int(raw_day)
        except (TypeError, ValueError):
            continue
        if 1 <= day <= days_in_month:
            days.add(day)
    return days


def _normalize_assignment_snapshot_record(
    record: dict,
    days_in_month: int,
) -> dict:
    raw_assignments = _decode_assignment_snapshot_value(
        record.get("Asignaciones diarias"), {}
    )
    if not isinstance(raw_assignments, dict):
        raw_assignments = {}
    assignments = {}
    for raw_day, raw_code in raw_assignments.items():
        try:
            day = int(raw_day)
        except (TypeError, ValueError):
            continue
        code = str(raw_code or "").strip().upper()
        if 1 <= day <= days_in_month and code:
            assignments[day] = code

    raw_details = _decode_assignment_snapshot_value(record.get("Detalles diarios"), {})
    if not isinstance(raw_details, dict):
        raw_details = {}
    daily_details = {}
    for raw_day, raw_detail in raw_details.items():
        try:
            day = int(raw_day)
        except (TypeError, ValueError):
            continue
        if not 1 <= day <= days_in_month or not isinstance(raw_detail, dict):
            continue
        detail = {}
        for field in ("route", "shift", "nomenclature", "code"):
            raw_value = raw_detail.get(field)
            if raw_value is None:
                continue
            value = str(raw_value).strip()
            if value:
                detail[field] = value.upper() if field in {"nomenclature", "code"} else value
        daily_details[day] = detail

    return {
        "controller": str(record.get("Controlador") or "").strip(),
        "credential": str(record.get("Credencial") or "").strip(),
        "shift": str(record.get("Turno") or "").strip(),
        "route": str(record.get("Ruta") or "").strip(),
        "nomenclature": str(record.get("Nomenclatura") or "").strip().upper(),
        "work_days": _assignment_snapshot_days(
            record.get("Días de trabajo"), days_in_month
        ),
        "rest_days": _assignment_snapshot_days(
            record.get("Días de descanso"), days_in_month
        ),
        "assignments": assignments,
        "daily_details": daily_details,
    }


def _assignment_detail_values(record: dict, field: str) -> list[str]:
    values = []
    for day in sorted(record["daily_details"]):
        value = record["daily_details"][day].get(field)
        if value and value not in values:
            values.append(value)
    if not values and record[field]:
        values.append(record[field])
    return values


def _assignment_detail_pairs(record: dict) -> list[dict[str, str]]:
    pairs = []
    for day in sorted(record["daily_details"]):
        detail = record["daily_details"][day]
        route = detail.get("route") or record["route"]
        nomenclature = detail.get("nomenclature") or record["nomenclature"]
        if not route and not nomenclature:
            continue
        pair = {"route": route or "—", "nomenclature": nomenclature}
        if pair not in pairs:
            pairs.append(pair)
    if not pairs and (record["route"] or record["nomenclature"]):
        pairs.append({
            "route": record["route"] or "—",
            "nomenclature": record["nomenclature"],
        })
    return pairs


def _assignment_comparison_rows(
    previous_values: list,
    current_values: list,
    empty_value: object,
) -> list[dict]:
    if not previous_values and not current_values:
        return [{"before": empty_value, "after": empty_value, "after_changed": False}]
    row_count = max(len(previous_values), len(current_values))
    rows = []
    for index in range(row_count):
        previous = previous_values[index] if index < len(previous_values) else None
        current = current_values[index] if index < len(current_values) else None
        rows.append({
            "before": previous,
            "after": current,
            "after_changed": (
                current is not None
                and current != empty_value
                and current not in previous_values
            ),
        })
    return rows


def _assignment_snapshot_signature(record: dict) -> tuple:
    return (
        record["controller"],
        record["credential"],
        record["shift"],
        record["route"],
        record["nomenclature"],
        tuple(sorted(record["work_days"])),
        tuple(sorted(record["rest_days"])),
        tuple(sorted(record["assignments"].items())),
        tuple(
            sorted(
                (day, tuple(sorted(detail.items())))
                for day, detail in record["daily_details"].items()
            )
        ),
    )


def _assignment_day_state(record: dict, day: int) -> dict:
    detail = record["daily_details"].get(day, {})
    code = detail.get("code") or record["assignments"].get(day, "")
    status = (
        "vacation" if code == "V"
        else "work" if day in record["work_days"]
        else "rest" if day in record["rest_days"]
        else "assigned" if code
        else "empty"
    )
    if code:
        label = code
    elif status == "rest":
        label = "D"
    elif status == "work":
        label = f'{record["nomenclature"]}{record["shift"]}'.strip() or "—"
    else:
        label = "—"

    if status == "rest":
        description = "Descanso"
    elif status == "empty":
        description = "Sin asignación"
    else:
        description_parts = []
        if status == "vacation":
            description_parts.append("Vacaciones")
        route = detail.get("route") or record["route"]
        shift = detail.get("shift") or record["shift"]
        if route:
            description_parts.append(route)
        if shift:
            description_parts.append(f"Turno {shift}")
        if code:
            description_parts.append(f"Código {code}")
        elif label != "—":
            description_parts.append(f"Asignación {label}")
        description = " · ".join(description_parts) or "Sin asignación"
    return {"label": label, "status": status, "detail": description}


def _assignment_day_change_signature(record: dict, day: int) -> tuple:
    detail = record["daily_details"].get(day, {})
    state = _assignment_day_state(record, day)
    return (
        state["status"],
        detail.get("code") or record["assignments"].get(day, ""),
        detail.get("route", ""),
        detail.get("shift", ""),
        detail.get("nomenclature", ""),
    )


def _assignment_calendar_cells(
    record: dict,
    days_in_month: int,
    first_weekday: int,
    changed_days: set[int],
) -> list[dict]:
    cells = [{"blank": True} for _ in range(first_weekday)]
    for day in range(1, days_in_month + 1):
        cells.append({
            "blank": False,
            "day": day,
            **_assignment_day_state(record, day),
            "changed": day in changed_days,
        })
    return cells


def prepare_assignment_history_comparisons(
    before: object,
    after: object,
    movement: object,
) -> list[dict]:
    previous_records = _assignment_snapshot_records(before)
    current_records = _assignment_snapshot_records(after)
    period = _assignment_history_period(
        movement, [*previous_records, *current_records]
    )
    if period is None:
        return []
    month, year = period
    first_weekday, days_in_month = monthrange(year, month)
    previous_by_credential = {
        str(record.get("Credencial") or "").strip(): record
        for record in previous_records
        if str(record.get("Credencial") or "").strip()
    }

    comparisons = []
    for current in current_records:
        credential = str(current.get("Credencial") or "").strip()
        previous = previous_by_credential.get(credential)
        if not credential or previous is None:
            continue
        previous_record = _normalize_assignment_snapshot_record(
            previous, days_in_month
        )
        current_record = _normalize_assignment_snapshot_record(
            current, days_in_month
        )
        if (
            _assignment_snapshot_signature(previous_record)
            == _assignment_snapshot_signature(current_record)
        ):
            continue

        if "_assignment_edited_days" in current:
            changed_days = _assignment_snapshot_days(
                current["_assignment_edited_days"], days_in_month
            )
            for day in range(1, days_in_month + 1):
                previous_status = _assignment_day_state(previous_record, day)["status"]
                current_status = _assignment_day_state(current_record, day)["status"]
                if previous_status != "empty" and current_status == "empty":
                    changed_days.add(day)
        else:
            changed_days = set()
            for day in range(1, days_in_month + 1):
                if (
                    _assignment_day_change_signature(previous_record, day)
                    != _assignment_day_change_signature(current_record, day)
                ):
                    changed_days.add(day)
        shifts_before = _assignment_detail_values(previous_record, "shift")
        shifts_after = _assignment_detail_values(current_record, "shift")
        route_pairs_before = _assignment_detail_pairs(previous_record)
        route_pairs_after = _assignment_detail_pairs(current_record)
        comparisons.append({
            "month": month,
            "year": year,
            "period_label": f"{MONTH_NAMES_ES[month - 1].capitalize()} {year}",
            "weekdays": ("L", "M", "M", "J", "V", "S", "D"),
            "controller": current_record["controller"] or previous_record["controller"],
            "credential": credential,
            "shifts_before": shifts_before,
            "shifts_after": shifts_after,
            "shift_rows": _assignment_comparison_rows(
                shifts_before, shifts_after, "—"
            ),
            "routes_before": _assignment_detail_values(previous_record, "route"),
            "routes_after": _assignment_detail_values(current_record, "route"),
            "nomenclatures_before": _assignment_detail_values(
                previous_record, "nomenclature"
            ),
            "nomenclatures_after": _assignment_detail_values(
                current_record, "nomenclature"
            ),
            "route_rows": _assignment_comparison_rows(
                route_pairs_before,
                route_pairs_after,
                {"route": "—", "nomenclature": ""},
            ),
            "before_cells": _assignment_calendar_cells(
                previous_record, days_in_month, first_weekday, changed_days
            ),
            "after_cells": _assignment_calendar_cells(
                current_record, days_in_month, first_weekday, changed_days
            ),
        })
    return comparisons


def prepare_assignment_history_registrations(
    after: object,
    movement: object,
) -> list[dict]:
    records = _assignment_snapshot_records(after)
    period = _assignment_history_period(movement, records)
    if period is None:
        return []
    month, year = period
    first_weekday, days_in_month = monthrange(year, month)
    calendars = []
    for record in records:
        normalized_record = _normalize_assignment_snapshot_record(
            record, days_in_month
        )
        credential = normalized_record["credential"]
        if not credential:
            continue
        calendars.append({
            "month": month,
            "year": year,
            "period_label": f"{MONTH_NAMES_ES[month - 1].capitalize()} {year}",
            "weekdays": ("L", "M", "M", "J", "V", "S", "D"),
            "controller": normalized_record["controller"],
            "credential": credential,
            "cells": _assignment_calendar_cells(
                normalized_record, days_in_month, first_weekday, set()
            ),
        })
    return calendars


def prepare_assignment_history_deletions(
    before: object,
    movement: object,
) -> list[dict]:
    records = _assignment_snapshot_records(before)
    period = _assignment_history_period(movement, records)
    if period is None:
        return []
    month, year = period
    first_weekday, days_in_month = monthrange(year, month)
    calendars = []
    for record in records:
        normalized_record = _normalize_assignment_snapshot_record(
            record, days_in_month
        )
        credential = normalized_record["credential"]
        if not credential:
            continue
        cells = _assignment_calendar_cells(
            normalized_record, days_in_month, first_weekday, set()
        )
        for cell in cells:
            if not cell["blank"]:
                cell["deleted"] = cell["status"] != "empty"
        calendars.append({
            "month": month,
            "year": year,
            "period_label": f"{MONTH_NAMES_ES[month - 1].capitalize()} {year}",
            "weekdays": ("L", "M", "M", "J", "V", "S", "D"),
            "controller": normalized_record["controller"],
            "credential": credential,
            "cells": cells,
        })
    return calendars


def prepare_history_entries(
    entries: list[dict],
    module_names: dict[str, str],
    route_type_names: dict[str, str] | None = None,
    section: str | None = None,
) -> list[dict]:
    prepared = []
    for entry in entries:
        before = entry.get("datos_anteriores")
        after = entry.get("datos_nuevos")
        comparison_rows = []
        is_route_link_entry = (
            entry.get("accion") == "vinculacion"
            and isinstance(after, dict)
            and "Módulo de destino" in after
            and "Rutas vinculadas" in after
        )
        form_order = history_form_field_order(entry.get("modificacion", ""))
        is_route_entry = form_order is not None and {"Ruta", "Tipo"}.issubset(form_order)

        def display_value(field: str, value: object) -> object:
            if not is_route_entry or field != "Tipo" or isinstance(value, bool):
                return value
            if isinstance(value, int):
                type_id = str(value)
            elif isinstance(value, str) and value.strip().isdigit():
                type_id = value.strip()
            else:
                return value
            return (route_type_names or {}).get(type_id, value)

        before_fields = history_snapshot_fields(before, form_order)
        after_fields = history_snapshot_fields(after, form_order)
        if before_fields and after_fields:
            previous_values = {
                field: display_value(field, value) for field, value in before_fields
            }
            new_values = {
                field: display_value(field, value) for field, value in after_fields
            }
            fields = list(dict.fromkeys([*previous_values, *new_values]))
            for field in fields:
                row = {
                    "field": field,
                    "before": format_history_value(previous_values.get(field), module_names, field),
                    "after": format_history_value(new_values.get(field), module_names, field),
                    "changed": previous_values.get(field) != new_values.get(field),
                }
                before_module_groups = history_module_status_groups(
                    field, previous_values.get(field)
                )
                after_module_groups = history_module_status_groups(
                    field, new_values.get(field)
                )
                if before_module_groups is not None or after_module_groups is not None:
                    row["before_module_groups"] = before_module_groups
                    row["after_module_groups"] = after_module_groups
                comparison_rows.append(row)
        action = entry.get("accion")
        assignment_comparisons = (
            prepare_assignment_history_comparisons(
                before, after, entry.get("modificacion", "")
            )
            if section == "asignaciones" and action == "edicion"
            else []
        )
        assignment_calendars = (
            prepare_assignment_history_registrations(
                after, entry.get("modificacion", "")
            )
            if section == "asignaciones" and action == "registro"
            else []
        )
        assignment_deletions = (
            prepare_assignment_history_deletions(
                before, entry.get("modificacion", "")
            )
            if section == "asignaciones" and action == "eliminacion"
            else []
        )
        is_module_deletion = (
            action == "eliminacion"
            and entry.get("modificacion", "").casefold().startswith("eliminó módulo ")
        )
        detail_snapshot = before if action in {"eliminacion", "desvinculacion"} else after
        detail_fields = history_snapshot_fields(detail_snapshot, form_order)
        if is_module_deletion:
            detail_fields = [
                (field, value)
                for field, value in detail_fields
                if field not in {
                    "Registros analíticos eliminados",
                    "Registros históricos de migración eliminados",
                }
            ]
        if not detail_fields and not is_module_deletion:
            detail_fields = after_fields or before_fields
        detail_rows = []
        for field, value in detail_fields:
            value = display_value(field, value)
            route_lines = None
            if (
                is_route_link_entry and field == "Rutas vinculadas"
            ) or (
                action in {"eliminacion", "desvinculacion"} and field == "Rutas"
            ) or (
                is_module_deletion and field == "Rutas compartidas desvinculadas"
            ):
                route_lines = format_history_route_lines(value)
            row = {"field": field}
            if route_lines is not None:
                row["value_lines"] = route_lines
            elif is_module_deletion and isinstance(value, list):
                row["value_lines"] = [
                    format_history_value(item, module_names, field)
                    for item in value
                ] or ["—"]
            elif is_module_deletion and isinstance(value, dict):
                row["value_lines"] = [
                    f"{key}: {format_history_value(item, module_names, key)}"
                    for key, item in value.items()
                    if key != "_field_order"
                ] or ["—"]
            else:
                row["value"] = format_history_value(value, module_names, field)
            module_groups = history_module_status_groups(field, value)
            if module_groups is not None:
                row["module_groups"] = module_groups
            detail_rows.append(row)
        description = entry.get("descripcion")
        if description and not detail_rows:
            detail_rows.append({
                "field": "Detalle",
                "value": format_history_value(description, module_names, "Detalle"),
            })
        prepared.append({
            **entry,
            "history_category": history_entry_category(entry.get("modificacion", "")),
            "movimiento_visible": display_history_movement(entry.get("modificacion", "")),
            "comparison_rows": comparison_rows,
            "detail_rows": detail_rows,
            "assignment_comparisons": assignment_comparisons,
            "assignment_calendars": assignment_calendars,
            "assignment_deletions": assignment_deletions,
        })
    return prepared


def assignment_history_snapshot(
    record: dict | None,
    edited_days: list[int] | None = None,
) -> dict | None:
    if record is None:
        return None

    snapshot = history_snapshot({
        "Controlador": record.get("name"),
        "Credencial": record.get("credential"),
        "Turno": record.get("shift"),
        "Ruta": record.get("route"),
        "Nomenclatura": record.get("nomenclature"),
        "Días de trabajo": _decode_assignment_snapshot_value(record.get("work_days"), []),
        "Días de descanso": _decode_assignment_snapshot_value(record.get("rest_days"), []),
        "Asignaciones diarias": _decode_assignment_snapshot_value(record.get("daily_assignments"), {}),
        "Detalles diarios": _decode_assignment_snapshot_value(record.get("daily_details"), {}),
    })
    if edited_days is not None:
        snapshot["_assignment_edited_days"] = sorted(set(edited_days))
    return snapshot


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
            if account_can_view_admin(account):
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
    if not account_can_view_admin(account):
        return redirect(url_for("connection_status"))
    today = date.today()
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
    else:
        attach_monthly_workday_counts(grouped_controllers, today.month, today.year)

    return render_template(
        "admin/dashboard.html",
        account=account,
        modules=modules,
        grouped_controllers=grouped_controllers,
        current_month_name=MONTH_NAMES_ES[today.month - 1],
    )


@app.get("/administrador/rol-mensual")
def admin_monthly_role_page():
    account = session.get("account")
    if not account_can_view_admin(account):
        return redirect(url_for("connection_status"))
    today = date.today()
    edit_estado_id = request.args.get("edit_estado_id", type=int)
    try:
        initialize_schema()
        modules = request_modules()
        estados_especiales = fetch_catalog_items("estados_especiales")
    except Exception:
        modules = []
        estados_especiales = []
    editing_estado_especial = next(
        (item for item in estados_especiales if item.get("id") == edit_estado_id),
        None,
    ) if edit_estado_id else None
    show_special_statuses = bool(editing_estado_especial) or request.args.get("tab") == "estados"
    requested_module = request.args.get("module_number", type=int)
    module_numbers = {int(module["id"]) for module in modules if module.get("id") is not None}
    module_number = requested_module if requested_module in module_numbers else (
        int(modules[0]["id"]) if modules else None
    )
    return render_template(
        "admin/rol_mensual.html",
        account=account,
        modules=modules,
        module_number=module_number,
        today={"year": today.year, "month": today.month, "day": today.day},
        admin_embed=True,
        estados_especiales=estados_especiales,
        editing_estado_especial=editing_estado_especial,
        show_special_statuses=show_special_statuses,
    )


@app.get("/administrador/historial")
def admin_history_page():
    account = session.get("account")
    if not account_can_view_admin(account):
        return redirect(url_for("connection_status"))
    modules = []
    history_error = None
    try:
        modules = request_modules()
        general_entries = fetch_history_entries(section="general")
        assignment_entries = fetch_history_entries(section="asignaciones")
        module_names = {str(module["id"]): module["nombre"] for module in modules}
        history_entries = [*general_entries, *assignment_entries]
        has_route_type = any(
            {"Ruta", "Tipo"}.issubset(
                history_form_field_order(entry.get("modificacion", "")) or []
            )
            for entry in history_entries
        )
        route_type_names = (
            {
                str(item["id"]): item["descripcion"]
                for item in fetch_catalog_items("tipos_rutas")
            }
            if has_route_type
            else {}
        )
        general_entries = prepare_history_entries(
            general_entries, module_names, route_type_names, section="general"
        )
        assignment_entries = prepare_history_entries(
            assignment_entries, module_names, route_type_names, section="asignaciones"
        )
    except Exception:
        app.logger.exception("No fue posible cargar las entradas del historial")
        general_entries = []
        assignment_entries = []
        history_error = "No fue posible cargar el historial. Intenta actualizar la página."
    return render_template(
        "admin/historial.html",
        account=account,
        modules=modules,
        module_names=module_names if not history_error else {},
        general_entries=general_entries,
        assignment_entries=assignment_entries,
        history_error=history_error,
    )


@app.post("/administrador/historial/vaciar")
def admin_clear_history():
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    try:
        module_number = int(request.form.get("module_number", ""))
    except (TypeError, ValueError):
        flash("Selecciona un módulo válido para vaciar su historial.", "error")
        return redirect(url_for("admin_history_page"))

    try:
        initialize_schema()
        module = next(
            (item for item in request_modules() if item["id"] == module_number),
            None,
        )
        if module is None:
            flash("El módulo seleccionado no es válido.", "error")
            return redirect(url_for("admin_history_page"))
        cleared_count = clear_history_for_module(module_number)
        if cleared_count:
            flash(
                f"Se vació el historial de {module['nombre']}. "
                f"Se limpiaron {cleared_count} movimientos.",
                "success",
            )
        else:
            flash(f"No había movimientos para vaciar en {module['nombre']}.", "success")
    except Exception:
        app.logger.exception("No fue posible vaciar el historial del módulo")
        flash("No fue posible vaciar el historial del módulo.", "error")
    return redirect(url_for("admin_history_page"))


@app.route("/administrador/rol-mensual/<int:module_number>/estado", methods=["GET", "POST"])
def admin_monthly_role_status(module_number: int):
    account = session.get("account")
    if not account or module_number not in range(1, MAX_MODULES + 1):
        return jsonify(error="No autorizado."), 403
    if request.method == "POST" and not account.get("is_admin"):
        return jsonify(error="No autorizado."), 403
    if (
        request.method == "GET"
        and not account_can_view_admin(account)
        and account.get("module_number") != module_number
    ):
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
        previous_active = get_monthly_role_activation(module_number, month, year)
        result = set_monthly_role_activation(module_number, month, year, active)
        record_history(
            account,
            f"{'Activó' if active else 'Desactivó'} el mes {month:02d}/{year}",
            module_number,
            "edicion",
            f"Mes: {month:02d}/{year}; Estado: {'Activo' if result else 'Inactivo'}",
            before={"Estado del mes": previous_active},
            after={"Estado del mes": result},
        )
        return jsonify({"activo": result})
    except Exception as error:
        return jsonify(error=f"No se pudo cambiar el estado del mes: {error}"), 400


@app.get("/administrador/controladores")
def admin_controllers_page():
    account = session.get("account")
    if not account_can_view_admin(account):
        return redirect(url_for("connection_status"))
    today = date.today()
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
    else:
        attach_monthly_workday_counts(grouped_controllers, today.month, today.year)

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
        current_month_name=MONTH_NAMES_ES[today.month - 1],
    )


@app.get("/administrador/usuarios")
def admin_users_page():
    account = session.get("account")
    if not account_can_view_admin(account):
        return redirect(url_for("connection_status"))
    edit_user_id = request.args.get("edit_user_id", type=int)
    try:
        initialize_schema()
        modules = request_modules()
        users = fetch_users()
        users_by_module = {}
        for user in users:
            if user.get("tipo_usuario") == "usuario" and user.get("module_number") is not None:
                users_by_module.setdefault(user["module_number"], []).append(user)
        grouped_users = [
            {
                "module_number": module["id"],
                "module_name": module["nombre"],
                "users": users_by_module.get(module["id"], []),
            }
            for module in modules
        ]
        admin_users = [user for user in users if user.get("tipo_usuario") == "admin"]
        consultant_users = [user for user in users if user.get("tipo_usuario") == "consultor"]
    except Exception:
        app.logger.exception("No fue posible cargar los usuarios y módulos")
        modules = []
        grouped_users = []
        admin_users = []
        consultant_users = []

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
        if editing_user is None:
            editing_user = next((user for user in consultant_users if user.get("id") == edit_user_id), None)

    return render_template(
        "admin/usuarios.html",
        account=account,
        grouped_users=grouped_users,
        modules=modules,
        editing_user=editing_user,
        admin_users=admin_users,
        consultant_users=consultant_users,
    )


@app.get("/administrador/modulos")
def admin_modules_page():
    account = session.get("account")
    if not account_can_view_admin(account):
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
            previous_module = next(
                (item for item in fetch_modules() if item["id"] == int(module_id)),
                None,
            )
            updated_module = update_module(int(module_id), nombre, direccion, latitud, longitud)
            if updated_module is None:
                flash("No se encontró el módulo para actualizar.", "error")
            else:
                record_history(
                    account,
                    f"Editó módulo {updated_module['nombre']} (de Módulos)",
                    int(module_id),
                    "edicion",
                    f"Nombre: {updated_module['nombre']}; Dirección: {updated_module['direccion']}; Latitud: {updated_module['latitud']}; Longitud: {updated_module['longitud']}",
                    before=history_snapshot({
                        "Nombre del módulo": previous_module["nombre"],
                        "Dirección": previous_module["direccion"],
                        "Latitud": previous_module["latitud"],
                        "Longitud": previous_module["longitud"],
                    }) if previous_module else None,
                    after=history_snapshot({
                        "Nombre del módulo": updated_module["nombre"],
                        "Dirección": updated_module["direccion"],
                        "Latitud": updated_module["latitud"],
                        "Longitud": updated_module["longitud"],
                    }),
                )
                flash("Módulo actualizado correctamente.", "success")
        else:
            created_module = create_module(nombre, direccion, latitud, longitud)
            if created_module is None:
                flash("Ya existen los veinte módulos disponibles.", "error")
            else:
                record_history(
                    account,
                    f"Registró módulo {created_module['nombre']} (de Módulos)",
                    int(created_module["id"]),
                    "registro",
                    f"Nombre: {created_module['nombre']}; Dirección: {created_module['direccion']}; Latitud: {created_module['latitud']}; Longitud: {created_module['longitud']}",
                    after=history_snapshot({
                        "Nombre del módulo": created_module["nombre"],
                        "Dirección": created_module["direccion"],
                        "Latitud": created_module["latitud"],
                        "Longitud": created_module["longitud"],
                    }),
                )
                flash("Módulo creado correctamente.", "success")
    except Exception:
        flash("No se pudo guardar el módulo. Verifica que el nombre no esté repetido.", "error")
    return redirect(url_for("admin_modules_page"))


@app.post("/administrador/modulos/<int:module_id>/eliminar")
def admin_delete_module(module_id: int):
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    action = request.form.get("action", "")
    admin_password = request.form.get("admin_password", "")
    if action not in {"clear", "delete"}:
        flash("Selecciona una acción válida para el módulo.", "error")
        return redirect(url_for("admin_modules_page"))
    if not admin_password:
        flash("La contraseña del administrador es obligatoria.", "error")
        return redirect(url_for("admin_modules_page"))

    try:
        verified_admin = authenticate_user(
            str(account.get("username", "")),
            admin_password,
        )
    except Exception:
        app.logger.exception("No fue posible verificar la contraseña del administrador")
        flash("No se pudo verificar la contraseña del administrador.", "error")
        return redirect(url_for("admin_modules_page"))
    if (
        not verified_admin
        or not verified_admin.get("is_admin")
        or verified_admin.get("username") != account.get("username")
    ):
        flash("La contraseña del administrador es incorrecta.", "error")
        return redirect(url_for("admin_modules_page"))

    try:
        initialize_schema()
        result = manage_module_data(
            module_id,
            action,
            str(account.get("username", "desconocido")),
        )
        if result["status"] == "missing":
            flash("No se encontró el módulo seleccionado.", "error")
        elif result["status"] == "last_module":
            flash("No se puede eliminar el último módulo registrado.", "error")
        elif action == "clear":
            flash(
                f"Se vació la información de {result['module']['nombre']}; "
                "el detalle quedó guardado en el historial de ese módulo.",
                "success",
            )
        else:
            flash(
                f"Se eliminó el módulo {result['module']['nombre']}; "
                "el movimiento quedó registrado en el historial de los demás módulos.",
                "success",
            )
    except Exception:
        app.logger.exception("No fue posible procesar la acción del módulo %s", module_id)
        flash("No fue posible completar la acción del módulo.", "error")
    return redirect(url_for("admin_modules_page"))


@app.get("/administrador/rutas")
def admin_routes_page():
    account = session.get("account")
    if not account_can_view_admin(account):
        return redirect(url_for("connection_status"))
    edit_route_id = request.args.get("edit_id", type=int)
    edit_tipo_id = request.args.get("edit_tipo_id", type=int)
    edit_servicio_id = request.args.get("edit_servicio_id", type=int)
    catalog_tab = request.args.get("catalog_tab", "rutas")
    if catalog_tab not in {"rutas", "tipos", "servicios"}:
        catalog_tab = "rutas"
    try:
        initialize_schema()
        modules = request_modules()
        module_names_by_id = {module["id"]: module["nombre"] for module in modules}
        grouped_routes = []
        for module in modules:
            routes = fetch_routes(module["id"])
            for route in routes:
                route["mod1_badge_number"] = module_badge_number(
                    route["mod1"],
                    module_names_by_id.get(route["mod1"]),
                )
            grouped_routes.append({
                "module_number": module["id"],
                "module_name": module["nombre"],
                "routes": routes,
            })
        tipos_rutas = fetch_catalog_items("tipos_rutas")
        servicios = fetch_catalog_items("servicio")
    except Exception:
        modules = []
        grouped_routes = []
        tipos_rutas = []
        servicios = []
    editing_tipo_ruta = next(
        (tipo for tipo in tipos_rutas if tipo.get("id") == edit_tipo_id),
        None,
    ) if edit_tipo_id else None
    editing_servicio = next(
        (servicio for servicio in servicios if servicio.get("id") == edit_servicio_id),
        None,
    ) if edit_servicio_id else None
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
    shared_module_statuses = {}
    if editing_route:
        try:
            shared_modules = fetch_shared_modules(editing_route["id"])
            shared_module_statuses = fetch_shared_module_statuses(editing_route["id"])
        except Exception:
            shared_modules = []
            shared_module_statuses = {}
    return render_template(
        "admin/rutas.html",
        account=account,
        modules=modules,
        grouped_routes=grouped_routes,
        editing_route=editing_route,
        shared_modules=shared_modules,
        shared_module_statuses=shared_module_statuses,
        tipos_rutas=tipos_rutas,
        servicios=servicios,
        editing_tipo_ruta=editing_tipo_ruta,
        editing_servicio=editing_servicio,
        catalog_tab=catalog_tab,
    )


@app.get("/administrador/analisis")
def admin_analysis_page():
    account = session.get("account")
    if not account_can_view_admin(account):
        return redirect(url_for("connection_status"))
    today = date.today()
    month = request.args.get("month", today.month, type=int)
    year = request.args.get("year", today.year, type=int)
    if month not in range(1, 13) or year not in range(1, 10000):
        month, year = today.month, today.year
    selected_credential = request.args.get("credential", "")
    selected_module = request.args.get("module", type=int)
    active_tab = request.args.get("tab", "resumen")
    if active_tab not in {"resumen", "controladores", "rutas", "incidencias"}:
        active_tab = "resumen"
    previous_period = (year - 1, 12) if month == 1 else (year, month - 1)
    next_period = (year + 1, 1) if month == 12 else (year, month + 1)
    if previous_period[0] < 1:
        previous_period = None
    if next_period[0] > 9999:
        next_period = None
    dashboard = {
        "registered_controllers": 0,
        "active_controllers": 0,
        "inactive_controllers": 0,
        "assigned_controllers": 0,
        "workers": [],
        "selected_worker": None,
        "route_days": [],
        "route_days_by_module": [],
        "calendar_days": [],
        "daily_summary": [],
    }
    modules = []
    analysis_error = None
    try:
        initialize_schema()
        modules = request_modules()
        dashboard = fetch_controller_analysis_dashboard(
            month,
            year,
            selected_credential or None,
            selected_module,
        )
    except Exception:
        app.logger.exception("No fue posible cargar las métricas de análisis")
        analysis_error = "No fue posible cargar los datos del análisis. Intenta actualizar la página."

    selected_worker = dashboard["selected_worker"]
    route_days = dashboard["route_days"]
    route_max = max((item["days"] for item in route_days), default=1) or 1
    route_points = [
        {
            "label": item["route"],
            "days": item["days"],
            "width": round(item["days"] / route_max * 100, 1),
        }
        for item in route_days
    ]

    route_days_by_module = dashboard.get("route_days_by_module", [])
    module_names = {
        str(module["id"]): module["nombre"]
        for module in modules
        if module.get("id") is not None
    }
    route_analytics_max = max(
        (item["days"] for item in route_days_by_module),
        default=1,
    ) or 1
    route_analytics = [
        {
            **item,
            "module_name": module_names.get(
                str(item["module_number"]),
                f'Módulo {item["module_number"]}',
            ),
            "width": round(item["days"] / route_analytics_max * 100, 1),
        }
        for item in sorted(
            route_days_by_module,
            key=lambda route: (-route["days"], route["module_number"], route["route"]),
        )
    ]
    top_route_analytics = route_analytics[:10]

    calendar_entries = {
        item["day"]: item for item in dashboard["calendar_days"]
    }
    first_weekday, days_in_month = monthrange(year, month)
    month_cells = [None] * first_weekday + list(range(1, days_in_month + 1))
    month_cells.extend([None] * ((7 - len(month_cells) % 7) % 7))
    calendar_weeks = [
        month_cells[index:index + 7]
        for index in range(0, len(month_cells), 7)
    ]
    status_labels = {
        "TRABAJADO": ("Trabajó", "is-work"),
        "DESCANSO": ("Descanso", "is-rest"),
        "VACACIONES": ("Vacaciones", "is-vacation"),
        "FALTA": ("Falta", "is-absence"),
        "INCAPACIDAD": ("Incapacidad", "is-incapacity"),
        "FESTIVO": ("Festivo", "is-holiday"),
        "PERMISO": ("Permiso", "is-permission"),
        "NO_PROGRAMADO": ("", ""),
    }
    calendar_grid = []
    for week in calendar_weeks:
        calendar_row = []
        for day in week:
            if day is None:
                calendar_row.append(None)
                continue
            entry = calendar_entries.get(day, {})
            code = str(entry.get("code") or "").strip().upper()
            status = str(entry.get("status") or "NO_PROGRAMADO").upper()
            if code in {"C/D", "CD"}:
                label, class_name = "C/D", "is-rest-change"
            elif code in {"D/F", "DF"}:
                label, class_name = "D/F", "is-holiday"
            elif code == "SEFI":
                label, class_name = "SEFI", "is-special"
            else:
                label, class_name = status_labels.get(status, ("", ""))
                if label == "Trabajó":
                    label = code[:8] or label
            calendar_row.append(
                {
                    "day": day,
                    "label": label,
                    "class_name": class_name,
                    "title": f'{status.replace("_", " ").title()} · {code}' if code else status.replace("_", " ").title(),
                }
            )
        calendar_grid.append(calendar_row)

    status_categories = (
        ("Trabajo", "worked", "is-work"),
        ("Descanso", "rest", "is-rest"),
        ("Falta", "absence", "is-absence"),
        ("Incapacidad", "incapacity", "is-incapacity"),
        ("Permiso", "permission", "is-permission"),
        ("Vacaciones", "vacation", "is-vacation"),
        ("Festivo", "holiday", "is-holiday"),
    )
    monthly_status_values = {
        key: sum(worker.get(key, 0) or 0 for worker in dashboard["workers"])
        for _, key, _ in status_categories
    }
    monthly_status_total = sum(monthly_status_values.values())

    def build_status_chart(values: dict) -> list[dict]:
        total = sum(values.get(key, 0) or 0 for _, key, _ in status_categories)
        return [
            {
                "label": label,
                "value": values.get(key, 0) or 0,
                "class_name": class_name,
                "width": round((values.get(key, 0) or 0) / total * 100, 1)
                if total else 0,
            }
            for label, key, class_name in status_categories
        ]

    monthly_status_chart = build_status_chart(monthly_status_values)
    status_chart = build_status_chart(selected_worker or {})

    module_summary = []
    for module in modules:
        module_workers = [
            worker for worker in dashboard["workers"]
            if str(worker.get("module_number")) == str(module.get("id"))
        ]
        values = {
            key: sum(worker.get(key, 0) or 0 for worker in module_workers)
            for _, key, _ in status_categories
        }
        total = sum(values.values())
        module_summary.append(
            {
                "name": module["nombre"],
                "module_number": module["id"],
                "assigned": len(module_workers),
                "total": total,
                "segments": [
                    {
                        "label": label,
                        "value": values[key],
                        "class_name": class_name,
                        "width": round(values[key] / total * 100, 1) if total else 0,
                    }
                    for label, key, class_name in status_categories
                ],
            }
        )

    daily_entries = {
        int(item["day"]): item
        for item in dashboard.get("daily_summary", [])
    }
    daily_calendar_grid = []
    for week in calendar_weeks:
        daily_row = []
        for day in week:
            if day is None:
                daily_row.append(None)
                continue
            entry = daily_entries.get(day, {})
            incidents = sum(
                entry.get(key, 0) or 0
                for key in ("absence", "incapacity", "permission")
            )
            worked = entry.get("worked", 0) or 0
            if not entry:
                class_name = "is-no-data"
            elif incidents:
                class_name = "has-incidents"
            elif worked:
                class_name = "has-work"
            else:
                class_name = "has-no-work"
            title = (
                f"Día {day}: sin datos analíticos para este periodo."
                if not entry else
                f"Día {day}: {worked} asignaciones de trabajo, {incidents} "
                f"incidencias y {entry.get('unprogrammed', 0)} sin programación."
            )
            daily_row.append(
                {
                    "day": day,
                    "worked": worked,
                    "incidents": incidents,
                    "has_data": bool(entry),
                    "class_name": class_name,
                    "title": title,
                }
            )
        daily_calendar_grid.append(daily_row)

    monthly_incident_totals = {
        key: monthly_status_values[key]
        for key in ("absence", "incapacity", "permission")
    }
    special_code_totals = {
        key: sum(worker.get(key, 0) or 0 for worker in dashboard["workers"])
        for key in ("change_of_rest", "holiday_rest", "sefi")
    }

    return render_template(
        "admin/analisis.html",
        account=account,
        modules=modules,
        dashboard=dashboard,
        analysis_error=analysis_error,
        month=month,
        year=year,
        month_label=MONTH_NAMES_ES[month - 1],
        previous_period=previous_period,
        next_period=next_period,
        active_tab=active_tab,
        selected_worker=selected_worker,
        route_points=route_points,
        route_max=route_max,
        calendar_grid=calendar_grid,
        status_chart=status_chart,
        monthly_status_chart=monthly_status_chart,
        monthly_status_total=monthly_status_total,
        module_summary=module_summary,
        route_analytics=route_analytics,
        top_route_analytics=top_route_analytics,
        daily_calendar_grid=daily_calendar_grid,
        monthly_incident_totals=monthly_incident_totals,
        special_code_totals=special_code_totals,
    )


@app.post("/administrador/rutas")
def admin_create_route():
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))

    payload = {field: str(request.form.get(field, "")).strip() for field in ("ruta", "origen", "destino", "servicio", "estado")}
    # El módulo principal siempre representa la ruta base y se guarda activo.
    payload["estado"] = "Activo"
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
    shared_module_statuses = {}
    for raw_status in request.form.getlist("module_statuses"):
        try:
            raw_module, status = raw_status.split(":", 1)
            shared_module_statuses[int(raw_module)] = status if status in {"Activo", "Inactivo"} else "Activo"
        except (TypeError, ValueError):
            flash("Los estados de los módulos no son válidos.", "error")
            return redirect(url_for("admin_routes_page"))
    shared_module_statuses = {
        module_id: status
        for module_id, status in shared_module_statuses.items()
        if module_id in shared_modules
    }

    try:
        initialize_schema()
        if route_id:
            previously_shared = set(fetch_shared_modules(int(route_id)))
            previous_shared_statuses = fetch_shared_module_statuses(int(route_id))
            with get_connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT ruta, origen, destino, servicio, estado, mod1, tipos FROM catalogos.rutas WHERE id = %s",
                        (int(route_id),),
                    )
                    previous_route = cursor.fetchone()
            previous_primary = previous_route[5] if previous_route else None
            saved = update_admin_route(int(route_id), {**payload, "mod1": module_number})
            if saved is None:
                flash("No se encontró la ruta para actualizar.", "error")
                return redirect(url_for("admin_routes_page"))
            else:
                record_history(
                    account,
                    f"Editó ruta {saved.get('ruta', payload['ruta'])} (de Rutas)",
                    sorted({
                        module_number,
                        *previously_shared,
                        *shared_modules,
                        *([previous_primary] if previous_primary else []),
                    }),
                    "edicion",
                    f"Ruta: {saved.get('ruta', payload['ruta'])}; Origen: {saved.get('origen', payload['origen'])}; Destino: {saved.get('destino', payload['destino'])}; Servicio: {saved.get('servicio', payload['servicio'])}; Estado: {saved.get('estado', payload['estado'])}; Módulos compartidos: {', '.join(map(str, shared_modules)) or 'ninguno'}",
                    before=history_snapshot({
                        "Ruta": previous_route[0],
                        "Tipo": previous_route[6],
                        "Origen": previous_route[1],
                        "Destino": previous_route[2],
                        "Servicio": previous_route[3],
                        "Estado": previous_route[4],
                        "Módulos vinculados": [
                            {"Módulo": previous_primary, "Estado": previous_route[4]},
                            *[
                                {"Módulo": shared_id, "Estado": previous_shared_statuses[shared_id]}
                                for shared_id in sorted(previously_shared)
                            ],
                        ],
                    }) if previous_route else None,
                    after=history_snapshot({
                        "Ruta": saved.get("ruta", payload["ruta"]),
                        "Tipo": saved.get("tipos"),
                        "Origen": saved.get("origen", payload["origen"]),
                        "Destino": saved.get("destino", payload["destino"]),
                        "Servicio": saved.get("servicio", payload["servicio"]),
                        "Estado": saved.get("estado", payload["estado"]),
                        "Módulos vinculados": [
                            {"Módulo": module_number, "Estado": saved.get("estado", payload["estado"])},
                            *[
                                {
                                    "Módulo": shared_id,
                                    "Estado": shared_module_statuses.get(shared_id, saved.get("estado", payload["estado"])),
                                }
                                for shared_id in sorted(shared_modules)
                            ],
                        ],
                    }),
                )
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
                f"Ruta: {saved.get('ruta', payload['ruta'])}; Origen: {saved.get('origen', payload['origen'])}; Destino: {saved.get('destino', payload['destino'])}; Servicio: {saved.get('servicio', payload['servicio'])}; Estado: {saved.get('estado', payload['estado'])}; Módulos compartidos: {', '.join(map(str, shared_modules)) or 'ninguno'}",
                after=history_snapshot({
                    "Ruta": saved.get("ruta", payload["ruta"]),
                    "Tipo": saved.get("tipos", payload["tipos"]),
                    "Origen": saved.get("origen", payload["origen"]),
                    "Destino": saved.get("destino", payload["destino"]),
                    "Servicio": saved.get("servicio", payload["servicio"]),
                    "Módulo de origen": module_number,
                    "Módulos compartidos": [
                        {
                            "Módulo": shared_module,
                            "Estado": shared_module_statuses.get(shared_module, saved.get("estado", payload["estado"])),
                        }
                        for shared_module in sorted(shared_modules)
                    ],
                    "Estado": saved.get("estado", payload["estado"]),
                }),
            )
            flash("Ruta creada correctamente.", "success")
        linked_modules = []
        for shared_module in shared_modules:
            linked_route = link_route_to_module(
                int(saved["id"]),
                shared_module,
                shared_module_statuses.get(shared_module),
            )
            linked_modules.append(linked_route["modulo_id"])
        newly_linked_modules = sorted(set(linked_modules) - (previously_shared if route_id else set()))
        if newly_linked_modules:
            record_history(
                account,
                f"Vinculó ruta {saved.get('ruta', payload['ruta'])} a otros módulos (de Rutas)",
                newly_linked_modules,
                "vinculacion",
                f"Ruta: {saved.get('ruta', payload['ruta'])}; Módulos vinculados: {', '.join(map(str, newly_linked_modules))}",
                after=history_snapshot({
                    "Ruta": saved.get("ruta", payload["ruta"]),
                    "Origen": saved.get("origen", payload["origen"]),
                    "Módulo de origen": saved.get("mod1", module_number),
                    "Módulos compartidos": newly_linked_modules,
                }),
            )
    except Exception:
        app.logger.exception("No se pudo guardar la ruta")
        flash("No se pudo guardar la ruta. Verifica los datos.", "error")
    return redirect(url_for("admin_routes_page"))


@app.post("/administrador/rutas/vincular")
def admin_link_routes():
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))

    try:
        target_module = int(request.form.get("target_module", ""))
        route_ids = list(dict.fromkeys(int(value) for value in request.form.getlist("route_ids")))
    except (TypeError, ValueError):
        flash("Selecciona un módulo y rutas válidas.", "error")
        return redirect(url_for("admin_routes_page"))

    if target_module not in range(1, MAX_MODULES + 1) or not route_ids:
        flash("Selecciona un módulo y al menos una ruta.", "error")
        return redirect(url_for("admin_routes_page", module_number=target_module))

    try:
        initialize_schema()
        available_modules = {int(module["id"]) for module in request_modules()}
        if target_module not in available_modules:
            flash("El módulo de destino no está disponible.", "error")
            return redirect(url_for("admin_routes_page"))
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, ruta, origen, destino, servicio, estado, mod1, tipos FROM catalogos.rutas WHERE id = ANY(%s) ORDER BY ruta",
                    (route_ids,),
                )
                route_details = cursor.fetchall()
        linked_count = link_routes_to_module(route_ids, target_module)
        if linked_count:
            route_summary = ", ".join(f"{route[1]} (#{route[0]})" for route in route_details)
            route_snapshots = [
                history_snapshot({
                    "Ruta": route[1],
                    "Tipo": route[7],
                    "Origen": route[2],
                    "Destino": route[3],
                    "Servicio": route[4],
                    "Módulo de origen": route[6],
                    "Módulos compartidos": sorted(
                        set(fetch_shared_modules(route[0])) | {target_module}
                    ),
                    "Estado": route[5],
                })
                for route in route_details
            ]
            record_history(
                account,
                f"Vinculó {linked_count} ruta(s) al módulo {target_module} (de Rutas)",
                target_module,
                "vinculacion",
                f"Rutas vinculadas: {route_summary or ', '.join(map(str, route_ids))}; Módulo de destino: {target_module}",
                after=history_snapshot({
                    "Módulo de destino": target_module,
                    "Rutas vinculadas": route_snapshots,
                }),
            )
        flash(f"{linked_count} ruta(s) vinculada(s) correctamente.", "success")
    except ValueError as error:
        flash(str(error), "error")
    except Exception:
        app.logger.exception("No fue posible vincular las rutas seleccionadas")
        flash("No se pudieron vincular las rutas seleccionadas.", "error")
    return redirect(url_for("admin_routes_page", module_number=target_module))


@app.post("/administrador/rutas/<int:route_id>/eliminar")
def admin_delete_route(route_id: int):
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    try:
        initialize_schema()
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT ruta, origen, destino, servicio, estado, mod1, tipos FROM catalogos.rutas WHERE id = %s",
                    (route_id,),
                )
                route = cursor.fetchone()
        shared_modules = fetch_shared_modules(route_id) if route else []
        route_modules = [route[5], *shared_modules] if route else []
        if route is None:
            flash("No se encontró la ruta para eliminar.", "error")
        elif delete_route(route_id):
            record_history(
                account,
                f"Eliminó ruta {route[0]} (de Rutas)",
                sorted(set(route_modules)),
                "eliminacion",
                f"Ruta: {route[0]}",
                before=history_snapshot({
                    "Ruta": route[0],
                    "Tipo": route[6],
                    "Origen": route[1],
                    "Destino": route[2],
                    "Servicio": route[3],
                    "Módulo de origen": route[5],
                    "Módulos compartidos": shared_modules,
                    "Estado": route[4],
                }) if route else None,
            )
            flash("Ruta eliminada correctamente.", "success")
        else:
            flash("No se encontró la ruta para eliminar.", "error")
    except Exception:
        flash("No se pudo eliminar la ruta.", "error")
    return redirect(url_for("admin_routes_page"))


@app.post("/administrador/rutas/eliminar-seleccionadas")
def admin_delete_selected_routes():
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))

    try:
        module_number = int(request.form.get("module_number", ""))
        route_ids = list(dict.fromkeys(int(value) for value in request.form.getlist("route_ids")))
    except (TypeError, ValueError):
        flash("Selecciona un módulo y rutas válidas.", "error")
        return redirect(url_for("admin_routes_page"))

    if module_number not in range(1, MAX_MODULES + 1) or not route_ids:
        flash("Selecciona un módulo y al menos una ruta.", "error")
        return redirect(url_for("admin_routes_page"))

    try:
        initialize_schema()
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, ruta, origen, destino, servicio, estado, mod1, tipos FROM catalogos.rutas WHERE id = ANY(%s) ORDER BY id",
                    (route_ids,),
                )
                routes_before_delete = cursor.fetchall()
        route_snapshots = []
        for route in routes_before_delete:
            route_snapshots.append(history_snapshot({
                "Ruta": route[1],
                "Tipo": route[7],
                "Origen": route[2],
                "Destino": route[3],
                "Servicio": route[4],
                "Módulo de origen": route[6],
                "Módulos compartidos": fetch_shared_modules(route[0]),
                "Estado": route[5],
            }))
        result = delete_routes_from_module(route_ids, module_number)
        if result["deleted_originals"] or result["unlinked_shared"]:
            record_history(
                account,
                f"Eliminó {result['deleted_originals']} ruta(s) y desvinculó {result['unlinked_shared']} ruta(s) compartida(s) (de Rutas)",
                module_number,
                "eliminacion",
                f"IDs de rutas: {', '.join(map(str, route_ids))}",
                before=history_snapshot({
                    "Módulo afectado": module_number,
                    "Rutas": route_snapshots,
                }),
            )
        messages = []
        if result["deleted_originals"]:
            messages.append(f'{result["deleted_originals"]} ruta(s) original(es) eliminada(s)')
        if result["unlinked_shared"]:
            messages.append(f'{result["unlinked_shared"]} ruta(s) compartida(s) desvinculada(s)')
        flash("; ".join(messages) + ".", "success")
    except ValueError as error:
        flash(str(error), "error")
    except Exception:
        app.logger.exception("No fue posible eliminar las rutas seleccionadas")
        flash("No se pudieron eliminar las rutas seleccionadas.", "error")
    return redirect(url_for("admin_routes_page", module_number=module_number))


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
        shared_modules = fetch_shared_modules(route_id)
        shared_statuses = fetch_shared_module_statuses(route_id)
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT ruta, origen, destino, servicio, estado, mod1, tipos FROM catalogos.rutas WHERE id = %s",
                    (route_id,),
                )
                previous_route = cursor.fetchone()
        updated_route = update_route_status(route_id, requested_status)
        if updated_route is None:
            flash("No se encontró la ruta para actualizar.", "error")
        else:
            route_name = str(previous_route[0]).strip()
            route_label = (
                route_name
                if route_name.casefold().startswith("ruta ")
                else f"Ruta {route_name}"
            )
            record_history(
                account,
                f"{route_label} {requested_status.lower()} (de Rutas)",
                sorted({updated_route["mod1"], *shared_modules}),
                "edicion",
                f"Estado: {requested_status}",
                before=history_snapshot({
                    "Ruta": previous_route[0],
                    "Tipo": previous_route[6],
                    "Origen": previous_route[1],
                    "Destino": previous_route[2],
                    "Servicio": previous_route[3],
                    "Estado": previous_route[4],
                    "Módulos vinculados": [
                        {"Módulo": previous_route[5], "Estado": previous_route[4]},
                        *[
                            {"Módulo": shared_id, "Estado": shared_statuses[shared_id]}
                            for shared_id in sorted(shared_modules)
                        ],
                    ],
                }) if previous_route else None,
                after=history_snapshot({
                    "Ruta": previous_route[0],
                    "Tipo": previous_route[6],
                    "Origen": previous_route[1],
                    "Destino": previous_route[2],
                    "Servicio": previous_route[3],
                    "Estado": updated_route["estado"],
                    "Módulos vinculados": [
                        {"Módulo": updated_route["mod1"], "Estado": updated_route["estado"]},
                        *[
                            {"Módulo": shared_id, "Estado": shared_statuses[shared_id]}
                            for shared_id in sorted(shared_modules)
                        ],
                    ],
                }) if previous_route else None,
            )
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
        shared_statuses = fetch_shared_module_statuses(route_id)
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT ruta, origen, destino, servicio, estado, mod1, tipos FROM catalogos.rutas WHERE id = %s",
                    (route_id,),
                )
                previous_route = cursor.fetchone()
        updated_route = update_module_route_status(route_id, module_number, requested_status)
        if updated_route is None:
            flash("No se encontró la ruta compartida.", "error")
        else:
            record_history(
                account,
                f"Ruta compartida {route_id} {requested_status.lower()} en el módulo {module_number} (de Rutas)",
                module_number,
                "edicion",
                f"ID de la ruta: {route_id}; Estado: {requested_status}",
                before=history_snapshot({
                    "Ruta": previous_route[0],
                    "Tipo": previous_route[6],
                    "Origen": previous_route[1],
                    "Destino": previous_route[2],
                    "Servicio": previous_route[3],
                    "Estado": previous_route[4],
                    "Módulos vinculados": [
                        {"Módulo": previous_route[5], "Estado": previous_route[4]},
                        *[
                            {"Módulo": shared_id, "Estado": shared_statuses[shared_id]}
                            for shared_id in sorted(shared_statuses)
                        ],
                    ],
                }) if previous_route else None,
                after=history_snapshot({
                    "Ruta": previous_route[0],
                    "Tipo": previous_route[6],
                    "Origen": previous_route[1],
                    "Destino": previous_route[2],
                    "Servicio": previous_route[3],
                    "Estado": previous_route[4],
                    "Módulos vinculados": [
                        {"Módulo": previous_route[5], "Estado": previous_route[4]},
                        *[
                            {
                                "Módulo": shared_id,
                                "Estado": requested_status if shared_id == module_number else shared_statuses[shared_id],
                            }
                            for shared_id in sorted(shared_statuses)
                        ],
                    ],
                }) if previous_route else None,
            )
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
        shared_statuses = fetch_shared_module_statuses(route_id)
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT ruta, origen, destino, servicio, estado, mod1, tipos FROM catalogos.rutas WHERE id = %s",
                    (route_id,),
                )
                route = cursor.fetchone()
        if unlink_route_from_module(route_id, module_number):
            record_history(
                account,
                f"Desvinculó ruta {route_id} del módulo {module_number} (de Rutas)",
                module_number,
                "desvinculacion",
                f"ID de la ruta: {route_id}; Módulo: {module_number}",
                before=history_snapshot({
                    "Ruta": route[0],
                    "Tipo": route[6],
                    "Origen": route[1],
                    "Destino": route[2],
                    "Servicio": route[3],
                    "Módulo de origen": route[5],
                    "Módulos compartidos": [
                        {
                            "Módulo": shared_id,
                            "Estado": shared_statuses[shared_id],
                        }
                        for shared_id in sorted(shared_statuses)
                    ],
                    "Estado": route[4],
                }) if route else None,
            )
            flash("Ruta desvinculada del módulo correctamente.", "success")
        else:
            flash("No se encontró la ruta compartida.", "error")
    except Exception:
        flash("No se pudo desvincular la ruta.", "error")
    return redirect(url_for("admin_routes_page"))


@app.get("/administrador/turnos")
def admin_turnos_page():
    account = session.get("account")
    if not account_can_view_admin(account):
        return redirect(url_for("connection_status"))
    edit_turno_id = request.args.get("edit_id", type=int)
    module_names = {}
    try:
        initialize_schema()
        renumber_turnos_by_start()
        modules = request_modules()
        turnos = fetch_catalog_items("turnos")
        module_names = {module["id"]: module["nombre"] for module in modules}
        turno_modules = fetch_turno_modules_map([turno["id"] for turno in turnos])
        turno_module_statuses = fetch_turno_module_statuses_map([turno["id"] for turno in turnos])
        for turno in turnos:
            turno["module_ids"] = turno_modules.get(turno["id"], [])
            turno["module_statuses"] = turno_module_statuses.get(turno["id"], {})
            turno["modules"] = [
                module_names.get(module_id, f"Módulo {module_id}")
                for module_id in turno["module_ids"]
            ] if turno.get("alcance") != "general" else []
        next_turno_number = max((turno["numero"] for turno in turnos), default=0) + 1
    except Exception:
        modules = []
        turnos = []
        turno_modules = {}
        turno_module_statuses = {}
        next_turno_number = 1
    editing_turno = next((turno for turno in turnos if turno.get("id") == edit_turno_id), None) if edit_turno_id else None
    selected_turno_modules = turno_modules.get(edit_turno_id, []) if editing_turno else []
    selected_turno_module_statuses = {}
    if editing_turno:
        try:
            selected_turno_module_statuses = fetch_turno_module_status_map(edit_turno_id)
        except Exception:
            selected_turno_module_statuses = {}
    return render_template(
        "admin/turnos.html",
        account=account,
        turnos=turnos,
        editing_turno=editing_turno,
        modules=modules,
        selected_turno_modules=selected_turno_modules,
        selected_turno_module_statuses=selected_turno_module_statuses,
        module_names=module_names,
        next_turno_number=next_turno_number,
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
    alcance = request.form.get("turno_scope", "especifico")
    if alcance not in {"general", "especifico"}:
        flash("El alcance del turno no es válido.", "error")
        return redirect(url_for("admin_turnos_page"))
    current_turno_id = int(turno_id) if turno_id and turno_id.isdigit() else None
    if current_turno_id is not None and not numero.isdigit():
        try:
            with get_connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT numero FROM catalogos.turnos WHERE id = %s",
                        (current_turno_id,),
                    )
                    existing_turno = cursor.fetchone()
        except Exception:
            app.logger.exception("No se pudo leer el número del turno %s", current_turno_id)
            flash("No se pudo cargar el turno para actualizar.", "error")
            return redirect(url_for("admin_turnos_page"))
        if existing_turno is None:
            flash("No se encontró el turno para actualizar.", "error")
            return redirect(url_for("admin_turnos_page"))
        numero = str(existing_turno[0])
    activo = alcance == "general" or request.form.get("activo") == "on"
    selected_modules = sorted({int(value) for value in request.form.getlist("turno_modules") if value.isdigit()})
    if alcance == "general":
        selected_modules = [module["id"] for module in request_modules()]
    elif not selected_modules:
        flash("Selecciona al menos un módulo para un turno específico.", "error")
        return redirect(url_for("admin_turnos_page"))
    module_statuses = {
        module_number: request.form.get(f"turno_module_status_{module_number}") == "Activo"
        for module_number in selected_modules
    }
    if alcance == "general":
        module_statuses = {module_number: True for module_number in selected_modules}
    module_summary = ", ".join(
        f"{module} ({'Activo' if module_statuses[module] else 'Inactivo'})"
        for module in selected_modules
    )
    if any(module_number not in range(1, MAX_MODULES + 1) for module_number in selected_modules):
        flash("Selecciona módulos válidos para el turno.", "error")
        return redirect(url_for("admin_turnos_page"))

    if not hora_inicio or not hora_fin:
        flash("Completa las horas de inicio y fin.", "error")
        return redirect(url_for("admin_turnos_page"))

    try:
        if turno_start_exists(hora_inicio, current_turno_id):
            flash("Ya existe un turno con esa hora de inicio.", "error")
            return redirect(url_for("admin_turnos_page"))
        numero = str(get_next_turno_number()) if current_turno_id is None else numero
        if not numero.isdigit():
            flash("No se pudo determinar el número consecutivo del turno.", "error")
            return redirect(url_for("admin_turnos_page"))
    except Exception:
        flash("No se pudo validar la hora de inicio del turno.", "error")
        return redirect(url_for("admin_turnos_page"))

    payload = {
        "numero": int(numero),
        "hora_inicio": hora_inicio,
        "hora_fin": hora_fin,
        "activo": activo,
        "alcance": alcance,
    }

    try:
        initialize_schema()
        if turno_id:
            previous_turno = next(
                (item for item in fetch_catalog_items("turnos") if item["id"] == int(turno_id)),
                None,
            )
            updated_turno = update_catalog_item("turnos", int(turno_id), payload)
            if updated_turno is None:
                flash("No se encontró el turno para actualizar.", "error")
                return redirect(url_for("admin_turnos_page"))
            previous_modules = fetch_turno_modules_map([int(turno_id)]).get(int(turno_id), [])
            previous_module_statuses = fetch_turno_module_statuses_map([int(turno_id)]).get(int(turno_id), {})
            set_turno_modules(int(turno_id), selected_modules, module_statuses)
            renumber_turnos_by_start()
            record_history(
                account,
                f"Editó {history_turno_time_label(updated_turno)} (de Turnos)",
                sorted(set(previous_modules) | set(selected_modules)),
                "edicion",
                f"Horario: {hora_inicio}-{hora_fin}; Alcance: {alcance}; Estado: {'Activo' if updated_turno['activo'] else 'Inactivo'}; Módulos: {module_summary}",
                before=history_turno_snapshot(
                    previous_turno,
                    previous_modules,
                    previous_module_statuses,
                ) if previous_turno else None,
                after=history_turno_snapshot(
                    updated_turno,
                    selected_modules,
                    module_statuses,
                ),
            )
            flash("Turno actualizado correctamente.", "success")
        else:
            created_turno = create_catalog_item("turnos", payload)
            set_turno_modules(created_turno["id"], selected_modules, module_statuses)
            renumber_turnos_by_start()
            record_history(
                account,
                f"Registró {history_turno_time_label(created_turno)} (de Turnos)",
                selected_modules,
                "registro",
                f"Horario: {hora_inicio}-{hora_fin}; Alcance: {alcance}; Estado: {'Activo' if created_turno['activo'] else 'Inactivo'}; Módulos: {module_summary}",
                after=history_turno_snapshot(
                    created_turno,
                    selected_modules,
                    module_statuses,
                ),
            )
            flash("Turno registrado correctamente.", "success")
    except Exception:
        app.logger.exception("No se pudo guardar el turno %s", current_turno_id or "nuevo")
        flash("No se pudo guardar el turno. Verifica que el número no esté repetido.", "error")

    return redirect(url_for("admin_turnos_page"))


@app.post("/administrador/turnos/<int:turno_id>/eliminar")
def admin_delete_turno(turno_id: int):
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    try:
        initialize_schema()
        turno = next(
            (item for item in fetch_catalog_items("turnos") if item["id"] == turno_id),
            None,
        )
        turno_modules = fetch_turno_modules_map([turno_id]).get(turno_id, [])
        turno_module_statuses = fetch_turno_module_statuses_map([turno_id]).get(turno_id, {})
        if delete_catalog_item("turnos", turno_id):
            record_history(
                account,
                f"Eliminó {history_turno_time_label(turno)} (de Turnos)",
                turno_modules,
                "eliminacion",
                (
                    f"Horario: {turno['hora_inicio']} a {turno['hora_fin']}"
                    if turno else "Horario no disponible"
                ),
                before=history_turno_snapshot(
                    turno,
                    turno_modules,
                    turno_module_statuses,
                ) if turno else None,
            )
            flash("Turno eliminado correctamente.", "success")
        else:
            flash("No se encontró el turno para eliminar.", "error")
    except Exception:
        flash("No se pudo eliminar el turno.", "error")
    return redirect(url_for("admin_turnos_page"))


@app.post("/administrador/turnos/eliminar-seleccionados")
def admin_delete_selected_turnos():
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))

    raw_turno_ids = request.form.getlist("turno_ids")
    try:
        turno_ids = list(dict.fromkeys(int(value) for value in raw_turno_ids))
    except (TypeError, ValueError):
        flash("Selecciona turnos válidos.", "error")
        return redirect(url_for("admin_turnos_page"))

    if not turno_ids or any(turno_id <= 0 for turno_id in turno_ids):
        flash("Selecciona al menos un turno válido.", "error")
        return redirect(url_for("admin_turnos_page"))

    try:
        initialize_schema()
        turno_modules = fetch_turno_modules_map(turno_ids)
        turno_module_statuses = fetch_turno_module_statuses_map(turno_ids)
        turnos_by_id = {
            turno["id"]: turno
            for turno in fetch_catalog_items("turnos")
            if turno["id"] in turno_ids
        }
        deleted_ids = delete_turnos_by_ids(turno_ids)
        renumber_turnos_by_start()
        for deleted_id in deleted_ids:
            deleted_turno = turnos_by_id.get(deleted_id)
            record_history(
                account,
                f"Eliminó {history_turno_time_label(deleted_turno)} (de Turnos)",
                turno_modules.get(deleted_id, []),
                "eliminacion",
                (
                    f"Horario: {deleted_turno['hora_inicio']} a {deleted_turno['hora_fin']}"
                    if deleted_turno else "Horario no disponible"
                ),
                before=history_turno_snapshot(
                    deleted_turno,
                    turno_modules.get(deleted_id, []),
                    turno_module_statuses.get(deleted_id, {}),
                ) if deleted_turno else None,
            )
        flash(f"{len(deleted_ids)} turno(s) eliminado(s) correctamente.", "success")
    except ValueError as error:
        flash(str(error), "error")
    except Exception:
        app.logger.exception("No fue posible eliminar los turnos seleccionados")
        flash("No se pudieron eliminar los turnos seleccionados.", "error")
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
        turno_modules = fetch_turno_modules_map([turno_id]).get(turno_id, [])
        turno_module_statuses = fetch_turno_module_statuses_map([turno_id]).get(turno_id, {})
        previous_turno = next(
            (item for item in fetch_catalog_items("turnos") if item["id"] == turno_id),
            None,
        )
        updated_shift = update_shift_status(turno_id, requested_status == "Activo")
        if updated_shift is None:
            flash("No se encontró el turno para actualizar.", "error")
        else:
            status_verb = "Activó" if requested_status == "Activo" else "Desactivó"
            record_history(
                account,
                f"{status_verb} {history_turno_time_label(previous_turno)} (de Turnos)",
                turno_modules,
                "edicion",
                f"Estado: {requested_status}",
                before=history_turno_snapshot(
                    previous_turno,
                    turno_modules,
                    turno_module_statuses,
                ) if previous_turno else None,
                after=history_turno_snapshot(
                    {**previous_turno, "activo": updated_shift["active"]},
                    turno_modules,
                    turno_module_statuses,
                ) if previous_turno else None,
            )
            flash(f"Turno {requested_status.lower()} correctamente.", "success")
    except Exception:
        flash("No se pudo cambiar el estado del turno.", "error")
    return redirect(url_for("admin_turnos_page"))


@app.post("/administrador/turnos/<int:turno_id>/modulos/<int:module_id>/estado")
def admin_toggle_turno_module_status(turno_id: int, module_id: int):
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    requested_status = str(request.form.get("estado", "")).strip()
    if requested_status not in {"Activo", "Inactivo"}:
        flash("El estado del turno por módulo no es válido.", "error")
        return redirect(url_for("admin_turnos_page"))
    try:
        initialize_schema()
        turno = next(
            (item for item in fetch_catalog_items("turnos") if item["id"] == turno_id),
            None,
        )
        turno_modules = fetch_turno_modules_map([turno_id]).get(turno_id, [])
        module_statuses = fetch_turno_module_statuses_map([turno_id]).get(turno_id, {})
        previous_module_status = module_statuses.get(module_id)
        updated = update_turno_module_status(
            turno_id,
            module_id,
            requested_status == "Activo",
        )
        if updated:
            status_verb = "Activó" if requested_status == "Activo" else "Desactivó"
            record_history(
                account,
                (
                    f"{status_verb} {history_turno_time_label(turno)} "
                    f"en el módulo {module_id} (de Turnos)"
                ),
                module_id,
                "edicion",
                (
                    f"Horario: {turno['hora_inicio']} a {turno['hora_fin']}; "
                    f"Módulo: {module_id}; Estado: {requested_status}"
                    if turno else f"Módulo: {module_id}; Estado: {requested_status}"
                ),
                before=history_turno_snapshot(turno, turno_modules, module_statuses)
                if turno else None,
                after=history_turno_snapshot(
                    turno,
                    turno_modules,
                    {**module_statuses, module_id: requested_status == "Activo"},
                ) if turno else None,
            )
        flash(
            f"Turno {requested_status.lower()} en el módulo correctamente."
            if updated else "No se encontró la asignación del turno en el módulo.",
            "success" if updated else "error",
        )
    except Exception:
        flash("No se pudo cambiar el estado del turno en el módulo.", "error")
    return redirect(url_for("admin_turnos_page", module_number=module_id))


@app.get("/administrador/tipos-rutas")
def admin_tipos_rutas_page():
    return redirect(url_for("admin_routes_page"))


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
        categoria = str(request.form.get("categoria", "")).strip().lower()
        activo = request.form.get("activo") == "on"
        if not codigo or not descripcion or categoria not in {
            "trabajo",
            "descanso",
            "falta",
            "vacaciones",
            "incapacidad",
        }:
            flash("Completa el código, la descripción y una categoría válida para el estado especial.", "error")
            return redirect(url_for("admin_monthly_role_page", tab="estados"))
        payload = {"codigo": codigo, "descripcion": descripcion, "categoria": categoria, "activo": activo}
        try:
            initialize_schema()
            if estado_id:
                previous_estado = next(
                    (item for item in fetch_catalog_items("estados_especiales") if item["id"] == int(estado_id)),
                    None,
                )
                saved_estado = update_catalog_item("estados_especiales", int(estado_id), payload)
                history_action = "edicion"
                history_verb = "Editó"
            else:
                saved_estado = create_catalog_item("estados_especiales", payload)
                history_action = "registro"
                history_verb = "Registró"
            if saved_estado is not None:
                record_history(
                    account,
                    f"{history_verb} estado especial {saved_estado['codigo']} (de Estados especiales)",
                    None,
                    history_action,
                    f"Código: {saved_estado['codigo']}; Descripción: {saved_estado['descripcion']}; Categoría: {saved_estado['categoria']}; Estado: {'Activo' if saved_estado['activo'] else 'Inactivo'}",
                    before=history_snapshot({
                        "Código": previous_estado["codigo"],
                        "Descripción": previous_estado["descripcion"],
                        "Categoría": previous_estado["categoria"],
                        "Estado": previous_estado["activo"],
                    }) if estado_id and previous_estado else None,
                    after=history_snapshot({
                        "Código": saved_estado["codigo"],
                        "Descripción": saved_estado["descripcion"],
                        "Categoría": saved_estado["categoria"],
                        "Estado": saved_estado["activo"],
                    }),
                )
            try:
                refresh_analysis_tables()
            except Exception:
                app.logger.exception(
                    "No se pudieron actualizar las tablas analíticas después de guardar el estado %s",
                    codigo,
                )
                flash(
                    "El estado especial se guardó, pero no se actualizaron las tablas analíticas.",
                    "error",
                )
                return redirect(url_for("admin_monthly_role_page", tab="estados"))
            if estado_id:
                flash("Estado especial actualizado correctamente.", "success")
            else:
                flash("Estado especial registrado correctamente.", "success")
        except Exception:
            flash("No se pudo guardar el estado especial. Verifica que el código no esté repetido.", "error")
        return redirect(url_for("admin_monthly_role_page", tab="estados"))

    if catalog == "servicio":
        catalog_tab = "servicios"
        servicio_id = request.form.get("servicio_id")
        nombre = str(request.form.get("nombre", "")).strip()
        activo_values = request.form.getlist("activo")
        activo = not activo_values or "on" in activo_values
        if not nombre:
            flash("El nombre del servicio es obligatorio.", "error")
            return redirect(url_for("admin_routes_page", catalog_tab=catalog_tab))
        if not valid_controller_name(nombre):
            flash("El nombre del servicio solo puede contener letras y espacios.", "error")
            return redirect(url_for("admin_routes_page", catalog_tab=catalog_tab))
        try:
            initialize_schema()
            if servicio_id:
                previous_servicio = next(
                    (item for item in fetch_catalog_items("servicio") if item["id"] == int(servicio_id)),
                    None,
                )
                updated_servicio = update_catalog_item("servicio", int(servicio_id), {"nombre": nombre, "activo": activo})
                if updated_servicio is None:
                    flash("No se encontró el servicio para actualizar.", "error")
                else:
                    record_history(
                        account,
                        f"Editó servicio {updated_servicio['nombre']} (de Servicios)",
                        None,
                        "edicion",
                        f"Nombre: {updated_servicio['nombre']}; Estado: {'Activo' if updated_servicio['activo'] else 'Inactivo'}",
                        before=history_snapshot({
                            "Nombre": previous_servicio["nombre"],
                            "Estado": previous_servicio["activo"],
                        }) if previous_servicio else None,
                        after=history_snapshot({
                            "Nombre": updated_servicio["nombre"],
                            "Estado": updated_servicio["activo"],
                        }),
                    )
                    flash("Servicio actualizado correctamente.", "success")
            else:
                created_servicio = create_catalog_item("servicio", {"nombre": nombre, "activo": activo})
                record_history(
                    account,
                    f"Registró servicio {created_servicio['nombre']} (de Servicios)",
                    None,
                    "registro",
                    f"Nombre: {created_servicio['nombre']}; Estado: {'Activo' if created_servicio['activo'] else 'Inactivo'}",
                    after=history_snapshot({
                        "Nombre": created_servicio["nombre"],
                        "Estado": created_servicio["activo"],
                    }),
                )
                flash("Servicio registrado correctamente.", "success")
        except Exception:
            flash("No se pudo guardar el servicio. Verifica que el nombre no esté repetido.", "error")
        return redirect(url_for("admin_routes_page", catalog_tab=catalog_tab))

    catalog_tab = "tipos"
    tipo_id = request.form.get("tipo_id")
    descripcion = str(request.form.get("descripcion", "")).strip()
    activo_values = request.form.getlist("activo")
    activo = not activo_values or "on" in activo_values

    if not descripcion:
        flash("La descripción del tipo de ruta es obligatoria.", "error")
        return redirect(url_for("admin_routes_page", catalog_tab=catalog_tab))
    if not valid_controller_name(descripcion):
        flash("La descripción del tipo de ruta solo puede contener letras y espacios.", "error")
        return redirect(url_for("admin_routes_page", catalog_tab=catalog_tab))

    payload = {"descripcion": descripcion, "activo": activo}

    try:
        initialize_schema()
        if tipo_id:
            previous_tipo = next(
                (item for item in fetch_catalog_items("tipos_rutas") if item["id"] == int(tipo_id)),
                None,
            )
            updated_tipo = update_catalog_item("tipos_rutas", int(tipo_id), payload)
            if updated_tipo is None:
                flash("No se encontró el tipo de ruta para actualizar.", "error")
                return redirect(url_for("admin_routes_page", catalog_tab=catalog_tab))
            record_history(
                account,
                f"Editó tipo de ruta {updated_tipo['descripcion']} (de Tipos de rutas)",
                None,
                "edicion",
                f"Descripción: {updated_tipo['descripcion']}; Estado: {'Activo' if updated_tipo['activo'] else 'Inactivo'}",
                before=history_snapshot({
                    "Descripción": previous_tipo["descripcion"],
                    "Estado": previous_tipo["activo"],
                }) if previous_tipo else None,
                after=history_snapshot({
                    "Descripción": updated_tipo["descripcion"],
                    "Estado": updated_tipo["activo"],
                }),
            )
            flash("Tipo de ruta actualizado correctamente.", "success")
        else:
            created_tipo = create_catalog_item("tipos_rutas", payload)
            record_history(
                account,
                f"Registró tipo de ruta {created_tipo['descripcion']} (de Tipos de rutas)",
                None,
                "registro",
                f"Descripción: {created_tipo['descripcion']}; Estado: {'Activo' if created_tipo['activo'] else 'Inactivo'}",
                after=history_snapshot({
                    "Descripción": created_tipo["descripcion"],
                    "Estado": created_tipo["activo"],
                }),
            )
            flash("Tipo de ruta registrado correctamente.", "success")
    except Exception:
        flash("No se pudo guardar el tipo de ruta. Verifica que la descripción no esté repetida.", "error")

    return redirect(url_for("admin_routes_page", catalog_tab=catalog_tab))


@app.post("/administrador/tipos-rutas/<int:tipo_id>/eliminar")
def admin_delete_tipo_ruta(tipo_id: int):
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    try:
        initialize_schema()
        tipo_ruta = next(
            (item for item in fetch_catalog_items("tipos_rutas") if item["id"] == tipo_id),
            None,
        )
        if delete_catalog_item("tipos_rutas", tipo_id):
            record_history(
                account,
                f"Eliminó tipo de ruta {tipo_id} (de Tipos de rutas)",
                None,
                "eliminacion",
                f"ID del tipo de ruta: {tipo_id}",
                before=history_snapshot({
                    "Descripción": tipo_ruta["descripcion"],
                    "Estado": tipo_ruta["activo"],
                }) if tipo_ruta else None,
            )
            flash("Tipo de ruta eliminado correctamente.", "success")
        else:
            flash("No se encontró el tipo de ruta para eliminar.", "error")
    except Exception:
        flash("No se pudo eliminar el tipo de ruta.", "error")
    return redirect(url_for("admin_routes_page", catalog_tab="tipos"))


@app.post("/administrador/tipos-rutas/<int:tipo_id>/estado")
def admin_toggle_tipo_ruta_status(tipo_id: int):
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    requested_status = str(request.form.get("estado", "")).strip()
    if requested_status not in {"Activo", "Inactivo"}:
        flash("El estado del tipo de ruta no es válido.", "error")
        return redirect(url_for("admin_routes_page", catalog_tab="tipos"))
    try:
        initialize_schema()
        previous_tipo = next(
            (item for item in fetch_catalog_items("tipos_rutas") if item["id"] == tipo_id),
            None,
        )
        updated = update_catalog_status("tipos_rutas", tipo_id, requested_status == "Activo")
        if updated is not None:
            record_history(
                account,
                f"Tipo de ruta {updated['descripcion']} {requested_status.lower()} (de Tipos de rutas)",
                None,
                "edicion",
                f"Descripción: {updated['descripcion']}; Estado: {requested_status}",
                before=history_snapshot({
                    "Descripción": previous_tipo["descripcion"],
                    "Estado": previous_tipo["activo"],
                }) if previous_tipo else None,
                after=history_snapshot({
                    "Descripción": updated["descripcion"],
                    "Estado": updated["activo"],
                }),
            )
        flash(
            f"Tipo de ruta {requested_status.lower()} correctamente."
            if updated else "No se encontró el tipo de ruta para actualizar.",
            "success" if updated else "error",
        )
    except Exception:
        flash("No se pudo cambiar el estado del tipo de ruta.", "error")
    return redirect(url_for("admin_routes_page", catalog_tab="tipos"))


@app.post("/administrador/estados-especiales/<int:estado_id>/eliminar")
def admin_delete_estado_especial(estado_id: int):
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    try:
        initialize_schema()
        estado = next(
            (item for item in fetch_catalog_items("estados_especiales") if item["id"] == estado_id),
            None,
        )
        if delete_catalog_item("estados_especiales", estado_id):
            record_history(
                account,
                f"Eliminó estado especial {estado_id} (de Estados especiales)",
                None,
                "eliminacion",
                f"ID del estado especial: {estado_id}",
                before=history_snapshot({
                    "Código": estado["codigo"],
                    "Descripción": estado["descripcion"],
                    "Categoría": estado["categoria"],
                    "Estado": estado["activo"],
                }) if estado else None,
            )
            try:
                refresh_analysis_tables()
            except Exception:
                app.logger.exception(
                    "No se pudieron actualizar las tablas analíticas después de eliminar el estado %s",
                    estado_id,
                )
                flash(
                    "El estado especial se eliminó, pero no se actualizaron las tablas analíticas.",
                    "error",
                )
                return redirect(url_for("admin_monthly_role_page", tab="estados"))
            flash("Estado especial eliminado correctamente.", "success")
        else:
            flash("No se encontró el estado especial para eliminar.", "error")
    except Exception:
        flash("No se pudo eliminar el estado especial.", "error")
    return redirect(url_for("admin_monthly_role_page", tab="estados"))


@app.post("/administrador/estados-especiales/<int:estado_id>/estado")
def admin_toggle_estado_especial_status(estado_id: int):
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    requested_status = str(request.form.get("estado", "")).strip()
    if requested_status not in {"Activo", "Inactivo"}:
        flash("El estado especial no es válido.", "error")
        return redirect(url_for("admin_monthly_role_page", tab="estados"))
    try:
        initialize_schema()
        previous_estado = next(
            (item for item in fetch_catalog_items("estados_especiales") if item["id"] == estado_id),
            None,
        )
        updated = update_catalog_status(
            "estados_especiales",
            estado_id,
            requested_status == "Activo",
        )
        if updated is not None:
            record_history(
                account,
                f"Estado especial {updated['codigo']} {requested_status.lower()} (de Estados especiales)",
                None,
                "edicion",
                f"Código: {updated['codigo']}; Categoría: {updated['categoria']}; Estado: {requested_status}",
                before=history_snapshot({
                    "Código": previous_estado["codigo"],
                    "Descripción": previous_estado["descripcion"],
                    "Categoría": previous_estado["categoria"],
                    "Estado": previous_estado["activo"],
                }) if previous_estado else None,
                after=history_snapshot({
                    "Código": updated["codigo"],
                    "Descripción": updated["descripcion"],
                    "Categoría": updated["categoria"],
                    "Estado": updated["activo"],
                }),
            )
        flash(
            f"Estado especial {requested_status.lower()} correctamente."
            if updated else "No se encontró el estado especial para actualizar.",
            "success" if updated else "error",
        )
    except Exception:
        flash("No se pudo cambiar el estado especial.", "error")
    return redirect(url_for("admin_monthly_role_page", tab="estados"))


@app.post("/administrador/servicios/<int:servicio_id>/eliminar")
def admin_delete_servicio(servicio_id: int):
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    try:
        initialize_schema()
        servicio = next(
            (item for item in fetch_catalog_items("servicio") if item["id"] == servicio_id),
            None,
        )
        if delete_catalog_item("servicio", servicio_id):
            record_history(
                account,
                f"Eliminó servicio {servicio_id} (de Servicios)",
                None,
                "eliminacion",
                f"ID del servicio: {servicio_id}",
                before=history_snapshot({
                    "Nombre": servicio["nombre"],
                    "Estado": servicio["activo"],
                }) if servicio else None,
            )
            flash("Servicio eliminado correctamente.", "success")
        else:
            flash("No se encontró el servicio para eliminar.", "error")
    except Exception:
        flash("No se pudo eliminar el servicio.", "error")
    return redirect(url_for("admin_routes_page", catalog_tab="servicios"))


@app.post("/administrador/servicios/<int:servicio_id>/estado")
def admin_toggle_servicio_status(servicio_id: int):
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    requested_status = str(request.form.get("estado", "")).strip()
    if requested_status not in {"Activo", "Inactivo"}:
        flash("El estado del servicio no es válido.", "error")
        return redirect(url_for("admin_routes_page", catalog_tab="servicios"))
    try:
        initialize_schema()
        previous_servicio = next(
            (item for item in fetch_catalog_items("servicio") if item["id"] == servicio_id),
            None,
        )
        updated = update_catalog_status("servicio", servicio_id, requested_status == "Activo")
        if updated is not None:
            record_history(
                account,
                f"Servicio {updated['nombre']} {requested_status.lower()} (de Servicios)",
                None,
                "edicion",
                f"Nombre: {updated['nombre']}; Estado: {requested_status}",
                before=history_snapshot({
                    "Nombre": previous_servicio["nombre"],
                    "Estado": previous_servicio["activo"],
                }) if previous_servicio else None,
                after=history_snapshot({
                    "Nombre": updated["nombre"],
                    "Estado": updated["activo"],
                }),
            )
        flash(
            f"Servicio {requested_status.lower()} correctamente."
            if updated else "No se encontró el servicio para actualizar.",
            "success" if updated else "error",
        )
    except Exception:
        flash("No se pudo cambiar el estado del servicio.", "error")
    return redirect(url_for("admin_routes_page", catalog_tab="servicios"))


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
        "active": request.form.get("estado", "Activo") == "Activo",
    }

    controller_id = request.form.get("controller_id")
    if not payload["nombre"] or not payload["credencial"] or not payload["sexo"] or not payload["mod1"]:
        flash("Completa todos los campos del controlador.", "error")
        return redirect(url_for("admin_controllers_page"))

    try:
        initialize_schema()
        if controller_id:
            with get_connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT nombre, credencial, sexo, mod1, active FROM catalogos.controladores WHERE id = %s",
                        (int(controller_id),),
                    )
                    previous_controller = cursor.fetchone()
            updated_controller = update_controller(int(controller_id), payload)
            if updated_controller is None:
                flash("No se encontró el controlador para actualizar.", "error")
                return redirect(url_for("admin_controllers_page"))
            record_history(
                account,
                f"Editó controlador {updated_controller['credencial']} (de Controladores)",
                updated_controller["mod1"],
                "edicion",
                f"Nombre: {updated_controller['nombre']}; Credencial: {updated_controller['credencial']}; Sexo: {updated_controller['sexo']}; Estado: {'Activo' if updated_controller['active'] else 'Inactivo'}",
                before=history_snapshot({
                    "Nombre": previous_controller[0],
                    "Credencial": previous_controller[1],
                    "Sexo": previous_controller[2],
                    "Módulo": previous_controller[3],
                    "Estado": previous_controller[4],
                }) if previous_controller else None,
                after=history_snapshot({
                    "Nombre": updated_controller["nombre"],
                    "Credencial": updated_controller["credencial"],
                    "Sexo": updated_controller["sexo"],
                    "Módulo": updated_controller["mod1"],
                    "Estado": updated_controller["active"],
                }),
            )
            flash("Controlador actualizado correctamente.", "success")
        else:
            created_controller = create_controller(payload)
            record_history(
                account,
                f"Registró controlador {payload['credencial']} (de Controladores)",
                payload["mod1"],
                "registro",
                f"Nombre: {created_controller.get('nombre', payload['nombre'])}; Credencial: {payload['credencial']}; Sexo: {payload['sexo']}; Estado: {'Activo' if created_controller.get('active', payload['active']) else 'Inactivo'}",
                after=history_snapshot({
                    "Nombre": created_controller.get("nombre", payload["nombre"]),
                    "Credencial": created_controller.get("credencial", payload["credencial"]),
                    "Sexo": created_controller.get("sexo", payload["sexo"]),
                    "Módulo": created_controller.get("mod1", payload["mod1"]),
                    "Estado": created_controller.get("active", payload["active"]),
                }),
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
                    "SELECT nombre, credencial, sexo, mod1, active FROM catalogos.controladores WHERE id = %s",
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
                    before=history_snapshot({
                        "Nombre": controller[0],
                        "Credencial": controller[1],
                        "Sexo": controller[2],
                        "Módulo": controller[3],
                        "Estado": controller[4],
                    }),
                )
            flash("Controlador eliminado correctamente.", "success")
        else:
            flash("No se encontró el controlador para eliminar.", "error")
    except Exception:
        flash("No se pudo eliminar el controlador.", "error")
    return redirect(url_for("admin_controllers_page"))


@app.post("/administrador/controladores/eliminar-seleccionados")
def admin_delete_selected_controllers():
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))

    try:
        module_number = int(request.form.get("module_number", ""))
        controller_ids = list(dict.fromkeys(int(value) for value in request.form.getlist("controller_ids")))
    except (TypeError, ValueError):
        flash("Selecciona un módulo y controladores válidos.", "error")
        return redirect(url_for("admin_controllers_page"))

    if module_number not in range(1, MAX_MODULES + 1) or not controller_ids:
        flash("Selecciona un módulo y al menos un controlador.", "error")
        return redirect(url_for("admin_controllers_page"))

    try:
        initialize_schema()
        controllers = delete_controllers_from_module(controller_ids, module_number)
        for controller in controllers:
            record_history(
                account,
                f"Eliminó controlador {controller['credencial']} (de Controladores)",
                controller["mod1"],
                "eliminacion",
                f"Nombre: {controller['nombre']}; Credencial: {controller['credencial']}; Sexo: {controller['sexo']}",
                before=history_snapshot({
                    "Nombre": controller["nombre"],
                    "Credencial": controller["credencial"],
                    "Sexo": controller["sexo"],
                    "Módulo": controller["mod1"],
                    "Estado": controller.get("active", True),
                }),
            )
        flash(f"{len(controllers)} controlador(es) eliminado(s) correctamente.", "success")
    except ValueError as error:
        flash(str(error), "error")
    except Exception:
        app.logger.exception("No fue posible eliminar los controladores seleccionados")
        flash("No se pudieron eliminar los controladores seleccionados.", "error")
    return redirect(url_for("admin_controllers_page", module_number=module_number))


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
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT nombre, credencial, sexo, mod1, active FROM catalogos.controladores WHERE id = %s",
                    (controller_id,),
                )
                previous_controller = cursor.fetchone()
        updated_controller = update_controller_status(controller_id, requested_status == "Activo")
        if updated_controller is None:
            flash("No se encontró el controlador para actualizar.", "error")
        else:
            record_history(
                account,
                f"Controlador {previous_controller[1]} {requested_status.lower()} (de Controladores)",
                previous_controller[3] if previous_controller else None,
                "edicion",
                f"ID del controlador: {controller_id}; Estado: {requested_status}",
                before=history_snapshot({
                    "Nombre": previous_controller[0],
                    "Credencial": previous_controller[1],
                    "Sexo": previous_controller[2],
                    "Módulo": previous_controller[3],
                    "Estado": previous_controller[4],
                }) if previous_controller else None,
                after=history_snapshot({
                    "Nombre": previous_controller[0],
                    "Credencial": previous_controller[1],
                    "Sexo": previous_controller[2],
                    "Módulo": previous_controller[3],
                    "Estado": updated_controller["active"],
                }) if previous_controller else None,
            )
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
    if tipo_usuario not in {"usuario", "admin", "consultor"}:
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
    users_page_url = (
        url_for("admin_users_page", edit_user_id=user_id)
        if user_id
        else url_for("admin_users_page")
    )

    if not username:
        flash("El nombre de usuario es obligatorio.", "error")
        return redirect(url_for("admin_users_page"))
    if correo and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", correo):
        flash("Ingresa un correo electrónico válido.", "error")
        return redirect(users_page_url)
    if telefono and not re.fullmatch(r"[0-9]{10}", telefono):
        flash("El teléfono debe contener exactamente 10 dígitos.", "error")
        return redirect(users_page_url)
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
            "active": request.form.get("activo") == "on",
        }
        if user_id:
            with get_connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT username, correo, telefono, module_number, is_admin, tipo_usuario, active FROM seguridad.usuarios WHERE id = %s",
                        (int(user_id),),
                    )
                    previous_user = cursor.fetchone()
            if password:
                payload["password_hash"] = generate_password_hash(password)
            updated_user = update_user(int(user_id), payload)
            if updated_user is None:
                flash("No se encontró el usuario para actualizar.", "error")
                return redirect(url_for("admin_users_page"))
            user_type = {
                "usuario": "Supervisor",
                "admin": "Administrador",
                "consultor": "Consultor",
            }.get(updated_user["tipo_usuario"], updated_user["tipo_usuario"])
            record_history(
                account,
                f"Editó usuario {updated_user['username']} (de Usuarios)",
                updated_user["module_number"],
                "edicion",
                f"Tipo: {user_type}; Estado: {'Activo' if updated_user['active'] else 'Inactivo'}",
                before=history_snapshot({
                    "Usuario": previous_user[0],
                    "Tipo de usuario": history_user_type_label(previous_user[5]),
                    "Correo electrónico": previous_user[1],
                    "Teléfono": previous_user[2],
                    "Módulo": previous_user[3],
                    "Estado": previous_user[6],
                }) if previous_user else None,
                after=history_snapshot({
                    "Usuario": updated_user["username"],
                    "Tipo de usuario": history_user_type_label(updated_user["tipo_usuario"]),
                    "Correo electrónico": updated_user.get("correo"),
                    "Teléfono": updated_user.get("telefono"),
                    "Módulo": updated_user.get("module_number"),
                    "Estado": updated_user["active"],
                }),
            )
            if password:
                record_history(
                    account,
                    f"Cambió la contraseña del usuario {updated_user['username']}",
                    updated_user["module_number"],
                    "contrasena",
                    "La contraseña del usuario fue actualizada por un administrador.",
                )
            flash("Usuario actualizado correctamente.", "success")
        else:
            created_user = create_user({
                **payload,
                "password_hash": generate_password_hash(password),
            })
            user_type = {
                "usuario": "Supervisor",
                "admin": "Administrador",
                "consultor": "Consultor",
            }.get(created_user["tipo_usuario"], created_user["tipo_usuario"])
            record_history(
                account,
                f"Registró usuario {created_user['username']} (de Usuarios)",
                created_user["module_number"],
                "registro",
                f"Tipo: {user_type}; Estado: {'Activo' if created_user['active'] else 'Inactivo'}",
                after=history_snapshot({
                    "Usuario": created_user["username"],
                    "Tipo de usuario": history_user_type_label(created_user["tipo_usuario"]),
                    "Correo electrónico": created_user.get("correo"),
                    "Teléfono": created_user.get("telefono"),
                    "Módulo": created_user.get("module_number"),
                    "Estado": created_user["active"],
                }),
            )
            flash("Usuario creado correctamente.", "success")
    except Exception:
        flash("No se pudo guardar el usuario. Verifica que los datos no estén repetidos.", "error")

    return redirect(url_for("admin_users_page"))


@app.post("/administrador/usuarios/<int:user_id>/estado")
def admin_toggle_user_status(user_id: int):
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    requested_status = str(request.form.get("estado", "")).strip()
    if requested_status not in {"Activo", "Inactivo"}:
        flash("El estado del usuario no es válido.", "error")
        return redirect(url_for("admin_users_page"))
    try:
        initialize_schema()
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT username, correo, telefono, module_number, tipo_usuario, active FROM seguridad.usuarios WHERE id = %s",
                    (user_id,),
                )
                previous_user = cursor.fetchone()
        updated = update_user_status(user_id, requested_status == "Activo")
        if updated is not None:
            record_history(
                account,
                f"Usuario {previous_user[0]} {requested_status.lower()} (de Usuarios)",
                updated.get("module_number"),
                "edicion",
                f"ID del usuario: {user_id}; Estado: {requested_status}",
                before=history_snapshot({
                    "Usuario": previous_user[0],
                    "Tipo de usuario": history_user_type_label(previous_user[4]),
                    "Correo electrónico": previous_user[1],
                    "Teléfono": previous_user[2],
                    "Módulo": previous_user[3],
                    "Estado": previous_user[5],
                }) if previous_user else None,
                after=history_snapshot({
                    "Usuario": previous_user[0],
                    "Tipo de usuario": history_user_type_label(previous_user[4]),
                    "Correo electrónico": previous_user[1],
                    "Teléfono": previous_user[2],
                    "Módulo": updated["module_number"],
                    "Estado": updated["active"],
                }) if previous_user else None,
            )
        flash(
            f"Usuario {requested_status.lower()} correctamente."
            if updated else "No se encontró el usuario para actualizar.",
            "success" if updated else "error",
        )
    except Exception:
        flash("No se pudo cambiar el estado del usuario.", "error")
    return redirect(url_for("admin_users_page"))


@app.post("/administrador/usuarios/<int:user_id>/eliminar")
def admin_delete_user(user_id: int):
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))
    try:
        initialize_schema()
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT username, correo, telefono, module_number, tipo_usuario, active FROM seguridad.usuarios WHERE id = %s",
                    (user_id,),
                )
                user = cursor.fetchone()
        if delete_user(user_id):
            record_history(
                account,
                f"Eliminó usuario {user[0] if user else user_id} (de Usuarios)",
                user[3] if user else None,
                "eliminacion",
                f"ID del usuario: {user_id}",
                before=history_snapshot({
                    "Usuario": user[0],
                    "Tipo de usuario": history_user_type_label(user[4]),
                    "Correo electrónico": user[1],
                    "Teléfono": user[2],
                    "Módulo": user[3],
                    "Estado": user[5],
                }) if user else None,
            )
            flash("Usuario eliminado correctamente.", "success")
        else:
            flash("No se encontró el usuario para eliminar.", "error")
    except Exception:
        flash("No se pudo eliminar el usuario.", "error")
    return redirect(url_for("admin_users_page"))


@app.post("/administrador/usuarios/eliminar-seleccionados")
def admin_delete_selected_users():
    account = session.get("account")
    if not account or not account.get("is_admin"):
        return redirect(url_for("connection_status"))

    try:
        user_ids = list(dict.fromkeys(int(value) for value in request.form.getlist("user_ids")))
    except (TypeError, ValueError):
        flash("Selecciona usuarios válidos.", "error")
        return redirect(url_for("admin_users_page"))

    if not user_ids:
        flash("Selecciona al menos un usuario.", "error")
        return redirect(url_for("admin_users_page"))

    try:
        initialize_schema()
        users = delete_users_by_ids(user_ids)
        for user in users:
            user_type = {
                "usuario": "Supervisor",
                "admin": "Administrador",
                "consultor": "Consultor",
            }.get(user["tipo_usuario"], user["tipo_usuario"])
            record_history(
                account,
                f"Eliminó usuario {user['username']} (de Usuarios)",
                user["module_number"],
                "eliminacion",
                f"Tipo: {user_type}",
                before=history_snapshot({
                    "Usuario": user["username"],
                    "Tipo de usuario": history_user_type_label(user["tipo_usuario"]),
                    "Correo electrónico": user.get("correo"),
                    "Teléfono": user.get("telefono"),
                    "Módulo": user.get("module_number"),
                    "Estado": user.get("active"),
                }),
            )
        flash(f"{len(users)} usuario(s) eliminado(s) correctamente.", "success")
    except ValueError as error:
        flash(str(error), "error")
    except Exception:
        app.logger.exception("No fue posible eliminar los usuarios seleccionados")
        flash("No se pudieron eliminar los usuarios seleccionados.", "error")
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


@app.get("/api/modulos/<int:module_number>/turnos")
def module_turnos(module_number: int):
    if not module_authorized(module_number):
        return jsonify(error="No autorizado."), 403
    try:
        initialize_schema()
        return jsonify(fetch_catalog_items("turnos", module_number))
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


@app.post("/api/turnos/<int:turno_id>/descartar")
def discard_assigned_turno(turno_id: int):
    account = session.get("account")
    module_number = account.get("module_number") if account else None
    if (
        not account
        or account.get("is_admin")
        or account.get("tipo_usuario") == "consultor"
        or type(module_number) is not int
        or module_number < 1
    ):
        return jsonify(error="No autorizado."), 403
    try:
        initialize_schema()
        turno = next(
            (
                item
                for item in fetch_catalog_items("turnos", module_number)
                if item["id"] == turno_id and item["activo"]
            ),
            None,
        )
        if turno is None:
            return jsonify(error="El turno ya no está disponible para este módulo."), 409
        recorded = record_history(
            account,
            f"Descartó turno {turno['numero']} (de Turnos)",
            module_number,
            "descarto",
            (
                f"Turno: {turno['numero']}; Inicio: {turno['hora_inicio']}; "
                f"Fin: {turno['hora_fin']}"
            ),
            before=history_turno_snapshot(
                turno, [module_number], {module_number: True}
            ),
        )
        if not recorded:
            return jsonify(error="No se pudo registrar el turno descartado."), 500
        return jsonify(ok=True)
    except Exception:
        app.logger.exception(
            "No se pudo registrar el descarte del turno %s para el módulo %s",
            turno_id,
            module_number,
        )
        return jsonify(error="No se pudo registrar el turno descartado."), 500


@app.post("/api/turnos/<int:turno_id>/agregar")
def add_assigned_turno(turno_id: int):
    account = session.get("account")
    module_number = account.get("module_number") if account else None
    if (
        not account
        or account.get("is_admin")
        or account.get("tipo_usuario") == "consultor"
        or type(module_number) is not int
        or module_number < 1
    ):
        return jsonify(error="No autorizado."), 403
    try:
        initialize_schema()
        turno = next(
            (
                item
                for item in fetch_catalog_items("turnos", module_number)
                if item["id"] == turno_id and item["activo"]
            ),
            None,
        )
        if turno is None:
            return jsonify(error="El turno ya no está disponible para este módulo."), 409
        recorded = record_history(
            account,
            f"Agregó turno {turno['numero']} (de Turnos)",
            module_number,
            "agrego",
            (
                f"Turno: {turno['numero']}; Inicio: {turno['hora_inicio']}; "
                f"Fin: {turno['hora_fin']}"
            ),
            after=history_turno_snapshot(
                turno, [module_number], {module_number: True}
            ),
        )
        if not recorded:
            return jsonify(error="No se pudo registrar el turno agregado."), 500
        return jsonify(ok=True)
    except Exception:
        app.logger.exception(
            "No se pudo registrar el turno %s agregado para el módulo %s",
            turno_id,
            module_number,
        )
        return jsonify(error="No se pudo registrar el turno agregado."), 500


CATALOG_FIELDS = {
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
        return redirect(url_for(
            "module_dashboard",
            module_number=module_number,
            controller_action="invalid",
        ))
    if not valid_controller_name(payload["nombre"]) or not valid_controller_credential(payload["credencial"]):
        return redirect(url_for(
            "module_dashboard",
            module_number=module_number,
            controller_action="invalid",
        ))
    payload["mod1"] = module_number
    payload["active"] = True
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
    except Exception as error:
        app.logger.exception(
            "No se pudo guardar el controlador con credencial %s en el módulo %s",
            payload["credencial"],
            module_number,
        )
        error_code = getattr(error, "sqlstate", None) or type(error).__name__
        return redirect(url_for(
            "module_dashboard",
            module_number=module_number,
            controller_action="error",
            controller_error=error_code,
        ))
    return redirect(url_for(
        "module_dashboard",
        module_number=module_number,
        controller_action="created",
        controller_id=created_controller["id"],
    ))


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
        if not valid_controller_name(str(payload["nombre"]).strip()):
            return jsonify(error="El nombre solo puede contener letras, acentos y espacios."), 400
        if not valid_controller_credential(str(payload["credencial"]).strip()):
            return jsonify(error="La credencial solo puede contener números."), 400

        mod1 = int(payload.get("mod1", account.get("module_number", 1) or 1))
        if account.get("is_admin") and not payload.get("mod1"):
            mod1 = 1

        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT nombre, credencial, sexo, mod1, active FROM catalogos.controladores WHERE id = %s",
                    (controller_id,),
                )
                previous_controller = cursor.fetchone()
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
            before={
                "Nombre": previous_controller[0],
                "Credencial": previous_controller[1],
                "Sexo": previous_controller[2],
                "Módulo": previous_controller[3],
                "Estado": previous_controller[4],
            } if previous_controller else None,
            after={
                "Nombre": updated["nombre"],
                "Credencial": updated["credencial"],
                "Sexo": updated["sexo"],
                "Módulo": updated["mod1"],
                "Estado": updated["active"],
            },
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


def _record_json_field(record: dict, field: str, expected_type: type, fallback):
    value = record.get(field)
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"El campo {field} de una asignación no es válido.") from error
    if not isinstance(value, expected_type):
        raise ValueError(f"El campo {field} de una asignación no es válido.")
    return value


def _record_assignment_code(record: dict, day: int) -> str:
    day_key = str(day)
    details = _record_json_field(record, "daily_details", dict, {})
    assignments = _record_json_field(record, "daily_assignments", dict, {})
    detail = details.get(day_key)
    code = detail.get("code") if isinstance(detail, dict) else None
    return str(code or assignments.get(day_key) or "").strip().upper()


def _record_day_list(record: dict, field: str) -> set[int]:
    days = _record_json_field(record, field, list, [])
    try:
        return {int(day) for day in days}
    except (TypeError, ValueError) as error:
        raise ValueError(f"El campo {field} de una asignación no es válido.") from error


def _copy_assignment_record(record: dict) -> dict:
    snapshot = copy(record)
    snapshot["work_days"] = sorted(_record_day_list(record, "work_days"))
    snapshot["rest_days"] = sorted(_record_day_list(record, "rest_days"))
    snapshot["daily_assignments"] = dict(
        _record_json_field(record, "daily_assignments", dict, {})
    )
    snapshot["daily_details"] = dict(
        _record_json_field(record, "daily_details", dict, {})
    )
    return snapshot


def _prepare_assignment_transfers(
    raw_transfers,
    previous_records: list[dict],
    submitted_records: list[dict],
    days_in_month: int,
    default_target_credential: str | None = None,
) -> tuple[list[dict], dict | None]:
    if raw_transfers is None or raw_transfers == []:
        return [], None
    if not isinstance(raw_transfers, list):
        raise ValueError("La lista de transferencias no es válida.")

    previous_by_credential = {
        str(record.get("credential", "")).strip(): record
        for record in previous_records
    }
    submitted_by_credential = {}
    for record in submitted_records:
        if not isinstance(record, dict):
            raise ValueError("Uno de los registros enviados no es válido.")
        credential = str(record.get("credential", "")).strip()
        if not credential or credential in submitted_by_credential:
            raise ValueError("Los registros enviados contienen credenciales inválidas o duplicadas.")
        submitted_by_credential[credential] = record

    source_before = {}
    source_after = {}
    target_before = {}
    target_after = {}
    events = []
    seen_transfers = set()

    for raw_transfer in raw_transfers:
        if not isinstance(raw_transfer, dict):
            raise ValueError("Una transferencia de código no es válida.")
        try:
            day = int(raw_transfer.get("day"))
        except (TypeError, ValueError) as error:
            raise ValueError("El día de una transferencia no es válido.") from error
        if isinstance(raw_transfer.get("day"), bool) or day < 1 or day > days_in_month:
            raise ValueError("El día de una transferencia no pertenece al mes seleccionado.")

        source_credential = str(raw_transfer.get("source_credential", "")).strip()
        target_credential = str(
            raw_transfer.get("target_credential") or default_target_credential or ""
        ).strip()
        code = str(raw_transfer.get("code", "")).strip().upper()
        if not source_credential or not target_credential or not code:
            raise ValueError("Faltan datos de una transferencia de código.")
        if source_credential == target_credential:
            raise ValueError("El titular actual y el nuevo deben ser distintos.")
        transfer_key = (source_credential, target_credential, day)
        if transfer_key in seen_transfers:
            raise ValueError("La misma asignación no se puede transferir dos veces.")
        seen_transfers.add(transfer_key)

        source = previous_by_credential.get(source_credential)
        target = submitted_by_credential.get(target_credential)
        if source is None or target is None:
            raise ValueError("La asignación cambió; vuelve a cargar el rol mensual.")
        if _record_assignment_code(source, day) != code:
            raise ValueError("El código ya no pertenece al titular actual; vuelve a cargar el rol mensual.")
        if _record_assignment_code(target, day) != code or day not in _record_day_list(target, "work_days"):
            raise ValueError("El nuevo controlador ya no tiene ese código asignado en el día seleccionado.")

        if source_credential in target_after:
            raise ValueError("No se pueden encadenar transferencias del mismo controlador en una operación.")
        if target_credential in source_after:
            raise ValueError("No se pueden encadenar transferencias del mismo controlador en una operación.")

        source_before.setdefault(source_credential, _copy_assignment_record(source))
        target_before.setdefault(
            target_credential,
            _copy_assignment_record(previous_by_credential[target_credential])
            if target_credential in previous_by_credential else None,
        )
        target_after[target_credential] = target
        source_record = source_after.get(source_credential)
        if source_record is None:
            source_record = copy(submitted_by_credential.get(source_credential, source))
            source_after[source_credential] = source_record

        work_days = _record_day_list(source_record, "work_days")
        rest_days = _record_day_list(source_record, "rest_days")
        assignments = dict(_record_json_field(source_record, "daily_assignments", dict, {}))
        details = dict(_record_json_field(source_record, "daily_details", dict, {}))
        day_key = str(day)
        work_days.discard(day)
        rest_days.add(day)
        assignments.pop(day_key, None)
        details.pop(day_key, None)
        source_record.update({
            "work_days": sorted(work_days),
            "rest_days": sorted(rest_days),
            "daily_assignments": assignments,
            "daily_details": details,
        })
        if source_credential in submitted_by_credential:
            submitted_by_credential[source_credential].update(source_record)

        events.append({
            "code": code,
            "day": day,
            "source_credential": source_credential,
            "target_credential": target_credential,
            "source": source_before[source_credential],
            "target": target,
        })

    target_credentials = set(target_after)
    if target_credentials.intersection(source_after):
        raise ValueError("No se puede transferir un código entre registros relacionados en la misma operación.")

    source_updates = [
        record
        for credential, record in source_after.items()
        if credential not in submitted_by_credential
    ]
    return source_updates, {
        "events": events,
        "source_before": source_before,
        "source_after": source_after,
        "target_before": target_before,
        "target_after": target_after,
    }


def _record_assignment_transfer_history(
    account: dict,
    module_number: int,
    month: int,
    year: int,
    transfer_plan: dict,
) -> None:
    def describe_transfer(item: dict) -> str:
        source = item["source"]
        target = item["target"]
        return (
            f"Código {item['code']} del día {item['day']}: "
            f"{source.get('name') or item['source_credential']} "
            f"({item['source_credential']}) a "
            f"{target.get('name') or item['target_credential']} "
            f"({item['target_credential']})"
        )

    source_descriptions = [
        describe_transfer(item)
        for item in transfer_plan["events"]
    ]
    record_history(
        account,
        f"Reasignó {len(source_descriptions)} código(s) del rol {month:02d}/{year} (de Asignación de Roles)",
        module_number,
        "edicion",
        "; ".join(source_descriptions),
        "asignaciones",
        before={
            "Asignaciones": [
                assignment_history_snapshot(record)
                for record in transfer_plan["source_before"].values()
            ]
        },
        after={
            "Asignaciones": [
                assignment_history_snapshot(record)
                for record in transfer_plan["source_after"].values()
            ]
        },
    )

    targets_by_action = {"edicion": [], "registro": []}
    for credential, record in transfer_plan["target_after"].items():
        action = "edicion" if transfer_plan["target_before"].get(credential) else "registro"
        targets_by_action[action].append((credential, record))
    for action, targets in targets_by_action.items():
        if not targets:
            continue
        target_credentials = {credential for credential, _record in targets}
        target_descriptions = [
            describe_transfer(item)
            for item in transfer_plan["events"]
            if item["target_credential"] in target_credentials
        ]
        before_records = [
            transfer_plan["target_before"][credential]
            for credential, _record in targets
            if transfer_plan["target_before"].get(credential) is not None
        ]
        after_records = [record for _credential, record in targets]
        verb = "Actualizó" if action == "edicion" else "Registró"
        target_count_label = "controlador" if len(targets) == 1 else "controladores"
        record_history(
            account,
            f"{verb} la asignación del código para {len(targets)} {target_count_label} "
            f"en el rol {month:02d}/{year} "
            "(de Asignación de Roles)",
            module_number,
            action,
            "; ".join(target_descriptions),
            "asignaciones",
            before={
                "Asignaciones": [
                    assignment_history_snapshot(record)
                    for record in before_records
                ]
            } if before_records else None,
            after={
                "Asignaciones": [
                    assignment_history_snapshot(record)
                    for record in after_records
                ]
            },
        )


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
    transfer_plan = None
    try:
        previous_records = records_for(month, year, module_number)
        _, transfer_plan = _prepare_assignment_transfers(
            payload.get("transfers"),
            previous_records,
            records,
            monthrange(year, month)[1],
        )
        initialize_schema()
        if transfer_plan:
            saved_count = save_month_records(
                records,
                module_number,
                month,
                year,
                expected_transfers=transfer_plan["events"],
            )
        else:
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
            "asignaciones",
            before={
                "Asignaciones": [
                    assignment_history_snapshot(item)
                    for item in previous_records
                ]
            } if history_action in {"edicion", "eliminacion"} else None,
            after={
                "Asignaciones": [
                    assignment_history_snapshot(item)
                    for item in records
                ]
            } if history_action in {"edicion", "registro"} else None,
        )
        if transfer_plan:
            _record_assignment_transfer_history(
                account,
                module_number,
                month,
                year,
                transfer_plan,
            )
        return jsonify(ok=True, saved_count=saved_count)
    except Exception as error:
        if transfer_plan and isinstance(error, ValueError):
            return jsonify(error=str(error)), 409
        return jsonify(error=f"No se pudieron guardar los registros: {error}"), 400


def _create_record():
    account = session.get("account")
    if not account:
        return jsonify(error="No autorizado."), 403
    payload = request.get_json(silent=True) or {}
    module_number = requested_module_number(account, payload)
    if not module_number:
        return jsonify(error="Falta el módulo del rol mensual."), 400
    required = ("name", "credential")
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
    raw_edited_days = payload.get("edited_days")
    edited_days = None
    if raw_edited_days is not None:
        if not isinstance(raw_edited_days, list):
            return jsonify(error="La lista de días editados no es válida."), 400
        try:
            edited_days = sorted({int(day) for day in raw_edited_days})
        except (TypeError, ValueError):
            return jsonify(error="La lista de días editados no es válida."), 400
        if any(day not in all_days for day in edited_days):
            return jsonify(error="Hay días editados que no pertenecen al mes seleccionado."), 400
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
    requires_route_assignment = any(
        normalized_assignments.get(str(day), "").upper() != "MD"
        for day in work_days
    ) and any(
        not str(payload.get(field, "")).strip()
        for field in ("shift", "route", "nomenclature")
    )
    if requires_route_assignment:
        work_special_codes = {
            str(item.get("codigo", "")).strip().upper()
            for item in fetch_catalog_items("estados_especiales")
            if item.get("categoria") == "trabajo"
        }
        if any(
            normalized_assignments.get(str(day), "").upper() != "MD"
            and normalized_assignments.get(str(day), "").upper() not in work_special_codes
            for day in work_days
        ):
            return jsonify(error="Completa ruta, turno y nomenclatura para los días de trabajo."), 400
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
        normalized_assignments.setdefault(
            str(day),
            f"{str(payload.get('nomenclature', '')).strip().upper()}{str(payload.get('shift', '')).strip()}",
        )
    final_work_days = [day for day in work_days if day not in vacation_days and day not in deleted_days]
    final_rest_days = [day for day in rest_days if day not in vacation_days and day not in deleted_days]
    record = {
        "name": normalize_display_text(payload["name"]),
        "credential": str(payload["credential"]).strip(),
        "shift": str(payload.get("shift", "")).strip(),
        "route": normalize_display_text(payload.get("route")),
        "nomenclature": str(payload.get("nomenclature", "")).strip().upper(),
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
    previous_records = records_for(month, year, module_number)
    previous_record = next(
        (
            dict(item)
            for item in previous_records
            if item.get("credential") == record["credential"]
        ),
        None,
    )
    try:
        transfer_source_records, transfer_plan = _prepare_assignment_transfers(
            payload.get("transfers"),
            previous_records,
            [record],
            last_day,
            record["credential"],
        )
    except (TypeError, ValueError) as error:
        return jsonify(error=str(error)), 409
    saved_records = []
    database_ready = False
    try:
        initialize_schema()
        database_ready = True
        if transfer_source_records:
            saved_records = upsert_records_atomically(
                [*transfer_source_records, record],
                expected_transfers=transfer_plan["events"],
            )
            saved = saved_records[-1]
        else:
            saved = upsert_record(record)
        saved_to_database = True
    except Exception as error:
        if transfer_source_records and database_ready:
            if isinstance(error, ValueError):
                return jsonify(error=str(error)), 409
            app.logger.exception(
                "No se pudo guardar la transferencia del código al registro %s",
                record["credential"],
            )
            return jsonify(
                error="No se pudo completar la transferencia; no se modificaron las asignaciones."
            ), 500
        saved_to_database = False
        for source_record in transfer_source_records:
            existing_source = next(
                (
                    item for item in memory_records
                    if item["credential"] == source_record["credential"]
                    and item["month"] == month
                    and item["year"] == year
                    and item.get("module_number") == module_number
                ),
                None,
            )
            if existing_source is None:
                app.logger.exception(
                    "No se encontró el titular actual %s en el almacenamiento disponible",
                    source_record["credential"],
                )
                return jsonify(
                    error="No se pudo completar la transferencia; vuelve a cargar el rol mensual."
                ), 503
            existing_source.update({
                "work_days": list(source_record["work_days"]),
                "rest_days": list(source_record["rest_days"]),
                "daily_assignments": dict(source_record["daily_assignments"]),
                "daily_details": dict(source_record["daily_details"]),
            })
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
    if saved_to_database:
        try:
            refresh_analysis_tables(month=month, year=year, module_number=module_number)
        except Exception:
            app.logger.exception(
                "El registro %s se guardó, pero no se pudieron actualizar las tablas analíticas",
                record["credential"],
            )
            return jsonify(
                error="El registro se guardó, pero no se pudieron actualizar las tablas analíticas."
            ), 500
    saved["updated_existing"] = previous_record is not None
    if transfer_plan:
        for source_record in transfer_source_records:
            transfer_plan["source_after"][source_record["credential"]] = source_record
        transfer_plan["target_after"][record["credential"]] = saved
        _record_assignment_transfer_history(
            account,
            module_number,
            month,
            year,
            transfer_plan,
        )
    else:
        history_action = "edicion" if saved["updated_existing"] else "registro"
        record_history(
            account,
            f"{'Editó' if saved['updated_existing'] else 'Registró'} a {record['credential']} ({month:02d}/{year}) (de Asignación de Roles)",
            module_number,
            history_action,
            format_code_changes(previous_record, saved),
            "asignaciones",
            before=assignment_history_snapshot(previous_record) if saved["updated_existing"] else None,
            after=assignment_history_snapshot(
                saved,
                edited_days=edited_days if saved["updated_existing"] else None,
            ),
        )
    return jsonify(saved), 201


@app.post("/api/records")
def create_record():
    try:
        return _create_record()
    except Exception:
        app.logger.exception("Error no controlado al guardar una asignación del rol mensual")
        return (
            jsonify(
                error=(
                    "No se pudo guardar la asignación por un error interno. "
                    "Consulta el traceback del servidor."
                )
            ),
            500,
        )


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
    deleted_from_database = False
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
            deleted_from_database = deleted
    except Exception:
        for item in list(memory_records):
            if item.get("credential") == credential and item.get("month") == month and item.get("year") == year and item.get("module_number") == module_number:
                memory_records.remove(item)
                deleted = True
    if deleted_from_database:
        try:
            refresh_analysis_tables(month=month, year=year, module_number=module_number)
        except Exception:
            app.logger.exception(
                "El registro %s se eliminó, pero no se pudieron actualizar las tablas analíticas",
                credential,
            )
            return jsonify(
                error="El registro se eliminó, pero no se pudieron actualizar las tablas analíticas."
            ), 500
    if deleted:
        record_history(
            account,
            f"Eliminó a {credential} ({month:02d}/{year}) (de Asignación de Roles)",
            module_number,
            "eliminacion",
            format_code_changes(previous_record, None),
            "asignaciones",
            before=assignment_history_snapshot(previous_record),
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
    record_history(
        account,
        f"Descargó Excel del rol {month:02d}/{year}",
        module_number,
        "descarga",
        None,
        "asignaciones",
    )
    return send_file(output, download_name=filename, as_attachment=True, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=not settings.is_production)
