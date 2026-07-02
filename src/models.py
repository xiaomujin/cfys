"""公共数据结构"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Node:
    ip: str
    port: int
    region: str

    @property
    def raw(self) -> str:
        return f"{self.ip}:{self.port}#{self.region}"


@dataclass(frozen=True)
class TcpResult:
    node: Node
    latency_ms: float


@dataclass(frozen=True)
class SpeedResult:
    node: Node
    latency_ms: float
    speed_mbps: float
    is_fast: bool
