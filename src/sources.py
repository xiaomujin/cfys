"""阶段1：拉取数据源 + 合并本地文件，去重"""

import random
import time
from pathlib import Path

import requests

from .config import AppConfig
from .models import Node
from .parser import load_nodes, parse_node

# CIDR 额外数据源：从 /24 子网列表中每个子网随机生成一个 IP
_CIDR_SOURCES = [
    "https://www.baipiao.eu.org/cloudflare/ips-v4",
]


def fetch_source(url: str, cfg: AppConfig) -> list[Node]:
    """拉取单个远程数据源"""
    for attempt in range(1, cfg.fetch_max_retries + 1):
        try:
            print(f"  请求 {url} (尝试 {attempt}/{cfg.fetch_max_retries})")
            resp = requests.get(
                url,
                timeout=(cfg.fetch_connect_timeout, cfg.fetch_timeout),
                headers={"User-Agent": "cf-optimizer/3.0"},
            )
            resp.raise_for_status()
            nodes = _parse_text(resp.text)
            print(f"  解析出 {len(nodes)} 个节点")
            return nodes
        except Exception as e:
            print(f"  失败: {e}")
            if attempt < cfg.fetch_max_retries:
                time.sleep(cfg.fetch_retry_delay)
    return []


def _random_ip_from_cidr(cidr: str) -> str | None:
    """从 /24 CIDR 生成随机 IP（最后一个八位组随机 0-255）"""
    cidr = cidr.strip()
    if not cidr or not cidr.endswith("/24"):
        return None
    base_ip = cidr.removesuffix("/24")
    parts = base_ip.split(".")
    if len(parts) != 4:
        return None
    parts[3] = str(random.randint(0, 255))
    return ".".join(parts)


def _cidr_local_path(url: str) -> Path:
    """从 URL 推导本地缓存文件名，如 ips-v4"""
    name = url.rstrip("/").rsplit("/", 1)[-1]
    return Path(f"{name}.txt")


def _fetch_cidr_source(url: str, cfg: AppConfig) -> list[Node]:
    """拉取 CIDR 列表，每个 /24 子网随机生成一个 IP，失败返回空列表"""
    local_file = _cidr_local_path(url)

    # 优先读取本地文件
    if local_file.exists():
        print(f"  从本地 {local_file} 加载 CIDR 列表")
        content = local_file.read_text(encoding="utf-8-sig")
    else:
        try:
            print(f"  请求 CIDR 源 {url}")
            resp = requests.get(
                url,
                timeout=(cfg.fetch_connect_timeout, cfg.fetch_timeout),
                headers={"User-Agent": "cf-optimizer/3.0"},
            )
            resp.raise_for_status()
            content = resp.text
            local_file.write_text(content, encoding="utf-8")
            print(f"  已保存到本地 {local_file}")
        except Exception as e:
            print(f"  CIDR 源拉取失败，跳过: {e}")
            return []

    nodes = []
    for line in content.splitlines():
        ip = _random_ip_from_cidr(line)
        if ip:
            nodes.append(Node(ip=ip, port=443, region=""))
    print(f"  从 CIDR 列表随机生成 {len(nodes)} 个 IP")
    return nodes


def fetch_all_sources(cfg: AppConfig) -> list[Node]:
    """拉取所有远程源 + 合并本地文件，去重"""
    all_nodes: list[Node] = []
    seen: set[tuple[str, int]] = set()

    # 远程源
    for src in cfg.additional_sources:
        if not src.enabled:
            continue
        nodes = fetch_source(src.url, cfg)
        for n in nodes:
            key = (n.ip, n.port)
            if key not in seen:
                seen.add(key)
                all_nodes.append(n)

    # CIDR 额外数据源（失败不影响流程）
    for url in _CIDR_SOURCES:
        for n in _fetch_cidr_source(url, cfg):
            key = (n.ip, n.port)
            if key not in seen:
                seen.add(key)
                all_nodes.append(n)

    # 本地文件
    local_nodes = load_nodes(cfg.input_file)
    if local_nodes:
        for n in local_nodes:
            key = (n.ip, n.port)
            if key not in seen:
                seen.add(key)
                all_nodes.append(n)
        print(f"  从本地 {cfg.input_file} 加载 {len(local_nodes)} 个节点")

    return all_nodes


def _parse_text(text: str) -> list[Node]:
    """从文本中解析节点"""
    nodes = []
    seen: set[tuple[str, int]] = set()
    for line in text.splitlines():
        node = parse_node(line)
        if node is None:
            continue
        key = (node.ip, node.port)
        if key not in seen:
            seen.add(key)
            nodes.append(node)
    return nodes
