from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.main import montar_frontend


def test_sirve_el_index_del_frontend_compilado(tmp_path):
    (tmp_path / "index.html").write_text("<h1>Calidades CUMS</h1>", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log(1)", encoding="utf-8")
    aplicacion = FastAPI()
    assert montar_frontend(aplicacion, tmp_path) is True
    cliente = TestClient(aplicacion)
    assert "Calidades CUMS" in cliente.get("/").text
    assert cliente.get("/app.js").status_code == 200


def test_sin_dist_no_monta_nada(tmp_path):
    assert montar_frontend(FastAPI(), tmp_path) is False
