"""Small public-CLI E2E fixture."""

E2E_REVISION = 1


def worker(value: int) -> int:
    # @trace FR-001
    return value + 1


def entry(value: int) -> int:
    # @trace FR-001
    return worker(value)


def test_worker_contract() -> None:
    # @trace FR-001
    # @test-id TEST-FR-001
    assert worker(1) == 2
