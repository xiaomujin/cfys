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


def write_best(path: Path, results: list[SpeedResult], extra_file: Path | None = None) -> None:
    """写入精选结果，可选追加额外地址文件内容"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for r in results:
            f.write(_format_line(r))
        # 追加额外地址文件内容
        if extra_file and extra_file.exists():
            f.write("\n")
            with extra_file.open("r", encoding="utf-8") as ef:
                for line in ef:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        f.write(line + "\n")


def write_fast_ips(path: Path, results: list[SpeedResult]) -> None:
    """将优选高速IP追加写入文件（累计模式，不清空原有内容，自动去重）"""
    # 读取已有的地址用于去重
    existing: set[str] = set()
    if path.exists():
        with path.open("r", encoding="utf-8-sig") as f:
            for line in f:
                text = line.strip()
                if text and not text.startswith("#"):
                    existing.add(text)

    # 收集新的高速IP
    new_lines: list[str] = []
    for r in results:
        if r.is_fast and r.node.raw not in existing and r.node.raw not in new_lines:
            new_lines.append(r.node.raw)

    # 追加写入（不清空原有内容）
    if new_lines:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as f:
            for line in new_lines:
                f.write(line + "\n")


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
