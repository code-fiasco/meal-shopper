"""Navigation and placeholder pages."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

PAGES = (
    ("/", "Planner"),
    ("/meals", "Meals"),
    ("/ingredients", "Ingredients"),
    ("/shopping", "Shopping"),
    ("/stock", "Stock"),
    ("/spending", "Spending"),
)


@pytest.fixture
def client(database_url: str) -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.mark.parametrize(("path", "heading"), PAGES)
def test_placeholder_page(client: TestClient, path: str, heading: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    body = response.text
    assert f"<h1>{heading}</h1>" in body
    assert 'src="/static/htmx.min.js"' in body
    assert 'href="/static/app.css"' in body
    assert "https://" not in body
    assert "http://" not in body
    for link, label in PAGES:
        assert f'href="{link}"' in body
        assert f">{label}</a>" in body


def test_current_page_is_not_colour_alone(client: TestClient) -> None:
    response = client.get("/meals")
    assert 'href="/meals" aria-current="page"' in response.text


def test_htmx_is_vendored(client: TestClient) -> None:
    response = client.get("/static/htmx.min.js")
    assert response.status_code == 200
    assert "htmx" in response.text.lower()


def test_stylesheet_has_visible_focus(client: TestClient) -> None:
    response = client.get("/static/app.css")
    assert response.status_code == 200
    assert ":focus-visible" in response.text
