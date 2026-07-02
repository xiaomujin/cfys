"""阶段4：写入结果文件"""

from collections import defaultdict
from pathlib import Path

from .models import SpeedResult

FAST_LABEL = "优选高速"


def _format_line(r: SpeedResult) -> str:
    if r.is_fast:
        return f"{r.node.raw} [{FAST_LABEL} {r.latency_ms}ms | {r.speed_mbps}Mbps]\n"
    return f"{r.node.raw} [{r.latency_ms}ms | {r.speed_mbps}Mbps]\n"


def write_results(path: Path, results: list[SpeedResult]) -> None:
    """写入完整结果"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for r in results:
            f.write(_format_line(r))


def select_best(
    results: list[SpeedResult],
    regions: list[str],
    max_per_region: int,
    prefer_fast: bool = True,
) -> list[SpeedResult]:
    """按地区筛选，每地区限制数量。prefer_fast 时优先选高速节点"""
    groups: dict[str, list[SpeedResult]] = defaultdict(list)
    for r in results:
        if r.node.region in regions:
            groups[r.node.region].append(r)

    selected: list[SpeedResult] = []

    for region in regions:
        items = groups.get(region, [])
        if not items:
            continue
        if prefer_fast:
            # 高速优先，其次按延迟排序
            items.sort(key=lambda reg: (not reg.is_fast, reg.latency_ms))
        else:
            items.sort(key=lambda reg: reg.latency_ms)
        picked = items[:max_per_region]
        selected.extend(picked)

    selected.sort(key=lambda reg: (reg.node.region, not reg.is_fast, reg.latency_ms))
    return selected


def write_best(path: Path, results: list[SpeedResult], add_file: Path | None = None) -> None:
    """写入精选结果

    Args:
        path: 精选结果输出文件路径
        results: 精选结果列表
        add_file: 额外地址文件路径，如果提供则同时写入
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for r in results:
            f.write(_format_line(r))

    # 同时写入额外地址文件
    if add_file is not None:
        add_file.parent.mkdir(parents=True, exist_ok=True)
        with add_file.open("w", encoding="utf-8", newline="\n") as f:
            for r in results:
                f.write(_format_line(r))


def print_summary(
    input_count: int,
    tcp_count: int,
    speed_count: int,
    fast_count: int,
    best_count: int,
    full_path: Path,
    best_path: Path,
) -> None:
    """打印统计摘要"""
    print(f"\n{'=' * 50}")
    print("测试结果汇总")
    print(f"{'=' * 50}")
    print(f"输入节点:    {input_count}")
    print(f"TCP 可达:    {tcp_count}")
    print(f"速度测试:    {speed_count}")
    print(f"优选高速:    {fast_count}")
    print(f"精选节点:    {best_count}")
    print(f"\n完整结果: {full_path}")
    print(f"精选结果: {best_path}")
    print(f"{'=' * 50}")
