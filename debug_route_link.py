import sys
sys.path.insert(0, '.')

from app.web import app
from app.db import get_connection, initialize_schema

initialize_schema()

with app.test_client() as client:
    with client.session_transaction() as session:
        session['account'] = {'username': 'user3', 'module_number': 3, 'is_admin': False}

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO catalogos.rutas (nomenclatura, ruta, origen, destino, servicio, estado, mod1) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                ('Z', 'Ruta Externa Prueba', 'Origen A', 'Destino A', 'Servicio A', 'Activo', 1),
            )
            route_id = cursor.fetchone()[0]
            connection.commit()
            print('INSERTED_ROUTE_ID', route_id)

    get_resp = client.get('/api/modulos/3/rutas-externas?origen_id=1&q=externa')
    print('GET_STATUS', get_resp.status_code)
    print('GET_JSON', get_resp.get_json())

    post_resp = client.post('/api/modulos/3/rutas/vincular', json={'ruta_id': route_id})
    print('POST_STATUS', post_resp.status_code)
    print('POST_JSON', post_resp.get_json())

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT id, mod1, ruta FROM catalogos.rutas WHERE id = %s', (route_id,))
            print('ROUTE_ROW', cursor.fetchone())
            cursor.execute('SELECT * FROM catalogos.modulo_ruta WHERE ruta_id = %s AND modulo_id = %s', (route_id, 3))
            print('MODULE_LINK_ROW', cursor.fetchone())
