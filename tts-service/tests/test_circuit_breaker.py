import pytest
from datetime import datetime, timedelta
from app.core.circuit_breaker import CircuitBreaker, CircuitState, CircuitBreakerOpenError


class TestCircuitBreaker:
    @pytest.fixture
    def circuit_breaker(self):
        return CircuitBreaker(
            name='test',
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

    def test_record_success_transitions_half_open_to_closed(self):
        cb = CircuitBreaker(
            name='test_half_open',
            failure_threshold=2,
            recovery_timeout=1,
        )
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        cb._last_failure_time = datetime.now() - timedelta(seconds=2)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb._failure_count == 0

    @pytest.mark.asyncio
    async def test_call_with_async_function(self):
        cb = CircuitBreaker(name='test_async', failure_threshold=3)

        async def async_func(x, y):
            return x + y

        result = await cb.call(async_func, 2, 3)
        assert result == 5
        assert cb.state == CircuitState.CLOSED

    def test_circuit_breaker_open_error(self):
        cb = CircuitBreaker(name='test_error', failure_threshold=1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        with pytest.raises(CircuitBreakerOpenError, match='Circuit test_error is open'):
            if not cb.can_execute():
                raise CircuitBreakerOpenError(f'Circuit {cb.name} is open')

    def test_half_open_max_calls_behavior(self):
        cb = CircuitBreaker(
            name='test_half_open_calls',
            failure_threshold=2,
            recovery_timeout=1,
            half_open_max_calls=1,
        )
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        cb._last_failure_time = datetime.now() - timedelta(seconds=2)
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.can_execute() is True
        cb._half_open_calls = 1
        assert cb.can_execute() is False
