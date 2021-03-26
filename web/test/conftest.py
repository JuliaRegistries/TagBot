import pytest

from src import app


@pytest.fixture
def client():
    with app.test_client() as client:
        yield client


@app.route("/die")
def die():
    raise Exception("!")
