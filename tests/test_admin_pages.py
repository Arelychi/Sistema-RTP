from app.web import app


def test_delete_routes_from_module_deletes_originals_and_unlinks_shares(monkeypatch):
    import app.db as db

    class FakeCursor:
        def __init__(self):
            self.rowcount = 0
            self.operations = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def execute(self, query, params):
            self.operations.append((query, params))
            if query.startswith("DELETE FROM catalogos.rutas"):
                self.rowcount = int(params[0] == 11 and params[1] == 2)
            else:
                self.rowcount = int(params[0] == 22 and params[1] == 2)

    class FakeConnection:
        def __init__(self):
            self.fake_cursor = FakeCursor()
            self.committed = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def cursor(self):
            return self.fake_cursor

        def commit(self):
            self.committed = True

    connection = FakeConnection()
    monkeypatch.setattr("app.db.get_connection", lambda: connection)

    result = db.delete_routes_from_module([11, 22], 2)

    assert result == {"deleted_originals": 1, "unlinked_shared": 1}
    assert connection.committed
    assert len(connection.fake_cursor.operations) == 3
    assert connection.fake_cursor.operations[0][0].startswith("DELETE FROM catalogos.rutas")
    assert connection.fake_cursor.operations[1][0].startswith("DELETE FROM catalogos.rutas")
    assert connection.fake_cursor.operations[2][0].startswith("DELETE FROM catalogos.modulo_ruta")


def test_delete_controllers_from_module_validates_scope_and_commits(monkeypatch):
    import app.db as db

    class FakeCursor:
        def __init__(self, rows):
            self.rows = rows
            self.deleted_ids = []
            self.operations = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def execute(self, query, params):
            self.operations.append((query, params))
            if query.lstrip().startswith("DELETE"):
                self.deleted_ids = [row[0] for row in self.rows]

        def fetchall(self):
            if self.operations[-1][0].lstrip().startswith("DELETE"):
                return [(controller_id,) for controller_id in self.deleted_ids]
            return self.rows

    class FakeConnection:
        def __init__(self, rows):
            self.fake_cursor = FakeCursor(rows)
            self.committed = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def cursor(self):
            return self.fake_cursor

        def commit(self):
            self.committed = True

    rows = [
        (17, "Ana", "12345", "Femenino", 2),
        (19, "Luis", "67890", "Masculino", 2),
    ]
    connection = FakeConnection(rows)
    monkeypatch.setattr("app.db.get_connection", lambda: connection)

    deleted = db.delete_controllers_from_module([17, 19, 17], 2)

    assert deleted == [
        {"id": 17, "nombre": "Ana", "credencial": "12345", "sexo": "Femenino", "mod1": 2},
        {"id": 19, "nombre": "Luis", "credencial": "67890", "sexo": "Masculino", "mod1": 2},
    ]
    assert connection.committed
    assert connection.fake_cursor.operations[0][1] == ([17, 19], 2)
    assert connection.fake_cursor.operations[1][1] == ([17, 19], 2)

    invalid_connection = FakeConnection(rows[:1])
    monkeypatch.setattr("app.db.get_connection", lambda: invalid_connection)
    try:
        db.delete_controllers_from_module([17, 19], 2)
    except ValueError as error:
        assert "ya no pertenece a este módulo" in str(error)
    else:
        raise AssertionError("Expected out-of-module controller selections to be rejected")
    assert not invalid_connection.committed


