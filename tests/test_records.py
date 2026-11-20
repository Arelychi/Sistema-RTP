import json
from datetime import date
from io import BytesIO

from openpyxl import load_workbook

import app.web as web
import app.db as db
from app.web import app


CURRENT_DATE = date.today()
TEST_MONTH = CURRENT_DATE.month % 12 + 1
TEST_YEAR = CURRENT_DATE.year + (CURRENT_DATE.month == 12)


def force_memory_mode(monkeypatch):
    def unavailable_database():
        raise RuntimeError("PostgreSQL no disponible")

    monkeypatch.setattr(web, "initialize_schema", unavailable_database)
    web.memory_records.clear()


def post_record(client, **overrides):
    payload = {
        "name": "Arely",
        "credential": "AR-01",
        "route": "Ruta Centro",
        "shift": "1",
        "nomenclature": "A",
        "month": TEST_MONTH,
        "year": TEST_YEAR,
        "work_days": [1, 2],
        "rest_days": [],
        "daily_assignments": {"1": "A1", "2": "A1"},
    }
    payload.update(overrides)
    return client.post("/api/records", json=payload)


def test_monthly_controller_workday_counts_use_saved_work_days(monkeypatch):
    class FakeCursor:
        def __init__(self):
            self.query = ""
            self.params = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def execute(self, query, params):
            self.query = query
            self.params = params

        def fetchall(self):
            return [("12345", 2, 20), ("67890", 1, 0)]

    class FakeConnection:
        def __init__(self):
            self.fake_cursor = FakeCursor()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def cursor(self):
            return self.fake_cursor

    connection = FakeConnection()
    monkeypatch.setattr(db, "get_connection", lambda: connection)

    counts = db.fetch_monthly_controller_workday_counts(11, 2026)

    assert counts == {("12345", 2): 20, ("67890", 1): 0}
    assert connection.fake_cursor.params == (11, 2026)
    assert "jsonb_array_elements_text" in connection.fake_cursor.query
    assert "sr.month = %s AND sr.year = %s" in connection.fake_cursor.query


def test_controller_analysis_returns_module_routes_and_daily_totals(monkeypatch):
    class FakeCursor:
        def __init__(self):
            self.query = ""
            self.parameters = None
            self.executed = []

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, query, parameters=None):
            self.query = query
            self.parameters = parameters
            self.executed.append((query, parameters))

        def fetchone(self):
            if "COUNT(*), COUNT(*) FILTER (WHERE active)" in self.query:
                return 2, 1
            if "COUNT(DISTINCT credential)" in self.query:
                return (1,)
            raise AssertionError(f"Unexpected fetchone query: {self.query}")

        def fetchall(self):
            if "SELECT credential, name, module_number, work_days_count" in self.query:
                return [("12345", "Ana", 2, 10, 1, 3, 1, 0, 1, 0, 1)]
            if "AS change_of_rest" in self.query:
                return [("12345", 2, 1, 2, 1)]
            if "COUNT(DISTINCT credential) AS controllers" in self.query:
                return [(2, "Ruta Centro", 5, 1)]
            if "COUNT(*) AS assignments" in self.query:
                return [(1, 1, 1, 0, 0, 0, 0, 0, 0, 0)]
            if "SELECT EXTRACT(DAY FROM work_date)::integer AS day" in self.query:
                return [(1, "TRABAJADO", "A1", "Ruta Centro", "Matutino")]
            if "SELECT route, COUNT(DISTINCT work_date) AS days" in self.query:
                return [("Ruta Centro", 5)]
            return []

    class FakeConnection:
        def __init__(self):
            self.fake_cursor = FakeCursor()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return self.fake_cursor

    connection = FakeConnection()
    monkeypatch.setattr(db, "get_connection", lambda: connection)

    dashboard = db.fetch_controller_analysis_dashboard(11, 2026, "12345", 2)

    assert dashboard["selected_worker"]["name"] == "Ana"
    assert dashboard["selected_worker"]["change_of_rest"] == 1
    assert dashboard["route_days_by_module"] == [
        {
            "module_number": 2,
            "route": "Ruta Centro",
            "days": 5,
            "controllers": 1,
        }
    ]
    assert dashboard["daily_summary"] == [
        {
            "day": 1,
            "assignments": 1,
            "worked": 1,
            "rest": 0,
            "absence": 0,
            "incapacity": 0,
            "permission": 0,
            "vacation": 0,
            "holiday": 0,
            "unprogrammed": 0,
        }
    ]
    unselected_dashboard = db.fetch_controller_analysis_dashboard(11, 2026)
    assert unselected_dashboard["selected_worker"] is None
    assert unselected_dashboard["route_days"] == []
    assert unselected_dashboard["calendar_days"] == []
    assert any("FROM analisis.ruta_dia" in query for query, _ in connection.fake_cursor.executed)
    assert any("FROM analisis.trabajador_dia" in query and "GROUP BY work_date" in query for query, _ in connection.fake_cursor.executed)


def test_daily_details_are_updated_without_changing_other_days(monkeypatch):
    force_memory_mode(monkeypatch)
    with app.test_client() as client:
        with client.session_transaction() as session:
            session["account"] = {"username": "user1", "module_number": 1, "is_admin": False}

        first = post_record(client)
        assert first.status_code == 201

        edited = post_record(
            client,
            work_days=[1, 2],
            daily_assignments={"1": "B2", "2": "A1"},
            daily_details={"1": {"route": "Ruta Norte", "shift": "2", "nomenclature": "B", "code": "B2"}},
        )
        assert edited.status_code == 201
        saved = edited.get_json()
        assert saved["daily_details"]["1"]["route"] == "Ruta Norte"
        assert saved["daily_details"]["1"]["shift"] == "2"
        assert saved["daily_assignments"]["2"] == "A1"


