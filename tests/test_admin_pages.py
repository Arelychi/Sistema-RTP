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


def test_admin_monthly_role_form_exposes_special_state_category(monkeypatch):
    monkeypatch.setattr("app.web.initialize_schema", lambda: None)
    monkeypatch.setattr("app.web.request_modules", lambda: [])
    monkeypatch.setattr(
        "app.web.fetch_catalog_items",
        lambda catalog: [
            {
                "id": 3,
                "codigo": "D/F",
                "descripcion": "Descanso por festivo",
                "categoria": "descanso",
                "activo": True,
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

    response = client.get("/administrador/rol-mensual")

    assert response.status_code == 200
    assert b'name="categoria"' in response.data
    assert b'value="descanso"' in response.data
    assert b'value="falta"' in response.data
    assert b'value="vacaciones"' in response.data
    assert b'value="incapacidad"' in response.data
    assert b'Descanso por festivo' in response.data
    assert b'<th>Categor\xc3\xada</th>' in response.data


def test_special_state_category_is_required_and_saved(monkeypatch):
    saved = []
    monkeypatch.setattr("app.web.initialize_schema", lambda: None)
    monkeypatch.setattr("app.web.refresh_analysis_tables", lambda: None)
    monkeypatch.setattr(
        "app.web.create_catalog_item",
        lambda catalog, payload: saved.append((catalog, payload)),
    )
    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {
            "username": "administrador",
            "module_number": None,
            "is_admin": True,
        }

    for code, category in (
        ("D/F", "descanso"),
        ("F", "falta"),
        ("V", "vacaciones"),
        ("I", "incapacidad"),
    ):
        response = client.post(
            "/administrador/tipos-rutas",
            data={
                "catalog": "estados_especiales",
                "codigo": code.lower(),
                "descripcion": "Estado especial",
                "categoria": category,
                "activo": "on",
            },
        )

        assert response.status_code == 302

    assert [catalog for catalog, _ in saved] == ["estados_especiales"] * 4
    assert [payload["categoria"] for _, payload in saved] == [
        "descanso",
        "falta",
        "vacaciones",
        "incapacidad",
    ]
    assert saved[0][1]["codigo"] == "D/F"


def test_special_state_rejects_categories_outside_supported_values(monkeypatch):
    created = []
    monkeypatch.setattr("app.web.initialize_schema", lambda: None)
    monkeypatch.setattr(
        "app.web.create_catalog_item",
        lambda catalog, payload: created.append((catalog, payload)),
    )
    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {
            "username": "administrador",
            "module_number": None,
            "is_admin": True,
        }

    response = client.post(
        "/administrador/tipos-rutas",
        data={
            "catalog": "estados_especiales",
            "codigo": "X",
            "descripcion": "Estado inválido",
            "categoria": "otro",
            "activo": "on",
        },
    )

    assert response.status_code == 302
    assert created == []


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
