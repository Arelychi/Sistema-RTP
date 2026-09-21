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


def test_admin_controllers_page_is_available():
    client = app.test_client()
    with client.session_transaction() as session:
        session['account'] = {
            'username': 'administrador',
            'module_number': None,
            'is_admin': True,
        }

    response = client.get('/administrador/controladores')

    assert response.status_code == 200
    assert b'Creaci\xc3\xb3n de controladores' in response.data
    assert b'Usuarios' not in response.data


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