def test_md_assignment_is_saved_as_a_work_day(monkeypatch):
    force_memory_mode(monkeypatch)
    with app.test_client() as client:
        with client.session_transaction() as session:
            session["account"] = {"username": "user1", "module_number": 1, "is_admin": False}

        response = post_record(
            client,
            work_days=[3],
            rest_days=[],
            daily_assignments={"3": "MD"},
            daily_details={},
        )

        assert response.status_code == 201
        saved = response.get_json()
        assert 3 in saved["work_days"]
        assert saved["daily_assignments"]["3"] == "MD"

        fetched = client.get(f"/api/records?month={TEST_MONTH}&year={TEST_YEAR}")
        assert fetched.status_code == 200
        assert fetched.get_json()[0]["work_days"] == [3]
        assert fetched.get_json()[0]["daily_assignments"]["3"] == "MD"


def test_md_assignment_without_route_uses_database_save_path(monkeypatch):
    persisted = {}
    saved = {
        "id": 12,
        "name": "Arely",
        "credential": "AR-01",
        "shift": "",
        "route": "",
        "nomenclature": "",
        "month": TEST_MONTH,
        "year": TEST_YEAR,
        "work_days": [3],
        "rest_days": [],
        "daily_assignments": {"3": "MD"},
        "daily_details": {},
        "module_number": 1,
    }

    def fake_upsert_record(record):
        persisted.update(record)
        return dict(saved)

    monkeypatch.setattr(web, "initialize_schema", lambda: None)
    monkeypatch.setattr(web, "records_for", lambda *args: [])
    monkeypatch.setattr(web, "upsert_record", fake_upsert_record)
    monkeypatch.setattr(web, "refresh_analysis_tables", lambda **_scope: None)
    monkeypatch.setattr(web, "record_history", lambda *args, **kwargs: None)

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["account"] = {"username": "user1", "module_number": 1, "is_admin": False}

        response = post_record(
            client,
            route="",
            shift="",
            nomenclature="",
            work_days=[3],
            rest_days=[],
            daily_assignments={"3": "MD"},
            daily_details={},
        )

    assert response.status_code == 201
    assert persisted["route"] == ""
    assert persisted["shift"] == ""
    assert json.loads(persisted["daily_assignments"]) == {"3": "MD"}
    assert response.get_json()["work_days"] == [3]


def test_upsert_record_update_returns_all_daily_details(monkeypatch):
    class Column:
        def __init__(self, name):
            self.name = name

    daily_details = {
        "1": {"route": "Ruta A", "shift": "1", "nomenclature": "A", "code": "A1"},
        "2": {"route": "Ruta B", "shift": "2", "nomenclature": "B", "code": "B2"},
        "3": {"route": "Ruta C", "shift": "3", "nomenclature": "C", "code": "C3"},
        "4": {"route": "Ruta D", "shift": "4", "nomenclature": "D", "code": "D4"},
    }

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, query, _parameters=None):
            if query.lstrip().startswith("SELECT id, work_days"):
                self.row = (
                    7,
                    json.dumps([1, 2, 3]),
                    json.dumps([]),
                    json.dumps({"1": "A1", "2": "B2", "3": "C3"}),
                    json.dumps({key: value for key, value in daily_details.items() if key != "4"}),
                )
                return

            columns = [
                column.strip()
                for column in query.split("RETURNING", 1)[1].split(",")
            ]
            returned_values = {
                "id": 7,
                "name": "Ana Prueba",
                "credential": "AR-01",
                "shift": "4",
                "route": "Ruta D",
                "nomenclature": "D",
                "month": TEST_MONTH,
                "year": TEST_YEAR,
                "work_days": [1, 2, 3, 4],
                "rest_days": [],
                "daily_assignments": {"1": "A1", "2": "B2", "3": "C3", "4": "D4"},
                "daily_details": daily_details,
                "module_number": 1,
            }
            self.description = [Column(column) for column in columns]
            self.row = tuple(returned_values[column] for column in columns)

        def fetchone(self):
            return self.row

    class Connection:
        def __init__(self):
            self.test_cursor = Cursor()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return self.test_cursor

        def commit(self):
            pass

    monkeypatch.setattr(db, "get_connection", lambda: Connection())

    saved = db.upsert_record({
        "name": "Ana Prueba",
        "credential": "AR-01",
        "shift": "4",
        "route": "Ruta D",
        "nomenclature": "D",
        "month": TEST_MONTH,
        "year": TEST_YEAR,
        "work_days": json.dumps([1, 2, 3, 4]),
        "rest_days": json.dumps([]),
        "daily_assignments": json.dumps({"1": "A1", "2": "B2", "3": "C3", "4": "D4"}),
        "daily_details": json.dumps(daily_details),
        "module_number": 1,
    })

    assert saved["daily_details"] == daily_details


def test_work_category_special_assignment_is_saved_as_work_without_route(monkeypatch):
    force_memory_mode(monkeypatch)
    monkeypatch.setattr(
        web,
        "fetch_catalog_items",
        lambda catalog: [{"codigo": "TR", "categoria": "trabajo"}],
    )
    monkeypatch.setattr(web, "record_history", lambda *args, **kwargs: None)

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["account"] = {"username": "user1", "module_number": 1, "is_admin": False}

        response = post_record(
            client,
            route="",
            shift="",
            nomenclature="",
            work_days=[3],
            rest_days=[],
            daily_assignments={"3": "TR"},
            daily_details={},
        )

    assert response.status_code == 201
    saved = response.get_json()
    assert saved["work_days"] == [3]
    assert saved["daily_assignments"]["3"] == "TR"


