"""推送优选 IP 到 Cloudflare DNS A 记录

从 full_ips.txt 筛选优选高速节点，生成 dns_ips.txt，通过 CF DNS 批量 API 更新 A 记录。
"""

import platform
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from src.config import load_config

DNS_OUTPUT_FILE = Path("dns_ips.txt")


def parse_result_file(filepath: Path) -> list[dict]:
    """解析 full_ips.txt，提取 IP、端口、地区、速度

    格式示例:
      1.2.3.4:443#HK [优选高速 50.0ms | 100.0Mbps]
      1.2.3.4:443#HK [50.0ms | 100.0Mbps]
    """
    if not filepath.exists():
        print(f"错误：未找到文件 {filepath}")
        sys.exit(1)

    entries = []
    pattern = re.compile(
        r"^(\d+\.\d+\.\d+\.\d+):(\d+)#(\w+)\s+\[.*?(?:(\d+\.?\d*)ms\s*\|\s*)?(\d+\.?\d*)Mbps\]"
    )
    with filepath.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = pattern.match(line)
            if m:
                entries.append({
                    "ip": m.group(1),
                    "port": int(m.group(2)),
                    "region": m.group(3).upper(),
                    "latency_ms": float(m.group(4)) if m.group(4) else float("inf"),
                    "speed_mbps": float(m.group(5)),
                })
    return entries


def ping_host(ip: str, timeout: float = 2.0) -> bool:
    """检测 IP 是否可达（跨平台）

    Windows: ping -n 1 -w <timeout_ms>
    Linux:   ping -c 1 -W <timeout_s>
    """
    param_n = "-n" if platform.system().lower() == "windows" else "-c"
    if platform.system().lower() == "windows":
        param_w = f"-w {int(timeout * 1000)}"
    else:
        param_w = f"-W {int(timeout)}"
    cmd = f"ping {param_n} 1 {param_w} {ip}"
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, timeout=timeout + 3
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, Exception):
        return False


def filter_and_select(
    entries: list[dict],
    target_count: int = 15,
    region_filter: set[str] | None = None,
    whitelist: bool = False,
    ping_check: bool = True,
    ping_timeout: float = 2.0,
    ping_workers: int = 50,
) -> list[dict]:
    """筛选并选取 top N 节点

    规则:
      1. 仅保留 port=443
      2. 地区过滤：whitelist=true 时只保留列表中的地区，false 时排除列表中的地区
      3. ping 可达性检查（可选）
      4. 按速度降序排序
      5. 取前 target_count 个
    """
    filtered = []
    skipped_port = 0
    skipped_region = 0

    for e in entries:
        if e["port"] != 443:
            skipped_port += 1
            continue
        if region_filter:
            if whitelist and e["region"] not in region_filter:
                skipped_region += 1
                continue
            if not whitelist and e["region"] in region_filter:
                skipped_region += 1
                continue
        filtered.append(e)

    parts = []
    if skipped_port > 0:
        parts.append(f"非443端口过滤({skipped_port}个)")
    if skipped_region > 0:
        mode = "白名单" if whitelist else "黑名单"
        parts.append(f"地区{mode}过滤({skipped_region}个)")

    # ping 可达性检查
    skipped_ping = 0
    if ping_check and filtered:
        print(f"正在 ping 检查 {len(filtered)} 个节点（并发 {ping_workers}，超时 {ping_timeout}s）...")
        ping_results = {}
        with ThreadPoolExecutor(max_workers=ping_workers) as executor:
            future_map = {
                executor.submit(ping_host, e["ip"], ping_timeout): e["ip"]
                for e in filtered
            }
            for future in as_completed(future_map):
                ip = future_map[future]
                try:
                    ping_results[ip] = future.result()
                except Exception:
                    ping_results[ip] = False

        before = len(filtered)
        filtered = [e for e in filtered if ping_results.get(e["ip"], False)]
        skipped_ping = before - len(filtered)
        parts.append(f"ping 不可达过滤({skipped_ping}个)")

    filter_str = " + ".join(parts) if parts else "无过滤"
    print(f"从 {len(entries)} 条记录中筛选出 {len(filtered)} 条（{filter_str}）")

    # 按速度降序
    filtered.sort(key=lambda e: e["speed_mbps"], reverse=True)
    selected = filtered[:target_count]

    if selected:
        print(f"选取前 {len(selected)} 个节点用于 DNS 更新:")
        for i, e in enumerate(selected, 1):
            print(f"  {i}. {e['ip']}:{e['port']}#{e['region']}  "
                  f"{e['speed_mbps']:.1f}Mbps  {e['latency_ms']:.1f}ms")

    return selected