def test_delete_users_by_ids_validates_selection_and_commits(monkeypatch):
    import app.db as db

    class FakeCursor:
        def __init__(self, rows):
            self.rows = rows
            self.operations = []
            self.returned_rows = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def execute(self, query, params):
            self.operations.append((query, params))
            self.returned_rows = (
                [(row[0],) for row in self.rows]
                if query.lstrip().startswith("DELETE")
                else self.rows
            )

        def fetchall(self):
            return self.returned_rows

    class FakeConnection:
        def __init__(self, rows):
            self.fake_cursor = FakeCursor(rows)
            self.committed = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def cursor(self):
            return self.fake_cursor

        def commit(self):
            self.committed = True

    rows = [
        (7, "supervisor-prueba", 1, "usuario"),
        (8, "admin-prueba", None, "admin"),
    ]
    connection = FakeConnection(rows)
    monkeypatch.setattr("app.db.get_connection", lambda: connection)

    deleted = db.delete_users_by_ids([7, 8, 7])

    assert deleted == [
        {"id": 7, "username": "supervisor-prueba", "module_number": 1, "tipo_usuario": "usuario"},
        {"id": 8, "username": "admin-prueba", "module_number": None, "tipo_usuario": "admin"},
    ]
    assert connection.committed
    assert connection.fake_cursor.operations[0][1] == ([7, 8],)
    assert connection.fake_cursor.operations[1][1] == ([7, 8],)

    invalid_connection = FakeConnection(rows[:1])
    monkeypatch.setattr("app.db.get_connection", lambda: invalid_connection)
    try:
        db.delete_users_by_ids([7, 8])
    except ValueError as error:
        assert "ya no está disponible" in str(error)
    else:
        raise AssertionError("Expected missing user selections to be rejected")
    assert not invalid_connection.committed


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
    assert b'class="admin-toast"' in response.data
    notification_script = client.get("/static/admin_notifications.js")
    assert notification_script.status_code == 200
    assert b"admin-module-changed" in notification_script.data
    assert b"adminPendingNotification" in notification_script.data
    assert b"activeSectionName()}: ${moduleName}" in notification_script.data
    assert b"Secci\xc3\xb3n: ${tabLabel(tab)}" not in notification_script.data
    assert b"if (activeModule && !hasPendingNotification)" in notification_script.data
    assert b"flashAlerts.length * 4500" in notification_script.data
    module_tabs_script = client.get("/static/admin_tabs.js")
    assert module_tabs_script.status_code == 200
    assert b"changed: previousModuleId !== selectedModule" in module_tabs_script.data