def test_unhandled_record_save_error_returns_json_with_http_500(monkeypatch):
    def fail_before_save(*args):
        raise RuntimeError("unexpected failure")

    monkeypatch.setattr(web, "monthly_role_is_closed", fail_before_save)

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["account"] = {"username": "user1", "module_number": 1, "is_admin": False}

        response = post_record(
            client,
            work_days=[3],
            daily_assignments={"3": "MD"},
            daily_details={},
        )

    assert response.status_code == 500
    assert response.is_json
    assert "traceback del servidor" in response.get_json()["error"]


def test_non_work_assignments_can_be_saved_without_route(monkeypatch):
    force_memory_mode(monkeypatch)
    with app.test_client() as client:
        with client.session_transaction() as session:
            session["account"] = {"username": "user1", "module_number": 1, "is_admin": False}

        response = post_record(
            client,
            route="",
            shift="",
            nomenclature="",
            work_days=[],
            rest_days=[1],
            daily_assignments={"1": "D", "2": "F"},
            daily_details={},
        )

    assert response.status_code == 201
    saved = response.get_json()
    assert saved["route"] == ""
    assert saved["shift"] == ""
    assert saved["rest_days"] == [1]
    assert saved["daily_assignments"] == {"1": "D", "2": "F"}


def test_regular_work_assignment_still_requires_route_details(monkeypatch):
    force_memory_mode(monkeypatch)
    with app.test_client() as client:
        with client.session_transaction() as session:
            session["account"] = {"username": "user1", "module_number": 1, "is_admin": False}

        response = post_record(
            client,
            route="",
            shift="",
            nomenclature="",
            work_days=[1],
            daily_assignments={"1": "A1"},
            daily_details={},
        )

    assert response.status_code == 400
    assert response.get_json()["error"] == "Completa ruta, turno y nomenclatura para los días de trabajo."


def test_single_record_save_refreshes_analysis_tables(monkeypatch):
    refreshed = []
    saved_record = {
        "id": 9,
        "name": "Arely",
        "credential": "AR-01",
        "shift": "1",
        "route": "Ruta Centro",
        "nomenclature": "A",
        "month": TEST_MONTH,
        "year": TEST_YEAR,
        "work_days": [1],
        "rest_days": [],
        "daily_assignments": {"1": "A1"},
        "daily_details": {},
        "module_number": 1,
    }
    monkeypatch.setattr(web, "initialize_schema", lambda: None)
    monkeypatch.setattr(web, "records_for", lambda *args: [])
    monkeypatch.setattr(web, "upsert_record", lambda record: dict(saved_record))
    monkeypatch.setattr(
        web,
        "refresh_analysis_tables",
        lambda **scope: refreshed.append(scope),
    )
    monkeypatch.setattr(web, "record_history", lambda *args, **kwargs: None)

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["account"] = {"username": "user1", "module_number": 1, "is_admin": False}

        response = post_record(client)

    assert response.status_code == 201
    assert refreshed == [{"month": TEST_MONTH, "year": TEST_YEAR, "module_number": 1}]


def test_scoped_analysis_refresh_only_rebuilds_selected_month_and_module(monkeypatch):
    class Cursor:
        def __init__(self):
            self.executed = []

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, query, parameters=None):
            self.executed.append((query, parameters))

    class Connection:
        def __init__(self):
            self.test_cursor = Cursor()
            self.committed = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return self.test_cursor

        def commit(self):
            self.committed = True

    connection = Connection()
    monkeypatch.setattr(db, "get_connection", lambda: connection)

    db.refresh_analysis_tables(month=10, year=2026, module_number=2)

    deletions = [
        (query, parameters)
        for query, parameters in connection.test_cursor.executed
        if query.startswith("DELETE FROM analisis.")
    ]
    inserts = [
        (query, parameters)
        for query, parameters in connection.test_cursor.executed
        if query.lstrip().startswith("INSERT INTO analisis.")
    ]
    assert len(deletions) == 4
    assert all(parameters == (10, 2026, 2) for _, parameters in deletions)
    assert len(inserts) == 4
    assert all(parameters == (10, 2026, 2) for _, parameters in inserts[:3])
    assert inserts[3][1] == (10, 2026, 2, 10, 2026, 2)
    assert not any("TRUNCATE analisis." in query for query, _ in connection.test_cursor.executed)
    assert connection.committed


def test_analysis_refresh_requires_complete_scope(monkeypatch):
    opened_connection = []
    monkeypatch.setattr(db, "get_connection", lambda: opened_connection.append(True))

    try:
        db.refresh_analysis_tables(month=10)
    except ValueError as error:
        assert str(error) == "Mes, año y módulo deben proporcionarse juntos."
    else:
        raise AssertionError("A refresh with an incomplete scope must be rejected.")

    assert not opened_connection


def test_monthly_bulk_save_uses_schedule_records_and_preserves_vacations(monkeypatch):
    class Cursor:
        def __init__(self):
            self.executed = []

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, query, parameters=None):
            self.executed.append((query, parameters))

    class Connection:
        def __init__(self):
            self.test_cursor = Cursor()
            self.committed = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return self.test_cursor

        def commit(self):
            self.committed = True

    connection = Connection()
    monkeypatch.setattr(db, "get_connection", lambda: connection)
    monkeypatch.setattr(db, "refresh_analysis_tables", lambda **_scope: None)

    saved = db.save_month_records(
        [
            {
                "name": "Ana Prueba",
                "credential": "AR-02",
                "shift": "1",
                "route": "Ruta Centro",
                "nomenclature": "A",
                "work_days": [1],
                "rest_days": [3],
                "vacation_days": [2],
                "daily_assignments": {"1": "A1"},
            }
        ],
        module_number=2,
        month=10,
        year=2026,
    )

    delete_query, _ = connection.test_cursor.executed[0]
    insert_query, insert_parameters = connection.test_cursor.executed[1]
    assert "DELETE FROM schedule_records" in delete_query
    assert "INSERT INTO schedule_records" in insert_query
    assert "programacion.registros" not in insert_query
    assert json.loads(insert_parameters[10]) == {"1": "A1", "2": "V"}
    assert saved == 1
    assert connection.committed


