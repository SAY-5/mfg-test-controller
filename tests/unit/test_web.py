"""Unit tests for the Flask web UI."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from flask.testing import FlaskClient

from mfg_test_controller.web import WebConfig, create_app

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def client(tmp_path: Path) -> Iterator[FlaskClient]:
    db_url = f"sqlite:///{tmp_path / 'web-test.db'}"
    config = WebConfig(
        db_url=db_url,
        plans_dir=REPO_ROOT / "plans",
        profiles_dir=REPO_ROOT / "profiles",
    )
    app = create_app(config)
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def test_healthz_returns_ok(client: FlaskClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.data == b"ok"


def test_index_renders_plans_and_recent(client: FlaskClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    body = response.data.decode()
    assert "station_bringup" in body
    assert "mfg-test-controller" in body


def test_plans_json_lists_station_bringup(client: FlaskClient) -> None:
    response = client.get("/plans")
    assert response.status_code == 200
    payload = response.get_json()
    assert isinstance(payload, list)
    names = [entry["name"] for entry in payload]
    assert "station_bringup" in names
    entry = next(e for e in payload if e["name"] == "station_bringup")
    assert entry["steps_count"] == 11
    assert entry["path"].endswith("station_bringup.yaml")


def test_post_unknown_plan_returns_404(client: FlaskClient) -> None:
    response = client.post("/plans/does_not_exist/run")
    assert response.status_code == 404
    assert "error" in response.get_json()


def test_runs_page_renders_empty(client: FlaskClient) -> None:
    response = client.get("/runs")
    assert response.status_code == 200
    assert b"All runs" in response.data


def test_trends_page_renders_empty(client: FlaskClient) -> None:
    response = client.get("/trends")
    assert response.status_code == 200
    assert b"Measurement trends" in response.data


def test_stream_unknown_run_returns_404(client: FlaskClient) -> None:
    response = client.get("/runs/stream/deadbeef")
    assert response.status_code == 404


def test_static_app_js_loads(client: FlaskClient) -> None:
    response = client.get("/static/app.js")
    assert response.status_code == 200
    assert b"EventSource" in response.data


def test_static_style_css_loads(client: FlaskClient) -> None:
    response = client.get("/static/style.css")
    assert response.status_code == 200
    assert b".card" in response.data
