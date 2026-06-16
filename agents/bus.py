"""
EventBus abstraction.

BE_EVENT_BUS=eager    -> EagerEventBus (dev/test: in-process await, no broker)
BE_EVENT_BUS=redpanda -> RedpandaEventBus (prod: aiokafka + Redpanda)
"""
import asyncio
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Callable, Awaitable
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from backend.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Topic registry (authoritative list of all event topics)
# ---------------------------------------------------------------------------

TOPICS = [
    "audit.created",
    "audit.cancelled",
    "discovery.started",
    "discovery.completed",
    "static.started",
    "static.completed",
    "dynamic.started",
    "dynamic.completed",
    "evidence.created",
    "finding.created",
    "report.requested",
    "report.generated",
    "audit.completed",
    "audit.failed",
]

# ---------------------------------------------------------------------------
# EventEnvelope
# ---------------------------------------------------------------------------


class EventEnvelope(BaseModel):
    """Canonical event message passed over every topic."""

    event_id: UUID = Field(default_factory=uuid4)
    event_type: str
    audit_id: UUID
    task_id: UUID | None = None
    correlation_id: str
    causation_id: str | None = None
    emitted_at: datetime = Field(default_factory=datetime.utcnow)
    payload: dict[str, Any] = Field(default_factory=dict)


HandlerFn = Callable[[EventEnvelope], Awaitable[None]]


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class EventBus(ABC):
    @abstractmethod
    async def publish(self, topic: str, envelope: EventEnvelope) -> None: ...

    @abstractmethod
    async def subscribe(self, topic: str, handler: HandlerFn) -> None: ...

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...


# ---------------------------------------------------------------------------
# EagerEventBus — dev/test backend
# ---------------------------------------------------------------------------


class EagerEventBus(EventBus):
    """Dev/test: directly awaits handlers in-process. No broker required."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[HandlerFn]] = {}

    async def publish(self, topic: str, envelope: EventEnvelope) -> None:
        handlers = self._handlers.get(topic, [])
        logger.debug(
            "EagerBus.publish",
            extra={
                "topic": topic,
                "event_id": str(envelope.event_id),
                "audit_id": str(envelope.audit_id),
            },
        )
        for h in handlers:
            await h(envelope)

    async def subscribe(self, topic: str, handler: HandlerFn) -> None:
        self._handlers.setdefault(topic, []).append(handler)

    async def start(self) -> None:
        logger.info("EagerEventBus started")

    async def stop(self) -> None:
        logger.info("EagerEventBus stopped")


# ---------------------------------------------------------------------------
# RedpandaEventBus — production backend
# ---------------------------------------------------------------------------


class RedpandaEventBus(EventBus):
    """Production: aiokafka producer/consumer against Redpanda."""

    def __init__(self, bootstrap_servers: str) -> None:
        self._bootstrap = bootstrap_servers
        self._producer: Any = None
        self._consumers: list[Any] = []
        self._handlers: dict[str, list[HandlerFn]] = {}
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        from aiokafka import AIOKafkaProducer

        self._producer = AIOKafkaProducer(bootstrap_servers=self._bootstrap)
        await self._producer.start()
        logger.info(
            "RedpandaEventBus producer started",
            extra={"servers": self._bootstrap},
        )

    async def stop(self) -> None:
        if self._producer:
            await self._producer.stop()
        for t in self._tasks:
            t.cancel()
        logger.info("RedpandaEventBus stopped")

    async def publish(self, topic: str, envelope: EventEnvelope) -> None:
        if not self._producer:
            raise RuntimeError("RedpandaEventBus not started")
        payload = envelope.model_dump_json().encode()
        key = str(envelope.audit_id).encode()
        await self._producer.send_and_wait(topic, value=payload, key=key)
        logger.debug(
            "RedpandaBus.publish",
            extra={"topic": topic, "audit_id": str(envelope.audit_id)},
        )

    async def subscribe(self, topic: str, handler: HandlerFn) -> None:
        self._handlers.setdefault(topic, []).append(handler)
        from aiokafka import AIOKafkaConsumer

        consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=self._bootstrap,
            group_id=f"pp-{topic}",
        )
        self._consumers.append(consumer)
        task = asyncio.create_task(self._consume(consumer, topic))
        self._tasks.append(task)

    async def _consume(self, consumer: Any, topic: str) -> None:
        await consumer.start()
        try:
            async for msg in consumer:
                envelope = EventEnvelope.model_validate_json(msg.value)
                for h in self._handlers.get(topic, []):
                    await h(envelope)
        finally:
            await consumer.stop()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_event_bus() -> EventBus:
    """Return the configured EventBus backend based on BE_EVENT_BUS setting."""
    from backend.config import settings

    if settings.event_bus == "redpanda":
        return RedpandaEventBus(settings.redpanda_bootstrap_servers)
    return EagerEventBus()