def test_legacy_schedule_migration_archives_conflicts_before_dropping_source():
    class Cursor:
        def __init__(self):
            self.executed = []
            self.results = [("programacion.registros",), (True,)]
            self.rowcount = 0

        def execute(self, query, parameters=None):
            self.executed.append(query)
            if "INSERT INTO programacion.registros_legacy_conflicts" in query:
                self.rowcount = 2
            elif "INSERT INTO schedule_records" in query:
                self.rowcount = 3

        def fetchone(self):
            return self.results.pop(0)

    cursor = Cursor()

    db._migrate_legacy_schedule_records(cursor)

    archive_index = next(
        index for index, query in enumerate(cursor.executed)
        if "INSERT INTO programacion.registros_legacy_conflicts" in query
    )
    migration_index = next(
        index for index, query in enumerate(cursor.executed)
        if "INSERT INTO schedule_records" in query
    )
    drop_index = next(
        index for index, query in enumerate(cursor.executed)
        if "DROP TABLE programacion.registros" in query
    )
    assert archive_index < migration_index < drop_index


def test_deleted_day_does_not_return_from_memory_merge(monkeypatch):
    force_memory_mode(monkeypatch)
    with app.test_client() as client:
        with client.session_transaction() as session:
            session["account"] = {"username": "user1", "module_number": 1, "is_admin": False}

        post_record(client)
        deleted = post_record(client, deleted_days=[1], daily_assignments={"2": "A1"})
        assert deleted.status_code == 201
        saved = deleted.get_json()
        assert "1" not in saved["daily_assignments"]
        assert 1 not in saved["work_days"]
        assert "2" in saved["daily_assignments"]

        response = client.get(f"/api/records?month={TEST_MONTH}&year={TEST_YEAR}")
        assert response.status_code == 200
        assert "1" not in response.get_json()[0]["daily_assignments"]


def test_same_credential_is_not_duplicated_in_table(monkeypatch):
    force_memory_mode(monkeypatch)
    with app.test_client() as client:
        with client.session_transaction() as session:
            session["account"] = {"username": "user1", "module_number": 1, "is_admin": False}

        first = post_record(client)
        assert first.status_code == 201

        repeated = post_record(client, name="Arely", credential="AR-01", route="Ruta Centro", shift="1", nomenclature="A")
        assert repeated.status_code == 201
        assert repeated.get_json()["updated_existing"] is True

        records = client.get(f"/api/records?month={TEST_MONTH}&year={TEST_YEAR}")
        assert records.status_code == 200
        assert len(records.get_json()) == 1
        assert records.get_json()[0]["credential"] == "AR-01"


def test_record_history_tracks_only_days_in_the_latest_edit(monkeypatch):
    force_memory_mode(monkeypatch)
    history_entries = []
    monkeypatch.setattr(
        web,
        "record_history",
        lambda *args, **kwargs: history_entries.append(kwargs),
    )
    with app.test_client() as client:
        with client.session_transaction() as session:
            session["account"] = {"username": "user1", "module_number": 1, "is_admin": False}

        previous_assignments = {
            **{str(day): "A1" for day in range(1, 10)},
            **{str(day): "J5" for day in range(10, 14)},
            **{str(day): "F4" for day in range(14, 18)},
        }
        current_assignments = {
            **{str(day): "A1" for day in range(1, 10)},
            **{str(day): "F4" for day in range(14, 18)},
            **{str(day): "I5" for day in range(18, 21)},
        }
        previous_work_days = list(range(1, 18))
        current_work_days = [*range(1, 10), *range(14, 21)]
        assert post_record(
            client,
            work_days=previous_work_days,
            daily_assignments=previous_assignments,
        ).status_code == 201
        updated = post_record(
            client,
            work_days=current_work_days,
            daily_assignments=current_assignments,
            edited_days=[10, 11, 12, 13, 18, 19, 20],
        )
        assert updated.status_code == 201

    registration_history = next(
        entry
        for entry in history_entries
        if entry.get("before") is None and entry.get("after") is not None
    )
    assert registration_history["after"]["Credencial"] == "AR-01"
    assert registration_history["after"]["Días de trabajo"] == previous_work_days

    edit_history = next(
        entry
        for entry in history_entries
        if entry.get("after", {}).get("_assignment_edited_days") is not None
    )
    assert edit_history["after"]["_assignment_edited_days"] == [
        10, 11, 12, 13, 18, 19, 20
    ]
    assert "_assignment_edited_days" not in [
        field for field, _ in web.history_snapshot_fields(edit_history["after"])
    ]
    comparison = web.prepare_assignment_history_comparisons(
        edit_history["before"],
        edit_history["after"],
        f"Editó a AR-01 ({TEST_MONTH:02d}/{TEST_YEAR}) (de Asignación de Roles)",
    )[0]
    changed_days = [
        cell["day"]
        for cell in comparison["after_cells"]
        if not cell["blank"] and cell["changed"]
    ]
    assert changed_days == [10, 11, 12, 13, 18, 19, 20]


