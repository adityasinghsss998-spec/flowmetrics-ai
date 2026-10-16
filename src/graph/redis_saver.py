import asyncio
import pickle
import random
from typing import Any, AsyncIterator, Sequence
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
    get_checkpoint_metadata,
    WRITES_IDX_MAP,
)
import redis.asyncio as aioredis


class AsyncRedisCheckpointSaver(BaseCheckpointSaver):
    """Async Redis checkpoint saver storing LangGraph checkpoints under
    ai_run:{thread_id} with 24h TTL, as specified in AGENTS.md.
    Uses Redis Hashes to avoid race conditions between concurrent aput and aput_writes."""

    def __init__(self, redis_client: aioredis.Redis, ttl: int = 86400):
        super().__init__()
        self.redis = redis_client
        self.ttl = ttl
        self._lock = asyncio.Lock()

    async def _get_field(self, thread_id: str, field: str) -> dict:
        raw = await self.redis.hget(f"ai_run:{thread_id}", field)
        if not raw:
            return {}
        try:
            return pickle.loads(raw if isinstance(raw, bytes) else raw.encode("latin1"))
        except Exception:
            return {}

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        thread_id: str = config["configurable"]["thread_id"]
        checkpoint_ns: str = config["configurable"].get("checkpoint_ns", "")

        async with self._lock:
            all_fields = await self.redis.hgetall(f"ai_run:{thread_id}")

        if not all_fields:
            return None

        def _unpack(key_name: bytes | str) -> dict:
            val = all_fields.get(key_name) or (all_fields.get(key_name.decode()) if isinstance(key_name, bytes) else all_fields.get(key_name.encode()))
            if not val:
                return {}
            try:
                return pickle.loads(val if isinstance(val, bytes) else val.encode("latin1"))
            except Exception:
                return {}

        storage_dict = _unpack(b"storage")
        writes_dict = _unpack(b"writes")
        blobs_dict = _unpack(b"blobs")

        storage = storage_dict.get(checkpoint_ns, {})

        def _load_blobs(thread_id: str, checkpoint_ns: str, versions: ChannelVersions) -> dict[str, Any]:
            return {
                k: self.serde.loads_typed(blobs_dict[(thread_id, checkpoint_ns, k, v)])
                for k, v in versions.items()
                if (thread_id, checkpoint_ns, k, v) in blobs_dict
                and blobs_dict[(thread_id, checkpoint_ns, k, v)][0] != "empty"
            }

        if checkpoint_id := get_checkpoint_id(config):
            if saved := storage.get(checkpoint_id):
                checkpoint, metadata, parent_checkpoint_id = saved
                writes = writes_dict.get((thread_id, checkpoint_ns, checkpoint_id), {}).values()
                checkpoint_: Checkpoint = self.serde.loads_typed(checkpoint)
                return CheckpointTuple(
                    config=config,
                    checkpoint={
                        **checkpoint_,
                        "channel_values": _load_blobs(
                            thread_id, checkpoint_ns, checkpoint_["channel_versions"]
                        ),
                    },
                    metadata=self.serde.loads_typed(metadata),
                    pending_writes=[
                        (id, c, self.serde.loads_typed(v)) for id, c, v, _ in writes
                    ],
                    parent_config=(
                        {
                            "configurable": {
                                "thread_id": thread_id,
                                "checkpoint_ns": checkpoint_ns,
                                "checkpoint_id": parent_checkpoint_id,
                            }
                        }
                        if parent_checkpoint_id
                        else None
                    ),
                )
        else:
            if storage:
                checkpoint_id = max(storage.keys())
                checkpoint, metadata, parent_checkpoint_id = storage[checkpoint_id]
                writes = writes_dict.get((thread_id, checkpoint_ns, checkpoint_id), {}).values()
                checkpoint_ = self.serde.loads_typed(checkpoint)
                return CheckpointTuple(
                    config={
                        "configurable": {
                            "thread_id": thread_id,
                            "checkpoint_ns": checkpoint_ns,
                            "checkpoint_id": checkpoint_id,
                        }
                    },
                    checkpoint={
                        **checkpoint_,
                        "channel_values": _load_blobs(
                            thread_id, checkpoint_ns, checkpoint_["channel_versions"]
                        ),
                    },
                    metadata=self.serde.loads_typed(metadata),
                    pending_writes=[
                        (id, c, self.serde.loads_typed(v)) for id, c, v, _ in writes
                    ],
                    parent_config=(
                        {
                            "configurable": {
                                "thread_id": thread_id,
                                "checkpoint_ns": checkpoint_ns,
                                "checkpoint_id": parent_checkpoint_id,
                            }
                        }
                        if parent_checkpoint_id
                        else None
                    ),
                )
        return None

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")

        c = checkpoint.copy()
        values: dict[str, Any] = c.pop("channel_values")

        async with self._lock:
            storage_dict = await self._get_field(thread_id, "storage")
            blobs_dict = await self._get_field(thread_id, "blobs")

            for k, v in new_versions.items():
                blobs_dict[(thread_id, checkpoint_ns, k, v)] = (
                    self.serde.dumps_typed(values[k]) if k in values else ("empty", b"")
                )
            if checkpoint_ns not in storage_dict:
                storage_dict[checkpoint_ns] = {}

            storage_dict[checkpoint_ns][checkpoint["id"]] = (
                self.serde.dumps_typed(c),
                self.serde.dumps_typed(get_checkpoint_metadata(config, metadata)),
                config["configurable"].get("checkpoint_id"),
            )

            await self.redis.hset(
                f"ai_run:{thread_id}",
                mapping={
                    "storage": pickle.dumps(storage_dict),
                    "blobs": pickle.dumps(blobs_dict),
                },
            )
            await self.redis.expire(f"ai_run:{thread_id}", self.ttl)

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"]["checkpoint_id"]

        async with self._lock:
            writes_dict = await self._get_field(thread_id, "writes")

            outer_key = (thread_id, checkpoint_ns, checkpoint_id)
            if outer_key not in writes_dict:
                writes_dict[outer_key] = {}
            outer_writes_ = writes_dict[outer_key]

            for idx, (c, v) in enumerate(writes):
                inner_key = (task_id, WRITES_IDX_MAP.get(c, idx))
                if inner_key[1] >= 0 and outer_writes_ and inner_key in outer_writes_:
                    continue
                outer_writes_[inner_key] = (
                    task_id,
                    c,
                    self.serde.dumps_typed(v),
                    task_path,
                )

            await self.redis.hset(
                f"ai_run:{thread_id}",
                "writes",
                pickle.dumps(writes_dict),
            )
            await self.redis.expire(f"ai_run:{thread_id}", self.ttl)

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        if not config:
            return
        t = await self.aget_tuple(config)
        if t:
            yield t

    def get_next_version(self, current: str | None, channel: None) -> str:
        if current is None:
            current_v = 0
        elif isinstance(current, int):
            current_v = current
        else:
            current_v = int(current.split(".")[0])
        next_v = current_v + 1
        next_h = random.random()
        return f"{next_v:032}.{next_h:016}"
