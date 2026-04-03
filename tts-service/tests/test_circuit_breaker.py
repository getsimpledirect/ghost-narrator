import pytest
from datetime import datetime, timedelta
from app.core.circuit_breaker import CircuitBreaker, CircuitState


class TestCircuitBreaker:
    @pytest.fixture
    def circuit_breaker(self):
        return CircuitBreaker(
            name="test",
            failure_threshold=3,
            recovery_timeout=5,
        )

    def test_initial_state_is_closed(self, circuit_breaker):
        assert circuit_breaker.state == CircuitState.CLOSED

    def test_opens_after_threshold_failures(self, circuit_breaker):
        for _ in range(3):
            circuit_breaker.record_failure()
        assert circuit_breaker.state == CircuitState.OPEN

    def test_half_open_after_recovery_timeout(self, circuit_breaker):
        for _ in range(3):
            circuit_breaker.record_failure()
        circuit_breaker._last_failure_time = datetime.now() - timedelta(seconds=6)
        assert circuit_breaker.can_execute() is True

    def test_allows_execution_when_closed(self, circuit_breaker):
        assert circuit_breaker.can_execute() is True