def test_bulk_registration_history_keeps_assignment_snapshots(monkeypatch):
    history_entries = []
    record = {
        "name": "Ana Prueba",
        "credential": "AR-02",
        "shift": "2",
        "route": "Ruta Norte",
        "nomenclature": "C",
        "work_days": [2, 3],
        "rest_days": [],
        "daily_assignments": {"2": "C2", "3": "C2"},
        "daily_details": {
            "2": {"route": "Ruta Norte", "shift": "2", "nomenclature": "C", "code": "C2"},
            "3": {"route": "Ruta Norte", "shift": "2", "nomenclature": "C", "code": "C2"},
        },
    }
    monkeypatch.setattr(web, "records_for", lambda *_args: [])
    monkeypatch.setattr(web, "initialize_schema", lambda: None)
    monkeypatch.setattr(
        web,
        "save_month_records",
        lambda records, module_number, month, year: len(records),
    )
    monkeypatch.setattr(
        web,
        "record_history",
        lambda *args, **kwargs: history_entries.append((args, kwargs)),
    )
    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {
            "username": "administrador",
            "module_number": 1,
            "is_admin": False,
        }

    response = client.post(
        "/api/records/save-all",
        json={
            "month": TEST_MONTH,
            "year": TEST_YEAR,
            "records": [record],
        },
    )

    assert response.status_code == 200
    history_args, history_kwargs = history_entries[0]
    assert history_args[3] == "registro"
    assert history_kwargs["after"]["Asignaciones"][0]["Credencial"] == "AR-02"
    assert history_kwargs["after"]["Asignaciones"][0]["Detalles diarios"] == record["daily_details"]


def test_switching_work_to_rest_or_vacation_replaces_previous_assignment(monkeypatch):
    force_memory_mode(monkeypatch)
    with app.test_client() as client:
        with client.session_transaction() as session:
            session["account"] = {"username": "user1", "module_number": 1, "is_admin": False}

        first = post_record(client)
        assert first.status_code == 201

        rest_update = post_record(client, work_days=[], rest_days=[1], daily_assignments={}, deleted_days=[])
        assert rest_update.status_code == 201
        rest_saved = rest_update.get_json()
        assert 1 in rest_saved["rest_days"]
        assert 1 not in rest_saved["work_days"]
        assert "1" not in rest_saved["daily_assignments"]

        vacation_update = post_record(client, work_days=[], rest_days=[], vacation_days=[1], daily_assignments={"1": "V"}, deleted_days=[])
        assert vacation_update.status_code == 201
        vacation_saved = vacation_update.get_json()
        assert 1 not in vacation_saved["work_days"]
        assert 1 not in vacation_saved["rest_days"]
        assert vacation_saved["daily_assignments"]["1"] == "V"


def test_upsert_records_atomically_commits_transfer_records_together(monkeypatch):
    class Column:
        def __init__(self, name):
            self.name = name

    columns = (
        "id", "name", "credential", "shift", "route", "nomenclature",
        "month", "year", "work_days", "rest_days", "daily_assignments",
        "daily_details", "module_number",
    )

    class Cursor:
        def __init__(self):
            self.executed = []
            self.description = []
            self.row = None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, query, parameters=None):
            self.executed.append(query)
            if "SELECT work_days, rest_days, daily_assignments, daily_details" in query:
                self.row = ([1], [], {"1": "A1"}, {})
                return
            if "SELECT id, work_days, rest_days, daily_assignments, daily_details" in query:
                self.row = (1, [], [], {}, {}) if parameters["credential"] == "AR-OLD" else None
                return
            self.description = [Column(column) for column in columns]
            row_id = parameters.get("id", 2)
            self.row = (
                row_id,
                parameters["name"],
                parameters["credential"],
                parameters["shift"],
                parameters["route"],
                parameters["nomenclature"],
                parameters["month"],
                parameters["year"],
                json.loads(parameters["work_days"]),
                json.loads(parameters["rest_days"]),
                json.loads(parameters["daily_assignments"]),
                json.loads(parameters["daily_details"]),
                parameters["module_number"],
            )

        def fetchone(self):
            return self.row

    class Connection:
        def __init__(self):
            self.test_cursor = Cursor()
            self.commit_count = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return self.test_cursor

        def commit(self):
            self.commit_count += 1

    connection = Connection()
    monkeypatch.setattr(db, "get_connection", lambda: connection)
    common = {
        "shift": "1",
        "route": "Ruta Centro",
        "nomenclature": "A",
        "month": TEST_MONTH,
        "year": TEST_YEAR,
        "module_number": 1,
    }
    source = {
        **common,
        "name": "Titular anterior",
        "credential": "AR-OLD",
        "work_days": json.dumps([]),
        "rest_days": json.dumps([1]),
        "daily_assignments": json.dumps({}),
        "daily_details": json.dumps({}),
    }
    target = {
        **common,
        "name": "Nuevo titular",
        "credential": "AR-NEW",
        "work_days": json.dumps([1]),
        "rest_days": json.dumps([]),
        "daily_assignments": json.dumps({"1": "A1"}),
        "daily_details": json.dumps({
            "1": {"route": "Ruta Centro", "shift": "1", "nomenclature": "A", "code": "A1"},
        }),
    }

    saved = db.upsert_records_atomically(
        [source, target],
        expected_transfers=[{
            "source_credential": "AR-OLD",
            "day": 1,
            "code": "A1",
            "source": {
                "work_days": [1],
                "rest_days": [],
                "daily_assignments": {"1": "A1"},
                "daily_details": {},
            },
        }],
    )

    assert connection.commit_count == 1
    writes = [
        query for query in connection.test_cursor.executed
        if "UPDATE schedule_records" in query or "INSERT INTO schedule_records" in query
    ]
    assert len(writes) == 2
    assert any("FOR UPDATE" in query for query in connection.test_cursor.executed)
    assert saved[0]["daily_assignments"] == {}
    assert saved[1]["daily_assignments"] == {"1": "A1"}


