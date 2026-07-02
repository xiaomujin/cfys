"""阶段1：拉取数据源 + 合并本地文件，去重"""

import time

import requests

from .config import AppConfig
from .models import Node
from .parser import load_nodes, parse_node


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
