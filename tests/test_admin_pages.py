from app.web import app, module_badge_number, prepare_history_entries


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
        (17, "Ana", "12345", "Femenino", 2, True),
        (19, "Luis", "67890", "Masculino", 2, False),
    ]
    connection = FakeConnection(rows)
    monkeypatch.setattr("app.db.get_connection", lambda: connection)

    deleted = db.delete_controllers_from_module([17, 19, 17], 2)

    assert deleted == [
        {"id": 17, "nombre": "Ana", "credencial": "12345", "sexo": "Femenino", "mod1": 2, "active": True},
        {"id": 19, "nombre": "Luis", "credencial": "67890", "sexo": "Masculino", "mod1": 2, "active": False},
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
        (7, "supervisor-prueba", "supervisor@example.test", "123", 1, "usuario", True),
        (8, "admin-prueba", "admin@example.test", "456", None, "admin", False),
    ]
    connection = FakeConnection(rows)
    monkeypatch.setattr("app.db.get_connection", lambda: connection)

    deleted = db.delete_users_by_ids([7, 8, 7])

    assert deleted == [
        {"id": 7, "username": "supervisor-prueba", "correo": "supervisor@example.test", "telefono": "123", "module_number": 1, "tipo_usuario": "usuario", "active": True},
        {"id": 8, "username": "admin-prueba", "correo": "admin@example.test", "telefono": "456", "module_number": None, "tipo_usuario": "admin", "active": False},
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


def test_create_history_entry_supports_multiple_modules(monkeypatch):
    import app.db as db

    class FakeCursor:
        def __init__(self):
            self.operation = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def execute(self, query, params):
            self.operation = (query, params)

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

    db.create_history_entry(
        "administrador",
        [1, 2],
        "Editó turno",
        detail="Módulos: 1, 2",
        before={"Estado": False},
        after={"Estado": True},
    )

    assert connection.committed
    assert "modulos" in connection.fake_cursor.operation[0]
    assert connection.fake_cursor.operation[1][1:3] == (None, [1, 2])
    import json

    assert json.loads(connection.fake_cursor.operation[1][-2]) == {"Estado": False}
    assert json.loads(connection.fake_cursor.operation[1][-1]) == {"Estado": True}


def test_clear_history_for_module_preserves_events_for_other_modules(monkeypatch):
    import app.db as db

    class FakeCursor:
        def __init__(self):
            self.operations = []
            self.rowcount = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def execute(self, query, params):
            self.operations.append((query, params))
            self.rowcount = 2 if query.lstrip().startswith("DELETE") else 3

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

    assert db.clear_history_for_module(2) == 5
    assert connection.committed
    delete_query, delete_params = connection.fake_cursor.operations[0]
    update_query, update_params = connection.fake_cursor.operations[1]
    assert "array_remove(modulos, %s::SMALLINT)" in delete_query
    assert "array_remove(modulos, %s::SMALLINT)" in update_query
    assert "cardinality(array_remove(modulos, %s::SMALLINT)) > 0" in update_query
    assert delete_params == (2, 2, 2)
    assert update_params == (2, 2, 2, 2, 2)


def test_history_comparison_rows_mark_changed_fields():
    entries = prepare_history_entries(
        [{"datos_anteriores": {"Estado": False}, "datos_nuevos": {"Estado": True}}],
        {},
    )

    assert entries[0]["comparison_rows"] == [
        {
            "field": "Estado",
            "before": "Inactivo",
            "after": "Activo",
            "changed": True,
        }
    ]


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
    assert b'data-admin-action-notification' in response.data
    dashboard_styles = client.get("/static/admin/dashboard.css")
    assert dashboard_styles.status_code == 200
    assert b"body.admin-page-body .admin-controller-toolbar .controller-filter-field {" in dashboard_styles.data
    assert b"height: 44px;" in dashboard_styles.data
    assert b"background-image: url(\"../imagenes/icons/busqueda.png\")" in dashboard_styles.data
    assert b"top: 70px;" in dashboard_styles.data
    assert b"right: 24px;" in dashboard_styles.data
    assert b"transform: translateY(-18px);" in dashboard_styles.data
    assert b'.admin-action-notification[data-type="delete"]' in dashboard_styles.data
    assert b'.admin-action-notification[data-type="edit"]' in dashboard_styles.data
    assert b'.admin-action-notification[data-type="error"]' in dashboard_styles.data
    assert b"background: #e7ad22;" in dashboard_styles.data
    assert b"background: #dc3545;" in dashboard_styles.data
    notification_script = client.get("/static/admin_notifications.js")
    assert notification_script.status_code == 200
    assert b"admin-module-changed" in notification_script.data
    assert b"admin-action-notification" in notification_script.data
    assert b"activeSectionName()}: ${moduleName}" in notification_script.data
    assert b"Secci\xc3\xb3n: ${tabLabel(tab)}" not in notification_script.data
    assert b"adminPendingNotification" not in notification_script.data
    assert b"moduleEditButton" not in notification_script.data
    assert b"index * 3100" in notification_script.data
    assert b"notificationType(alertMessage, category)" in notification_script.data
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
    assert b"function formSnapshot(form)" in save_feedback_script.data
    assert b"admin-edit-form-ready" in save_feedback_script.data
    assert b"event.defaultPrevented" in save_feedback_script.data


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
    assert b'data-admin-status-row-key="controller-' in response.data
    assert b'data-admin-status-form' in response.data
    assert b'this.form.requestSubmit();' in response.data
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
    status_feedback_script = client.get("/static/admin_save_feedback.js")
    assert b"data-admin-status-form" in status_feedback_script.data
    assert b"Cambiando estatus" in status_feedback_script.data
    assert b"statusRow.dataset.adminStatusRowKey" in status_feedback_script.data
    assert b"scrollRowIntoView(statusRow, changedStatus.moduleId)" in status_feedback_script.data


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
    assert b'type="email" name="correo"' in response.data
    assert b'pattern="[^@\\s]+@[^@\\s]+\\.[^@\\s]+"' in response.data
    assert b'type="tel" name="telefono"' in response.data
    assert b'inputmode="numeric" pattern="[0-9]{10}" maxlength="10"' in response.data
    assert b"this.value.replace(/[^0-9]/g, '').slice(0, 10)" in response.data


def test_admin_user_contact_fields_reject_invalid_email_and_phone(monkeypatch):
    monkeypatch.setattr(
        "app.web.initialize_schema",
        lambda: (_ for _ in ()).throw(AssertionError("No debe guardar datos inválidos")),
    )
    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {
            "username": "administrador",
            "module_number": None,
            "is_admin": True,
        }

    invalid_contacts = [
        {"correo": "no-es-correo", "telefono": "1234567890"},
        {"correo": "usuario@example.com", "telefono": "12345abc90"},
        {"correo": "usuario@example.com", "telefono": "123456789"},
    ]
    for contacts in invalid_contacts:
        response = client.post(
            "/administrador/usuarios",
            data={
                "user_id": "7",
                "username": "usuario-prueba",
                "tipo_usuario": "admin",
                **contacts,
            },
        )
        assert response.status_code == 302
        assert response.location.endswith("/administrador/usuarios?edit_user_id=7")


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
    assert (
        b'aria-label="Seleccionar todos los usuarios que coinciden con los filtros"'
        in response.data
    )
    assert "row?.dataset.adminFilterMatch !== 'false'" in response.get_data(as_text=True)
    assert (
        "checkbox.closest('[data-admin-filter-row]')?.dataset.adminFilterMatch !== 'false'"
        in response.get_data(as_text=True)
    )
    page_html = response.get_data(as_text=True)
    assert "attributeFilter: ['hidden', 'data-admin-filter-match']" in page_html
    assert "const selectionObserver = new MutationObserver(updateBulkSelection);" in page_html
    assert "rows.forEach((row) => selectionObserver.observe(row, {" in page_html
    assert "new MutationObserver(updateBulkSelection).observe(group, {" not in page_html
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
    monkeypatch.setattr("app.web.record_history", lambda *args, **kwargs: histories.append((args, kwargs)))
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
    assert histories[0][0][1:] == (
        "Eliminó usuario supervisor-prueba (de Usuarios)",
        1,
        "eliminacion",
        "Tipo: Supervisor",
    )
    assert histories[1][0][1:] == (
        "Eliminó usuario admin-prueba (de Usuarios)",
        None,
        "eliminacion",
        "Tipo: Administrador",
    )
    with client.session_transaction() as session:
        assert session["_flashes"][-1][1] == "2 usuario(s) eliminado(s) correctamente."


def test_admin_delete_user_history_uses_username(monkeypatch):
    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def execute(self, query, params):
            assert "SELECT username, correo, telefono, module_number" in query
            assert params == (7,)

        def fetchone(self):
            return ("usuario-prueba", "usuario@example.test", "1234567890", 1, "usuario", True)

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def cursor(self):
            return FakeCursor()

    histories = []
    monkeypatch.setattr("app.web.initialize_schema", lambda: None)
    monkeypatch.setattr("app.web.get_connection", lambda: FakeConnection())
    monkeypatch.setattr("app.web.delete_user", lambda user_id: user_id == 7)
    monkeypatch.setattr("app.web.record_history", lambda *args, **kwargs: histories.append((args, kwargs)))
    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {
            "username": "administrador",
            "module_number": None,
            "is_admin": True,
        }

    response = client.post("/administrador/usuarios/7/eliminar")

    assert response.status_code == 302
    assert histories[0][0][1] == "Eliminó usuario usuario-prueba (de Usuarios)"
    assert histories[0][0][4] == "ID del usuario: 7"


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
    assert response.data.count(b'data-admin-letters-only') == 2
    assert response.data.count(b'pattern="[\\p{L}]+(?:\\s+[\\p{L}]+)*"') == 2
    assert b"this.value.replace(/[^\\p{L}\\s]/gu, '')" in response.data
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
    dashboard_styles = client.get("/static/admin/dashboard.css")
    assert (
        b".admin-controller-delete-modal .admin-delete-button::before"
        in dashboard_styles.data
    )
    assert b"filter: brightness(0) invert(1);" in dashboard_styles.data
    assert b'data-delete-kind="tipo de ruta"' in response.data
    assert b'data-delete-kind="servicio"' in response.data
    assert b'data-delete-kind="ruta"' in response.data
    assert b'data-route-bulk-select value="3"' in response.data
    assert b'data-route-select-all aria-label="Seleccionar todas las rutas visibles"' in response.data
    assert b'admin-route-table admin-route-selectable' in response.data
    assert b'data-route-module-count' in response.data
    assert b'admin-route-module-table-picker' in response.data
    assert b'id="route-module-menu"' in response.data
    assert b'data-route-available-count' in response.data
    assert b'id="route-selected-modules" aria-live="polite"' in response.data
    assert b'data-route-selected-count' in response.data


def test_admin_route_catalog_names_reject_digits(monkeypatch):
    monkeypatch.setattr(
        "app.web.initialize_schema",
        lambda: (_ for _ in ()).throw(AssertionError("No debe guardar nombres con números")),
    )
    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {
            "username": "administrador",
            "module_number": None,
            "is_admin": True,
        }

    invalid_catalog_names = [
        ({"catalog": "servicio", "nombre": "Servicio 2"}, "servicios"),
        ({"descripcion": "Tipo 3"}, "tipos"),
    ]
    for form_data, catalog_tab in invalid_catalog_names:
        response = client.post("/administrador/tipos-rutas", data=form_data)
        assert response.status_code == 302
        assert response.location.endswith(f"/administrador/rutas?catalog_tab={catalog_tab}")


def test_module_badge_number_prefers_number_in_display_name():
    assert module_badge_number(10, "Modulo 9") == "9"
    assert module_badge_number(9, "Módulo 7") == "7"
    assert module_badge_number(10, "Terminal Norte") == "10"


def test_shared_route_badge_uses_display_module_number_without_changing_id(monkeypatch):
    monkeypatch.setattr("app.web.initialize_schema", lambda: None)
    monkeypatch.setattr(
        "app.web.request_modules",
        lambda: [
            {"id": 1, "nombre": "Módulo 1"},
            {"id": 10, "nombre": "Modulo 9"},
        ],
    )
    monkeypatch.setattr(
        "app.web.fetch_routes",
        lambda module_number: (
            [
                {
                    "id": 20,
                    "nomenclatura": "B",
                    "ruta": "Ruta compartida",
                    "origen": "Origen",
                    "destino": "Destino",
                    "servicio": "Servicio",
                    "estado": "Activo",
                    "mod1": 10,
                    "is_external": True,
                    "tipos_descripcion": "Tipo",
                    "shared_modules": [],
                }
            ]
            if module_number == 1
            else []
        ),
    )
    monkeypatch.setattr("app.web.fetch_catalog_items", lambda catalog: [])
    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {
            "username": "administrador",
            "module_number": None,
            "is_admin": True,
        }

    response = client.get("/administrador/rutas")

    assert response.status_code == 200
    assert (
        b'data-route-source-module="9" aria-label="Ruta compartida desde el m\xc3\xb3dulo 9">M9</span>'
        in response.data
    )
    assert b'data-route-module="10"' in response.data
    assert b'class="admin-route-module-option" data-module-id="1"' in response.data
    assert b'admin-route-module-number' not in response.data
    assert b'class="admin-form-actions admin-route-form-actions"' in response.data
    assert b"routeRows.filter((row) => row.dataset.adminFilterMatch !== 'false').length" in response.data
    assert b'data-route-individual-actions' in response.data
    assert b'data-route-status-action' in response.data
    assert b'data-admin-status-row-key="route-' in response.data
    assert b'data-admin-status-form' in response.data
    assert b'this.form.requestSubmit();' in response.data
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
    dashboard_styles = client.get("/static/admin/dashboard.css")
    assert b"#route-form-modal .admin-route-module-table-picker .admin-route-module-status" in dashboard_styles.data
    assert b".admin-route-modal .admin-route-turno-like-picker .admin-route-module-status" not in dashboard_styles.data


def test_admin_route_edit_reports_success_after_recording_history(monkeypatch):
    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def execute(self, query, params):
            assert "SELECT ruta, origen, destino, servicio, estado, mod1, tipos" in query
            assert params == (42,)

        def fetchone(self):
            return ("Ruta Norte", "Centro", "Norte", "Ordinario", "Activo", 1, 3)

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def cursor(self):
            return FakeCursor()

    histories = []
    monkeypatch.setattr("app.web.initialize_schema", lambda: None)
    monkeypatch.setattr("app.web.fetch_shared_modules", lambda route_id: [2])
    monkeypatch.setattr("app.web.fetch_shared_module_statuses", lambda route_id: {2: "Activo"})
    monkeypatch.setattr("app.web.get_connection", lambda: FakeConnection())
    monkeypatch.setattr(
        "app.web.update_admin_route",
        lambda route_id, route: {
            "id": route_id,
            "ruta": route["ruta"],
            "origen": route["origen"],
            "destino": route["destino"],
            "servicio": route["servicio"],
            "estado": "Activo",
            "mod1": route["mod1"],
            "tipos": route["tipos"],
        },
    )
    monkeypatch.setattr(
        "app.web.link_route_to_module",
        lambda route_id, module_number, estado=None: {"modulo_id": module_number},
    )
    monkeypatch.setattr(
        "app.web.record_history",
        lambda *args, **kwargs: histories.append((args, kwargs)),
    )
    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {"username": "administrador", "is_admin": True}

    response = client.post(
        "/administrador/rutas",
        data={
            "route_id": "42",
            "ruta": "Ruta Norte Actualizada",
            "origen": "Centro",
            "destino": "Norte",
            "servicio": "Ordinario",
            "tipos": "3",
            "mod1": "1",
            "shared_modules": ["2"],
            "module_statuses": ["2:Activo"],
        },
    )

    assert response.status_code == 302
    with client.session_transaction() as session:
        assert session["_flashes"][-1][1] == "Ruta actualizada correctamente."
    assert histories[0][0][2] == [1, 2]


def test_admin_route_delete_history_uses_route_name_not_id(monkeypatch):
    history = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def execute(self, query, params):
            assert "SELECT ruta, origen, destino, servicio, estado, mod1, tipos" in query
            assert params == (42,)

        def fetchone(self):
            return ("Ruta Norte", "Centro", "Norte", "Ordinario", "Activo", 1, 3)

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr("app.web.initialize_schema", lambda: None)
    monkeypatch.setattr("app.web.get_connection", lambda: FakeConnection())
    monkeypatch.setattr("app.web.fetch_shared_modules", lambda route_id: [2])
    monkeypatch.setattr("app.web.delete_route", lambda route_id: True)
    monkeypatch.setattr(
        "app.web.record_history",
        lambda *args, **kwargs: history.append((args, kwargs)),
    )
    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {"username": "administrador", "is_admin": True}

    response = client.post("/administrador/rutas/42/eliminar")

    assert response.status_code == 302
    assert history[0][0][1] == "Eliminó ruta Ruta Norte (de Rutas)"
    assert history[0][0][3] == "eliminacion"
    assert history[0][0][4] == "Ruta: Ruta Norte"
    assert "42" not in history[0][0][1]


def test_admin_unlink_shared_route_records_desvinculacion_history(monkeypatch):
    history = []
    unlinked = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def execute(self, query, params):
            assert "SELECT ruta, origen, destino, servicio, estado, mod1, tipos" in query
            assert params == (42,)

        def fetchone(self):
            return ("Ruta Norte", "Centro", "Norte", "Ordinario", "Activo", 1, 3)

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr("app.web.initialize_schema", lambda: None)
    monkeypatch.setattr("app.web.get_connection", lambda: FakeConnection())
    monkeypatch.setattr(
        "app.web.fetch_shared_module_statuses",
        lambda route_id: {2: "Activo", 3: "Inactivo"},
    )
    monkeypatch.setattr(
        "app.web.unlink_route_from_module",
        lambda route_id, module_number: unlinked.append((route_id, module_number)) or True,
    )
    monkeypatch.setattr(
        "app.web.record_history",
        lambda *args, **kwargs: history.append((args, kwargs)),
    )
    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {"username": "administrador", "is_admin": True}

    response = client.post("/administrador/rutas/42/modulo/2/desvincular")

    assert response.status_code == 302
    assert unlinked == [(42, 2)]
    assert history[0][0][2:4] == (2, "desvinculacion")
    assert history[0][1]["before"]["Ruta"] == "Ruta Norte"


def test_admin_route_creation_history_separates_origin_and_linked_modules(monkeypatch):
    histories = []
    linked_modules = []
    monkeypatch.setattr("app.web.initialize_schema", lambda: None)
    monkeypatch.setattr(
        "app.web.create_route",
        lambda route, module_number: {
            "id": 42,
            **route,
            "mod1": module_number,
            "estado": "Activo",
        },
    )
    monkeypatch.setattr(
        "app.web.link_route_to_module",
        lambda route_id, module_number, estado=None: (
            linked_modules.append((route_id, module_number, estado))
            or {"modulo_id": module_number}
        ),
    )
    monkeypatch.setattr(
        "app.web.record_history",
        lambda *args, **kwargs: histories.append((args, kwargs)),
    )
    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {"username": "administrador", "is_admin": True}

    response = client.post(
        "/administrador/rutas",
        data={
            "ruta": "Ruta Norte",
            "origen": "Centro",
            "destino": "Norte",
            "servicio": "Ordinario",
            "tipos": "3",
            "mod1": "1",
            "shared_modules": ["2", "3"],
            "module_statuses": ["2:Activo", "3:Inactivo"],
        },
    )

    assert response.status_code == 302
    assert len(histories) == 2
    assert histories[0][0][2:4] == (1, "registro")
    assert histories[1][0][2:4] == ([2, 3], "vinculacion")
    assert linked_modules == [(42, 2, "Activo"), (42, 3, "Inactivo")]


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
    monkeypatch.setattr("app.web.record_history", lambda *args, **kwargs: histories.append((args, kwargs)))
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


def test_normal_role_code_conflict_dialog_highlights_assignment_details():
    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {
            "username": "usuario-prueba",
            "module_number": 2,
            "is_admin": False,
            "tipo_usuario": "usuario",
        }

    response = client.get("/modulo/2/rol")

    assert response.status_code == 200
    for field in (
        b'id="code-conflict-details"',
        b'data-conflict-code',
        b'data-conflict-controller',
        b'data-conflict-credential',
        b'data-conflict-day',
        b'data-conflict-existing-controller',
        b'value="transfer" checked',
        b'<strong>Mantener c\xc3\xb3digo duplicado</strong>',
        b'<span class="code-conflict-option-badge is-duplicate">Duplicado</span>',
        b'<strong>Reasignar titularidad</strong>',
        b'<span class="code-conflict-option-badge is-transfer">Transferir</span>',
    ):
        assert field in response.data
    assert b'z-index: 1100' in client.get("/static/rol_de_controladores.css").data


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
    assert b'data-admin-status-row-key="special-state-' in special_states_response.data
    assert b'data-admin-status-form' in special_states_response.data
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
    assert b'id="code-conflict-details"' in response.data
    assert b'data-conflict-code' in response.data
    assert b'data-conflict-controller' in response.data
    assert b'data-conflict-day' in response.data
    assert b'value="transfer" checked' in response.data
    assert b'<strong>Mantener c\xc3\xb3digo duplicado</strong>' in response.data
    assert b'<span class="code-conflict-option-badge is-duplicate">Duplicado</span>' in response.data
    assert b'<strong>Reasignar titularidad</strong>' in response.data
    assert b'<span class="code-conflict-option-badge is-transfer">Transferir</span>' in response.data
    assert b'data-admin-pagination' in response.data
    assert b'admin_registry_toolbar.js' in response.data
    assert b'id="controller-delete-modal"' in response.data
    assert b'data-delete-kind="estado especial"' in response.data
    assert b'data-special-state-modal-open' in response.data
    assert b'id="special-state-form-modal"' in response.data
    assert b'data-admin-edit-guard="false"' in response.data
    assert b'data-special-state-submit data-admin-edit-save ' in response.data
    assert b'data-special-state-submit data-admin-edit-save hidden' not in response.data
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
    assert b'data-admin-edit-guard="true"' in edit_response.data
    assert b'data-special-state-submit data-admin-edit-save hidden>Actualizar estado</button>' in edit_response.data


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
    schedule_script = client.get("/static/rol_de_controladores.js")
    assert b"classList.add('schedule-assignment-modal-open')" in schedule_script.data
    assert b"classList.remove('schedule-assignment-modal-open')" in schedule_script.data
    assert b"classList.add('schedule-assignment-open')" not in schedule_script.data
    assert b'saveAssignmentButton.hidden = Boolean(scheduleAssignmentModal && state.selectedRecord && !state.editingDays.size)' in schedule_script.data
    assert b'(scheduleAssignmentModal || !state.editingDays.size) ? \'Guardar asignaci\xc3\xb3n\' : \'Guardar edici\xc3\xb3n\'' in schedule_script.data
    assert b'if (scheduleAssignmentModal && state.selectedRecord && !state.editingDays.size)' in schedule_script.data
    schedule_styles = client.get("/static/rol_de_controladores.css")
    assert b"body.schedule-assignment-modal-open { overflow: hidden; }" in schedule_styles.data
    assert b'.schedule-assignment-actions .primary-button[hidden] { display: none !important; }' in schedule_styles.data
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


def test_manage_module_data_clears_scoped_records_and_audits_both_actions(monkeypatch):
    import json
    import app.db as db

    class FakeCursor:
        def __init__(self):
            self.rows = []
            self.one = None
            self.rowcount = 0
            self.operations = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def execute(self, query, params=None):
            normalized = " ".join(query.lower().split())
            self.operations.append((query, params))
            self.rows = []
            self.one = None
            self.rowcount = 0
            if normalized.startswith("select id, nombre, direccion, latitud, longitud from catalogos.modulos"):
                self.rows = [
                    (2, "Módulo Centro", "Calle Uno", 19.4, -99.1),
                    (3, "Módulo Norte", "Calle Dos", 19.5, -99.2),
                ]
            elif normalized.startswith("select r.id, r.ruta, r.origen"):
                self.rows = [(51, "R1", "Centro", "Norte", "Servicio", 3, 2)]
            elif normalized.startswith("select id, ruta, origen, destino, servicio, estado, nomenclatura from catalogos.rutas"):
                self.rows = []
            elif normalized.startswith("select t.id, t.numero"):
                self.rows = [
                    (71, 8, "07:00", "15:00", "general", False),
                    (72, 9, "15:00", "23:00", "especifico", True),
                ]
            elif normalized.startswith("delete from catalogos.turno_modulo"):
                self.rows = [(71,), (72,)]
            elif normalized.startswith("delete from catalogos.turnos as t"):
                self.rows = [(9, "15:00", "23:00")]
            elif normalized.startswith("delete from seguridad.usuarios"):
                self.rows = [("user2", "usuario")]
            elif normalized.startswith("delete from catalogos.controladores"):
                self.rows = [("Ana", "123")]
            elif normalized.startswith("delete from schedule_records"):
                self.rows = [("Ana", "123", 9, 2025)]
            elif normalized.startswith("delete from catalogos.rol_mensual_periodos"):
                self.rows = [(9, 2025, False)]
            elif normalized.startswith("delete from catalogos.modulo_ruta"):
                self.rows = [(51,)]
            elif normalized.startswith("delete from analisis."):
                self.rowcount = 2
            elif normalized.startswith("select to_regclass"):
                self.one = (None,)
            elif normalized.startswith("delete from catalogos.modulos"):
                self.rowcount = 1
            elif normalized.startswith("insert into seguridad.historial_rol_mensual"):
                self.rowcount = 1

        def fetchall(self):
            return self.rows

        def fetchone(self):
            return self.one

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

    connections = []

    def get_connection():
        connection = FakeConnection()
        connections.append(connection)
        return connection

    monkeypatch.setattr("app.db.get_connection", get_connection)

    clear_result = db.manage_module_data(2, "clear", "administrador")
    delete_result = db.manage_module_data(2, "delete", "administrador")

    assert clear_result["status"] == "cleared"
    assert delete_result["status"] == "deleted"
    assert all(connection.committed for connection in connections)

    clear_operations = connections[0].fake_cursor.operations
    clear_queries = [query.lower() for query, _ in clear_operations]
    assert any("delete from seguridad.usuarios" in query for query in clear_queries)
    assert any("delete from schedule_records" in query for query in clear_queries)
    assert any("insert into catalogos.turno_modulo" in query for query in clear_queries)
    assert not any("delete from catalogos.modulos" in query for query in clear_queries)
    clear_history = next(
        params
        for query, params in clear_operations
        if query.lower().startswith("insert into seguridad.historial_rol_mensual")
    )
    clear_snapshot = json.loads(clear_history[-2])
    assert clear_history[2] == [2]
    assert clear_snapshot["Asignaciones mensuales eliminadas por período"] == {
        "2025-09": 1
    }
    assert clear_snapshot["Cuentas eliminadas"] == [
        {"Usuario": "user2", "Tipo": "usuario"}
    ]
    assert clear_snapshot["Latitud"] == 19.4
    assert clear_snapshot["Turnos específicos desvinculados"] == [
        {"Turno": 9, "Inicio": "15:00", "Fin": "23:00"}
    ]

    delete_operations = connections[1].fake_cursor.operations
    delete_queries = [query.lower() for query, _ in delete_operations]
    assert any("delete from catalogos.modulos" in query for query in delete_queries)
    delete_history = next(
        params
        for query, params in delete_operations
        if query.lower().startswith("insert into seguridad.historial_rol_mensual")
    )
    assert delete_history[1] is None
    assert delete_history[2] == [3]


def test_manage_module_data_prevents_deleting_the_last_module(monkeypatch):
    import app.db as db

    class FakeCursor:
        def __init__(self):
            self.operations = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def execute(self, query, params=None):
            self.operations.append((query, params))

        def fetchall(self):
            return [(1, "Módulo único", "Calle", 19.4, -99.1)]

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

    result = db.manage_module_data(1, "delete", "administrador")

    assert result == {"status": "last_module"}
    assert not connection.committed
    assert len(connection.fake_cursor.operations) == 1


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
    assert b'admin-edit-form-ready' in response.data
    assert b'admin-edit-form-reset' in response.data
    assert b'id="module-action-modal"' in response.data
    assert b'name="admin_password"' in response.data
    assert b'data-module-action-select="clear"' in response.data
    assert b'data-module-action-select="delete"' in response.data
    assert b'name="action" value="clear" data-module-action-value' in response.data
    assert b'data-module-action-submit' in response.data
    assert b'data-module-action-password-toggle' in response.data
    assert b'data-module-action-password-field' in response.data
    assert b'id="module-action-password-error" role="alert" hidden' in response.data
    assert (
        "Ingresa la contraseña del administrador para ejecutar la acción.".encode()
        in response.data
    )
    assert b"moduleActionPassword.addEventListener('invalid'" in response.data
    assert b"moduleActionPasswordField.classList.add('is-shaking')" in response.data
    assert b"<th>Nombre</th>" in response.data
    assert b"<th>Direcci\xc3\xb3n</th>" in response.data
    assert b"<th>Latitud</th>" in response.data
    assert b"<th>Longitud</th>" in response.data
    assert b'<td class="admin-module-name"><strong>M\xc3\xb3dulo Centro</strong></td>' in response.data
    assert b'data-admin-pagination' in response.data
    assert b'<td class="admin-module-address">Calle principal</td>' in response.data
    assert b'<td class="admin-module-coordinate">19.4</td>' in response.data
    assert b'<td class="admin-module-coordinate">-99.1</td>' in response.data
    assert response.data.count(b'class="admin-controller-action-icon"') == 2
    assert b'aria-label="Editar m\xc3\xb3dulo M\xc3\xb3dulo Centro"' in response.data
    assert b'aria-label="Acciones para el m\xc3\xb3dulo M\xc3\xb3dulo Centro"' in response.data
    dashboard_styles = client.get("/static/admin/dashboard.css")
    assert dashboard_styles.status_code == 200
    assert b".admin-modules-page .admin-modules-table td.admin-controller-actions {\n  display: table-cell;\n  width: 1%;" in dashboard_styles.data
    assert b"body.admin-modules-page .admin-modules-table .admin-controller-actions .admin-edit-button:hover .admin-controller-action-icon" in dashboard_styles.data
    assert b"body.admin-modules-page .admin-modules-table .admin-controller-actions .admin-delete-button:hover .admin-controller-action-icon" in dashboard_styles.data


def test_admin_module_actions_require_and_verify_admin_password(monkeypatch):
    authentication_attempts = []
    module_actions = []

    monkeypatch.setattr("app.web.initialize_schema", lambda: None)

    def authenticate(username, password):
        authentication_attempts.append((username, password))
        if password != "correct-password":
            return None
        return {"username": username, "is_admin": True}

    def manage_module_data(module_id, action, actor_username):
        module_actions.append((module_id, action, actor_username))
        return {
            "status": "cleared" if action == "clear" else "deleted",
            "module": {"id": module_id, "nombre": "Módulo Prueba"},
        }

    monkeypatch.setattr("app.web.authenticate_user", authenticate)
    monkeypatch.setattr("app.web.manage_module_data", manage_module_data)
    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {
            "username": "administrador",
            "module_number": None,
            "is_admin": True,
        }

    missing_password = client.post(
        "/administrador/modulos/4/eliminar",
        data={"action": "clear"},
    )
    assert missing_password.status_code == 302
    assert authentication_attempts == []
    assert module_actions == []

    invalid_password = client.post(
        "/administrador/modulos/4/eliminar",
        data={"action": "delete", "admin_password": "wrong-password"},
    )
    assert invalid_password.status_code == 302
    assert authentication_attempts == [("administrador", "wrong-password")]
    assert module_actions == []

    for action in ("clear", "delete"):
        response = client.post(
            "/administrador/modulos/4/eliminar",
            data={"action": action, "admin_password": "correct-password"},
        )
        assert response.status_code == 302

    assert module_actions == [
        (4, "clear", "administrador"),
        (4, "delete", "administrador"),
    ]


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
    assert b'data-admin-action-notification' in response.data
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
    dashboard_styles = client.get("/static/admin/dashboard.css")
    assert (
        b"body.admin-turnos-page [data-turno-individual-actions][hidden] {\n"
        b"  display: inline-flex !important;\n"
        b"  visibility: hidden;\n"
        b"  pointer-events: none;"
        in dashboard_styles.data
    )
    assert b'admin-turno-module-table-picker' in response.data
    assert b'id="turno-module-menu"' in response.data
    assert b'id="turno-selected-modules" aria-live="polite"' in response.data
    assert b'data-turno-available-count' in response.data
    assert b'data-turno-selected-count' in response.data
    assert b'data-turno-current-number' in response.data
    assert b'aria-label="Turno 3">#3</span>' in response.data
    assert b'admin-turno-summary-card' not in response.data
    assert b'admin-turno-summary-item' not in response.data
    assert b'admin-turno-time-overview' in response.data
    assert b'8 horas' not in response.data
    assert b'Duraci\xc3\xb3n del turno' not in response.data
    assert b'id="turno-start-display"' in response.data
    assert b'id="turno-end-display"' in response.data
    assert b'M\xc3\xb3dulos disponibles' in response.data
    assert b'M\xc3\xb3dulos seleccionados' in response.data
    assert b'admin-route-module-number' not in response.data
    turno_styles = client.get("/static/admin/dashboard.css")
    assert b".admin-turno-modal .admin-turno-module-table-picker .admin-turno-module-status" in turno_styles.data
    assert b".admin-turno-modal .admin-turno-module-table-picker .admin-turno-module-remove" in turno_styles.data
    assert b"min-width: 54px;" in turno_styles.data
    assert response.data.count(b'class="admin-secondary-button" type="button" data-turno-modal-close>Cancelar</button>') == 2
    assert b'data-admin-pagination' in response.data
    assert b'id="turno-page-count"' in response.data
    assert b'data-admin-visible-count-target="turno-page-count"' in response.data
    filter_script = client.get("/static/admin_registry_toolbar.js")
    assert b"selectedRouteFilters.turnoType.includes(row.dataset.filterTurnoType)" in filter_script.data
    assert b"visibleCount.textContent = String(matchingRowCount)" in filter_script.data


def test_admin_turnos_specific_edit_keeps_selected_modules_and_number_visible(monkeypatch):
    monkeypatch.setattr("app.web.initialize_schema", lambda: None)
    monkeypatch.setattr("app.web.renumber_turnos_by_start", lambda: None)
    monkeypatch.setattr(
        "app.web.request_modules",
        lambda: [
            {"id": 1, "nombre": "Módulo Uno"},
            {"id": 2, "nombre": "Módulo Dos"},
        ],
    )
    monkeypatch.setattr(
        "app.web.fetch_catalog_items",
        lambda catalog: [
            {
                "id": 42,
                "numero": 7,
                "hora_inicio": "07:00",
                "hora_fin": "15:00",
                "alcance": "especifico",
                "activo": True,
            }
        ],
    )
    monkeypatch.setattr("app.web.fetch_turno_modules_map", lambda turno_ids: {42: [2]})
    monkeypatch.setattr("app.web.fetch_turno_module_statuses_map", lambda turno_ids: {42: {2: False}})
    monkeypatch.setattr("app.web.fetch_turno_module_status_map", lambda turno_id: {2: False})
    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {
            "username": "administrador",
            "module_number": None,
            "is_admin": True,
        }

    response = client.get("/administrador/turnos?edit_id=42")

    assert response.status_code == 200
    assert b'data-selected-modules="2"' in response.data
    assert b'data-module-id="2"' in response.data
    assert b'data-module-name="M\xc3\xb3dulo Dos"' in response.data
    assert b'data-module-status="Inactivo"' in response.data
    assert b'aria-label="Turno 7">#7</span>' in response.data
    assert b'<span class="admin-turno-module-count" data-turno-available-count>1</span>' in response.data
    assert b'<span class="admin-turno-module-count is-selected" data-turno-selected-count>1</span>' in response.data


def test_admin_delete_selected_turnos_renumbers_and_reports_count(monkeypatch):
    deleted = []
    renumbered = []
    histories = []
    monkeypatch.setattr("app.web.initialize_schema", lambda: None)
    monkeypatch.setattr(
        "app.web.delete_turnos_by_ids",
        lambda turno_ids: deleted.append(turno_ids) or [42, 43],
    )
    monkeypatch.setattr("app.web.fetch_turno_modules_map", lambda turno_ids: {42: [1, 2], 43: [2]})
    monkeypatch.setattr(
        "app.web.fetch_turno_module_statuses_map",
        lambda turno_ids: {42: {1: True, 2: False}, 43: {2: True}},
    )
    monkeypatch.setattr(
        "app.web.fetch_catalog_items",
        lambda catalog: [
            {"id": 42, "numero": 1, "hora_inicio": "07:00", "hora_fin": "15:00", "alcance": "especifico", "activo": True},
            {"id": 43, "numero": 2, "hora_inicio": "15:00", "hora_fin": "23:00", "alcance": "general", "activo": True},
        ],
    )
    monkeypatch.setattr("app.web.record_history", lambda *args, **kwargs: histories.append((args, kwargs)))
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
    assert [history[0][2] for history in histories] == [[1, 2], [2]]
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


def test_admin_turno_history_movements_use_hours_instead_of_number(monkeypatch):
    history_entries = []
    turnos = {}

    def create_turno(_catalog, payload):
        turno = {"id": 42, **payload}
        turnos[turno["id"]] = turno
        return turno

    def update_turno(_catalog, turno_id, payload):
        turno = {**turnos[turno_id], **payload}
        turnos[turno_id] = turno
        return turno

    monkeypatch.setattr(web, "initialize_schema", lambda: None)
    monkeypatch.setattr(web, "request_modules", lambda: [{"id": 2}])
    monkeypatch.setattr(web, "turno_start_exists", lambda *_args: False)
    monkeypatch.setattr(web, "get_next_turno_number", lambda: 8)
    monkeypatch.setattr(web, "create_catalog_item", create_turno)
    monkeypatch.setattr(web, "update_catalog_item", update_turno)
    monkeypatch.setattr(web, "fetch_catalog_items", lambda *_args: list(turnos.values()))
    monkeypatch.setattr(
        web,
        "fetch_turno_modules_map",
        lambda turno_ids: {turno_id: [2] for turno_id in turno_ids if turno_id in turnos},
    )
    monkeypatch.setattr(
        web,
        "fetch_turno_module_statuses_map",
        lambda turno_ids: {turno_id: {2: True} for turno_id in turno_ids if turno_id in turnos},
    )
    monkeypatch.setattr(web, "set_turno_modules", lambda *_args: None)
    monkeypatch.setattr(web, "renumber_turnos_by_start", lambda: None)
    monkeypatch.setattr(
        web,
        "delete_catalog_item",
        lambda _catalog, turno_id: turnos.pop(turno_id, None) is not None,
    )
    monkeypatch.setattr(
        web,
        "record_history",
        lambda *args, **kwargs: history_entries.append((args, kwargs)),
    )

    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {"username": "administrador", "is_admin": True}

    created = client.post(
        "/administrador/turnos",
        data={
            "hora_inicio": "07:00",
            "hora_fin": "15:00",
            "turno_scope": "general",
        },
    )
    assert created.status_code == 302

    updated = client.post(
        "/administrador/turnos",
        data={
            "turno_id": "42",
            "numero": "8",
            "hora_inicio": "08:00",
            "hora_fin": "16:00",
            "turno_scope": "general",
        },
    )
    assert updated.status_code == 302

    deleted = client.post("/administrador/turnos/42/eliminar")
    assert deleted.status_code == 302

    assert [args[1] for args, _kwargs in history_entries] == [
        "Registró turno de 07:00 a 15:00 (de Turnos)",
        "Editó turno de 08:00 a 16:00 (de Turnos)",
        "Eliminó turno de 08:00 a 16:00 (de Turnos)",
    ]
    assert [args[3] for args, _kwargs in history_entries] == [
        "registro",
        "edicion",
        "eliminacion",
    ]
    assert history_entries[2][0][4] == "Horario: 08:00 a 16:00"


def test_admin_history_page_separates_general_and_assignment_entries(monkeypatch):
    import re
    from datetime import datetime

    entry = {
        "usuario": "administrador",
        "modulo": 2,
        "modificacion": "Movimiento de prueba",
        "descripcion": "Detalle de prueba",
        "accion": "registro",
        "fecha_hora": datetime(2026, 11, 11, 12, 0, 0),
        "datos_anteriores": None,
        "datos_nuevos": {
            "_field_order": ["Nombre", "Credencial", "Sexo", "Módulo", "Estado"],
            "Nombre": "Ana Prueba",
            "Credencial": "123",
            "Sexo": "Femenino",
            "Módulo": 2,
            "Estado": True,
        },
    }
    sections = {
        "general": [
            {
                **entry,
                "modificacion": "Registró controlador 123 (de Controladores)",
                "modulos": [2],
            },
            {
                **entry,
                "modificacion": "Registró ruta Norte (de Rutas)",
                "modulo": 1,
                "modulos": [1, 2, 3],
                "datos_nuevos": {
                    "_field_order": ["Ruta", "Tipo", "Módulos vinculados"],
                    "Ruta": "Norte",
                    "Tipo": 6,
                    "Módulos vinculados": [
                        {"Módulo": 1, "Estado": "Activo"},
                        {"Módulo": 2, "Estado": "Activo"},
                        {"Módulo": 3, "Estado": "Inactivo"},
                    ],
                },
            },
            {
                **entry,
                "modificacion": "Registró turno 8 (de Turnos)",
                "modulo": 1,
                "modulos": [1, 2],
                "datos_nuevos": {
                    "_field_order": ["Número", "Módulos disponibles"],
                    "Número": 8,
                    "Módulos disponibles": [
                        {"Módulo": 1, "Estado": True},
                        {"Módulo": 2, "Estado": False},
                    ],
                },
            },
            {
                **entry,
                "accion": "descarto",
                "modulo": 2,
                "modulos": [2],
                "modificacion": "Descartó turno 8 (de Turnos)",
                "descripcion": "Turno: 8; Inicio: 07:00; Fin: 15:00",
                "datos_anteriores": {
                    "_field_order": ["Número"],
                    "Número": 8,
                },
                "datos_nuevos": None,
            },
            {
                **entry,
                "accion": "agrego",
                "modulo": 2,
                "modulos": [2],
                "modificacion": "Agregó turno 8 (de Turnos)",
                "descripcion": "Turno: 8; Inicio: 07:00; Fin: 15:00",
                "datos_anteriores": None,
                "datos_nuevos": {
                    "_field_order": ["Número"],
                    "Número": 8,
                },
            },
            {
                **entry,
                "accion": "edicion",
                "modificacion": "Editó ruta Norte (de Rutas)",
                "modulo": 1,
                "modulos": [1, 2, 3],
                "datos_anteriores": {
                    "_field_order": ["Ruta", "Módulos vinculados"],
                    "Ruta": "Norte",
                    "Módulos vinculados": [
                        {"Módulo": 1, "Estado": "Activo"},
                        {"Módulo": 2, "Estado": "Inactivo"},
                        {"Módulo": 3, "Estado": "Inactivo"},
                    ],
                },
                "datos_nuevos": {
                    "_field_order": ["Ruta", "Módulos vinculados"],
                    "Ruta": "Norte",
                    "Módulos vinculados": [
                        {"Módulo": 1, "Estado": "Inactivo"},
                        {"Módulo": 2, "Estado": "Activo"},
                        {"Módulo": 3, "Estado": "Activo"},
                    ],
                },
            },
            {
                **entry,
                "accion": "vinculacion",
                "modificacion": "Vinculó 2 ruta(s) al módulo 1 (de Rutas)",
                "modulo": 1,
                "modulos": [1],
                "descripcion": "Rutas vinculadas: 45 (#39), Norte (#144)",
                "datos_nuevos": {
                    "Módulo de destino": 1,
                    "Rutas vinculadas": [
                        {"Ruta": "45", "Módulo de origen": 2},
                        {"Ruta": "Norte", "Módulo de origen": 3},
                    ],
                },
            },
            {
                **entry,
                "accion": "eliminacion",
                "modificacion": "Eliminó rutas del módulo 1 (de Rutas)",
                "modulo": 1,
                "modulos": [1],
                "descripcion": "IDs de rutas: 39, 144",
                "datos_anteriores": {
                    "Módulo afectado": 1,
                    "Rutas": [
                        {"Ruta": "45", "Módulo de origen": 2},
                        {"Ruta": "Norte", "Módulo de origen": 3},
                    ],
                },
                "datos_nuevos": None,
            },
            {
                **entry,
                "accion": "desvinculacion",
                "modificacion": "Desvinculó ruta 144 del módulo 1 (de Rutas)",
                "modulo": 1,
                "modulos": [1],
                "descripcion": "ID de la ruta: 144; Módulo: 1",
                "datos_anteriores": {
                    "Ruta": "Ruta Desvinculada",
                    "Módulo de origen": 3,
                    "Módulos compartidos": [
                        {"Módulo": 1, "Estado": "Activo"},
                    ],
                },
                "datos_nuevos": None,
            },
        ],
        "asignaciones": [
            {
                **entry,
                "modulo": None,
                "modulos": [1, 2],
                "modificacion": "Editó a 123 en el rol mensual",
            }
        ],
    }
    requested_sections = []
    monkeypatch.setattr(
        "app.web.request_modules",
        lambda: [
            {"id": 1, "nombre": "Módulo 1"},
            {"id": 2, "nombre": "Módulo 2"},
            {"id": 3, "nombre": "Módulo 3"},
        ],
    )
    monkeypatch.setattr(
        "app.web.fetch_catalog_items",
        lambda table: [{"id": 6, "descripcion": "Ruta Oficial RTP"}],
    )
    monkeypatch.setattr(
        "app.web.fetch_history_entries",
        lambda limit=500, section=None: requested_sections.append(section) or sections[section],
    )
    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {
            "username": "administrador",
            "module_number": None,
            "is_admin": True,
        }

    response = client.get("/administrador/historial")

    assert response.status_code == 200
    tabs_end = response.data.index(b'data-history-tab="asignaciones"')
    toolbar_start = response.data.index(b'data-history-toolbar')
    tables_start = response.data.index(b'data-history-panel="general"')
    assert tabs_end < toolbar_start < tables_start
    assert b'data-history-search aria-label="Buscar por fecha, hora o usuario" placeholder="Fecha, hora o usuario"' in response.data
    assert b'data-history-category-filter-group' in response.data
    assert b'data-history-action-filter-heading' in response.data
    for category in (
        "controladores",
        "rutas",
        "tipos",
        "servicios",
        "usuarios",
        "turnos",
        "modulos",
        "estados_especiales",
    ):
        assert f'data-history-category-filter value="{category}"'.encode() in response.data
    for action in (
        "registro",
        "edicion",
        "eliminacion",
        "agrego",
        "descarto",
        "vinculacion",
        "desvinculacion",
        "descarga",
        "contrasena",
        "inicio_sesion",
        "cierre_sesion",
    ):
        assert f'data-history-action-filter value="{action}"'.encode() in response.data
    assert b'data-history-category="rutas"' in response.data
    assert b'data-history-action="edicion"' in response.data
    assert b'data-history-action="agrego"' in response.data
    assert b'data-history-action="descarto"' in response.data
    assert b'class="history-action is-agrego"' in response.data
    assert b'class="history-action is-descarto"' in response.data
    assert b"Agrego" in response.data
    assert b"Descarto" in response.data
    assert b"matchesModule && matchesSearch && matchesCategory && matchesAction" in response.data
    assert b"historyCategoryFilterGroup.hidden = isAssignments" in response.data
    assert b"historyActionFilterHeading.textContent = isAssignments ? 'Acci\xc3\xb3n' : 'Categor\xc3\xada Acciones'" in response.data
    assert b"if (isAssignments)" in response.data
    assert b'class="history-action is-desvinculacion"' in response.data
    for action_label in ("Edito", "Elimino", "Vinculo", "Desvinculo"):
        assert f"<span>{action_label}</span>".encode() in response.data
    assert b"Ruta Desvinculada" in response.data
    assert b"Resumen del movimiento" not in response.data
    assert b"admin-history-avatar" not in response.data
    normalized_history_html = re.sub(r"\s+", " ", response.get_data(as_text=True))
    assert "<td> administrador </td>" in normalized_history_html
    assert requested_sections == ["general", "asignaciones"]
    assert b'data-history-tab="general"' in response.data
    assert b'data-history-tab="asignaciones"' in response.data
    assert b'data-admin-module="1"' in response.data
    assert b'data-admin-module="2"' in response.data
    assert b'<th>Fecha y hora</th>' in response.data
    assert b"Ruta Oficial RTP" in response.data
    assert response.data.index(b'<th>Fecha y hora</th>') < response.data.index(b'<th>Usuario</th>')
    assert response.data.index(b'<th>Usuario</th>') < response.data.index(b'<th>Acci\xc3\xb3n</th>')
    assert response.data.index(b'<th>Acci\xc3\xb3n</th>') < response.data.index(b'<th>Movimiento</th>')
    assert response.data.index(b'<th>Movimiento</th>') < response.data.index(b'<th>M\xc3\xb3dulo</th>')
    assert response.data.index(b'<th>M\xc3\xb3dulo</th>') < response.data.index(b'<th>Detalle</th>')
    assert b"Mi\xc3\xa9, 11 noviembre 2026" in response.data
    assert b"M\xc3\xb3dulo 2" in response.data
    assert b'data-module-numbers="1,2"' in response.data
    assert b'admin-module-changed' in response.data
    assert b"filterHistory(document.querySelector('[data-admin-module].active')" in response.data
    assert b"Registr\xc3\xb3 controlador 123" in response.data
    assert b"Registr\xc3\xb3 controlador 123 (de Controladores)" not in response.data
    assert b'data-history-drawer' in response.data
    assert b'aria-modal="true"' in response.data
    assert b'Detalle de Auditor\xc3\xada' in response.data
    assert b'Informaci\xc3\xb3n del Movimiento' in response.data
    assert b'<th scope="row">Nombre</th>' in response.data
    assert b"<div>45 - M\xc3\xb3dulo de origen 2</div>" in response.data
    assert b"<div>Norte - M\xc3\xb3dulo de origen 3</div>" in response.data
    assert (
        b'<th class="admin-history-module-group-field" scope="rowgroup" rowspan="2">'
        b'M\xc3\xb3dulos vinculados</th>'
    ) in response.data
    assert (
        b'<span class="admin-history-module-group-state is-activo">Activo</span>'
        in response.data
    )
    assert b'data-history-module-number="1">M1</span>' in response.data
    assert b'data-history-module-number="2">M2</span>' in response.data
    assert (
        b'<th class="admin-history-module-group-field" scope="rowgroup" rowspan="2">'
        b'M\xc3\xb3dulos disponibles</th>'
    ) in response.data
    assert (
        b'<span class="admin-history-module-group-state is-inactivo">Inactivo</span>'
        in response.data
    )
    assert b'class="admin-history-comparison-module-groups"' in response.data
    assert (
        b'<span class="admin-history-module-group-state is-activo">Activo</span>'
        in response.data
    )
    assert (
        b'<span class="admin-history-module-group-state is-inactivo">Inactivo</span>'
        in response.data
    )
    assert (
        b'<div class="admin-history-comparison-module-list">'
        b'<span class="admin-history-module-color-badge" data-history-module-number="2">M2</span>'
        in response.data
    )
    assert b'admin-history-log-id' not in response.data
    assert b'admin-history-detail-description' not in response.data
    assert b'data-history-clear-form' in response.data
    assert b'name="module_number" value=""' in response.data
    assert b'>Vaciar historial</button>' in response.data
    assert (
        b'data-delete-confirm-title="\xc2\xbfVaciar historial del m\xc3\xb3dulo?"'
        in response.data
    )
    assert b"Edit\xc3\xb3 a 123 en el rol mensual" in response.data
    history_styles = client.get("/static/admin/dashboard.css")
    assert b".admin-history-drawer .history-action.is-registro" in history_styles.data
    assert (
        b".history-row.is-eliminacion .history-action, "
        b".history-row.is-desvinculacion .history-action { color: #a43e4c; background: #fff0f1; }"
        in history_styles.data
    )
    assert (
        b".admin-history-drawer .history-action.is-eliminacion, "
        b".admin-history-drawer .history-action.is-desvinculacion { color: #a43e4c; background: #fff0f1; }"
        in history_styles.data
    )
    assert b".admin-history-module-color-badge" in history_styles.data
    assert b"width: 64px;" in history_styles.data
    history_scripts = client.get("/static/admin_tabs.js")
    assert b".admin-history-module-color-badge[data-history-module-number]" in history_scripts.data
    assert b"detailTemplate.content" in history_scripts.data
    assert b"'1': '#027a35'" in history_scripts.data
    confirmation_script = client.get("/static/admin_delete_confirmation.js")
    assert b"form.dataset.deleteConfirmTitle" in confirmation_script.data


def test_assignment_edit_history_renders_role_comparison_only_in_assignments(monkeypatch):
    from datetime import datetime

    before_record = {
        "_field_order": [
            "Controlador", "Credencial", "Turno", "Ruta", "Nomenclatura",
            "Días de trabajo", "Días de descanso", "Asignaciones diarias",
            "Detalles diarios",
        ],
        "Controlador": "Ana Prueba",
        "Credencial": "123",
        "Turno": "2",
        "Ruta": "Ruta C",
        "Nomenclatura": "C",
        "Días de trabajo": [1, 2],
        "Días de descanso": [3],
        "Asignaciones diarias": {"1": "A1", "2": "C2"},
        "Detalles diarios": {
            "1": {"route": "Ruta A", "shift": "1", "nomenclature": "A", "code": "A1"},
            "2": {"route": "Ruta C", "shift": "2", "nomenclature": "C", "code": "C2"},
        },
    }
    after_record = {
        **before_record,
        "Turno": "1",
        "Ruta": "Ruta E",
        "Nomenclatura": "E",
        "Días de trabajo": [1, 2, 4],
        "Asignaciones diarias": {"1": "A1", "2": "B1", "4": "E1"},
        "Detalles diarios": {
            **before_record["Detalles diarios"],
            "2": {"route": "Ruta B", "shift": "1", "nomenclature": "B", "code": "B1"},
            "4": {"route": "Ruta E", "shift": "1", "nomenclature": "E", "code": "E1"},
        },
    }
    unchanged_record = {
        **before_record,
        "Credencial": "456",
        "Controlador": "Luis Prueba",
    }
    entry = {
        "usuario": "administrador",
        "modulo": 1,
        "modulos": [1],
        "descripcion": "Asignaciones del rol mensual",
        "accion": "edicion",
        "fecha_hora": datetime(2026, 11, 11, 12, 0, 0),
        "modificacion": "Editó asignaciones del rol 11/2026",
        "datos_anteriores": {
            "Asignaciones": [before_record, unchanged_record],
        },
        "datos_nuevos": {
            "Asignaciones": [after_record, unchanged_record],
        },
    }
    general_entry = {
        **entry,
        "modificacion": "Editó otro registro",
        "datos_anteriores": before_record,
        "datos_nuevos": after_record,
    }
    sections = {"general": [general_entry], "asignaciones": [entry]}
    monkeypatch.setattr(
        "app.web.request_modules",
        lambda: [{"id": 1, "nombre": "Módulo 1"}],
    )
    monkeypatch.setattr(
        "app.web.fetch_history_entries",
        lambda limit=500, section=None: sections[section],
    )
    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {
            "username": "administrador",
            "module_number": None,
            "is_admin": True,
        }

    response = client.get("/administrador/historial")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    general_start = html.index('data-history-panel="general"')
    assignments_start = html.index('data-history-panel="asignaciones"')
    general_panel = html[general_start:assignments_start]
    assignments_panel = html[assignments_start:]
    assert "data-assignment-role-comparison" not in general_panel
    assert "Cambios registrados" in general_panel
    assert "data-assignment-role-comparison" in assignments_panel
    assert "Resaltar solo cambios" in assignments_panel
    assert "Noviembre 2026" in assignments_panel
    assert "Turnos" in assignments_panel
    assert "Rutas" in assignments_panel
    assert '<th scope="col">TURNO</th>' in assignments_panel
    assert assignments_panel.count('<th scope="col">RUTA</th>') == 2
    assert assignments_panel.count('<th scope="col">NOM</th>') == 2
    assert '<th scope="colgroup">ANTERIOR</th>' in assignments_panel
    assert '<th scope="colgroup">NUEVO</th>' in assignments_panel
    assert "<td>1</td><td>1</td>" in assignments_panel
    assert "<td>2</td><td></td>" in assignments_panel
    assert "<td>Ruta A</td><td>(A)</td><td>Ruta A</td><td>(A)</td>" in assignments_panel
    assert "<td>Ruta C</td><td>(C)</td>" in assignments_panel
    assert 'class="is-role-value-changed">Ruta B</td>' in assignments_panel
    assert 'class="is-role-value-changed">(B)</td>' in assignments_panel
    assert 'class="is-role-value-changed">Ruta E</td>' in assignments_panel
    assert 'class="is-role-value-changed">(E)</td>' in assignments_panel
    assert "admin-history-role-stats" not in assignments_panel
    assert 'data-assignment-day="30"' in assignments_panel
    assert 'data-assignment-day="31"' not in assignments_panel
    assert assignments_panel.count('<article class="admin-history-role-comparison') == 1
    assert "data-assignment-highlight-toggle" in assignments_panel
    assert "data-assignment-inspector-before" in assignments_panel
    assert "data-assignment-inspector-after" in assignments_panel
    assert "is-assignment-comparison', hasAssignmentComparison" in assignments_panel
    assert "comparison.classList.toggle('is-change-highlighted', isEnabled)" in assignments_panel
    history_styles = client.get("/static/admin/dashboard.css")
    assert b".admin-history-drawer-panel.is-assignment-comparison {" in history_styles.data
    assert b"width: min(768px, 100vw);" in history_styles.data
    assert b".admin-history-role-stats" not in history_styles.data
    assert b".admin-history-role-table-card" in history_styles.data
    assert (
        b".admin-history-role-calendar.is-after .admin-history-role-day.is-changed {"
        in history_styles.data
    )
    assert (
        b".admin-history-role-calendar.is-after .admin-history-role-day.is-changed::after"
        in history_styles.data
    )
    assert (
        b".admin-history-role-calendar .admin-history-role-day:not(.is-changed)"
        in history_styles.data
    )
    assert (
        b".admin-history-role-comparison.is-deletion-calendar .admin-history-role-day.is-deleted"
        in history_styles.data
    )
    assert (
        b".admin-history-role-comparison.is-change-highlighted .admin-history-role-calendar.is-before .admin-history-role-day.is-changed"
        in history_styles.data
    )
    assert b"opacity: .18;" in history_styles.data
    assert b"background: #fef3c7;" in history_styles.data
    assert b"border-radius: 50%;" in history_styles.data
    assert (
        b".admin-history-role-calendar.is-after .admin-history-role-day.is-rest.is-changed"
        not in history_styles.data
    )


def test_assignment_registration_history_renders_single_calendar(monkeypatch):
    from datetime import datetime

    record = {
        "Controlador": "Ana Prueba",
        "Credencial": "123",
        "Turno": "2",
        "Ruta": "Ruta A",
        "Nomenclatura": "C",
        "Días de trabajo": [2, 3, 4],
        "Días de descanso": [],
        "Asignaciones diarias": {"2": "C2", "3": "C2", "4": "C2"},
        "Detalles diarios": {
            str(day): {
                "route": "Ruta A",
                "shift": "2",
                "nomenclature": "C",
                "code": "C2",
            }
            for day in (2, 3, 4)
        },
    }
    entry = {
        "usuario": "administrador",
        "modulo": 1,
        "modulos": [1],
        "descripcion": "Asignación del rol mensual",
        "accion": "registro",
        "fecha_hora": datetime(2026, 11, 11, 12, 0, 0),
        "modificacion": "Registró a 123 (11/2026) (de Asignación de Roles)",
        "datos_anteriores": None,
        "datos_nuevos": record,
    }
    deletion_entry = {
        **entry,
        "accion": "eliminacion",
        "modificacion": "Eliminó a 123 (11/2026) (de Asignación de Roles)",
        "datos_anteriores": record,
        "datos_nuevos": None,
    }
    sections = {
        "general": [entry, deletion_entry],
        "asignaciones": [entry, deletion_entry],
    }
    monkeypatch.setattr(
        "app.web.request_modules",
        lambda: [{"id": 1, "nombre": "Módulo 1"}],
    )
    monkeypatch.setattr(
        "app.web.fetch_history_entries",
        lambda limit=500, section=None: sections[section],
    )
    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {
            "username": "administrador",
            "module_number": None,
            "is_admin": True,
        }

    response = client.get("/administrador/historial")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assignments_start = html.index('data-history-panel="asignaciones"')
    assignments_panel = html[assignments_start:]
    assert 'data-assignment-role-registration' in assignments_panel
    assert 'data-assignment-role-comparison' not in assignments_panel
    assert 'class="admin-history-role-calendars is-single"' in assignments_panel
    assert "Calendario registrado" in assignments_panel
    assert "Noviembre 2026" in assignments_panel
    assert "Ana Prueba" in assignments_panel
    assert 'data-assignment-registration-day="2"' in assignments_panel
    assert "<small>C2</small>" in assignments_panel
    assert "Resaltar solo cambios" not in assignments_panel
    assert 'data-assignment-role-deletion' in assignments_panel
    assert "Días eliminados" in assignments_panel
    assert 'class="admin-history-role-day is-work is-deleted"' in assignments_panel
    assert 'data-assignment-deleted-day="2"' in assignments_panel
    assert (
        'class="admin-history-role-day is-empty" data-assignment-deleted-day="5"'
        in assignments_panel
    )
    assert "Asignación eliminada" in assignments_panel


def test_assignment_history_comparison_handles_individual_snapshot_and_leap_month():
    import app.web as web

    before_record = {
        "Controlador": "Ana Prueba",
        "Credencial": "123",
        "Turno": "1",
        "Ruta": "Ruta Norte",
        "Nomenclatura": "A",
        "Días de trabajo": [1],
        "Días de descanso": [],
        "Asignaciones diarias": {"1": "A1"},
        "Detalles diarios": {
            "1": {"route": "Ruta Norte", "shift": "1", "nomenclature": "A", "code": "A1"},
        },
    }
    after_record = {
        **before_record,
        "Turno": "2",
        "Ruta": "Ruta Sur",
        "Nomenclatura": "B",
        "Asignaciones diarias": {"1": "B2"},
        "Detalles diarios": {
            "1": {"route": "Ruta Sur", "shift": "2", "nomenclature": "B", "code": "B2"},
        },
    }
    prepared = web.prepare_history_entries(
        [{
            "accion": "edicion",
            "modificacion": "Editó a 123 (02/2024) (de Asignación de Roles)",
            "datos_anteriores": before_record,
            "datos_nuevos": after_record,
        }],
        {},
        section="asignaciones",
    )

    comparison = prepared[0]["assignment_comparisons"][0]
    month_cells = [cell for cell in comparison["before_cells"] if not cell["blank"]]
    changed_days = [
        cell["day"]
        for cell in comparison["before_cells"]
        if not cell["blank"] and cell["changed"]
    ]
    assert comparison["period_label"] == "Febrero 2024"
    assert comparison["shifts_before"] == ["1"]
    assert comparison["shifts_after"] == ["2"]
    assert comparison["routes_before"] == ["Ruta Norte"]
    assert comparison["routes_after"] == ["Ruta Sur"]
    assert comparison["nomenclatures_before"] == ["A"]
    assert comparison["nomenclatures_after"] == ["B"]
    assert changed_days == [1]
    assert len(month_cells) == 29
    assert month_cells[-1]["day"] == 29
    assert len(comparison["before_cells"]) == 32
    assert comparison["before_cells"][3]["day"] == 1

    legacy_comparison = web.prepare_assignment_history_comparisons(
        {**before_record, "Detalles diarios": {}},
        {**after_record, "Detalles diarios": {}},
        "Editó a 123 (02/2024) (de Asignación de Roles)",
    )[0]
    assert legacy_comparison["shifts_before"] == ["1"]
    assert legacy_comparison["shifts_after"] == ["2"]
    assert legacy_comparison["routes_before"] == ["Ruta Norte"]
    assert legacy_comparison["routes_after"] == ["Ruta Sur"]


def test_assignment_history_highlights_only_the_day_with_a_cell_change():
    import app.web as web

    before_record = {
        "Controlador": "Ana Prueba",
        "Credencial": "123",
        "Turno": "2",
        "Ruta": "Ruta C",
        "Nomenclatura": "C",
        "Días de trabajo": list(range(2, 18)),
        "Días de descanso": [],
        "Asignaciones diarias": {str(day): "C2" for day in range(2, 18)},
        "Detalles diarios": {},
    }
    after_record = {
        **before_record,
        "Turno": "1",
        "Ruta": "Ruta E",
        "Nomenclatura": "E",
        "Días de trabajo": list(range(2, 19)),
        "Asignaciones diarias": {
            **before_record["Asignaciones diarias"],
            "18": "D3",
        },
        "Detalles diarios": {
            "18": {"route": "Ruta E", "shift": "1", "nomenclature": "D", "code": "D3"},
        },
    }

    comparison = web.prepare_assignment_history_comparisons(
        before_record,
        after_record,
        "Editó asignaciones del rol 11/2026",
    )[0]
    changed_days = [
        cell["day"]
        for cell in comparison["after_cells"]
        if not cell["blank"] and cell["changed"]
    ]

    assert changed_days == [18]

    same_code_before = {
        **before_record,
        "Días de trabajo": list(range(2, 19)),
        "Asignaciones diarias": {
            **before_record["Asignaciones diarias"],
            "18": "C2",
        },
        "Detalles diarios": {
            "18": {"route": "Ruta C", "shift": "2", "nomenclature": "C", "code": "C2"},
        },
    }
    same_code_after = {
        **same_code_before,
        "Ruta": "Ruta E",
        "Detalles diarios": {
            "18": {"route": "Ruta E", "shift": "2", "nomenclature": "C", "code": "C2"},
        },
    }
    same_code_comparison = web.prepare_assignment_history_comparisons(
        same_code_before,
        same_code_after,
        "Editó asignaciones del rol 11/2026",
    )[0]
    same_code_changed_days = [
        cell["day"]
        for cell in same_code_comparison["after_cells"]
        if not cell["blank"] and cell["changed"]
    ]

    assert same_code_changed_days == [18]

    before_assignments = {
        **{str(day): "A1" for day in range(2, 5)},
        **{str(day): "B2" for day in range(5, 8)},
    }
    before_details = {
        **{
            str(day): {"route": "Ruta A", "shift": "1", "nomenclature": "A", "code": "A1"}
            for day in range(2, 5)
        },
        **{
            str(day): {"route": "Ruta B", "shift": "2", "nomenclature": "B", "code": "B2"}
            for day in range(5, 8)
        },
    }
    role_before = {
        **before_record,
        "Días de trabajo": list(range(2, 8)),
        "Asignaciones diarias": before_assignments,
        "Detalles diarios": before_details,
    }
    role_after = {
        **role_before,
        "Turno": "3",
        "Ruta": "Ruta C",
        "Nomenclatura": "C",
        "Días de trabajo": list(range(2, 11)),
        "Asignaciones diarias": {
            **before_assignments,
            **{str(day): "C3" for day in range(8, 11)},
        },
        "Detalles diarios": {
            **before_details,
            **{
                str(day): {"route": "Ruta C", "shift": "3", "nomenclature": "C", "code": "C3"}
                for day in range(8, 11)
            },
        },
    }
    role_comparison = web.prepare_assignment_history_comparisons(
        role_before,
        role_after,
        "Editó asignaciones del rol 11/2026",
    )[0]
    after_cells = {
        cell["day"]: cell
        for cell in role_comparison["after_cells"]
        if not cell["blank"]
    }
    role_changed_days = [
        day for day, cell in after_cells.items() if cell["changed"]
    ]

    assert role_changed_days == [8, 9, 10]
    assert all(after_cells[day]["status"] == "work" for day in range(2, 8))


def test_assignment_history_highlights_deleted_days_in_the_latest_edit():
    import app.web as web

    before_record = {
        "Controlador": "Ana Prueba",
        "Credencial": "123",
        "Turno": "5",
        "Ruta": "Ruta J",
        "Nomenclatura": "J",
        "Días de trabajo": [10, 11, 12, 13],
        "Días de descanso": [],
        "Asignaciones diarias": {
            "10": "J5",
            "11": "J5",
            "12": "J5",
            "13": "J5",
        },
        "Detalles diarios": {},
    }
    after_record = {
        **before_record,
        "Días de trabajo": [18, 19, 20],
        "Asignaciones diarias": {"18": "I5", "19": "I5", "20": "I5"},
        "_assignment_edited_days": [18, 19, 20],
    }

    comparison = web.prepare_assignment_history_comparisons(
        before_record,
        after_record,
        "Editó asignaciones del rol 11/2026",
    )[0]
    changed_days = [
        cell["day"]
        for cell in comparison["after_cells"]
        if not cell["blank"] and cell["changed"]
    ]

    assert changed_days == [10, 11, 12, 13, 18, 19, 20]


def test_assignment_history_tables_show_full_before_and_after_assignments():
    import app.web as web

    before_details = {
        "1": {"route": "Ruta A", "shift": "1", "nomenclature": "A", "code": "A1"},
        "2": {"route": "Ruta B", "shift": "2", "nomenclature": "B", "code": "B2"},
        "3": {"route": "Ruta C", "shift": "3", "nomenclature": "C", "code": "C3"},
    }
    before_record = {
        "Controlador": "Ana Prueba",
        "Credencial": "123",
        "Turno": "3",
        "Ruta": "Ruta C",
        "Nomenclatura": "C",
        "Días de trabajo": [1, 2, 3],
        "Días de descanso": [],
        "Asignaciones diarias": {"1": "A1", "2": "B2", "3": "C3"},
        "Detalles diarios": before_details,
    }
    after_record = {
        **before_record,
        "Turno": "4",
        "Ruta": "Ruta D",
        "Nomenclatura": "D",
        "Días de trabajo": [1, 2, 3, 4],
        "Asignaciones diarias": {"1": "A1", "2": "B2", "3": "C3", "4": "D4"},
        "Detalles diarios": {
            **before_details,
            "4": {"route": "Ruta D", "shift": "4", "nomenclature": "D", "code": "D4"},
        },
    }

    comparison = web.prepare_assignment_history_comparisons(
        before_record,
        after_record,
        "Editó asignaciones del rol 11/2026",
    )[0]

    assert comparison["shifts_before"] == ["1", "2", "3"]
    assert comparison["shifts_after"] == ["1", "2", "3", "4"]
    assert comparison["shift_rows"] == [
        {"before": "1", "after": "1", "after_changed": False},
        {"before": "2", "after": "2", "after_changed": False},
        {"before": "3", "after": "3", "after_changed": False},
        {"before": None, "after": "4", "after_changed": True},
    ]
    assert comparison["routes_before"] == ["Ruta A", "Ruta B", "Ruta C"]
    assert comparison["routes_after"] == ["Ruta A", "Ruta B", "Ruta C", "Ruta D"]
    assert comparison["nomenclatures_before"] == ["A", "B", "C"]
    assert comparison["nomenclatures_after"] == ["A", "B", "C", "D"]
    assert comparison["route_rows"] == [
        {
            "before": {"route": "Ruta A", "nomenclature": "A"},
            "after": {"route": "Ruta A", "nomenclature": "A"},
            "after_changed": False,
        },
        {
            "before": {"route": "Ruta B", "nomenclature": "B"},
            "after": {"route": "Ruta B", "nomenclature": "B"},
            "after_changed": False,
        },
        {
            "before": {"route": "Ruta C", "nomenclature": "C"},
            "after": {"route": "Ruta C", "nomenclature": "C"},
            "after_changed": False,
        },
        {
            "before": None,
            "after": {"route": "Ruta D", "nomenclature": "D"},
            "after_changed": True,
        },
    ]

    replacement_record = {
        **after_record,
        "Turno": "5",
        "Ruta": "Ruta F",
        "Nomenclatura": "F",
        "Detalles diarios": {
            "1": {"route": "Ruta C", "shift": "3", "nomenclature": "C", "code": "C3"},
            "2": {"route": "Ruta D", "shift": "4", "nomenclature": "D", "code": "D4"},
            "3": {"route": "Ruta F", "shift": "5", "nomenclature": "F", "code": "F5"},
        },
    }
    replacement = web.prepare_assignment_history_comparisons(
        before_record,
        replacement_record,
        "Editó asignaciones del rol 11/2026",
    )[0]

    assert replacement["shifts_after"] == ["3", "4", "5"]
    assert replacement["routes_after"] == ["Ruta C", "Ruta D", "Ruta F"]
    assert replacement["nomenclatures_after"] == ["C", "D", "F"]


def test_admin_clear_history_targets_only_selected_existing_module(monkeypatch):
    cleared_modules = []
    monkeypatch.setattr("app.web.initialize_schema", lambda: None)
    monkeypatch.setattr(
        "app.web.request_modules",
        lambda: [{"id": 1, "nombre": "Módulo Uno"}, {"id": 2, "nombre": "Módulo Dos"}],
    )
    monkeypatch.setattr(
        "app.web.clear_history_for_module",
        lambda module_number: cleared_modules.append(module_number) or 4,
    )
    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {"username": "administrador", "is_admin": True}

    response = client.post(
        "/administrador/historial/vaciar",
        data={"module_number": "2"},
    )

    assert response.status_code == 302
    assert response.location.endswith("/administrador/historial")
    assert cleared_modules == [2]
    with client.session_transaction() as session:
        assert session["_flashes"][-1][1] == (
            "Se vació el historial de Módulo Dos. Se limpiaron 4 movimientos."
        )

    response = client.post(
        "/administrador/historial/vaciar",
        data={"module_number": "3"},
    )
    assert response.status_code == 302
    assert cleared_modules == [2]


def test_history_movement_hides_origin_section_suffix():
    entries = prepare_history_entries(
        [
            {
                "accion": "registro",
                "modificacion": "Registró controlador 45345 (de Controladores)",
            }
        ],
        {},
    )

    assert entries[0]["movimiento_visible"] == "Registró controlador 45345"


def test_history_categories_map_movement_sections_to_filter_values():
    sections = {
        "Controladores": "controladores",
        "Rutas": "rutas",
        "Tipos de rutas": "tipos",
        "Servicios": "servicios",
        "Usuarios": "usuarios",
        "Turnos": "turnos",
        "Módulos": "modulos",
        "Estados especiales": "estados_especiales",
    }
    entries = prepare_history_entries(
        [
            {"modificacion": f"Registró elemento (de {section})"}
            for section in sections
        ],
        {},
    )

    assert [entry["history_category"] for entry in entries] == list(sections.values())


def test_history_description_remains_available_without_description_elements():
    entries = prepare_history_entries(
        [
            {
                "accion": "inicio_sesion",
                "modificacion": "Inicio de sesión",
                "descripcion": "El usuario inició sesión correctamente.",
                "datos_anteriores": None,
                "datos_nuevos": None,
            },
            {
                "accion": "vinculacion",
                "modificacion": "Vinculó ruta Norte a otros módulos",
                "descripcion": "Módulo de destino: 2",
                "datos_anteriores": None,
                "datos_nuevos": {"Ruta": "Norte", "Origen": "Centro"},
            },
            {
                "accion": "desvinculacion",
                "modificacion": "Desvinculó ruta Norte del módulo 2",
                "descripcion": "ID de la ruta: 42; Módulo: 2",
                "datos_anteriores": {
                    "Ruta": "Norte",
                    "Origen": "Centro",
                    "Destino": "Terminal",
                },
                "datos_nuevos": None,
            },
        ],
        {},
    )

    assert entries[0]["detail_rows"] == [
        {
            "field": "Detalle",
            "value": "El usuario inició sesión correctamente.",
        }
    ]
    assert entries[1]["detail_rows"] == [
        {"field": "Ruta", "value": "Norte"},
        {"field": "Origen", "value": "Centro"},
    ]
    assert entries[2]["detail_rows"] == [
        {"field": "Ruta", "value": "Norte"},
        {"field": "Origen", "value": "Centro"},
        {"field": "Destino", "value": "Terminal"},
    ]


def test_route_link_history_shows_only_route_name_and_origin_module():
    entries = prepare_history_entries(
        [
            {
                "accion": "vinculacion",
                "modificacion": "Vinculó 2 ruta(s) al módulo 1 (de Rutas)",
                "descripcion": "Rutas vinculadas: 45 (#39), Norte (#144)",
                "datos_nuevos": {
                    "Módulo de destino": 1,
                    "Rutas vinculadas": [
                        {
                            "Ruta": "45",
                            "Tipo": 3,
                            "Origen": "Conti",
                            "Módulo de origen": 2,
                        },
                        {
                            "Ruta": "Norte",
                            "Tipo": 4,
                            "Origen": "Chihuahua",
                            "Módulo de origen": 5,
                        },
                    ],
                },
            }
        ],
        {"1": "Módulo 1", "2": "Módulo 2", "5": "Módulo 5"},
    )

    assert entries[0]["detail_rows"] == [
        {"field": "Módulo de destino", "value": "Módulo 1"},
        {
            "field": "Rutas vinculadas",
            "value_lines": [
                "45 - Módulo de origen 2",
                "Norte - Módulo de origen 5",
            ],
        },
    ]


def test_module_deletion_history_omits_summary_rows_and_separates_details():
    entries = prepare_history_entries(
        [
            {
                "accion": "eliminacion",
                "modificacion": "Eliminó módulo Módulo Centro (de Módulos)",
                "datos_anteriores": {
                    "_field_order": [
                        "Nombre del módulo",
                        "Cuentas eliminadas",
                        "Rutas compartidas desvinculadas",
                        "Registros analíticos eliminados",
                        "Registros históricos de migración eliminados",
                    ],
                    "Nombre del módulo": "Módulo Centro",
                    "Cuentas eliminadas": [
                        {"Usuario": "user1", "Tipo": "usuario"},
                        {"Usuario": "user2", "Tipo": "usuario"},
                    ],
                    "Rutas compartidas desvinculadas": [
                        {
                            "Ruta": "Ruta Norte",
                            "Origen": "Centro",
                            "Destino": "Terminal",
                            "Módulo de origen": 2,
                        },
                    ],
                    "Registros analíticos eliminados": {
                        "Días de ruta": 35,
                        "Días de controlador": 90,
                    },
                    "Registros históricos de migración eliminados": 0,
                },
            }
        ],
        {"2": "Módulo 2"},
    )

    detail_rows = entries[0]["detail_rows"]
    assert [row["field"] for row in detail_rows] == [
        "Nombre del módulo",
        "Cuentas eliminadas",
        "Rutas compartidas desvinculadas",
    ]
    assert detail_rows[1]["value_lines"] == [
        "Usuario: user1; Tipo: usuario",
        "Usuario: user2; Tipo: usuario",
    ]
    assert detail_rows[2]["value_lines"] == [
        "Ruta Norte - Módulo de origen 2",
    ]


def test_bulk_route_deletion_history_formats_each_route_on_its_own_line():
    entries = prepare_history_entries(
        [
            {
                "accion": "eliminacion",
                "modificacion": "Eliminó rutas (de Rutas)",
                "descripcion": "IDs de rutas: 39, 144",
                "datos_anteriores": {
                    "Rutas": [
                        {
                            "Ruta": "45",
                            "Tipo": 3,
                            "Origen": "Conti",
                            "Módulo de origen": 2,
                        },
                        {
                            "Ruta": "Sgrhtryt",
                            "Tipo": 1262,
                            "Origen": "Chihuahua",
                            "Módulo de origen": 5,
                        },
                    ],
                    "Módulo afectado": 1,
                },
            }
        ],
        {"1": "Módulo 1", "2": "Módulo 2", "5": "Módulo 5"},
    )

    route_row = next(
        row for row in entries[0]["detail_rows"] if row["field"] == "Rutas"
    )
    assert route_row == {
        "field": "Rutas",
        "value_lines": [
            "45 - Módulo de origen 2",
            "Sgrhtryt - Módulo de origen 5",
        ],
    }
    assert all(
        row["field"] != "Resumen del movimiento"
        for row in entries[0]["detail_rows"]
    )


def test_history_drawer_fields_follow_form_order_and_resolve_shared_modules():
    entries = prepare_history_entries(
        [
            {
                "accion": "vinculacion",
                "modificacion": "Vinculó ruta X a otros módulos",
                "datos_anteriores": None,
                "datos_nuevos": {
                    "Estado": "Activo",
                    "Módulos compartidos": [2, 3],
                    "Servicio": "Ordinario",
                    "Destino": "Terminal",
                    "Origen": "Centro",
                    "Tipo": "Express",
                    "Ruta": "Ruta X",
                },
            }
        ],
        {"2": "Módulo Dos", "3": "Módulo Tres"},
    )

    assert [row["field"] for row in entries[0]["detail_rows"]] == [
        "Ruta",
        "Tipo",
        "Origen",
        "Destino",
        "Servicio",
        "Módulos compartidos",
        "Estado",
    ]
    assert entries[0]["detail_rows"][5]["value"] == "Módulo Dos, Módulo Tres"


def test_history_route_type_ids_render_catalog_descriptions():
    entries = prepare_history_entries(
        [
            {
                "accion": "edicion",
                "modificacion": "Editó ruta Ruta Centro (de Rutas)",
                "datos_anteriores": {"Ruta": "Ruta Centro", "Tipo": 6},
                "datos_nuevos": {"Ruta": "Ruta Centro", "Tipo": "6"},
            }
        ],
        {},
        {"6": "Ruta Oficial RTP"},
    )

    type_comparison = next(
        row for row in entries[0]["comparison_rows"] if row["field"] == "Tipo"
    )
    type_detail = next(
        row for row in entries[0]["detail_rows"] if row["field"] == "Tipo"
    )
    assert type_comparison == {
        "field": "Tipo",
        "before": "Ruta Oficial RTP",
        "after": "Ruta Oficial RTP",
        "changed": False,
    }
    assert type_detail["value"] == "Ruta Oficial RTP"


def test_admin_link_routes_history_includes_origin_and_shared_modules(monkeypatch):
    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def execute(self, query, params):
            assert "SELECT id, ruta, origen, destino, servicio, estado, mod1, tipos" in query
            assert params == ([42],)

        def fetchall(self):
            return [(42, "Ruta Norte", "Centro", "Norte", "Ordinario", "Activo", 1, 3)]

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def cursor(self):
            return FakeCursor()

    histories = []
    monkeypatch.setattr("app.web.initialize_schema", lambda: None)
    monkeypatch.setattr("app.web.request_modules", lambda: [{"id": 2, "nombre": "Módulo Dos"}])
    monkeypatch.setattr("app.web.get_connection", lambda: FakeConnection())
    monkeypatch.setattr("app.web.link_routes_to_module", lambda route_ids, module: 1)
    monkeypatch.setattr("app.web.fetch_shared_modules", lambda route_id: [2])
    monkeypatch.setattr(
        "app.web.record_history",
        lambda *args, **kwargs: histories.append((args, kwargs)),
    )
    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {"username": "administrador", "is_admin": True}

    response = client.post(
        "/administrador/rutas/vincular",
        data={"target_module": "2", "route_ids": ["42"]},
    )

    assert response.status_code == 302
    assert histories[0][0][3] == "vinculacion"
    route_snapshot = histories[0][1]["after"]["Rutas vinculadas"][0]
    assert route_snapshot["Origen"] == "Centro"
    assert route_snapshot["Módulo de origen"] == 1
    assert route_snapshot["Módulos compartidos"] == [2]


def test_admin_user_edit_records_status_comparison(monkeypatch):
    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def execute(self, query, params):
            assert "SELECT username, correo, telefono, module_number" in query
            assert params == (7,)

        def fetchone(self):
            return ("supervisor", "supervisor@example.test", "123", 2, False, "usuario", True)

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def cursor(self):
            return FakeCursor()

    entries = []
    monkeypatch.setattr("app.web.initialize_schema", lambda: None)
    monkeypatch.setattr("app.web.get_connection", lambda: FakeConnection())
    monkeypatch.setattr(
        "app.web.update_user",
        lambda user_id, payload: {
            "id": user_id,
            "username": payload["username"],
            "module_number": payload["module_number"],
            "tipo_usuario": payload["tipo_usuario"],
            "active": payload["active"],
        },
    )
    monkeypatch.setattr(
        "app.web.record_history",
        lambda *args, **kwargs: entries.append((args, kwargs)),
    )

    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {
            "username": "administrador",
            "module_number": None,
            "is_admin": True,
        }

    response = client.post(
        "/administrador/usuarios",
        data={
            "user_id": "7",
            "username": "supervisor",
            "tipo_usuario": "usuario",
            "module_number": "2",
        },
    )

    assert response.status_code == 302
    assert len(entries) == 1
    assert entries[0][0][3] == "edicion"
    assert entries[0][1]["before"]["Estado"] is True
    assert entries[0][1]["after"]["Estado"] is False


def test_admin_route_status_history_uses_route_name(monkeypatch):
    history = []
    monkeypatch.setattr("app.web.initialize_schema", lambda: None)
    monkeypatch.setattr("app.web.fetch_shared_modules", lambda route_id: [2])
    monkeypatch.setattr(
        "app.web.fetch_shared_module_statuses",
        lambda route_id: {2: "Activo"},
    )

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def execute(self, query, params):
            assert "SELECT ruta, origen, destino, servicio, estado, mod1, tipos" in query
            assert params == (9,)

        def fetchone(self):
            return ("Ruta Centro", "Centro", "Terminal", "Ordinario", "Activo", 1, 3)

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr("app.web.get_connection", lambda: FakeConnection())
    monkeypatch.setattr(
        "app.web.update_route_status",
        lambda route_id, status: {"id": route_id, "estado": status, "mod1": 1},
    )
    monkeypatch.setattr(
        "app.web.record_history",
        lambda *args, **kwargs: history.append((args, kwargs)),
    )

    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {"username": "administrador", "is_admin": True}

    response = client.post(
        "/administrador/rutas/9/estado",
        data={"estado": "Inactivo"},
    )

    assert response.status_code == 302
    assert history[0][0][1] == "Ruta Centro inactivo (de Rutas)"


def test_admin_controller_status_history_uses_credential(monkeypatch):
    history = []
    monkeypatch.setattr("app.web.initialize_schema", lambda: None)

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def execute(self, query, params):
            assert "SELECT nombre, credencial, sexo, mod1, active" in query
            assert params == (9,)

        def fetchone(self):
            return ("Ana Pérez", "CR-045", "F", 2, True)

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr("app.web.get_connection", lambda: FakeConnection())
    monkeypatch.setattr(
        "app.web.update_controller_status",
        lambda controller_id, active: {"id": controller_id, "active": active},
    )
    monkeypatch.setattr(
        "app.web.record_history",
        lambda *args, **kwargs: history.append((args, kwargs)),
    )

    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {"username": "administrador", "is_admin": True}

    response = client.post(
        "/administrador/controladores/9/estado",
        data={"estado": "Inactivo"},
    )

    assert response.status_code == 302
    assert history[0][0][1] == "Controlador CR-045 inactivo (de Controladores)"


def test_admin_user_status_history_uses_affected_user_module(monkeypatch):
    history = []
    monkeypatch.setattr("app.web.initialize_schema", lambda: None)
    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def execute(self, query, params):
            assert "SELECT username, correo, telefono, module_number" in query
            assert params == (7,)

        def fetchone(self):
            return ("supervisor", "supervisor@example.test", "123", 3, "usuario", True)

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr("app.web.get_connection", lambda: FakeConnection())
    monkeypatch.setattr(
        "app.web.update_user_status",
        lambda user_id, active: {
            "id": user_id,
            "username": "supervisor",
            "active": active,
            "module_number": 3,
        },
    )
    monkeypatch.setattr(
        "app.web.record_history",
        lambda *args, **kwargs: history.append((args, kwargs)),
    )

    client = app.test_client()
    with client.session_transaction() as session:
        session["account"] = {
            "username": "administrador",
            "module_number": None,
            "is_admin": True,
        }

    response = client.post(
        "/administrador/usuarios/7/estado",
        data={"estado": "Inactivo"},
    )

    assert response.status_code == 302
    assert history[0][0][0]["username"] == "administrador"
    assert history[0][0][2] == 3
    assert history[0][0][3] == "edicion"
    assert history[0][0][1] == "Usuario supervisor inactivo (de Usuarios)"
    assert history[0][1]["before"]["Estado"] is True
    assert history[0][1]["after"]["Estado"] is False
