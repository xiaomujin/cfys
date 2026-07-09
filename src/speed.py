"""阶段3：下载速度测试（curl 子进程）"""

import asyncio
import shutil
import subprocess
import sys

from tqdm import tqdm

from .models import Node, SpeedResult, TcpResult

SPEED_DOMAIN = "speed.cloudflare.com"
SPEED_PATH = "/__down"
SPEED_BYTES = 20 * 1024 * 1024  # 20MB


def _get_curl() -> str | None:
    if sys.platform == "win32":
        return shutil.which("curl.exe") or shutil.which("curl")
    return shutil.which("curl")


def _measure_speed(node: Node, timeout: float, process_buffer: float) -> float:
    """用 curl 测量单节点下载速度，返回 Mbps"""
    curl = _get_curl()
    if curl is None:
        return 0.0

    url = f"https://{SPEED_DOMAIN}:{node.port}{SPEED_PATH}?bytes={SPEED_BYTES}"
    cmd = [
        curl,
        "-s", "-o", "NUL" if sys.platform == "win32" else "/dev/null",
        "-w", "%{http_code} %{speed_download} %{time_connect} %{time_starttransfer}",
        "--resolve", f"{SPEED_DOMAIN}:{node.port}:{node.ip}",
        "--connect-timeout", str(min(5.0, timeout)),
        "--max-time", str(timeout),
        "--insecure", url,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + process_buffer,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        if not result.stdout.strip():
            return 0.0
        parts = result.stdout.strip().split()
        if len(parts) >= 2:
            http_code = int(parts[0])
            speed_download = float(parts[1])  # bytes/sec
            if http_code == 200 and speed_download > 0:
                return round((speed_download * 8) / 1_000_000, 2)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    return 0.0


async def run_speed_tests(
    candidates: list[TcpResult],
    *,
    timeout: float,
    process_buffer: float,
    workers: int,
    min_speed: float,
    verbose: bool = False,
) -> list[SpeedResult]:
    """并发下载速度测试"""
    queue: asyncio.Queue[TcpResult | None] = asyncio.Queue()
    results: list[SpeedResult] = []
    progress = tqdm(total=len(candidates), desc="下载速度测试", unit="ip")

    async def worker() -> None:
        while True:
            candidate = await queue.get()
            try:
                if candidate is None:
                    return
                speed = await asyncio.to_thread(
                    _measure_speed, candidate.node, timeout, process_buffer
                )
                result = SpeedResult(
                    node=candidate.node,
                    latency_ms=candidate.latency_ms,
                    speed_mbps=speed,
                    is_fast=speed >= min_speed,
                )
                results.append(result)
                if verbose:
                    status = "FAST" if result.is_fast else ""
                    tqdm.write(f"[SPEED] {candidate.node.raw} -> {speed} Mbps {status}")
                progress.update(1)
            finally:
                queue.task_done()

    num_workers = max(1, min(workers, len(candidates)))
    tasks = [asyncio.create_task(worker()) for _ in range(num_workers)]
    for cand in candidates:
        queue.put_nowait(cand)
    for _ in tasks:
        queue.put_nowait(None)

    await queue.join()
    await asyncio.gather(*tasks)
    progress.close()

    results.sort(key=lambda r: (r.node.region, r.latency_ms, -r.speed_mbps))
    return results
