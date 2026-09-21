from app.web import app
from app.db import get_connection


def _create_route(module_number: int, route_name: str = "Ruta Externa"):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO catalogos.rutas (nomenclatura, ruta, origen, destino, servicio, estado, mod1)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                ("Z", route_name, "Origen A", "Destino A", "Servicio A", "Activo", module_number),
            )
            route_id = cursor.fetchone()[0]
        connection.commit()
        return route_id


def test_rutas_externas_crud_flow():
    with app.test_client() as client:
        with client.session_transaction() as session:
            session["account"] = {"username": "user3", "module_number": 3, "is_admin": False}

        ruta_id = _create_route(1, "Ruta Externa Prueba")

        response = client.get("/api/modulos/3/rutas-externas?origen_id=1&q=externa")
        assert response.status_code == 200
        payload = response.get_json()
        assert isinstance(payload, list)

        post_response = client.post(
            "/api/modulos/3/rutas/vincular",
            json={"ruta_id": ruta_id},
        )
        assert post_response.status_code == 201
        data = post_response.get_json()
        assert data["ruta_id"] == ruta_id
        assert data["estado"] == "Activo"

        patch_response = client.patch(
            f"/api/modulos/3/rutas/{ruta_id}/estado",
            json={"estado": "Inactivo"},
        )
        assert patch_response.status_code == 200
        assert patch_response.get_json()["estado"] == "Inactivo"

        delete_response = client.delete(f"/api/modulos/3/rutas/{ruta_id}/desvincular")
        assert delete_response.status_code == 200
        assert delete_response.get_json()["deleted"] is True
