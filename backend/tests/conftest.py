import pytest
from _pytest.monkeypatch import MonkeyPatch


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="run tests that require external services such as Docker PostgreSQL",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-integration"):
        return

    skip_integration = pytest.mark.skip(reason="need --run-integration to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)


@pytest.fixture(autouse=True)
def block_unit_test_embedding_network(
    request: pytest.FixtureRequest,
    monkeypatch: MonkeyPatch,
) -> None:
    if "integration" in request.keywords:
        return

    def blocked_urlopen(*args: object, **kwargs: object) -> object:
        raise AssertionError("Unit tests must not make embedding network calls")

    monkeypatch.setattr("app.providers.embeddings.request.urlopen", blocked_urlopen)
