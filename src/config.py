"""配置加载：读取 config.toml → AppConfig"""

import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SourceConfig:
    url: str
    enabled: bool


@dataclass(frozen=True)
class PushConfig:
    enabled: bool
    account_id: str
    api_token: str
    kv_namespace_id: str
    input_file: Path
    extra_enabled: bool
    extra_file: Path


@dataclass(frozen=True)
class DnsConfig:
    enabled: bool
    zone_id: str
    api_token: str
    record_name: str
    ttl: int
    proxied: bool
    target_count: int
    blocked_regions: list[str]
    regions_whitelist: bool
    max_retries: int
    retry_delay: int
    ping_check: bool
    ping_timeout: float
    ping_workers: int


@dataclass(frozen=True)
class AppConfig:
    # 数据源
    additional_sources: list[SourceConfig]
    input_file: Path
    # TCP 测试
    tcp_timeout: float
    tcp_workers: int
    top_per_region: int
    # 速度测试
    speed_timeout: float
    speed_process_buffer: float
    speed_workers: int
    min_speed_mbps: float
    # 输出
    full_output_file: Path
    best_output_file: Path
    # 地区筛选
    regions: list[str]
    prefer_fast: bool
    max_per_region: int
    # 拉取
    fetch_max_retries: int
    fetch_retry_delay: float
    fetch_timeout: float
    fetch_connect_timeout: float
    # 推送
    push: PushConfig
    dns: DnsConfig


def load_config(path: str | Path = "config.toml") -> AppConfig:
    config_path = Path(path)
    if not config_path.exists():
        print(f"错误：未找到配置文件 {config_path}")
        sys.exit(1)

    with open(config_path, "rb") as f:
        raw = tomllib.load(f)

    def g(table: str, key: str, default=None):
        return raw.get(table, {}).get(key, default)

    sources = []
    for src in raw.get("ADDITIONAL_SOURCES", []):
        if isinstance(src, dict) and src.get("url"):
            sources.append(SourceConfig(
                url=src["url"],
                enabled=src.get("enabled", True),
            ))

    return AppConfig(
        additional_sources=sources,
        input_file=Path(g("app", "INPUT_FILE", "ips.txt")),
        tcp_timeout=g("tcp", "TIMEOUT", 1.5),
        tcp_workers=g("tcp", "WORKERS", 500),
        top_per_region=g("tcp", "TOP_PER_REGION", 10),
        speed_timeout=g("speed", "TIMEOUT", 6.0),
        speed_process_buffer=g("speed", "PROCESS_BUFFER", 8.0),
        speed_workers=g("speed", "WORKERS", 16),
        min_speed_mbps=g("speed", "MIN_MBPS", 10.0),
        full_output_file=Path(g("output", "FULL_FILE", "full_ips.txt")),
        best_output_file=Path(g("output", "BEST_FILE", "best_ips.txt")),
        regions=[r.upper() for r in g("regions", "LIST", ["HK", "JP", "KR", "US", "TW"])],
        prefer_fast=g("regions", "PREFER_FAST", True),
        max_per_region=g("regions", "MAX_PER_REGION", 5),
        fetch_max_retries=g("fetch", "MAX_RETRIES", 3),
        fetch_retry_delay=g("fetch", "RETRY_DELAY", 3),
        fetch_timeout=g("fetch", "TIMEOUT", 10),
        fetch_connect_timeout=g("fetch", "CONNECT_TIMEOUT", 5),
        push=PushConfig(
            enabled=g("push", "ENABLED", False),
            account_id=g("push", "ACCOUNT_ID", ""),
            api_token=g("push", "API_TOKEN", ""),
            kv_namespace_id=g("push", "KV_NAMESPACE_ID", ""),
            input_file=Path(g("push", "INPUT_FILE", "best_ips.txt")),
            extra_enabled=g("push", "EXTRA_ENABLED", False),
            extra_file=Path(g("push", "EXTRA_FILE", "add.txt")),
        ),
        dns=DnsConfig(
            enabled=g("dns", "ENABLED", False),
            zone_id=g("dns", "ZONE_ID", ""),
            api_token=g("dns", "API_TOKEN", ""),
            record_name=g("dns", "RECORD_NAME", ""),
            ttl=g("dns", "TTL", 120),
            proxied=g("dns", "PROXIED", False),
            target_count=g("dns", "TARGET_COUNT", 15),
            blocked_regions=g("dns", "BLOCKED_REGIONS", []),
            regions_whitelist=g("dns", "REGIONS_WHITELIST", False),
            max_retries=g("dns", "MAX_RETRIES", 5),
            retry_delay=g("dns", "RETRY_DELAY", 10),
            ping_check=g("dns", "PING_CHECK", True),
            ping_timeout=g("dns", "PING_TIMEOUT", 2.0),
            ping_workers=g("dns", "PING_WORKERS", 50),
        ),
    )
