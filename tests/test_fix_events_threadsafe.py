import asyncio
import threading

from treemem.events import EventBus


def test_worker_thread_emit_reaches_event_loop_subscriber(tmp_path):
    async def run():
        bus = EventBus(tmp_path / "vault")
        queue = bus.subscribe()
        worker = threading.Thread(target=lambda: bus.emit("recall", {"path": "/"}))
        worker.start(); worker.join()
        received = await asyncio.wait_for(queue.get(), timeout=1)
        assert received["type"] == "recall"
        bus.unsubscribe(queue)
    asyncio.run(run())
