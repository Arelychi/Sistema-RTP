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


def test_delete_turnos_by_ids_validates_selection_and_commits(monkeypatch):
    import app.db as db

    class FakeCursor:
        def __init__(self, rows):
            self.rows = rows
            self.operations = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def execute(self, query, params):
            self.operations.append((query, params))

        def fetchall(self):
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

    connection = FakeConnection([(42,), (43,)])
    monkeypatch.setattr("app.db.get_connection", lambda: connection)

    deleted = db.delete_turnos_by_ids([42, 43, 42])

    assert deleted == [42, 43]
    assert connection.committed
    assert len(connection.fake_cursor.operations) == 2
    assert "FOR UPDATE" in connection.fake_cursor.operations[0][0]
    assert connection.fake_cursor.operations[0][1] == ([42, 43],)
    assert connection.fake_cursor.operations[1][1] == ([42, 43],)

    invalid_connection = FakeConnection([(42,)])
    monkeypatch.setattr("app.db.get_connection", lambda: invalid_connection)
    try:
        db.delete_turnos_by_ids([42, 43])
    except ValueError as error:
        assert "ya no está disponible" in str(error)
    else:
        raise AssertionError("Expected missing selected turns to be rejected")
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
    monkeypatch.setattr("app.web.fetch_monthly_controller_workday_counts", lambda month, year: {})
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
    dashboard_styles = client.get("/static/admin/dashboard.css")
    assert dashboard_styles.status_code == 200
    assert b"body.admin-page-body .admin-controller-toolbar .controller-filter-field {" in dashboard_styles.data
    assert b"height: 44px;" in dashboard_styles.data
    assert b"background-image: url(\"../imagenes/icons/busqueda.png\")" in dashboard_styles.data
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
    delete_script = client.get("/static/admin_delete_confirmation.js")
    assert delete_script.status_code == 200
    assert b"admin-operation-start" in delete_script.data
    assert b"Eliminando ${form.dataset.deleteKind" in delete_script.data
    save_feedback_script = client.get("/static/admin_save_feedback.js")
    assert save_feedback_script.status_code == 200
    assert b"admin-operation-start" in save_feedback_script.data
    assert b"window.requestAnimationFrame(function () {" in save_feedback_script.data
    assert b"scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' })" in save_feedback_script.data
    assert b"[data-route-page-next], [data-admin-page-next]" in save_feedback_script.data


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
            },
            {
                "id": 18,
                "nombre": "Luis Sin Asignación",
                "credencial": "67890",
                "sexo": "Masculino",
                "mod1": 1,
                "active": True,
            },
        ],
    )
    monkeypatch.setattr(
        "app.web.fetch_monthly_controller_workday_counts",
        lambda month, year: {("12345", 1): 20},
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
    assert b'<table class="admin-controller-table admin-controller-selectable admin-route-table" aria-label="Controladores del M\xc3\xb3dulo Uno">' in response.data
    assert b'<th>Nombre del controlador</th>' in response.data
    assert b'aria-label="Editar Ana Prueba"' in response.data
    assert b'aria-label="Eliminar Ana Prueba"' in response.data
    assert b'data-controller-delete-form' in response.data
    assert b'data-delete-confirm-form' in response.data
    assert b'data-delete-kind="controlador"' in response.data
    assert b'class="admin-controller-table admin-controller-selectable admin-route-table"' in response.data
    assert b'data-controller-select-all' in response.data
    assert b'data-controller-bulk-select value="17"' in response.data
    assert b'data-controller-monthly-days="20"' in response.data
    assert b'data-controller-monthly-assignment="Asignado"' in response.data
    assert b'data-controller-monthly-assignment="No asignado"' in response.data
    assert response.data.count(b'class="admin-route-shared-module-badge admin-controller-monthly-assignment-badge"') == 1
    assert b'data-controller-assignment-badge tabindex="0"' in response.data
    assert b'data-controller-filter-option="assignment" value="Asignado"' in response.data
    assert b'data-controller-filter-option="assignment" value="No asignado"' in response.data
    assert b'data-controller-month-name="' in response.data
    assert b'data-controller-assignment-tooltip' in response.data
    assert b"El controlador tiene ${assignedDays} ${dayLabel} (trabajo, incluido M\xc3\xb3dulo (MD))" in response.data
    assert b"selected.assignment.includes(row.dataset.controllerMonthlyAssignment)" in response.data
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
    assert b'class="admin-secondary-button" type="button" data-user-modal-close>Cancelar</button>' in response.data


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
    assert b"body.admin-users-page .admin-user-select-column {\n  display: table-cell;" in user_styles.data
    assert b"body.admin-users-page .admin-users-toolbar > .admin-create-controller-button {\n  height: 42px;" in user_styles.data
    assert b"body.admin-users-page .is-users-selection-mode .admin-controller-status .route-switch," in user_styles.data
    assert b"body.admin-users-page .is-users-selection-mode .admin-controller-status .route-switch input:disabled + .route-status-badge" in user_styles.data
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
    import json
    import re

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
                "shared_modules": [
                    {"id": 1, "nombre": "Módulo Uno"},
                    {"id": 2, "nombre": "Módulo Dos"},
                ],
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
    assert response.data.count(b'class="admin-secondary-button" type="button" data-route-modal-close>Cancelar</button>') == 2
    assert b'imagenes/icons/vinculado.png' in response.data
    assert b'id="route-link-modal"' in response.data
    assert b'data-route-link-source="1"' in response.data
    assert b'data-route-link-source="2" data-route-link-module-name="M\xc3\xb3dulo Dos" hidden' in response.data
    assert b'data-admin-save-loader' in response.data
    assert b"Vinculando rutas..." in response.data
    assert b"adminPendingRouteLinkFeedback" in response.data
    assert b"routeIds: Array.from(selectedRoutes.keys())" in response.data
    assert b'data-route-id="3" data-route-module="1" data-route-name="Centro" data-route-shared-modules=' in response.data
    assert b'data-route-original="true"' in response.data
    serialized_shared_modules = re.findall(
        r"data-route-shared-modules='([^']*)'",
        response.get_data(as_text=True),
    )
    assert any(
        any(module["id"] == 2 and module["nombre"] == "Módulo Dos" for module in json.loads(value))
        for value in serialized_shared_modules
    )
    assert b'id="route-sharing-tooltip"' in response.data
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
                "route_days_by_module": [
                    {
                        "module_number": 2,
                        "route": "Ruta Centro",
                        "days": 6,
                        "controllers": 1,
                    }
                ],
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
                "daily_summary": [
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
                    },
                    {
                        "day": 2,
                        "assignments": 1,
                        "worked": 0,
                        "rest": 1,
                        "absence": 0,
                        "incapacity": 0,
                        "permission": 0,
                        "vacation": 0,
                        "holiday": 0,
                        "unprogrammed": 0,
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
    assert balance_card.count('class="analysis-status-row"') == 7
    assert all(category in balance_card for category in ("Trabajo", "Vacaciones", "Descanso", "Falta", "Incapacidad", "Permiso", "Festivo"))
    assert b"An\xc3\xa1lisis | Administrador" in response.data
    assert b"Controladores" in response.data
    assert b">Rutas</a>" in response.data
    assert b"Controladores registrados" in response.data
    assert b"17" in response.data
    assert b"Ruta Centro" in response.data
    assert b"Luis Prueba" in response.data
    assert b"M\xc3\xb3dulo 2" in response.data
    assert b'class="analysis-calendar-day is-work"' in response.data
    assert b'class="analysis-calendar-day is-rest-change"' in response.data
    assert b"C/D \xc2\xb7 Cambio de descanso" in response.data
    assert b'id="analysis-summary"' in response.data
    assert b'id="analysis-incidents"' in response.data
    assert b'class="analysis-calendar-day analysis-heatmap-day has-work"' in response.data
    assert b'class="analysis-calendar-day analysis-heatmap-day has-no-work"' in response.data

    routes_response = client.get(
        "/administrador/analisis?month=10&year=2026&tab=rutas"
    )
    assert routes_response.status_code == 200
    assert b'href="/administrador/analisis?month=10&amp;year=2026&amp;tab=rutas" aria-current="page">Rutas</a>' in routes_response.data
    assert b"Detalle por m\xc3\xb3dulo" in routes_response.data
    assert b"Ruta Centro" in routes_response.data
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
    assert b'class="admin-form-grid admin-special-state-fields-grid"' in response.data
    assert b'class="admin-turno-active-field admin-route-field admin-controller-field admin-controller-module-field admin-special-state-active-field"' in response.data
    assert b'class="admin-controller-module-display admin-special-state-active-display"' in response.data
    assert b"specialStateActiveDisplay.classList.toggle('is-inactive', !specialStateActive.checked)" in response.data
    special_states_response = client.get("/administrador/rol-mensual?tab=estados")
    assert special_states_response.status_code == 200
    assert b'data-route-status-action' in special_states_response.data
    assert b'name="estado" value="Activo"' in special_states_response.data
    assert b'Cambiar estado del estado especial' in special_states_response.data
    assert b'aria-label="Editar estado especial D/F"' in special_states_response.data
    assert b'aria-label="Eliminar estado especial D/F"' in special_states_response.data
    assert b'imagenes/icons/lapiz.png' in special_states_response.data
    assert b'imagenes/icons/eliminar.png' in special_states_response.data
    dashboard_styles = client.get("/static/admin/dashboard.css")
    assert dashboard_styles.status_code == 200
    assert b"#special-state-form-modal .admin-special-state-fields-grid {\n  display: grid;" in dashboard_styles.data
    assert b"#special-state-form-modal .admin-controller-module-display.is-inactive" in dashboard_styles.data
    assert b"#special-status-section .admin-route-table td.admin-controller-actions .admin-edit-button," in dashboard_styles.data
    assert b"#special-status-section .admin-route-table td.admin-controller-actions .admin-delete-button:hover {" in dashboard_styles.data
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
    assert b'data-special-state-modal-open' in response.data
    assert b'id="special-state-form-modal"' in response.data
    assert b'class="admin-form-shell"' in response.data
    assert b'data-special-state-modal-close>Cancelar</button>' in response.data
    assert b'data-special-state-submit>Guardar estado</button>' in response.data
    tabs_header_start = response.data.index(b'class="admin-module-header admin-routes-page-header admin-role-page-header')
    monthly_section_start = response.data.index(b'id="monthly-role-section"')
    special_section_start = response.data.index(b'id="special-status-section"')
    assert tabs_header_start < monthly_section_start < special_section_start
    assert response.data.count(b'role="tablist" aria-label="Secciones de rol mensual"') == 1
    assert b'<iframe' not in response.data

    edit_response = client.get("/administrador/rol-mensual?edit_estado_id=3")
    assert edit_response.status_code == 200
    assert b'id="special-state-form-modal" role="dialog" aria-modal="true"' in edit_response.data
    assert b'<h2 id="special-state-form-title">Editar estado especial</h2>' in edit_response.data
    assert b'name="estado_id" value="3"' in edit_response.data


def test_special_state_status_toggle_validates_and_updates(monkeypatch):
    updated = []
    monkeypatch.setattr("app.web.initialize_schema", lambda: None)
    monkeypatch.setattr(
        "app.web.update_catalog_status",
        lambda catalog, item_id, active: updated.append((catalog, item_id, active))
        or {"id": item_id, "activo": active},
    )
    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {
            "username": "administrador",
            "module_number": None,
            "is_admin": True,
        }

    response = client.post(
        "/administrador/estados-especiales/3/estado",
        data={"estado": "Inactivo"},
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/administrador/rol-mensual?tab=estados")
    assert updated == [("estados_especiales", 3, False)]

    response = client.post(
        "/administrador/estados-especiales/3/estado",
        data={"estado": "desconocido"},
    )

    assert response.status_code == 302
    assert updated == [("estados_especiales", 3, False)]


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
    assert b'id="monthly-role-count">0</strong>' in response.data
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
    assert b'monthlyRoleCount.textContent = String(grouped.length)' in script_response.data
    dashboard_styles = client.get("/static/admin/dashboard.css")
    assert b'.admin-embedded-role .month-controls {' in dashboard_styles.data


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
    assert b'id="schedule-assignment-modal" class="admin-controller-modal schedule-assignment-modal" role="dialog" aria-modal="true"' in response.data
    assert b'class="admin-controller-modal-dialog schedule-assignment-dialog"' in response.data
    assert b'class="admin-form-shell schedule-assignment-shell"' in response.data
    assert b'class="schedule-grid-toggle"' not in response.data
    assert b'id="create-record"' not in response.data
    assert b'id="day-edit-actions"' not in response.data
    assert b'id="form-message"' not in response.data
    assert b'class="admin-form-actions schedule-assignment-actions"' in response.data
    assert b'id="schedule-assignment-cancel" class="admin-secondary-button" type="button">Cancelar</button>' in response.data
    assert b'form="schedule-form">Guardar asignaci\xc3\xb3n</button>' in response.data
    assert b'id="cancel-edit-button"' not in response.data
    assert b'id="clear-days" class="admin-secondary-button calendar-clear-button"' in response.data
    assert b'id="schedule-grid" class="schedule-grid"' in response.data
    form_start = response.data.index(b'<form id="schedule-form"')
    form_end = response.data.index(b'</form>', form_start)
    footer_start = response.data.index(b'class="admin-form-actions schedule-assignment-actions"')
    assert form_start < form_end < footer_start
    assert b'class="schedule-table-heading"' not in response.data
    assert b'id="monthly-role-period"' not in response.data
    assert b'class="admin-controller-toolbar admin-role-schedule-toolbar"' in response.data
    assert b'id="schedule-status-filter"' in response.data
    assert b'class="record-count admin-role-schedule-record-count"' not in response.data
    assert b'id="save-all-records"' not in response.data
    assert b'card-heading-controlador' not in response.data

    regular_response = client.get("/modulo/1/rol")
    assert regular_response.status_code == 200
    assert b'id="schedule-assignment-modal"' not in regular_response.data
    assert b'id="open-schedule-assignment"' not in regular_response.data
    assert b'id="cancel-edit-button"' in regular_response.data
    assert b'id="save-all-records"' in regular_response.data
    assert b'class="schedule-grid-toggle"' in regular_response.data
    assert b'id="create-record"' in regular_response.data
    assert b'id="day-edit-actions"' in regular_response.data
    assert b'id="form-message"' in regular_response.data
    assert b'id="clear-days" class="text-button"' in regular_response.data
    assert b'class="schedule-table-heading"' not in regular_response.data
    assert b'id="monthly-role-period"' in regular_response.data
    assert b'id="record-count"' in regular_response.data
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
    assert b"<th>Nombre</th>" in response.data
    assert b"<th>Direcci\xc3\xb3n</th>" in response.data
    assert b"<th>Latitud</th>" in response.data
    assert b"<th>Longitud</th>" in response.data
    assert b'<td class="admin-module-name"><strong>M\xc3\xb3dulo Centro</strong></td>' in response.data
    assert b'data-admin-pagination' in response.data
    assert b'<td class="admin-module-address">Calle principal</td>' in response.data
    assert b'<td class="admin-module-coordinate">19.4</td>' in response.data
    assert b'<td class="admin-module-coordinate">-99.1</td>' in response.data
    assert b'id="controller-delete-modal"' in response.data
    assert b'data-delete-kind="m\xc3\xb3dulo"' in response.data
    assert response.data.count(b'class="admin-controller-action-icon"') == 2
    assert b'aria-label="Editar m\xc3\xb3dulo M\xc3\xb3dulo Centro"' in response.data
    assert b'aria-label="Eliminar m\xc3\xb3dulo M\xc3\xb3dulo Centro"' in response.data
    dashboard_styles = client.get("/static/admin/dashboard.css")
    assert dashboard_styles.status_code == 200
    assert b".admin-modules-page .admin-modules-table td.admin-controller-actions {\n  display: table-cell;\n  width: 1%;" in dashboard_styles.data
    assert b"body.admin-modules-page .admin-modules-table .admin-controller-actions .admin-edit-button:hover .admin-controller-action-icon" in dashboard_styles.data
    assert b"body.admin-modules-page .admin-modules-table .admin-controller-actions .admin-delete-button:hover .admin-controller-action-icon" in dashboard_styles.data


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
        session["_flashes"] = [("success", "Turno registrado correctamente.")]

    response = client.get("/administrador/turnos")

    assert response.status_code == 200
    assert b'<div class="admin-alerts" aria-live="polite" hidden>' in response.data
    assert b'<div class="admin-alert admin-alert-success">Turno registrado correctamente.</div>' in response.data
    assert b'data-admin-toast' in response.data
    assert b'id="controller-delete-modal"' in response.data
    assert b'data-delete-kind="turno" data-delete-name="2"' in response.data
    assert b'admin_delete_confirmation.js' in response.data
    assert b'data-route-filter-toggle' in response.data
    assert b'data-route-filter-option="turnoType" value="general"' in response.data
    assert b'data-route-filter-option="turnoType" value="especifico"' in response.data
    assert b'data-filter-turno-type="general"' in response.data
    assert b'data-admin-ignore-module-filter' in response.data
    assert b'data-turno-select-all' in response.data
    assert b'data-turno-bulk-select value="42"' in response.data
    assert b'data-turno-cancel-selection hidden' in response.data
    assert b'data-turno-bulk-delete-button' in response.data
    assert response.data.count(b'class="admin-secondary-button" type="button" data-turno-modal-close>Cancelar</button>') == 2
    assert b'data-admin-pagination' in response.data
    assert b'id="turno-page-count"' in response.data
    assert b'data-admin-visible-count-target="turno-page-count"' in response.data
    filter_script = client.get("/static/admin_registry_toolbar.js")
    assert b"selectedRouteFilters.turnoType.includes(row.dataset.filterTurnoType)" in filter_script.data
    assert b"visibleCount.textContent = String(matchingRowCount)" in filter_script.data


def test_admin_delete_selected_turnos_renumbers_and_reports_count(monkeypatch):
    deleted = []
    renumbered = []
    monkeypatch.setattr("app.web.initialize_schema", lambda: None)
    monkeypatch.setattr(
        "app.web.delete_turnos_by_ids",
        lambda turno_ids: deleted.append(turno_ids) or [42, 43],
    )
    monkeypatch.setattr("app.web.renumber_turnos_by_start", lambda: renumbered.append(True))
    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {
            "username": "administrador",
            "module_number": None,
            "is_admin": True,
        }

    response = client.post(
        "/administrador/turnos/eliminar-seleccionados",
        data={"turno_ids": ["42", "43", "42"]},
    )

    assert response.status_code == 302
    assert deleted == [[42, 43]]
    assert renumbered == [True]
    with client.session_transaction() as session:
        assert ("success", "2 turno(s) eliminado(s) correctamente.") in session["_flashes"]


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