def test_code_transfer_moves_original_controller_to_rest_and_records_both_snapshots(monkeypatch):
    force_memory_mode(monkeypatch)
    original = {
        "name": "Titular anterior",
        "credential": "AR-OLD",
        "route": "Ruta Centro",
        "shift": "1",
        "nomenclature": "A",
        "month": TEST_MONTH,
        "year": TEST_YEAR,
        "module_number": 1,
        "work_days": [1],
        "rest_days": [],
        "daily_assignments": {"1": "A1"},
        "daily_details": {
            "1": {"route": "Ruta Centro", "shift": "1", "nomenclature": "A", "code": "A1"},
        },
    }
    web.memory_records.append(original)
    history_entries = []
    monkeypatch.setattr(
        web,
        "record_history",
        lambda *args, **kwargs: history_entries.append((args, kwargs)),
    )

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["account"] = {"username": "user1", "module_number": 1, "is_admin": False}

        response = post_record(
            client,
            name="Nuevo titular",
            credential="AR-NEW",
            work_days=[1],
            daily_assignments={"1": "A1"},
            daily_details={
                "1": {"route": "Ruta Centro", "shift": "1", "nomenclature": "A", "code": "A1"},
            },
            transfers=[{
                "source_credential": "AR-OLD",
                "target_credential": "AR-NEW",
                "day": 1,
                "code": "A1",
            }],
        )

    assert response.status_code == 201
    old_record = next(record for record in web.memory_records if record["credential"] == "AR-OLD")
    new_record = next(record for record in web.memory_records if record["credential"] == "AR-NEW")
    assert old_record["work_days"] == []
    assert old_record["rest_days"] == [1]
    assert "1" not in old_record["daily_assignments"]
    assert "1" not in old_record["daily_details"]
    assert new_record["daily_assignments"]["1"] == "A1"
    assert len(history_entries) == 2
    source_args, source_kwargs = history_entries[0]
    target_args, target_kwargs = history_entries[1]
    assert source_args[1].startswith("Reasignó 1 código")
    assert source_args[3] == "edicion"
    assert source_kwargs["before"]["Asignaciones"][0]["Credencial"] == "AR-OLD"
    assert source_kwargs["before"]["Asignaciones"][0]["Días de trabajo"] == [1]
    assert source_kwargs["after"]["Asignaciones"][0]["Días de descanso"] == [1]
    assert "1" not in source_kwargs["after"]["Asignaciones"][0]["Asignaciones diarias"]
    assert target_args[3] == "registro"
    assert target_kwargs["after"]["Asignaciones"][0]["Credencial"] == "AR-NEW"


def test_code_transfer_rejects_stale_conflict_without_creating_target(monkeypatch):
    force_memory_mode(monkeypatch)
    original = {
        "name": "Titular anterior",
        "credential": "AR-OLD",
        "route": "Ruta Centro",
        "shift": "1",
        "nomenclature": "A",
        "month": TEST_MONTH,
        "year": TEST_YEAR,
        "module_number": 1,
        "work_days": [1],
        "rest_days": [],
        "daily_assignments": {"1": "B2"},
        "daily_details": {},
    }
    web.memory_records.append(original)

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["account"] = {"username": "user1", "module_number": 1, "is_admin": False}

        response = post_record(
            client,
            credential="AR-NEW",
            daily_assignments={"1": "A1", "2": "A1"},
            transfers=[{
                "source_credential": "AR-OLD",
                "target_credential": "AR-NEW",
                "day": 1,
                "code": "A1",
            }],
        )

    assert response.status_code == 409
    assert len(web.memory_records) == 1
    assert web.memory_records[0]["daily_assignments"]["1"] == "B2"


def test_bulk_code_transfer_updates_the_old_holder_for_admin(monkeypatch):
    original = {
        "name": "Titular anterior",
        "credential": "AR-OLD",
        "route": "Ruta Centro",
        "shift": "1",
        "nomenclature": "A",
        "work_days": [1],
        "rest_days": [],
        "daily_assignments": {"1": "A1"},
        "daily_details": {
            "1": {"route": "Ruta Centro", "shift": "1", "nomenclature": "A", "code": "A1"},
        },
    }
    new_record = {
        "name": "Nuevo titular",
        "credential": "AR-NEW",
        "route": "Ruta Centro",
        "shift": "1",
        "nomenclature": "A",
        "work_days": [1],
        "rest_days": [],
        "daily_assignments": {"1": "A1"},
        "daily_details": {
            "1": {"route": "Ruta Centro", "shift": "1", "nomenclature": "A", "code": "A1"},
        },
    }
    saved_records = []
    history_entries = []
    monkeypatch.setattr(web, "records_for", lambda *_args: [dict(original)])
    monkeypatch.setattr(web, "initialize_schema", lambda: None)
    monkeypatch.setattr(
        web,
        "save_month_records",
        lambda records, module_number, month, year, **_kwargs: (
            saved_records.extend(records) or len(records)
        ),
    )
    monkeypatch.setattr(
        web,
        "record_history",
        lambda *args, **kwargs: history_entries.append((args, kwargs)),
    )

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["account"] = {
                "username": "administrador",
                "module_number": 1,
                "is_admin": True,
            }

        response = client.post(
            "/api/records/save-all",
            json={
                "month": TEST_MONTH,
                "year": TEST_YEAR,
                "module_number": 1,
                "records": [dict(original), new_record],
                "transfers": [{
                    "source_credential": "AR-OLD",
                    "target_credential": "AR-NEW",
                    "day": 1,
                    "code": "A1",
                }],
            },
        )

    assert response.status_code == 200
    saved_old = next(record for record in saved_records if record["credential"] == "AR-OLD")
    assert saved_old["work_days"] == []
    assert saved_old["rest_days"] == [1]
    assert "1" not in saved_old["daily_assignments"]
    assert len(history_entries) == 3
    transfer_args, transfer_kwargs = history_entries[-2]
    assert transfer_args[1].startswith("Reasignó 1 código")
    target_args, target_kwargs = history_entries[-1]
    assert target_args[3] == "registro"
    assert target_kwargs["after"]["Asignaciones"][0]["Credencial"] == "AR-NEW"


