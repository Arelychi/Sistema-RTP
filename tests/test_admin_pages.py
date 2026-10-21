from app.web import app


def test_module_login_opens_monthly_role(monkeypatch):
    monkeypatch.setattr("app.web.initialize_schema", lambda: None)
    monkeypatch.setattr(
        "app.web.authenticate_user",
        lambda username, password: {
            "username": username,
            "module_number": 2,
            "is_admin": False,
        },
    )
    monkeypatch.setattr("app.web.record_history", lambda *args, **kwargs: None)

    response = app.test_client().post(
        "/",
        data={"username": "user2", "password": "user2"},
    )

    assert response.status_code == 302
    assert response.location.endswith("/modulo/2/rol")


def test_admin_controllers_page_is_available(monkeypatch):
    monkeypatch.setattr("app.web.initialize_schema", lambda: None)
    monkeypatch.setattr(
        "app.web.request_modules",
        lambda: [{"id": 1, "nombre": "Módulo Uno"}],
    )
    monkeypatch.setattr("app.web.fetch_controllers", lambda: [])
    client = app.test_client()
    with client.session_transaction() as session:
        session['account'] = {
            'username': 'administrador',
            'module_number': None,
            'is_admin': True,
        }

    response = client.get('/administrador/controladores')

    assert response.status_code == 200
    assert b'Controladores registrados' in response.data
    assert b'href="/administrador/controladores"' in response.data


def test_admin_users_page_is_available():
    client = app.test_client()
    with client.session_transaction() as session:
        session['account'] = {
            'username': 'administrador',
            'module_number': None,
            'is_admin': True,
        }

    response = client.get('/administrador/usuarios')

    assert response.status_code == 200
    assert b'Usuarios' in response.data
    assert b'Creaci\xc3\xb3n de controladores' not in response.data


def test_admin_modules_page_has_creation_modal_and_module_filter(monkeypatch):
    monkeypatch.setattr("app.web.initialize_schema", lambda: None)
    monkeypatch.setattr(
        "app.web.request_modules",
        lambda: [
            {
                "id": 2,
                "nombre": "Módulo Centro",
                "direccion": "Calle principal",
                "latitud": 19.4,
                "longitud": -99.1,
            }
        ],
    )
    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {
            "username": "administrador",
            "module_number": None,
            "is_admin": True,
        }

    response = client.get("/administrador/modulos")

    assert response.status_code == 200
    assert b"Crear m\xc3\xb3dulo" in response.data
    assert b'id="module-form-modal"' in response.data
    assert b'data-admin-type-filter' in response.data
    assert b'data-module-modal-cancel' in response.data
    assert b'data-module-save-button' in response.data


def test_turno_edit_preserves_number_when_form_omits_it(monkeypatch):
    class Cursor:
        def execute(self, query, params):
            assert "SELECT numero FROM catalogos.turnos" in query
            assert params == (42,)

        def fetchone(self):
            return (6,)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

    class Connection:
        def cursor(self):
            return Cursor()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

    updated = {}
    modules = {}
    monkeypatch.setattr("app.web.initialize_schema", lambda: None)
    monkeypatch.setattr("app.web.get_connection", Connection)
    monkeypatch.setattr("app.web.turno_start_exists", lambda hora, exclude_id: False)
    monkeypatch.setattr(
        "app.web.update_catalog_item",
        lambda table, item_id, payload: updated.update(payload) or {"id": item_id},
    )
    monkeypatch.setattr(
        "app.web.set_turno_modules",
        lambda turno_id, module_ids, statuses: modules.update(
            turno_id=turno_id,
            module_ids=module_ids,
            statuses=statuses,
        ),
    )
    monkeypatch.setattr("app.web.renumber_turnos_by_start", lambda: None)

    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {"username": "administrador", "is_admin": True}

    response = client.post(
        "/administrador/turnos",
        data={
            "turno_id": "42",
            "hora_inicio": "10:00",
            "hora_fin": "18:00",
            "turno_scope": "especifico",
            "turno_modules": "2",
            "turno_module_status_2": "Activo",
        },
    )

    assert response.status_code == 302
    assert updated["numero"] == 6
    assert modules == {"turno_id": 42, "module_ids": [2], "statuses": {2: True}}