def write_dns_ips(path: Path, entries: list[dict]) -> None:
    """将筛选结果写入 dns_ips.txt"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for e in entries:
            f.write(f"{e['ip']}:{e['port']}#{e['region']}\n")
    print(f"已写入 {len(entries)} 条记录到 {path}")


def push_to_dns(
    api_token: str,
    zone_id: str,
    record_name: str,
    ips: list[str],
    ttl: int = 120,
    proxied: bool = False,
    max_retries: int = 5,
    retry_delay: int = 10,
) -> bool:
    """批量更新 Cloudflare DNS A 记录

    策略：删除所有已有 A 记录 → 批量创建新记录
    """
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    for attempt in range(1, max_retries + 1):
        print(f"\n[DNS 更新] 尝试 {attempt}/{max_retries}...")
        try:
            # 1. 查询已有 A 记录
            list_url = (
                f"https://api.cloudflare.com/client/v4/zones/{zone_id}"
                f"/dns_records?type=A&name={record_name}"
            )
            resp = requests.get(list_url, headers=headers, timeout=30)
            resp.raise_for_status()
            result = resp.json()
            if not result.get("success"):
                raise Exception(f"查询 DNS 记录失败: {result.get('errors')}")

            existing = result.get("result", [])
            deletes = [{"id": rec["id"]} for rec in existing]

            # 2. 构造新记录
            posts = [
                {
                    "name": record_name,
                    "type": "A",
                    "content": ip,
                    "ttl": ttl,
                    "proxied": proxied,
                }
                for ip in ips
            ]

            # 3. 批量更新
            batch_url = (
                f"https://api.cloudflare.com/client/v4/zones/{zone_id}"
                f"/dns_records/batch"
            )
            payload = {"deletes": deletes, "posts": posts}
            resp = requests.post(batch_url, headers=headers, json=payload, timeout=30)
            resp.raise_for_status()
            result = resp.json()
            if not result.get("success"):
                raise Exception(f"批量更新失败: {result.get('errors')}")

            print(f"✅ DNS 批量更新成功！{record_name} → {len(ips)} 个 A 记录")
            print("   DNS 解析将随机返回这些 IP，实现负载均衡。")
            return True

        except Exception as e:
            print(f"[尝试 {attempt}/{max_retries}] DNS 更新出错: {e}")
            if attempt < max_retries:
                print(f"等待 {retry_delay} 秒后重试...")
                time.sleep(retry_delay)
            else:
                print(f"❌ DNS 更新失败，已重试 {max_retries} 次: {e}")
                return False

    return False


def run_push(cfg=None) -> int:
    """供 main.py 调用的入口

    流程: full_ips.txt → 筛选 → dns_ips.txt → CF DNS
    """
    if cfg is None:
        cfg = load_config()

    dns = cfg.dns
    if not dns.enabled:
        print("DNS 推送未启用，跳过")
        return 0

    if not all([dns.zone_id, dns.api_token, dns.record_name]):
        print("错误：请在 config.toml [dns] 中填写 zone_id、api_token、record_name")
        return 1

    # 从 full_ips.txt 解析
    entries = parse_result_file(cfg.full_output_file)
    if not entries:
        print("full_ips.txt 为空，跳过 DNS 推送")
        return 0

    region_set = {r.upper() for r in dns.blocked_regions} if dns.blocked_regions else None
    selected = filter_and_select(
        entries,
        target_count=dns.target_count,
        region_filter=region_set,
        whitelist=dns.regions_whitelist,
        ping_check=dns.ping_check,
        ping_timeout=dns.ping_timeout,
        ping_workers=dns.ping_workers,
    )
    if not selected:
        print("无可用节点，跳过 DNS 推送")
        return 0

    # 写入 dns_ips.txt
    write_dns_ips(DNS_OUTPUT_FILE, selected)

    unique_ips = list(dict.fromkeys(e["ip"] for e in selected))

    ok = push_to_dns(
        api_token=dns.api_token,
        zone_id=dns.zone_id,
        record_name=dns.record_name,
        ips=unique_ips,
        ttl=dns.ttl,
        proxied=dns.proxied,
        max_retries=dns.max_retries,
        retry_delay=dns.retry_delay,
    )
    return 0 if ok else 1


def main() -> int:
    return run_push()


if __name__ == "__main__":
    raise SystemExit(main())