def test_updating_rest_and_md_days_to_work_persists_route_assignments(monkeypatch):
    force_memory_mode(monkeypatch)
    with app.test_client() as client:
        with client.session_transaction() as session:
            session["account"] = {"username": "user1", "module_number": 1, "is_admin": False}

        created = post_record(
            client,
            work_days=[],
            rest_days=[1, 2],
            daily_assignments={"1": "D", "2": "D"},
            daily_details={},
        )
        assert created.status_code == 201

        md_assignment = post_record(
            client,
            work_days=[2],
            rest_days=[1],
            daily_assignments={"1": "D", "2": "MD"},
            daily_details={},
        )
        assert md_assignment.status_code == 201

        updated = post_record(
            client,
            work_days=[1, 2],
            rest_days=[],
            daily_assignments={"1": "A2", "2": "A2"},
            daily_details={
                "1": {
                    "route": "Ruta Centro",
                    "shift": "2",
                    "nomenclature": "A",
                    "code": "A2",
                },
                "2": {
                    "route": "Ruta Centro",
                    "shift": "2",
                    "nomenclature": "A",
                    "code": "A2",
                },
            },
        )

        assert updated.status_code == 201
        saved = updated.get_json()
        assert saved["work_days"] == [1, 2]
        assert saved["rest_days"] == []
        assert saved["daily_assignments"] == {"1": "A2", "2": "A2"}
        assert saved["daily_details"]["1"]["code"] == "A2"
        assert saved["daily_details"]["2"]["code"] == "A2"


def test_special_rest_code_is_preserved_and_counted_as_rest_in_memory(monkeypatch):
    force_memory_mode(monkeypatch)
    with app.test_client() as client:
        with client.session_transaction() as session:
            session["account"] = {"username": "user1", "module_number": 1, "is_admin": False}

        response = post_record(
            client,
            work_days=[],
            rest_days=[1],
            daily_assignments={"1": "D/F"},
            daily_details={},
        )

        assert response.status_code == 201
        saved = response.get_json()
        assert saved["rest_days"] == [1]
        assert saved["daily_assignments"]["1"] == "D/F"

        fetched = client.get(f"/api/records?month={TEST_MONTH}&year={TEST_YEAR}")
        assert fetched.status_code == 200
        assert fetched.get_json()[0]["daily_assignments"]["1"] == "D/F"
        assert fetched.get_json()[0]["rest_days"] == [1]


def test_role_status_codes_keep_their_own_assignments_in_memory(monkeypatch):
    force_memory_mode(monkeypatch)
    assignments = {
        "1": "MD",
        "3": "V",
        "4": "C/D",
        "5": "D/F",
        "6": "F",
        "7": "I",
        "8": "SE",
    }

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["account"] = {"username": "user1", "module_number": 1, "is_admin": False}

        response = post_record(
            client,
            work_days=[1],
            rest_days=[2, 4, 5],
            vacation_days=[3],
            daily_assignments=assignments,
            daily_details={},
        )

        assert response.status_code == 201
        saved = response.get_json()
        assert saved["daily_assignments"] == assignments
        assert saved["work_days"] == [1]
        assert saved["rest_days"] == [2, 4, 5]
        assert saved["daily_assignments"]["3"] == "V"

        fetched = client.get(f"/api/records?month={TEST_MONTH}&year={TEST_YEAR}")
        assert fetched.status_code == 200
        fetched_record = fetched.get_json()[0]
        assert fetched_record["daily_assignments"] == assignments
        assert fetched_record["work_days"] == [1]
        assert fetched_record["rest_days"] == [2, 4, 5]


def test_delete_record_by_credential(monkeypatch):
    force_memory_mode(monkeypatch)
    history_entries = []
    monkeypatch.setattr(
        web,
        "record_history",
        lambda *args, **kwargs: history_entries.append((args, kwargs)),
    )
    with app.test_client() as client:
        with client.session_transaction() as session:
            session["account"] = {"username": "user1", "module_number": 1, "is_admin": False}

        created = post_record(
            client,
            work_days=[1, 2],
            daily_assignments={"1": "A1", "2": "A1"},
            daily_details={
                "1": {"route": "Ruta Centro", "shift": "1", "nomenclature": "A", "code": "A1"},
                "2": {"route": "Ruta Centro", "shift": "1", "nomenclature": "A", "code": "A1"},
            },
        )
        assert created.status_code == 201

        deleted = client.post(
            "/api/records/delete",
            json={"credential": "AR-01", "month": TEST_MONTH, "year": TEST_YEAR},
        )
        assert deleted.status_code == 200
        payload = deleted.get_json()
        assert payload["deleted"] is True

        records = client.get(f"/api/records?month={TEST_MONTH}&year={TEST_YEAR}")
        assert records.status_code == 200
        assert records.get_json() == []

    deletion_history = next(kwargs for args, kwargs in history_entries if args[3] == "eliminacion")
    assert deletion_history["before"]["Credencial"] == "AR-01"
    assert deletion_history["before"]["Detalles diarios"]["1"]["route"] == "Ruta Centro"
    assert deletion_history["after"] is None


def test_normal_user_discarding_assigned_shift_records_history(monkeypatch):
    history_entries = []
    shift = {
        "id": 42,
        "numero": 8,
        "hora_inicio": "07:00",
        "hora_fin": "15:00",
        "activo": True,
        "alcance": "especifico",
    }

    monkeypatch.setattr(web, "initialize_schema", lambda: None)
    monkeypatch.setattr(
        web,
        "fetch_catalog_items",
        lambda catalog, module_number: [shift] if catalog == "turnos" and module_number == 2 else [],
    )
    monkeypatch.setattr(
        web,
        "record_history",
        lambda *args, **kwargs: history_entries.append((args, kwargs)) or True,
    )

    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {
            "username": "usuario-prueba",
            "module_number": 2,
            "is_admin": False,
            "tipo_usuario": "usuario",
        }

    response = client.post("/api/turnos/42/descartar")

    assert response.status_code == 200
    assert response.get_json() == {"ok": True}
    history_args, history_kwargs = history_entries[0]
    assert history_args[1] == "Descartó turno 8 (de Turnos)"
    assert history_args[2:4] == (2, "descarto")
    assert web.history_entry_category(history_args[1]) == "turnos"
    assert history_kwargs["before"]["Número"] == 8
    assert history_kwargs["before"]["Módulos disponibles"] == [
        {"Módulo": 2, "Estado": True}
    ]

    monkeypatch.setattr(web, "fetch_catalog_items", lambda *_args: [])
    unavailable = client.post("/api/turnos/42/descartar")
    assert unavailable.status_code == 409
    assert len(history_entries) == 1


