"""Centralized Ollama model coordination to minimize VRAM thrashing.

This module provides intelligent model management to:
- Track which models are currently loaded in VRAM
- Queue requests when VRAM is insufficient
- Unload least-recently-used models when needed
- Prevent concurrent model switches that cause thrashing

Usage:
    coordinator = get_coordinator()
    if await coordinator.acquire_model("qwen2.5:7b"):
        try:
            # Use the model
            ...
        finally:
            await coordinator.release_model("qwen2.5:7b")
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


class ModelStatus(Enum):
    """Status of a model in the coordinator."""
    UNLOADED = "unloaded"
    LOADING = "loading"
    LOADED = "loaded"
    UNLOADING = "unloading"


@dataclass
class ModelState:
    """Tracks the state of a single model."""
    status: ModelStatus = ModelStatus.UNLOADED
    last_used: Optional[datetime] = None
    vram_mb: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    waiters: int = 0


class ModelCoordinator:
    """Coordinates model loading/unloading to minimize VRAM thrashing.

    The coordinator maintains a registry of known models and their estimated
    VRAM usage. When a request comes in for a model that would exceed the
    available VRAM budget, it unloads the least-recently-used models first.

    Key features:
    - Per-model locking to prevent concurrent load/unload of same model
    - VRAM budget tracking to avoid OOM errors
    - LRU eviction policy for model unloading
    - Waiter counting to avoid unloading models with pending requests
    """

    # Estimated VRAM usage per model (in MB)
    # These are approximations - actual usage varies by quantization and context
    MODEL_VRAM_MB = {
        # Vision models
        "qwen2.5vl:7b": 6000,
        "qwen3-vl:8b": 6500,
        "deepseek-vl2": 6000,
        # Text models
        "qwen2.5:7b": 4700,
        "qwen2.5:14b": 9000,
        # Polish models
        "SpeakLeash/bielik-11b-v3.0-instruct:Q5_K_M": 9600,
        # Embedding models (small)
        "nomic-embed-text": 274,
        "mxbai-embed-large": 670,
    }

    # Default VRAM estimate for unknown models
    DEFAULT_VRAM_MB = 5000

    def __init__(self, max_vram_mb: int = 12000):
        """Initialize the coordinator.

        Args:
            max_vram_mb: Maximum VRAM budget in megabytes (default 12GB)
        """
        self.max_vram_mb = max_vram_mb
        self._models: dict[str, ModelState] = {}
        self._global_lock = asyncio.Lock()
        self._metrics = {
            "acquisitions": 0,
            "releases": 0,
            "evictions": 0,
            "timeouts": 0,
        }

    def _get_model_state(self, model: str) -> ModelState:
        """Get or create state tracking for a model."""
        if model not in self._models:
            vram = self.MODEL_VRAM_MB.get(model, self.DEFAULT_VRAM_MB)
            self._models[model] = ModelState(vram_mb=vram)
        return self._models[model]

    def _current_vram_usage(self) -> int:
        """Calculate current VRAM usage from loaded models."""
        return sum(
            s.vram_mb for s in self._models.values()
            if s.status == ModelStatus.LOADED
        )

    def _get_eviction_candidates(self) -> list[tuple[str, ModelState]]:
        """Get models that can be evicted, sorted by LRU (oldest first)."""
        candidates = [
            (name, state) for name, state in self._models.items()
            if state.status == ModelStatus.LOADED and state.waiters == 0
        ]
        # Sort by last_used (oldest first, None = very old)
        candidates.sort(key=lambda x: x[1].last_used or datetime.min)
        return candidates

    async def acquire_model(self, model: str, timeout: float = None) -> bool:
        """Request access to a model, waiting if necessary.

        This method ensures the model is loaded and ready for use. If VRAM
        is insufficient, it will evict other models first. If the model
        is already being loaded by another request, it will wait.

        Args:
            model: The model name (e.g., "qwen2.5:7b")
            timeout: Maximum time to wait in seconds (default from settings)

        Returns:
            True if the model was acquired, False on timeout
        """
        if not settings.MODEL_COORDINATION_ENABLED:
            return True

        if timeout is None:
            timeout = float(settings.MODEL_SWITCH_QUEUE_TIMEOUT)

        state = self._get_model_state(model)
        state.waiters += 1

        try:
            async with asyncio.timeout(timeout):
                async with state.lock:
                    # Check if we need to free VRAM
                    needed_vram = state.vram_mb
                    current_vram = self._current_vram_usage()

                    if state.status != ModelStatus.LOADED:
                        if current_vram + needed_vram > self.max_vram_mb:
                            # Need to evict some models first
                            freed = await self._free_vram(needed_vram)
                            logger.debug(f"Freed {freed}MB VRAM for {model}")

                        state.status = ModelStatus.LOADED
                        logger.info(
                            f"Model {model} acquired "
                            f"(VRAM: {self._current_vram_usage()}MB / {self.max_vram_mb}MB)"
                        )

                    state.last_used = datetime.now()
                    self._metrics["acquisitions"] += 1
                    return True

        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for model {model} after {timeout}s")
            self._metrics["timeouts"] += 1
            return False
        finally:
            state.waiters -= 1

    async def release_model(self, model: str) -> None:
        """Release a model after use.

        This doesn't unload the model immediately - it just updates the
        last_used timestamp so the LRU eviction can work properly.

        Args:
            model: The model name to release
        """
        if not settings.MODEL_COORDINATION_ENABLED:
            return

        state = self._get_model_state(model)
        state.last_used = datetime.now()
        self._metrics["releases"] += 1

    async def _free_vram(self, needed_mb: int) -> int:
        """Unload models to free at least needed_mb of VRAM.

        Uses LRU eviction policy - unloads the least recently used models
        that don't have waiters.

        Args:
            needed_mb: Minimum VRAM to free in megabytes

        Returns:
            Total VRAM freed in megabytes
        """
        # Import here to avoid circular dependency
        from app import ollama_client

        candidates = self._get_eviction_candidates()
        freed = 0

        for name, state in candidates:
            if freed >= needed_mb:
                break

            logger.info(f"Evicting model {name} to free {state.vram_mb}MB VRAM")
            state.status = ModelStatus.UNLOADING

            try:
                await ollama_client.unload_model(name)
                state.status = ModelStatus.UNLOADED
                freed += state.vram_mb
                self._metrics["evictions"] += 1
            except Exception as e:
                logger.warning(f"Failed to unload model {name}: {e}")
                # Reset status since unload failed
                state.status = ModelStatus.LOADED

        return freed

    async def force_unload(self, model: str) -> bool:
        """Force unload a specific model.

        Use this when you explicitly want to free VRAM for a known model.

        Args:
            model: The model name to unload

        Returns:
            True if unloaded successfully
        """
        if model not in self._models:
            return True

        state = self._models[model]
        if state.status != ModelStatus.LOADED:
            return True

        from app import ollama_client

        async with state.lock:
            state.status = ModelStatus.UNLOADING
            try:
                await ollama_client.unload_model(model)
                state.status = ModelStatus.UNLOADED
                logger.info(f"Force unloaded model {model}")
                return True
            except Exception as e:
                logger.warning(f"Failed to force unload {model}: {e}")
                state.status = ModelStatus.LOADED
                return False

    async def free_vram_for_external(self, needed_mb: int) -> int:
        """Free VRAM for an external model (e.g., Whisper, Torch).

        Use this before loading non-Ollama models that need GPU memory.
        Evicts Ollama models using LRU policy until enough VRAM is available.

        Args:
            needed_mb: Minimum VRAM to free in megabytes

        Returns:
            Total VRAM freed in megabytes
        """
        if not settings.MODEL_COORDINATION_ENABLED:
            return 0

        current_usage = self._current_vram_usage()
        available = self.max_vram_mb - current_usage

        if available >= needed_mb:
            logger.debug(
                f"Sufficient VRAM available ({available}MB >= {needed_mb}MB needed)"
            )
            return 0

        to_free = needed_mb - available
        logger.info(
            f"Freeing {to_free}MB VRAM for external model "
            f"(current: {current_usage}MB, need: {needed_mb}MB)"
        )
        return await self._free_vram(to_free)

    def get_status(self) -> dict:
        """Get current status of all tracked models.

        Returns:
            Dictionary with model states and metrics
        """
        return {
            "models": {
                name: {
                    "status": state.status.value,
                    "vram_mb": state.vram_mb,
                    "last_used": state.last_used.isoformat() if state.last_used else None,
                    "waiters": state.waiters,
                }
                for name, state in self._models.items()
            },
            "total_vram_mb": self._current_vram_usage(),
            "max_vram_mb": self.max_vram_mb,
            "metrics": self._metrics.copy(),
        }

    def mark_model_loaded(self, model: str) -> None:
        """Mark a model as loaded (for external loads like ollama API).

        Call this when a model is loaded outside the coordinator's control
        (e.g., when ollama auto-loads on first request).

        Args:
            model: The model name that was loaded
        """
        state = self._get_model_state(model)
        state.status = ModelStatus.LOADED
        state.last_used = datetime.now()


# Singleton instance
_coordinator: Optional[ModelCoordinator] = None


def get_coordinator() -> ModelCoordinator:
    """Get the singleton ModelCoordinator instance.

    The coordinator is created lazily on first access, using the
    MODEL_MAX_VRAM_MB setting for the VRAM budget.

    Returns:
        The singleton ModelCoordinator
    """
    global _coordinator
    if _coordinator is None:
        _coordinator = ModelCoordinator(
            max_vram_mb=settings.MODEL_MAX_VRAM_MB
        )
    return _coordinator


def reset_coordinator() -> None:
    """Reset the coordinator (for testing purposes)."""
    global _coordinator
    _coordinator = None
