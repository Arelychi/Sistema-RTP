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
    with app.test_client() as client:
        with client.session_transaction() as session:
            session["account"] = {"username": "user1", "module_number": 1, "is_admin": False}

        created = post_record(client)
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
