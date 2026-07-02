"""Cloudflare IP 优选工具

流水线：拉取数据源 → TCP 延迟测试 → 下载速度测试 → 写入结果
"""

import asyncio

from src.config import load_config
from src.sources import fetch_all_sources
from src.tcp import run_tcp_tests, select_candidates
from src.speed import run_speed_tests
from src.output import write_results, write_best, select_best, print_summary
from push_proxyip import run_push
from push_dns import run_push as run_push_dns
from push_github import run_push as run_push_github


async def run() -> int:
    cfg = load_config()

    print("=" * 50)
    print("Cloudflare IP 优选工具")
    print(f"TCP: 超时 {cfg.tcp_timeout}s，并发 {cfg.tcp_workers}")
    print(f"速度: 超时 {cfg.speed_timeout}s，并发 {cfg.speed_workers}")
    print(f"每区域候选: {cfg.top_per_region}")
    print(f"精选地区: {cfg.regions} (max={cfg.max_per_region}, prefer_fast={cfg.prefer_fast})")
    print("=" * 50)

    # === 阶段 1: 拉取数据源 ===
    print("\n[阶段 1/4] 拉取数据源...")
    nodes = fetch_all_sources(cfg)
    if not nodes:
        print("未获取到任何节点，退出。")
        return 1
    print(f"共 {len(nodes)} 个唯一节点")

    # === 阶段 2: TCP 延迟测试 ===
    print(f"\n[阶段 2/4] TCP 延迟测试...")
    tcp_results = await run_tcp_tests(
        nodes,
        timeout=cfg.tcp_timeout,
        workers=cfg.tcp_workers,
    )
    if not tcp_results:
        print("无 TCP 可达节点，退出。")
        return 1
    tcp_results.sort(key=lambda r: r.latency_ms)
    print(f"TCP 可达: {len(tcp_results)} 个节点")

    # 候选筛选
    candidates = select_candidates(tcp_results, cfg.top_per_region)
    print(f"候选池: {len(candidates)} 个节点")

    # === 阶段 3: 下载速度测试 ===
    print(f"\n[阶段 3/4] 下载速度测试...")
    speed_results = await run_speed_tests(
        candidates,
        timeout=cfg.speed_timeout,
        process_buffer=cfg.speed_process_buffer,
        workers=cfg.speed_workers,
        min_speed=cfg.min_speed_mbps,
    )

    # === 阶段 4: 写入结果 ===
    print(f"\n[阶段 4/4] 写入结果...")
    write_results(cfg.full_output_file, speed_results)

    best_results = select_best(
        speed_results, cfg.regions, cfg.max_per_region, cfg.prefer_fast
    )
    write_best(cfg.best_output_file, best_results, cfg.push.extra_file)

    fast_count = sum(1 for r in speed_results if r.is_fast)
    print_summary(
        input_count=len(nodes),
        tcp_count=len(tcp_results),
        speed_count=len(speed_results),
        fast_count=fast_count,
        best_count=len(best_results),
        full_path=cfg.full_output_file,
        best_path=cfg.best_output_file,
    )

    # === 推送到 edgetunnel KV ===
    run_push(cfg)

    # === 推送到 Cloudflare DNS ===
    run_push_dns(cfg)

    # === 推送到 GitHub ===
    run_push_github(cfg)

    return 0


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
