"""地区发现：通过 CF-RAY 头部识别 CIDR 生成 IP 的实际区域"""

import asyncio
import json
import time
from pathlib import Path

import requests
from tqdm import tqdm

from .models import Node, TcpResult

# locations.json 本地缓存路径
_LOCATIONS_FILE = Path("locations.json")
_LOCATIONS_URL = "https://www.baipiao.eu.org/cloudflare/locations"


def _load_locations() -> dict[str, str]:
    """加载 IATA → cca2 映射，优先读本地缓存"""
    if _LOCATIONS_FILE.exists():
        print(f"  从本地 {_LOCATIONS_FILE} 加载地区数据")
        data = json.loads(_LOCATIONS_FILE.read_text(encoding="utf-8-sig"))
    else:
        print(f"  请求 {_LOCATIONS_URL}")
        resp = requests.get(_LOCATIONS_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        _LOCATIONS_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  已保存到本地 {_LOCATIONS_FILE}")

    return {loc["iata"]: loc["cca2"] for loc in data if "iata" in loc and "cca2" in loc}


async def _probe_cf_ray(ip: str, timeout: float) -> tuple[str | None, str]:
    """通过 HTTP 请求 CF-RAY 头部提取机房 IATA 代码

    返回 (iata, status):
      - (iata_code, "ok")       成功
      - (None, "connect_fail")  TCP 连接失败
      - (None, "no_header")     无 CF-RAY 头
    """
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, 80), timeout=timeout
        )
    except (OSError, TimeoutError, asyncio.TimeoutError):
        return None, "connect_fail"

    try:
        request = f"GET / HTTP/1.1\r\nHost: {ip}\r\nUser-Agent: Mozilla/5.0\r\nConnection: close\r\n\r\n"
        writer.write(request.encode())
        await writer.drain()

        response = b""
        while True:
            chunk = await asyncio.wait_for(reader.read(4096), timeout=timeout)
            if not chunk:
                break
            response += chunk
            if b"\r\n\r\n" in response:
                break

        for line in response.decode(errors="ignore").split("\r\n"):
            if line.lower().startswith("cf-ray"):
                cf_ray = line.split(":", 1)[1].strip()
                parts = cf_ray.split("-")
                if len(parts) >= 2:
                    return parts[-1].upper(), "ok"
        return None, "no_header"
    except (OSError, TimeoutError, asyncio.TimeoutError):
        return None, "connect_fail"
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (OSError, TimeoutError, asyncio.TimeoutError):
            pass


async def discover_regions(
    tcp_results: list[TcpResult],
    timeout: float = 3.0,
    workers: int = 200,
) -> list[TcpResult]:
    """为无地区的节点通过 CF-RAY 发现实际区域"""
    unknown = [r for r in tcp_results if not r.node.region]
    if not unknown:
        return tcp_results

    print(f"\n[地区发现] {len(unknown)} 个节点待识别...")
    try:
        locations = _load_locations()
    except Exception as e:
        print(f"  加载地区数据失败: {e}")
        return tcp_results

    queue: asyncio.Queue[TcpResult | None] = asyncio.Queue()
    updated: dict[int, TcpResult] = {}  # id → new TcpResult
    no_header_ids: set[int] = set()  # 无 CF-RAY 的节点 id，需剔除
    progress = tqdm(total=len(unknown), desc="地区发现", unit="ip")

    stats = {"ok": 0, "connect_fail": 0, "no_header": 0, "iata_not_found": 0}

    async def worker() -> None:
        while True:
            item = await queue.get()
            try:
                if item is None:
                    return
                iata, status = await _probe_cf_ray(item.node.ip, timeout)
                if status == "ok" and iata in locations:
                    new_node = Node(
                        ip=item.node.ip, port=item.node.port, region=locations[iata]
                    )
                    updated[id(item)] = TcpResult(
                        node=new_node, latency_ms=item.latency_ms
                    )
                    stats["ok"] += 1
                    progress.set_postfix_str(f"{item.node.ip} → {locations[iata]}")
                elif status == "ok":
                    # 有 IATA 但不在 locations 中
                    stats["iata_not_found"] += 1
                    tqdm.write(f"[地区发现] {item.node.ip} → IATA={iata} 未在 locations 中找到")
                else:
                    stats[status] += 1
                    if status == "no_header":
                        no_header_ids.add(id(item))
                progress.update(1)
            finally:
                queue.task_done()

    num_workers = max(1, min(workers, len(unknown)))
    tasks = [asyncio.create_task(worker()) for _ in range(num_workers)]
    for r in unknown:
        queue.put_nowait(r)
    for _ in tasks:
        queue.put_nowait(None)

    await queue.join()
    await asyncio.gather(*tasks)
    progress.close()

    # 合并结果：替换有地区的节点，剔除无 CF-RAY 的节点
    result = []
    for r in tcp_results:
        if id(r) in no_header_ids:
            continue
        result.append(updated.get(id(r), r))

    found = stats["ok"]
    print(f"  识别成功: {found}/{len(unknown)}, 剔除无CF-RAY: {stats['no_header']}")
    print(f"  连接失败: {stats['connect_fail']}, IATA未收录: {stats['iata_not_found']}")
    return result
