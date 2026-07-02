"""阶段2：TCP 延迟测试 + 候选筛选"""

import asyncio
import heapq
import time
from collections import defaultdict

from tqdm import tqdm

from .models import Node, TcpResult


async def tcping(node: Node, timeout: float) -> float | None:
    """单次 TCP 连接测速，返回延迟(ms)"""
    start = time.perf_counter()
    writer: asyncio.StreamWriter | None = None
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(node.ip, node.port), timeout=timeout
        )
        return round((time.perf_counter() - start) * 1000, 2)
    except (OSError, TimeoutError, asyncio.TimeoutError):
        return None
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except (OSError, TimeoutError, asyncio.TimeoutError):
                pass


async def run_tcp_tests(
    nodes: list[Node],
    *,
    timeout: float,
    workers: int,
    verbose: bool = False,
) -> list[TcpResult]:
    """并发 TCP 测试"""
    queue: asyncio.Queue[Node | None] = asyncio.Queue()
    results: list[TcpResult] = []
    progress = tqdm(total=len(nodes), desc="TCP 延迟测试", unit="ip")

    async def worker() -> None:
        while True:
            w_node = await queue.get()
            try:
                if w_node is None:
                    return
                latency = await tcping(w_node, timeout)
                if latency is not None:
                    results.append(TcpResult(node=w_node, latency_ms=latency))
                    if verbose:
                        tqdm.write(f"[TCP] {w_node.raw} -> {latency} ms")
                progress.update(1)
            finally:
                queue.task_done()

    num_workers = max(1, min(workers, len(nodes)))
    tasks = [asyncio.create_task(worker()) for _ in range(num_workers)]
    for node in nodes:
        queue.put_nowait(node)
    for _ in tasks:
        queue.put_nowait(None)

    await queue.join()
    await asyncio.gather(*tasks)
    progress.close()
    return results


def select_candidates(results: list[TcpResult], top_per_region: int) -> list[TcpResult]:
    """每区域保留延迟最低的 N 个候选"""
    groups: dict[str, list[tuple[float, int, TcpResult]]] = defaultdict(list)
    limit = max(1, top_per_region)

    for index, result in enumerate(results):
        heap = groups[result.node.region]
        item = (-result.latency_ms, -index, result)
        if len(heap) < limit:
            heapq.heappush(heap, item)
        else:
            heapq.heappushpop(heap, item)

    candidates = [
        item[2] for region in sorted(groups) for item in groups[region]
    ]
    candidates.sort(key=lambda reg: (reg.node.region, reg.latency_ms))
    return candidates
