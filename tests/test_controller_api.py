from app import web


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
