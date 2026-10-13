"""
Concurrency and Hardware Resource Management (Phase 3).
Provides thread-safe and async-safe serialization for GPU/VRAM access on local hardware (4GB VRAM constraint).
Tracks active workers, queue depth, throughput metrics, and prevents GPU OOM / thrashing.
"""
import asyncio
import os
import threading
import time
from contextlib import contextmanager, asynccontextmanager
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends
from backend.auth import User, get_current_user

router = APIRouter(prefix="/concurrency", tags=["Concurrency"])


class GPUConcurrencyManager:
    """
    Manages serialized GPU access to prevent VRAM out-of-memory errors
    when multiple concurrent client requests hit local LLM inference engines.
    """

    def __init__(self, max_concurrency: int = 1):
        self.max_concurrency = max(1, int(os.getenv("MAX_GPU_CONCURRENCY", str(max_concurrency))))
        self._thread_lock = threading.Lock()
        self._semaphore = threading.Semaphore(self.max_concurrency)
        self._async_semaphore: Optional[asyncio.Semaphore] = None
        self._active_workers = 0
        self._waiting_count = 0
        self._total_processed = 0
        self._total_wait_time = 0.0
        self._peak_queue_depth = 0

    def _ensure_async_semaphore(self) -> asyncio.Semaphore:
        if self._async_semaphore is None:
            self._async_semaphore = asyncio.Semaphore(self.max_concurrency)
        return self._async_semaphore

    @contextmanager
    def acquire(self):
        """Synchronous context manager for thread-safe GPU acquisition."""
        t0 = time.perf_counter()
        with self._thread_lock:
            self._waiting_count += 1
            if self._waiting_count > self._peak_queue_depth:
                self._peak_queue_depth = self._waiting_count

        acquired = self._semaphore.acquire(timeout=300)
        try:
            wait_duration = time.perf_counter() - t0
            with self._thread_lock:
                self._waiting_count = max(0, self._waiting_count - 1)
                if acquired:
                    self._active_workers += 1
                    self._total_wait_time += wait_duration

            if not acquired:
                raise TimeoutError("Timed out waiting for GPU inference slot (exceeded 300s).")
            yield
        finally:
            if acquired:
                with self._thread_lock:
                    self._active_workers = max(0, self._active_workers - 1)
                    self._total_processed += 1
                self._semaphore.release()

    @asynccontextmanager
    async def acquire_async(self):
        """Asynchronous context manager for coroutine-safe GPU acquisition."""
        sem = self._ensure_async_semaphore()
        t0 = time.perf_counter()
        with self._thread_lock:
            self._waiting_count += 1
            if self._waiting_count > self._peak_queue_depth:
                self._peak_queue_depth = self._waiting_count

        try:
            await sem.acquire()
            wait_duration = time.perf_counter() - t0
            with self._thread_lock:
                self._waiting_count = max(0, self._waiting_count - 1)
                self._active_workers += 1
                self._total_wait_time += wait_duration
            yield
        finally:
            with self._thread_lock:
                self._active_workers = max(0, self._active_workers - 1)
                self._total_processed += 1
            sem.release()

    def get_metrics(self) -> Dict[str, Any]:
        """Returns live hardware concurrency telemetry."""
        with self._thread_lock:
            avg_wait = (
                round(self._total_wait_time / self._total_processed, 4)
                if self._total_processed > 0
                else 0.0
            )
            return {
                "max_concurrency": self.max_concurrency,
                "active_workers": self._active_workers,
                "queue_depth": self._waiting_count,
                "peak_queue_depth": self._peak_queue_depth,
                "total_processed": self._total_processed,
                "average_wait_seconds": avg_wait,
                "vram_policy": "Serialized (4GB Dedicated VRAM Safety)",
            }


# Singleton GPU concurrency manager
gpu_manager = GPUConcurrencyManager(max_concurrency=1)


@router.get("/status")
def get_concurrency_status(current_user: User = Depends(get_current_user)):
    """Returns real-time GPU concurrency and queue status."""
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "telemetry": gpu_manager.get_metrics(),
    }