def test_admin_controllers_table_has_reference_actions_and_delete_modal(monkeypatch):
    monkeypatch.setattr("app.web.initialize_schema", lambda: None)
    monkeypatch.setattr(
        "app.web.request_modules",
        lambda: [{"id": 1, "nombre": "Módulo Uno"}],
    )
    monkeypatch.setattr(
        "app.web.fetch_controllers",
        lambda: [
            {
                "id": 17,
                "nombre": "Ana Prueba",
                "credencial": "12345",
                "sexo": "Femenino",
                "mod1": 1,
                "active": True,
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

    response = client.get("/administrador/controladores")

    assert response.status_code == 200
    assert b'role="table" aria-label="Controladores del M\xc3\xb3dulo Uno"' in response.data
    assert b'role="columnheader">Nombre del controlador</span>' in response.data
    assert b'aria-label="Editar Ana Prueba"' in response.data
    assert b'aria-label="Eliminar Ana Prueba"' in response.data
    assert b'data-controller-delete-form' in response.data
    assert b'data-delete-confirm-form' in response.data
    assert b'data-delete-kind="controlador"' in response.data
    assert b'class="admin-controller-table admin-controller-selectable"' in response.data
    assert b'data-controller-select-all' in response.data
    assert b'data-controller-bulk-select value="17"' in response.data
    assert b'data-controller-cancel-selection hidden' in response.data
    assert b'data-controller-create-or-delete data-controller-modal-open>Crear controlador' in response.data
    assert b'data-controller-individual-actions' in response.data
    assert b'data-controller-bulk-delete-form' in response.data
    assert b'data-controller-status-action' in response.data
    assert b'data-admin-pagination' in response.data
    assert b'data-admin-page-prev' in response.data
    assert b'data-admin-page-next' in response.data
    assert b'const pageSize = 10' in response.data
    assert b'id="controller-delete-modal"' in response.data
    assert b'aria-describedby="controller-delete-message"' in response.data
    assert b'id="controller-status-filter"' in response.data
    assert b'data-controller-filter-option="gender" value="Femenino"' in response.data
    assert b'data-controller-filter-option="gender" value="Masculino"' in response.data
    assert b'data-controller-filter-option="gender" value="Otro"' in response.data
    assert b'data-controller-filter-option="status" value="Activo"' in response.data
    assert b'data-controller-filter-option="status" value="Inactivo"' in response.data
    assert b'data-controller-gender="Femenino"' in response.data
    assert b'onclick="return confirm' not in response.data
    assert b"updateBulkSelection" in response.data
    assert b"toolbar.classList.toggle('is-controller-selection-mode', selectionMode)" in response.data
    assert b"submitBulkDelete" in response.data
    dashboard_styles = client.get("/static/admin/dashboard.css")
    assert dashboard_styles.status_code == 200
    assert b".admin-module-group-tabbed > .admin-controller-toolbar.is-controller-selection-mode" in dashboard_styles.data
    assert b"grid-template-columns: minmax(0, 1fr) minmax(150px, 190px) minmax(180px, 200px)" in dashboard_styles.data
    assert b"minmax(170px, 190px) minmax(180px, 200px)" in dashboard_styles.data
    assert b"[data-controller-individual-actions][hidden] {\n  display: inline-flex !important;\n  visibility: hidden;\n  pointer-events: none;" in dashboard_styles.data
    assert b".admin-controller-page-panel .admin-controller-item[hidden]" in dashboard_styles.data
    assert b"display: none !important;" in dashboard_styles.data


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


def test_admin_users_table_separates_user_contact_columns(monkeypatch):
    monkeypatch.setattr("app.web.initialize_schema", lambda: None)
    monkeypatch.setattr(
        "app.web.request_modules",
        lambda: [{"id": 1, "nombre": "Módulo Uno"}],
    )
    monkeypatch.setattr(
        "app.web.fetch_users",
        lambda: [
            {
                "id": 7,
                "username": "usuario-prueba",
                "correo": "usuario@example.com",
                "telefono": "555-0100",
                "tipo_usuario": "usuario",
                "active": True,
                "module_number": 1,
            },
            {
                "id": 8,
                "username": "admin-prueba",
                "correo": "admin@example.com",
                "telefono": "",
                "tipo_usuario": "admin",
                "active": False,
                "module_number": None,
            },
            {
                "id": 9,
                "username": "consultor-prueba",
                "correo": "consultor@example.com",
                "telefono": "",
                "tipo_usuario": "consultor",
                "active": True,
                "module_number": None,
            },
        ],
    )
    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {
            "username": "administrador",
            "module_number": None,
            "is_admin": True,
        }

    response = client.get("/administrador/usuarios")

    assert response.status_code == 200
    table = response.data.split(b'<table class="admin-route-table admin-user-table admin-user-selectable">', 1)[1]
    assert b"<th>Usuarios</th><th>Correo</th><th>Tel\xc3\xa9fono</th><th>Tipo</th><th>Estatus</th><th>Acciones</th>" in table
    assert b'<th class="admin-user-select-column"><input type="checkbox" data-users-select-all' in response.data
    assert b'data-users-bulk-select value="7"' in response.data
    assert b'data-users-cancel-selection hidden' in response.data
    assert b'data-user-modal-open>Crear usuario' in response.data
    assert b'data-users-selection-group' in response.data
    assert b'data-users-bulk-delete-form' in response.data
    assert b'data-users-bulk-delete-button hidden' in response.data
    assert b'data-user-individual-actions' in response.data
    assert b"row.classList.toggle('is-bulk-selected'" in response.data
    assert b"statusInput.disabled = selectionMode" in response.data
    assert b"event.stopImmediatePropagation()" in response.data
    assert b"function setHidden(element, hidden)" in response.data
    assert b'<td class="admin-user-select-column"><input type="checkbox" data-users-bulk-select value="7"' in table
    assert b"<td><strong>usuario-prueba</strong></td>" in table
    assert b"<td>usuario@example.com</td>" in table
    assert b"<td>555-0100</td>" in table
    assert b'id="controller-delete-modal"' in response.data
    assert b'data-delete-kind="usuario"' in response.data
    assert response.data.count(b'class="admin-controller-toolbar admin-users-toolbar') == 3
    assert response.data.count(b'data-route-filter-option="userType" value="Supervisor"') == 3
    assert response.data.count(b'data-route-filter-option="userType" value="Administrador"') == 3
    assert response.data.count(b'data-route-filter-option="userType" value="Consultor"') == 3
    assert response.data.count(b'data-route-filter-option="status" value="Activo"') == 3
    assert response.data.count(b'data-route-filter-option="status" value="Inactivo"') == 3
    assert b'data-filter-type="Supervisor"' in response.data
    assert b'data-filter-type="Administrador"' in response.data
    assert b'data-filter-type="Consultor"' in response.data
    assert response.data.count(b'data-admin-visible-count-target="users-page-count"') == 3
    assert b'id="users-page-count" data-users-page-count' in response.data
    assert response.data.count(b'<nav class="admin-route-pagination" data-admin-pagination') == 3
    toolbar_script = client.get("/static/admin_registry_toolbar.js")
    assert b'visibleCountIsCurrent' in toolbar_script.data
    assert b'admin-user-view-changed' in toolbar_script.data
    assert b'selectedRouteFilters.userType.includes(row.dataset.filterType)' in toolbar_script.data
    user_styles = client.get("/static/admin/dashboard.css")
    assert b".admin-user-list .admin-user-item[hidden]" in user_styles.data
    assert b".admin-user-table tbody tr[hidden]" in user_styles.data
    assert b".admin-user-table.admin-user-selectable tbody tr.is-bulk-selected td" in user_styles.data
    assert "Se eliminarán ${userNames.length} usuario(s) seleccionado(s).".encode() in response.data


def test_admin_delete_selected_users_records_each_deletion(monkeypatch):
    deleted = []
    histories = []
    monkeypatch.setattr("app.web.initialize_schema", lambda: None)
    monkeypatch.setattr(
        "app.web.delete_users_by_ids",
        lambda user_ids: (
            deleted.append(user_ids)
            or [
                {"id": 7, "username": "supervisor-prueba", "module_number": 1, "tipo_usuario": "usuario"},
                {"id": 8, "username": "admin-prueba", "module_number": None, "tipo_usuario": "admin"},
            ]
        ),
    )
    monkeypatch.setattr("app.web.record_history", lambda *args: histories.append(args))
    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {
            "username": "administrador",
            "module_number": None,
            "is_admin": True,
        }

    response = client.post(
        "/administrador/usuarios/eliminar-seleccionados",
        data={"user_ids": ["7", "8", "7"]},
    )

    assert response.status_code == 302
    assert response.location.endswith("/administrador/usuarios")
    assert deleted == [[7, 8]]
    assert len(histories) == 2
    assert histories[0][1:] == (
        "Eliminó usuario supervisor-prueba (de Usuarios)",
        1,
        "eliminacion",
        "Tipo: Supervisor",
    )
    assert histories[1][1:] == (
        "Eliminó usuario admin-prueba (de Usuarios)",
        None,
        "eliminacion",
        "Tipo: Administrador",
    )
    with client.session_transaction() as session:
        assert session["_flashes"][-1][1] == "2 usuario(s) eliminado(s) correctamente."


def test_admin_routes_page_renders_dynamic_multiselect_filters(monkeypatch):
    monkeypatch.setattr("app.web.initialize_schema", lambda: None)
    monkeypatch.setattr(
        "app.web.request_modules",
        lambda: [
            {"id": 1, "nombre": "Módulo Uno"},
            {"id": 2, "nombre": "Módulo Dos"},
        ],
    )
    monkeypatch.setattr(
        "app.web.fetch_routes",
        lambda module_number: [
            {
                "id": 3 if module_number == 1 else 4,
                "nomenclatura": "R-03" if module_number == 1 else "R-04",
                "ruta": "Centro" if module_number == 1 else "Compartida",
                "origen": "Norte",
                "destino": "Sur",
                "servicio": "Servicio especial",
                "estado": "Activo",
                "mod1": 1,
                "is_external": module_number == 2,
                "tipos_descripcion": "Tipo suburbano",
            }
        ],
    )
    monkeypatch.setattr(
        "app.web.fetch_catalog_items",
        lambda catalog: (
            [{"id": 5, "nombre": "Servicio especial", "activo": True}]
            if catalog == "servicio"
            else [{"id": 8, "descripcion": "Tipo suburbano", "activo": True}]
        ),
    )
    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {
            "username": "administrador",
            "module_number": None,
            "is_admin": True,
        }

    response = client.get("/administrador/rutas")

    assert response.status_code == 200
    assert b'data-admin-route-filters' in response.data
    assert b'data-route-filter-option="status" value="Activo"' in response.data
    assert b'data-route-filter-option="status" value="Inactivo"' in response.data
    assert b'data-route-filter-option="category" value="Originales"' in response.data
    assert b'data-route-filter-option="category" value="Compartidas"' in response.data
    assert b'data-route-filter-option="service" value="Servicio especial"' in response.data
    assert b'data-route-filter-option="type" value="Tipo suburbano"' in response.data
    assert b'data-filter-service="Servicio especial"' in response.data
    assert b'data-filter-route-type="Tipo suburbano"' in response.data
    assert b"Select a view" not in response.data
    assert response.data.count(b'<nav class="admin-route-pagination" data-admin-pagination') == 2
    assert b'data-route-link-open="1"' in response.data
    assert b'imagenes/icons/vinculado.png' in response.data
    assert b'id="route-link-modal"' in response.data
    assert b'data-route-link-source="1"' in response.data
    assert b'data-route-link-source="2" data-route-link-module-name="M\xc3\xb3dulo Dos" hidden' in response.data
    assert b'data-route-id="3" data-route-module="1" data-route-name="Centro" data-route-original="true"' in response.data
    assert b'class="admin-route-shared-module-badge" data-route-source-module="1" aria-label="Ruta compartida desde el m\xc3\xb3dulo 1">M1</span>' in response.data
    assert response.data.count(b'class="admin-route-shared-module-badge"') == 1
    assert b'id="controller-delete-modal"' in response.data
    assert b'data-delete-kind="tipo de ruta"' in response.data
    assert b'data-delete-kind="servicio"' in response.data
    assert b'data-delete-kind="ruta"' in response.data
    assert b'data-route-bulk-select value="3"' in response.data
    assert b'data-route-select-all aria-label="Seleccionar todas las rutas visibles"' in response.data
    assert b'admin-route-table admin-route-selectable' in response.data
    assert b'data-route-module-count' in response.data
    assert b"routeRows.filter((row) => row.dataset.adminFilterMatch !== 'false').length" in response.data
    assert b'data-route-individual-actions' in response.data
    assert b'data-route-status-action' in response.data
    assert b'data-route-status-display' not in response.data
    assert b"if (statusInput) statusInput.disabled = selectionMode;" in response.data
    assert b"modulePanel.classList.toggle('is-route-selection-mode', selectionMode)" in response.data
    assert b'data-route-selected-actions' not in response.data
    assert b'data-route-bulk-delete-form' in response.data
    assert b'action="/administrador/rutas/eliminar-seleccionadas"' in response.data
    assert b'data-route-pagination aria-label="Paginaci\xc3\xb3n de rutas"' in response.data
    assert b'data-route-page-prev' in response.data
    assert b'data-route-page-next' in response.data
    assert b'const pageSize = 10;' in response.data
    assert b'data-route-cancel-selection hidden>Cancelar selecci\xc3\xb3n</button>' in response.data
    assert b'data-route-create-or-delete data-route-modal-open>Crear ruta</button>' in response.data


def test_admin_link_routes_posts_selected_routes_for_target_module(monkeypatch):
    linked = []
    monkeypatch.setattr("app.web.initialize_schema", lambda: None)
    monkeypatch.setattr(
        "app.web.request_modules",
        lambda: [{"id": 1, "nombre": "Módulo Uno"}, {"id": 2, "nombre": "Módulo Dos"}],
    )
    monkeypatch.setattr(
        "app.web.link_routes_to_module",
        lambda route_ids, module_number: linked.append((route_ids, module_number)) or len(route_ids),
    )
    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {
            "username": "administrador",
            "module_number": None,
            "is_admin": True,
        }

    response = client.post(
        "/administrador/rutas/vincular",
        data={"target_module": "2", "route_ids": ["3", "7", "3"]},
    )

    assert response.status_code == 302
    assert response.location.endswith("/administrador/rutas?module_number=2")
    assert linked == [([3, 7], 2)]


def test_admin_delete_selected_routes_keeps_originals_and_shared_routes_distinct(monkeypatch):
    deleted = []
    monkeypatch.setattr("app.web.initialize_schema", lambda: None)
    monkeypatch.setattr(
        "app.web.delete_routes_from_module",
        lambda route_ids, module_number: (
            deleted.append((route_ids, module_number))
            or {"deleted_originals": 1, "unlinked_shared": 1}
        ),
    )
    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {
            "username": "administrador",
            "module_number": None,
            "is_admin": True,
        }

    response = client.post(
        "/administrador/rutas/eliminar-seleccionadas",
        data={"module_number": "2", "route_ids": ["3", "7", "3"]},
    )

    assert response.status_code == 302
    assert response.location.endswith("/administrador/rutas?module_number=2")
    assert deleted == [([3, 7], 2)]
    with client.session_transaction() as session:
        assert session["_flashes"][-1][1] == "1 ruta(s) original(es) eliminada(s); 1 ruta(s) compartida(s) desvinculada(s)."


def test_admin_delete_selected_controllers_is_limited_to_module(monkeypatch):
    deleted = []
    histories = []
    monkeypatch.setattr("app.web.initialize_schema", lambda: None)
    monkeypatch.setattr(
        "app.web.delete_controllers_from_module",
        lambda controller_ids, module_number: (
            deleted.append((controller_ids, module_number))
            or [
                {"id": 17, "nombre": "Ana Prueba", "credencial": "12345", "sexo": "Femenino", "mod1": 2},
                {"id": 19, "nombre": "Luis Prueba", "credencial": "67890", "sexo": "Masculino", "mod1": 2},
            ]
        ),
    )
    monkeypatch.setattr("app.web.record_history", lambda *args: histories.append(args))
    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {
            "username": "administrador",
            "module_number": None,
            "is_admin": True,
        }

    response = client.post(
        "/administrador/controladores/eliminar-seleccionados",
        data={"module_number": "2", "controller_ids": ["17", "19", "17"]},
    )

    assert response.status_code == 302
    assert response.location.endswith("/administrador/controladores?module_number=2")
    assert deleted == [([17, 19], 2)]
    assert len(histories) == 2
    with client.session_transaction() as session:
        assert session["_flashes"][-1][1] == "2 controlador(es) eliminado(s) correctamente."


def test_admin_analysis_dashboard_uses_monthly_controller_data(monkeypatch):
    worker = {
        "credential": "12345",
        "name": "Luis Prueba",
        "module_number": 2,
        "worked": 10,
        "incapacity": 1,
        "rest": 4,
        "vacation": 2,
        "absence": 1,
        "holiday": 1,
        "permission": 0,
        "special_status": 1,
        "change_of_rest": 1,
        "holiday_rest": 1,
        "sefi": 1,
    }
    dashboard_calls = []
    monkeypatch.setattr("app.web.initialize_schema", lambda: None)
    monkeypatch.setattr(
        "app.web.request_modules",
        lambda: [{"id": 2, "nombre": "Módulo Dos"}],
    )
    monkeypatch.setattr(
        "app.web.fetch_controller_analysis_dashboard",
        lambda month, year, credential, module: (
            dashboard_calls.append((month, year, credential, module))
            or {
                "registered_controllers": 17,
                "active_controllers": 2,
                "inactive_controllers": 15,
                "assigned_controllers": 1,
                "workers": [worker],
                "selected_worker": worker,
                "route_days": [{"route": "Ruta Centro", "days": 6}],
                "calendar_days": [
                    {
                        "day": 1,
                        "status": "TRABAJADO",
                        "code": "R1M",
                        "route": "Ruta Centro",
                        "shift": "Matutino",
                    },
                    {
                        "day": 2,
                        "status": "DESCANSO",
                        "code": "C/D",
                        "route": "",
                        "shift": "",
                    },
                ],
            }
        ),
    )
    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {
            "username": "administrador",
            "module_number": None,
            "is_admin": True,
        }

    response = client.get(
        "/administrador/analisis?month=10&year=2026&credential=12345&module=2"
    )

    assert response.status_code == 200
    assert dashboard_calls == [(10, 2026, "12345", 2)]
    html = response.data.decode()
    balance_card = html.split('class="analysis-dashboard-card analysis-balance-card"', 1)[1].split("</article>", 1)[0]
    assert balance_card.count('class="analysis-status-row"') == 4
    assert all(category in balance_card for category in ("Trabajo", "Vacaciones", "Descanso", "Falta"))
    assert all(category not in balance_card for category in ("Incapacidades", "C/D · Cambio", "D/F · Descanso", "SEFI"))
    assert b"ControlDesk" in response.data
    assert b"Controladores" in response.data
    assert b"Rutas</button>" in response.data
    assert b"Controladores registrados" in response.data
    assert b"17" in response.data
    assert b"Ruta Centro" in response.data
    assert b"Luis Prueba" in response.data
    assert b"M\xc3\xb3dulo 2" in response.data
    assert b'class="analysis-calendar-day is-work"' in response.data
    assert b'class="analysis-calendar-day is-rest-change"' in response.data
    assert b"C/D \xc2\xb7 Cambio de descanso" in response.data
    assert b'class="admin-module-tabs"' in response.data
    assert b'class="admin-sidebar"' in response.data
    assert b'type="search"' not in response.data


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
    assert b'admin-module-header admin-routes-page-header admin-role-page-header route-tab-active' in response.data
    assert b'class="admin-registry-tab active"' in response.data
    assert b'<span class="admin-page-tab-label">Rol mensual</span>' in response.data
    assert b'<span class="admin-page-tab-label">Estados especiales</span>' in response.data
    assert b'class="admin-header"' not in response.data
    assert b'id="monthly-role-section" class="admin-role-page-section admin-monthly-role-section"' in response.data
    assert b'id="special-status-section" class="admin-role-page-section admin-special-status-section" hidden' in response.data
    assert b'data-admin-pagination' in response.data
    assert b'admin_registry_toolbar.js' in response.data
    assert b'id="controller-delete-modal"' in response.data
    assert b'data-delete-kind="estado especial"' in response.data
    tabs_header_start = response.data.index(b'class="admin-module-header admin-routes-page-header admin-role-page-header')
    monthly_section_start = response.data.index(b'id="monthly-role-section"')
    special_section_start = response.data.index(b'id="special-status-section"')
    assert tabs_header_start < monthly_section_start < special_section_start
    assert response.data.count(b'role="tablist" aria-label="Secciones de rol mensual"') == 1
    assert b'<iframe' not in response.data


def test_admin_monthly_role_uses_shared_module_aware_schedule(monkeypatch):
    monkeypatch.setattr("app.web.initialize_schema", lambda: None)
    monkeypatch.setattr(
        "app.web.request_modules",
        lambda: [{"id": 1, "nombre": "Módulo Uno"}, {"id": 2, "nombre": "Módulo Dos"}],
    )
    monkeypatch.setattr("app.web.fetch_catalog_items", lambda catalog: [])
    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {
            "username": "administrador",
            "module_number": None,
            "is_admin": True,
        }

    response = client.get("/administrador/rol-mensual?module_number=2")
    assert response.status_code == 200
    assert b'data-module="2"' in response.data
    assert b'data-admin-module="1"' in response.data
    assert b'data-admin-module="2"' in response.data
    assert b'class="schedule-toolbar card"' in response.data
    assert b'class="schedule-grid"' in response.data
    assert b'class="card schedule-table-card"' in response.data
    role_content_start = response.data.index(b'class="admin-content-grid admin-route-content-grid admin-role-content-grid"')
    monthly_section_start = response.data.index(b'id="monthly-role-section"')
    monthly_toolbar_start = response.data.index(b'class="schedule-toolbar card"', role_content_start)
    assert monthly_section_start < role_content_start < monthly_toolbar_start
    table_card_start = response.data.index(b'<section class="card schedule-table-card">')
    table_card_content = response.data.index(b'<section class="card-schedule">', table_card_start)
    table_container = response.data.index(b'<div class="table-container schedule-table-container">')
    table_card_content_end = response.data.index(b'</section>', table_container)
    assert table_card_start < table_card_content < table_container < table_card_content_end
    assert b'<iframe' not in response.data
    assert b'rol_de_controladores.js' in response.data

    script_response = client.get("/static/rol_de_controladores.js")
    assert script_response.status_code == 200
    assert b"addEventListener('admin-module-changed'" in script_response.data
    assert b'/api/modulos/${moduleNumber}/controladores' in script_response.data
    assert b'&module_number=${moduleNumber}' in script_response.data
    assert b'module_number: activeModuleNumber' in script_response.data


def test_admin_embedded_schedule_has_assignment_modal(monkeypatch):
    monkeypatch.setattr("app.web.get_monthly_role_activation", lambda *args: False)
    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {
            "username": "administrador",
            "module_number": None,
            "is_admin": True,
        }

    response = client.get("/modulo/1/rol?admin_embed=1")

    assert response.status_code == 200
    assert b'id="open-schedule-assignment"' in response.data
    assert b'Crear asignaci\xc3\xb3n' in response.data
    assert b'imagenes/icons/mas.png' in response.data
    assert b'id="schedule-assignment-modal" class="schedule-assignment-modal" hidden' in response.data
    assert b'id="schedule-grid" class="schedule-grid"' in response.data
    assert b'class="schedule-table-heading"' in response.data
    assert b'card-heading-controlador' not in response.data

    regular_response = client.get("/modulo/1/rol")
    assert regular_response.status_code == 200
    assert b'id="schedule-assignment-modal"' not in regular_response.data
    assert b'id="open-schedule-assignment"' not in regular_response.data
    assert b'id="schedule-grid" class="schedule-grid"' in regular_response.data


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
        ("TR", "trabajo"),
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

    assert [catalog for catalog, _ in saved] == ["estados_especiales"] * 5
    assert [payload["categoria"] for _, payload in saved] == [
        "trabajo",
        "descanso",
        "falta",
        "vacaciones",
        "incapacidad",
    ]
    assert saved[1][1]["codigo"] == "D/F"


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


def test_admin_modules_page_has_creation_modal_without_module_filter(monkeypatch):
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
    assert b'data-admin-type-filter' not in response.data
    assert b'data-module-modal-cancel' in response.data
    assert b'data-module-save-button' in response.data
    assert b'<span>Nombre</span>\n                  <span>Direcci\xc3\xb3n</span>\n                  <span>Latitud</span>\n                  <span>Longitud</span>' in response.data
    assert b'<strong class="admin-module-name">M\xc3\xb3dulo Centro</strong>' in response.data
    assert b'data-admin-pagination' in response.data
    assert b'<span class="admin-module-address">Calle principal</span>' in response.data
    assert b'<span class="admin-module-coordinate">19.4</span>' in response.data
    assert b'<span class="admin-module-coordinate">-99.1</span>' in response.data
    assert b'id="controller-delete-modal"' in response.data
    assert b'data-delete-kind="m\xc3\xb3dulo"' in response.data
    assert response.data.count(b'class="admin-controller-action-icon"') == 2
    assert b'aria-label="Editar m\xc3\xb3dulo M\xc3\xb3dulo Centro"' in response.data
    assert b'aria-label="Eliminar m\xc3\xb3dulo M\xc3\xb3dulo Centro"' in response.data


def test_admin_turnos_page_uses_delete_confirmation_modal(monkeypatch):
    monkeypatch.setattr("app.web.initialize_schema", lambda: None)
    monkeypatch.setattr("app.web.renumber_turnos_by_start", lambda: None)
    monkeypatch.setattr("app.web.request_modules", lambda: [{"id": 1, "nombre": "Módulo Uno"}])
    monkeypatch.setattr(
        "app.web.fetch_catalog_items",
        lambda catalog: [
            {
                "id": 42,
                "numero": 2,
                "hora_inicio": "07:00",
                "hora_fin": "15:00",
                "alcance": "general",
                "activo": True,
            }
        ],
    )
    monkeypatch.setattr("app.web.fetch_turno_modules_map", lambda turno_ids: {})
    monkeypatch.setattr("app.web.fetch_turno_module_statuses_map", lambda turno_ids: {})
    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {
            "username": "administrador",
            "module_number": None,
            "is_admin": True,
        }

    response = client.get("/administrador/turnos")

    assert response.status_code == 200
    assert b'id="controller-delete-modal"' in response.data
    assert b'data-delete-kind="turno" data-delete-name="2"' in response.data
    assert b'admin_delete_confirmation.js' in response.data
    assert b'data-route-filter-toggle' in response.data
    assert b'data-route-filter-option="turnoType" value="general"' in response.data
    assert b'data-route-filter-option="turnoType" value="especifico"' in response.data
    assert b'data-filter-turno-type="general"' in response.data
    assert b'data-admin-pagination' in response.data
    assert b'id="turno-page-count"' in response.data
    assert b'data-admin-visible-count-target="turno-page-count"' in response.data
    filter_script = client.get("/static/admin_registry_toolbar.js")
    assert b"selectedRouteFilters.turnoType.includes(row.dataset.filterTurnoType)" in filter_script.data
    assert b"visibleCount.textContent = String(matchingRowCount)" in filter_script.data


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
