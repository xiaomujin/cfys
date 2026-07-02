"""节点解析：IP:Port#Region 格式"""

from pathlib import Path

from .models import Node


def parse_node(line: str) -> Node | None:
    """解析单行节点，格式: IP:Port#Region"""
    text = line.strip()
    if not text or text.startswith("#") or "#" not in text:
        return None

    address, region = (part.strip() for part in text.split("#", 1))
    if not address or not region or ":" not in address:
        return None

    ip, port_text = (part.strip() for part in address.rsplit(":", 1))
    try:
        port = int(port_text)
    except ValueError:
        return None

    if not ip or not 1 <= port <= 65535:
        return None
    return Node(ip=ip, port=port, region=region.upper())


def load_nodes(path: Path) -> list[Node]:
    """从文件加载节点，去重"""
    if not path.exists():
        return []

    nodes: list[Node] = []
    seen: set[tuple[str, int]] = set()
    with path.open("r", encoding="utf-8-sig") as f:
        for line in f:
            node = parse_node(line)
            if node is None:
                continue
            key = (node.ip, node.port)
            if key in seen:
                continue
            seen.add(key)
            nodes.append(node)
    return nodes
