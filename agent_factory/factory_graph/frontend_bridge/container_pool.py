"""
容器池管理器 - 实现运行实例内的容器复用，降低启动延迟

核心思路：
1. 同一个运行实例可以复用容器，不同 session 保持 checkpoint 与工作目录隔离
2. 容器池维护热容器，避免频繁创建/销毁
3. 智能清理：根据活跃度和内存压力动态调整池大小
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Deque

from agent_factory.factory_graph.frontend_bridge.container_runtime_handle import AgentRuntimeContainerHandle

logger = logging.getLogger(__name__)


@dataclass
class PooledContainer:
    """池化容器的元数据"""

    handle: AgentRuntimeContainerHandle
    package_id: str
    runtime_instance_id: str
    package_fingerprint: str
    created_at: float
    last_used: float
    total_requests: int = 0


class ContainerPool:
    """
    容器池管理器

    策略：
    - 每个 package 维护 1-N 个热容器（根据并发需求动态调整）
    - 容器仅在同一 runtime instance 内复用
    - 空闲容器保持温热，超时后清理
    """

    def __init__(
        self,
        *,
        max_containers_per_package: int = 3,
        max_total_containers: int = 20,
        idle_timeout_seconds: int = 300,
        cleanup_interval_seconds: int = 60,
    ):
        self.max_containers_per_package = max_containers_per_package
        self.max_total_containers = max_total_containers
        self.idle_timeout_seconds = idle_timeout_seconds
        self.cleanup_interval_seconds = cleanup_interval_seconds

        # (package_id, runtime_instance_id) -> deque of PooledContainer
        self._available_by_runtime: dict[tuple[str, str], Deque[PooledContainer]] = {}
        # handle -> PooledContainer
        self._in_use: dict[AgentRuntimeContainerHandle, PooledContainer] = {}

        self._lock = threading.RLock()
        self._cleanup_timer: threading.Timer | None = None
        self._closed = False

        self._schedule_cleanup()

    def acquire(
        self,
        package_id: str,
        package_fingerprint: str,
        runtime_instance_id: str,
        *,
        create_fn: Callable[[], AgentRuntimeContainerHandle],
    ) -> AgentRuntimeContainerHandle:
        """
        获取一个可用容器

        Args:
            package_id: Agent package ID
            package_fingerprint: package 指纹（版本标识）
            runtime_instance_id: 稳定运行实例标识
            create_fn: 容器创建函数（当池中无可用容器时调用）

        Returns:
            可用的容器 handle
        """
        with self._lock:
            if self._closed:
                raise RuntimeError("Container pool is closed")

            runtime_key = (package_id, runtime_instance_id)

            # 1. 仅复用相同运行实例的空闲容器
            available = self._available_by_runtime.get(runtime_key)
            if available:
                for pooled in list(available):
                    # 指纹匹配且容器健康
                    if (
                        pooled.package_fingerprint == package_fingerprint
                        and pooled.handle.is_running
                    ):
                        available.remove(pooled)
                        pooled.last_used = time.monotonic()
                        pooled.total_requests += 1
                        self._in_use[pooled.handle] = pooled
                        logger.debug(
                            "Reused container from pool: package=%s, total_requests=%d",
                            package_id,
                            pooled.total_requests,
                        )
                        return pooled.handle

            # 2. 检查是否达到池上限
            total_containers = self._total_container_count()
            if total_containers >= self.max_total_containers:
                # 尝试清理最久未用的容器腾出空间
                if not self._evict_least_recently_used():
                    raise RuntimeError(
                        f"Container pool exhausted: {total_containers} containers active "
                        f"(max={self.max_total_containers})"
                    )

            # 3. 创建新容器
            try:
                handle = create_fn()
                pooled = PooledContainer(
                    handle=handle,
                    package_id=package_id,
                    runtime_instance_id=runtime_instance_id,
                    package_fingerprint=package_fingerprint,
                    created_at=time.monotonic(),
                    last_used=time.monotonic(),
                    total_requests=1,
                )
                self._in_use[handle] = pooled
                logger.info(
                    "Created new container: package=%s, total=%d",
                    package_id,
                    total_containers + 1,
                )
                return handle
            except Exception as exc:
                logger.error("Failed to create container for %s: %s", package_id, exc)
                raise

    def release(self, handle: AgentRuntimeContainerHandle) -> None:
        """
        释放容器回池（而不是销毁）

        如果容器健康且池未满，则保留供后续复用；否则关闭
        """
        with self._lock:
            if self._closed:
                handle.close()
                return

            pooled = self._in_use.pop(handle, None)
            if pooled is None:
                # 不是池管理的容器，直接关闭
                handle.close()
                return

            # 检查容器是否健康且值得保留
            if not handle.is_running:
                logger.debug("Container died, discarding: package=%s", pooled.package_id)
                return

            runtime_key = (pooled.package_id, pooled.runtime_instance_id)
            package_available_count = sum(
                len(items)
                for (package_id, _), items in self._available_by_runtime.items()
                if package_id == pooled.package_id
            )

            # 检查该 package 的池是否已满
            if package_available_count >= self.max_containers_per_package:
                logger.debug(
                    "Package pool full, closing container: package=%s, pool_size=%d",
                    pooled.package_id,
                    package_available_count,
                )
                handle.close()
                return

            # 加入空闲池
            runtime_available = self._available_by_runtime.setdefault(runtime_key, deque())
            pooled.last_used = time.monotonic()
            runtime_available.append(pooled)
            logger.debug(
                "Released container to pool: package=%s, runtime_instance=%s, pool_size=%d",
                pooled.package_id,
                pooled.runtime_instance_id,
                len(runtime_available),
            )

    def evict_package(self, package_id: str) -> int:
        """
        清理指定 package 的所有容器（package 更新/删除时调用）

        Returns:
            清理的容器数量
        """
        with self._lock:
            count = 0

            # 清理空闲容器
            for runtime_key, available in list(self._available_by_runtime.items()):
                if runtime_key[0] != package_id:
                    continue
                del self._available_by_runtime[runtime_key]
                for pooled in available:
                    pooled.handle.close()
                    count += 1

            # 标记使用中的容器（在 release 时不回池）
            for pooled in list(self._in_use.values()):
                if pooled.package_id == package_id:
                    # 不能直接关闭（可能正在处理请求），但确保不回池
                    pooled.package_fingerprint = "__evicted__"
                    count += 1

            logger.info("Evicted %d containers for package %s", count, package_id)
            return count

    def close_all(self) -> None:
        """关闭池，清理所有容器"""
        with self._lock:
            self._closed = True

            if self._cleanup_timer is not None:
                self._cleanup_timer.cancel()
                self._cleanup_timer = None

            # 关闭所有空闲容器
            for package_available in self._available_by_runtime.values():
                for pooled in package_available:
                    pooled.handle.close()
            self._available_by_runtime.clear()

            # 关闭所有使用中的容器
            for pooled in self._in_use.values():
                pooled.handle.close()
            self._in_use.clear()

            logger.info("Container pool closed")

    def stats(self) -> dict[str, Any]:
        """返回池的统计信息"""
        with self._lock:
            available_by_package: dict[str, int] = {}
            for (package_id, _), containers in self._available_by_runtime.items():
                available_by_package[package_id] = available_by_package.get(package_id, 0) + len(containers)
            in_use_by_package: dict[str, int] = {}
            for pooled in self._in_use.values():
                in_use_by_package[pooled.package_id] = in_use_by_package.get(pooled.package_id, 0) + 1

            return {
                "total_available": sum(len(c) for c in self._available_by_runtime.values()),
                "total_in_use": len(self._in_use),
                "total_containers": self._total_container_count(),
                "available_by_package": available_by_package,
                "in_use_by_package": in_use_by_package,
                "max_total_containers": self.max_total_containers,
                "max_containers_per_package": self.max_containers_per_package,
            }

    def _total_container_count(self) -> int:
        """当前池中的总容器数（空闲 + 使用中）"""
        return len(self._in_use) + sum(len(c) for c in self._available_by_runtime.values())

    def _evict_least_recently_used(self) -> bool:
        """
        清理最久未用的空闲容器

        Returns:
            是否成功清理了至少一个容器
        """
        oldest_pooled: PooledContainer | None = None
        oldest_runtime_key: tuple[str, str] | None = None

        for runtime_key, available in self._available_by_runtime.items():
            for pooled in available:
                if oldest_pooled is None or pooled.last_used < oldest_pooled.last_used:
                    oldest_pooled = pooled
                    oldest_runtime_key = runtime_key

        if oldest_pooled is not None and oldest_runtime_key is not None:
            available = self._available_by_runtime[oldest_runtime_key]
            available.remove(oldest_pooled)
            oldest_pooled.handle.close()
            logger.info(
                "Evicted LRU container: package=%s, idle_time=%.1fs",
                oldest_runtime_key[0],
                time.monotonic() - oldest_pooled.last_used,
            )
            return True

        return False

    def _cleanup_idle_containers(self) -> None:
        """定期清理超时的空闲容器"""
        with self._lock:
            if self._closed:
                return

            now = time.monotonic()
            cleaned = 0

            for runtime_key, available in list(self._available_by_runtime.items()):
                for pooled in list(available):
                    idle_time = now - pooled.last_used

                    # 超时或容器已死
                    if idle_time > self.idle_timeout_seconds or not pooled.handle.is_running:
                        available.remove(pooled)
                        pooled.handle.close()
                        cleaned += 1
                        logger.debug(
                            "Cleaned idle container: package=%s, idle_time=%.1fs",
                            runtime_key[0],
                            idle_time,
                        )

                # 移除空队列
                if not available:
                    del self._available_by_runtime[runtime_key]

            if cleaned > 0:
                logger.info("Cleanup: removed %d idle containers, %d remaining", cleaned, self._total_container_count())

        # 重新调度
        self._schedule_cleanup()

    def _schedule_cleanup(self) -> None:
        """调度下一次清理任务"""
        if self._closed:
            return
        self._cleanup_timer = threading.Timer(
            self.cleanup_interval_seconds,
            self._cleanup_idle_containers,
        )
        self._cleanup_timer.daemon = True
        self._cleanup_timer.start()


def _env_int(name: str, default: int) -> int:
    """从环境变量读取整数"""
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


# 全局容器池实例（按需创建）
_global_pool: ContainerPool | None = None
_global_pool_lock = threading.Lock()


def get_global_container_pool() -> ContainerPool:
    """获取全局容器池单例"""
    global _global_pool
    if _global_pool is None:
        with _global_pool_lock:
            if _global_pool is None:
                _global_pool = ContainerPool(
                    max_containers_per_package=_env_int("AGENTFACTORY_POOL_MAX_PER_PACKAGE", 3),
                    max_total_containers=_env_int("AGENTFACTORY_POOL_MAX_TOTAL", 20),
                    idle_timeout_seconds=_env_int("AGENTFACTORY_POOL_IDLE_TIMEOUT", 300),
                    cleanup_interval_seconds=_env_int("AGENTFACTORY_POOL_CLEANUP_INTERVAL", 60),
                )
                logger.info("Initialized global container pool: %s", _global_pool.stats())
    return _global_pool


def shutdown_global_container_pool() -> None:
    """Close and discard the process-local pool during backend shutdown."""
    global _global_pool
    with _global_pool_lock:
        if _global_pool is not None:
            _global_pool.close_all()
            _global_pool = None
