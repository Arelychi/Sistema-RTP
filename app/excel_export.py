from calendar import monthrange
from datetime import date
from io import BytesIO
import re

import pandas as pd


def nomenclature_sort_key(record: dict) -> list[object]:
    value = str(record.get("nomenclature") or "").strip().casefold()
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", value)]


def build_turnos_excel(
    records: list[dict],
    month: int,
    year: int,
    routes: list[dict] | None = None,
) -> BytesIO:
    total_days = monthrange(year, month)[1]
    visible_headers = [
        "NOM",
        "RUTA",
        "Origen",
        "Destino",
        "NOMBRE DEL CONTROLADOR",
        "CREDENCIAL",
    ]
    hidden_headers = ["TURNO"]
    day_headers = list(range(1, total_days + 1))
    headers = [*visible_headers, *hidden_headers, *day_headers]
    rows = []
    route_by_key = {}
    for route in routes or []:
        for key in (route.get("ruta"), route.get("nomenclatura")):
            normalized_key = str(key or "").strip().casefold()
            if normalized_key:
                route_by_key[normalized_key] = route

    for record in sorted(records, key=nomenclature_sort_key):
        assignments = record.get("daily_assignments") or {}
        details = record.get("daily_details") or {}
        work_days = set(record.get("work_days") or [])
        rest_days = set(record.get("rest_days") or [])
        route = route_by_key.get(str(record.get("route") or "").strip().casefold())
        if route is None:
            route = route_by_key.get(str(record.get("nomenclature") or "").strip().casefold())
        row = [
            str(record.get("nomenclature") or ""),
            str(record.get("route") or ""),
            str((route or {}).get("origen") or ""),
            str((route or {}).get("destino") or ""),
            str(record.get("name") or "").strip(),
            str(record.get("credential") or "").strip(),
            str(record.get("shift") or ""),
        ]

        for day in range(1, total_days + 1):
            literal_day = str(day)
            if literal_day in assignments:
                value = str(assignments[literal_day]).strip() or ""
            elif literal_day in details:
                detail = details[literal_day]
                code = detail.get("code") if isinstance(detail, dict) else ""
                value = str(code).strip() if code is not None else ""
            elif day in rest_days:
                value = "D"
            elif day in work_days:
                value = f"{record.get('nomenclature', '')}{record.get('shift', '')}"
            else:
                value = ""
            row.append(value)

        rows.append(row)

    frame = pd.DataFrame(rows, columns=headers)
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        workbook = writer.book
        worksheet = workbook.add_worksheet("Turnos")
        writer.sheets["Turnos"] = worksheet

        header_format = workbook.add_format({
            "bold": True,
            "font_color": "#FFFFFF",
            "bg_color": "#203F64",
            "border": 1,
            "border_color": "#B8C9D8",
            "align": "center",
            "valign": "vcenter",
            "text_wrap": True,
        })
        day_number_format = workbook.add_format({
            "bold": True,
            "font_color": "#FFFFFF",
            "bg_color": "#203F64",
            "border": 1,
            "border_color": "#B8C9D8",
            "align": "center",
            "valign": "vcenter",
        })
        cell_format = workbook.add_format({
            "border": 1,
            "border_color": "#C6D2DD",
            "align": "left",
            "valign": "vcenter",
        })
        centered_cell_format = workbook.add_format({
            "border": 1,
            "border_color": "#C6D2DD",
            "align": "center",
            "valign": "vcenter",
        })
        rest_format = workbook.add_format({
            "border": 1,
            "border_color": "#C6D2DD",
            "bg_color": "#718096",
            "font_color": "#FFFFFF",
            "align": "center",
            "valign": "vcenter",
        })

        for column_index, column_name in enumerate(visible_headers):
            worksheet.merge_range(0, column_index, 1, column_index, column_name, header_format)
        for column_index, column_name in enumerate(hidden_headers, len(visible_headers)):
            worksheet.write(0, column_index, column_name, header_format)
            worksheet.write(1, column_index, "", header_format)

        day_start = len(visible_headers) + len(hidden_headers)
        weekday_names = ("L", "M", "M", "J", "V", "S", "D")
        for day_index, day in enumerate(day_headers):
            column_index = day_start + day_index
            weekday = weekday_names[date(year, month, day).weekday()]
            worksheet.write(0, column_index, weekday, header_format)
            worksheet.write(1, column_index, day, day_number_format)

        for row_index, row in enumerate(frame.itertuples(index=False, name=None), 2):
            for column_index, value in enumerate(row):
                if column_index == 6:
                    format_to_use = centered_cell_format
                elif column_index >= day_start and str(value).strip().upper() == "D":
                    format_to_use = rest_format
                elif column_index >= day_start:
                    format_to_use = centered_cell_format
                else:
                    format_to_use = cell_format
                worksheet.write(row_index, column_index, value, format_to_use)

        worksheet.set_row(0, 28)
        worksheet.set_row(1, 22)
        worksheet.freeze_panes(2, day_start)
        worksheet.set_column(0, 0, 6)
        worksheet.set_column(1, 1, 8)
        worksheet.set_column(2, 3, 31)
        worksheet.set_column(4, 4, 26)
        worksheet.set_column(5, 5, 14)
        worksheet.set_column(6, 6, None, None, {"hidden": True})
        worksheet.set_column(day_start, day_start + total_days - 1, 4)

    output.seek(0)
    return output
