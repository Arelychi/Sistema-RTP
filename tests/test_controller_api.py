from app import web


def test_module_controller_creation_persists_and_reports_success(monkeypatch):
    created = []
    monkeypatch.setattr(web, "initialize_schema", lambda: None)
    monkeypatch.setattr(web, "fetch_controller_by_credential", lambda credential: None)
    monkeypatch.setattr(
        web,
        "create_controller",
        lambda payload: created.append(dict(payload)) or {
            "id": 15,
            "nombre": payload["nombre"],
            "credencial": payload["credencial"],
            "sexo": payload["sexo"],
            "mod1": payload["mod1"],
        },
    )
    monkeypatch.setattr(web, "record_history", lambda *args, **kwargs: None)

    client = web.app.test_client()
    with client.session_transaction() as session:
        session["account"] = {"username": "user2", "module_number": 2, "is_admin": False}

    response = client.post(
        "/modulo/2/controladores",
        data={"nombre": "Ana García", "credencial": "7788", "sexo": "Femenino"},
    )

    assert response.status_code == 302
    assert response.location.endswith("controller_action=created&controller_id=15")
    assert created == [{
        "nombre": "Ana García",
        "credencial": "7788",
        "sexo": "Femenino",
        "mod1": 2,
        "active": True,
    }]


def test_module_controller_creation_surfaces_database_failure(monkeypatch, caplog):
    monkeypatch.setattr(web, "initialize_schema", lambda: None)
    monkeypatch.setattr(web, "fetch_controller_by_credential", lambda credential: None)

    def fail_create_controller(payload):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(web, "create_controller", fail_create_controller)

    client = web.app.test_client()
    with client.session_transaction() as session:
        session["account"] = {"username": "user2", "module_number": 2, "is_admin": False}

    response = client.post(
        "/modulo/2/controladores",
        data={"nombre": "Ana García", "credencial": "7788", "sexo": "Femenino"},
    )

    assert response.status_code == 302
    assert "controller_action=error" in response.location
    assert "controller_error=RuntimeError" in response.location
    assert "database unavailable" in caplog.text


def test_controller_update_and_delete_endpoints(monkeypatch):
    app = web.app

    def fake_initialize_schema():
        return None

    def fake_update_controller(controller_id, payload):
        assert controller_id == 7
        assert payload == {"nombre": "Ana", "credencial": "7788", "sexo": "Femenino", "mod1": 2}
        return {"id": 7, "nombre": "Ana", "credencial": "7788", "sexo": "Femenino", "mod1": 2}

    def fake_delete_controller(controller_id):
        assert controller_id == 7
        return True

    monkeypatch.setattr(web, "initialize_schema", fake_initialize_schema)
    monkeypatch.setattr(web, "update_controller", fake_update_controller)
    monkeypatch.setattr(web, "delete_controller", fake_delete_controller)

    client = app.test_client()

    with client.session_transaction() as session:
        session["account"] = {"username": "user2", "module_number": 2, "is_admin": False}

    response = client.put(
        "/api/controladores/7",
        json={"nombre": "Ana", "credencial": "7788", "sexo": "Femenino"},
    )
    assert response.status_code == 200
    assert response.get_json()["credencial"] == "7788"

    response = client.delete("/api/controladores/7")
    assert response.status_code == 200
    assert response.get_json()["ok"] is True
