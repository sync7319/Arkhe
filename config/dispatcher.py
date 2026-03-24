"""
Rate-limited LLM dispatcher — queue-based scheduling with precise wait times.

Instead of 200 tasks independently polling for capacity every 5 seconds,
a small pool of workers drains a shared queue. Slot acquisition is serialized
via an asyncio.Lock so only one worker calculates/claims a slot at a time.
The actual HTTP call runs concurrently after the lock is released.

Result: requests fire at the exact moment capacity opens. Zero wasted slots,
zero thundering herd, maximum throughput within provider rate limits.
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger("arkhe.dispatcher")

# Workers drain the queue concurrently. 10 is enough to keep the network
# saturated (each HTTP call takes 3-10s; 10 in-flight = 30-100 RPM capacity).
WORKER_COUNT = 10
MAX_RETRIES  = 3


@dataclass
class WorkItem:
    pool: list[tuple[str, str]]       # (provider, model) priority list
    system: str
    user_prompt: str
    max_tokens: int
    role: str
    estimated_tokens: int
    future: asyncio.Future
    retries: int = field(default=0, init=False)


class Dispatcher:
    def __init__(self):
        self._queue: asyncio.Queue[WorkItem] = asyncio.Queue()
        self._schedule_lock = asyncio.Lock()
        self._started = False

    async def start(self):
        if self._started:
            return
        self._started = True
        for i in range(WORKER_COUNT):
            asyncio.create_task(self._worker(i))
        logger.info(f"[dispatcher] Started {WORKER_COUNT} workers")

    async def submit(
        self,
        pool: list[tuple[str, str]],
        system: str,
        user_prompt: str,
        max_tokens: int,
        role: str,
    ) -> str:
        if not pool:
            raise RuntimeError("Empty model pool — no API keys configured for this tier. Check your .env.")

        # Auto-start on first submit if not explicitly started
        if not self._started:
            await self.start()

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        estimated = (len(system) + len(user_prompt)) // 4
        item = WorkItem(
            pool=pool,
            system=system,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            role=role,
            estimated_tokens=estimated,
            future=future,
        )
        await self._queue.put(item)
        return await future

    async def _worker(self, worker_id: int):
        """Pull items from the queue and process them forever."""
        while True:
            item = await self._queue.get()
            try:
                result = await self._acquire_and_fire(item)
                if not item.future.done():
                    item.future.set_result(result)
            except Exception as e:
                if not item.future.done():
                    item.future.set_exception(e)
            finally:
                self._queue.task_done()

    async def _acquire_and_fire(self, item: WorkItem) -> str:
        """Acquire a slot (serialized), fire the request (concurrent). Never gives up."""
        from config.model_router import (
            is_cooling, cooling_remaining, try_acquire_slot,
            mark_cooling, time_until_slot_opens,
        )
        from config.llm_client import (
            get_api_key, _dispatch_async,
            _rate_limit_exceptions, _transient_exceptions,
        )

        while True:
            provider = None
            model = None

            # ── Serialized slot acquisition ──────────────────────────
            async with self._schedule_lock:
                best_wait = float("inf")

                for p, m in item.pool:
                    if is_cooling(m):
                        remaining = cooling_remaining(m)
                        if remaining > 0:
                            best_wait = min(best_wait, remaining + 0.5)
                            continue

                    wait = time_until_slot_opens(m, item.estimated_tokens)

                    if wait == float("inf"):
                        continue  # daily limit exhausted, skip

                    if wait == 0.0:
                        # Capacity right now — claim the slot atomically
                        if try_acquire_slot(m, item.estimated_tokens):
                            provider, model = p, m
                            break
                        # Slot was claimed between check and acquire (rare)
                        continue

                    best_wait = min(best_wait, wait)

            # ── If we got a slot, fire the request ───────────────────
            if provider and model:
                result = await self._fire(item, provider, model)
                if result is not None:
                    return result
                # result is None = recoverable error, loop back to re-acquire
                continue

            # ── No slot available — sleep precisely, then retry ──────
            if best_wait == float("inf"):
                # All models cooling or daily-exhausted
                min_cool = min(
                    (cooling_remaining(m) for _, m in item.pool),
                    default=30,
                )
                sleep_time = max(min_cool, 1) + 0.5
                logger.debug(f"[dispatcher/{item.role}] all models unavailable — sleeping {sleep_time:.1f}s")
                await asyncio.sleep(sleep_time)
            else:
                # Sleep until the exact moment a slot opens (+ tiny buffer)
                sleep_time = best_wait + 0.1
                logger.debug(f"[dispatcher/{item.role}] next slot in {sleep_time:.1f}s")
                await asyncio.sleep(sleep_time)

    async def _fire(self, item: WorkItem, provider: str, model: str) -> str | None:
        """Execute the LLM call. Returns result string, or None to signal retry."""
        from config.model_router import mark_cooling
        from config.llm_client import (
            get_api_key, _dispatch_async,
            _rate_limit_exceptions, _transient_exceptions,
        )

        try:
            api_key = get_api_key(provider)
        except ValueError:
            logger.warning(f"[dispatcher] No API key for {provider} — skipping {model}")
            return None

        rate_limit_exc = _rate_limit_exceptions(provider)
        transient_exc  = _transient_exceptions(provider)

        try:
            result = await _dispatch_async(
                provider, model, api_key,
                item.system, item.user_prompt, item.max_tokens,
            )
            logger.debug(f"[dispatcher/{item.role}] {model} succeeded")
            item.retries = 0
            return result

        except rate_limit_exc:
            mark_cooling(model, provider)
            logger.warning(f"[dispatcher/{item.role}] 429 on {model} — cooling")
            return None  # re-acquire with next model

        except transient_exc as e:
            item.retries += 1
            logger.warning(f"[dispatcher/{item.role}] transient error on {model} (attempt {item.retries}): {e}")
            if item.retries < MAX_RETRIES:
                await asyncio.sleep(2 * item.retries)
            return None

        except Exception as e:
            err = str(e)
            if "NVIDIA_EMPTY_CONTENT" in err:
                logger.warning(f"[dispatcher/{item.role}] {model} returned empty — will retry")
                await asyncio.sleep(2)
                return None
            if "404" in err or "NOT_FOUND" in err:
                mark_cooling(model, provider)
                logger.warning(f"[dispatcher/{item.role}] {model} not found (404) — cooling")
                return None
            # Truly non-retryable
            logger.error(f"[dispatcher/{item.role}] fatal error on {model}: {e}")
            raise


# ── Singleton ────────────────────────────────────────────────────────────────

_dispatcher: Dispatcher | None = None


def get_dispatcher() -> Dispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = Dispatcher()
    return _dispatcher


async def start_dispatcher():
    d = get_dispatcher()
    await d.start()