def test_normal_user_readding_discarded_shift_records_history(monkeypatch):
    history_entries = []
    shift = {
        "id": 42,
        "numero": 8,
        "hora_inicio": "07:00",
        "hora_fin": "15:00",
        "activo": True,
        "alcance": "especifico",
    }

    monkeypatch.setattr(web, "initialize_schema", lambda: None)
    monkeypatch.setattr(
        web,
        "fetch_catalog_items",
        lambda catalog, module_number: [shift] if catalog == "turnos" and module_number == 2 else [],
    )
    monkeypatch.setattr(
        web,
        "record_history",
        lambda *args, **kwargs: history_entries.append((args, kwargs)) or True,
    )

    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {
            "username": "usuario-prueba",
            "module_number": 2,
            "is_admin": False,
            "tipo_usuario": "usuario",
        }

    response = client.post("/api/turnos/42/agregar")

    assert response.status_code == 200
    assert response.get_json() == {"ok": True}
    history_args, history_kwargs = history_entries[0]
    assert history_args[1] == "Agregó turno 8 (de Turnos)"
    assert history_args[2:4] == (2, "agrego")
    assert web.history_entry_category(history_args[1]) == "turnos"
    assert history_kwargs["after"]["Número"] == 8
    assert history_kwargs["after"]["Módulos disponibles"] == [
        {"Módulo": 2, "Estado": True}
    ]

    monkeypatch.setattr(web, "fetch_catalog_items", lambda *_args: [])
    unavailable = client.post("/api/turnos/42/agregar")
    assert unavailable.status_code == 409
    assert len(history_entries) == 1


def test_module_turnos_catalog_is_module_scoped_and_authorized(monkeypatch):
    fetched_catalogs = []
    shift = {"id": 42, "numero": 8, "activo": True}

    monkeypatch.setattr(web, "initialize_schema", lambda: None)
    monkeypatch.setattr(
        web,
        "fetch_catalog_items",
        lambda catalog, module_number=None: (
            fetched_catalogs.append((catalog, module_number)) or [shift]
        ),
    )

    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {
            "username": "administrador",
            "is_admin": True,
            "module_number": None,
        }

    response = client.get("/api/modulos/2/turnos")

    assert response.status_code == 200
    assert response.get_json() == [shift]
    assert fetched_catalogs == [("turnos", 2)]

    with client.session_transaction() as session:
        session["account"] = {
            "username": "usuario-prueba",
            "is_admin": False,
            "module_number": 1,
        }

    forbidden = client.get("/api/modulos/2/turnos")
    assert forbidden.status_code == 403
    assert fetched_catalogs == [("turnos", 2)]


def test_schedule_records_follow_latest_controller_name(monkeypatch):
    force_memory_mode(monkeypatch)
    web.memory_controllers = [{"id": 5, "nombre": "Ana García", "credencial": "AR-01", "sexo": "Femenino", "mod1": 1}]
    web.memory_records = [{
        "id": 1,
        "name": "Ana Vieja",
        "credential": "AR-01",
        "shift": "1",
        "route": "Ruta Centro",
        "nomenclature": "A",
        "month": TEST_MONTH,
        "year": TEST_YEAR,
        "work_days": [1],
        "rest_days": [],
        "daily_assignments": {"1": "A1"},
        "daily_details": {"1": {"route": "Ruta Centro", "shift": "1", "nomenclature": "A", "code": "A1"}},
        "module_number": 1,
    }]

    records = web.records_for(TEST_MONTH, TEST_YEAR, 1)

    assert records[0]["name"] == "Ana García"
    assert records[0]["credential"] == "AR-01"


def test_excel_export_has_summary_matrix_structure(monkeypatch):
    force_memory_mode(monkeypatch)
    web.memory_controllers = [{"id": 5, "nombre": "Ana García", "credencial": "AR-01", "sexo": "Femenino", "mod1": 1}]
    web.memory_records = [{
        "id": 1,
        "name": "Ana Vieja",
        "credential": "AR-01",
        "shift": "1",
        "route": "Ruta Centro",
        "nomenclature": "A",
        "month": TEST_MONTH,
        "year": TEST_YEAR,
        "work_days": [1, 2],
        "rest_days": [],
        "daily_assignments": {"1": "A1", "2": "V"},
        "daily_details": {
            "1": {"route": "Ruta Centro", "shift": "1", "nomenclature": "A", "code": "A1"},
            "2": {"route": "Ruta Centro", "shift": "1", "nomenclature": "A", "code": "V"},
        },
        "module_number": 1,
    }]

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["account"] = {"username": "user1", "module_number": 1, "is_admin": False}

        response = client.get("/export/excel?month=8&year=2026")
        assert response.status_code == 200

        workbook = load_workbook(filename=BytesIO(response.data))
        sheet = workbook.active
        headers = [cell.value for cell in sheet[1]]

        assert "NOM" in headers
        assert "RUTA" in headers
        assert "Origen" in headers
        assert "Destino" in headers
        assert "NOMBRE DEL CONTROLADOR" in headers
        assert "TURNO" in headers
        assert sheet.max_column >= 9
