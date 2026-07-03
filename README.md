# Cloudflare IP 优选工具

异步 Cloudflare CDN 节点测速工具，通过 TCP 延迟 + 下载带宽双重筛选，输出最优节点列表。支持推送到 edgetunnel KV、Cloudflare DNS 和 GitHub。

## 工作流程

```
拉取数据源 → TCP 延迟测试 → 下载速度测试 → 写入结果 → 推送
```

1. **数据源拉取** — 远程 URL + 本地文件合并去重
2. **TCP 延迟测试** — asyncio 并发 TCP 连接，按地区保留延迟最低的候选
3. **下载速度测试** — curl 子进程下载 5MB 测速文件，标记高速节点
4. **结果输出** — `full_ips.txt`（完整）和 `best_ips.txt`（按地区精选）
5. **推送** — 可选，推送到 edgetunnel KV / Cloudflare DNS / GitHub

## 安装

```bash
pip install requests tqdm
```

- Python 3.11+（依赖 `tomllib`）
- 系统 `curl`（速度测试依赖）

## 使用

```bash
# 编辑 config.toml 配置数据源和参数
python main.py
```

## 配置

所有配置在 `config.toml` 中。

### 数据源

```toml
[app]
INPUT_FILE = "ips.txt"          # 本地节点文件

# 远程源（可追加多个）
[[ADDITIONAL_SOURCES]]
url = "https://example.com/nodes.txt"
enabled = true
```

节点格式：`IP:Port#Region`，例如 `1.2.3.4:443#US`

### TCP 测试 `[tcp]`

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `TIMEOUT` | 连接超时（秒） | `1.5` |
| `WORKERS` | 并发数 | `500` |
| `TOP_PER_REGION` | 每地区保留候选数 | `10` |

### 速度测试 `[speed]`

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `TIMEOUT` | 下载超时（秒） | `6.0` |
| `PROCESS_BUFFER` | 进程缓冲时间（秒） | `8.0` |
| `WORKERS` | 并发数 | `16` |
| `MIN_MBPS` | 高速标记阈值（Mbps） | `10.0` |

### 地区筛选 `[regions]`

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `LIST` | 地区代码列表 | `["HK","JP","KR","US","TW"]` |
| `PREFER_FAST` | 精选优先高速节点 | `true` |
| `MAX_PER_REGION` | 每地区最多保留数 | `5` |

### 输出 `[output]`

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `FULL_FILE` | 完整结果文件 | `full_ips.txt` |
| `BEST_FILE` | 精选结果文件 | `best_ips.txt` |
| `EXTRA_FILE` | 额外地址文件（追加到精选结果） | `add.txt` |

### 数据源拉取 `[fetch]`

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `MAX_RETRIES` | 最大重试次数 | `3` |
| `RETRY_DELAY` | 重试间隔（秒） | `3` |
| `TIMEOUT` | HTTP 响应超时（秒） | `10` |
| `CONNECT_TIMEOUT` | HTTP 连接超时（秒） | `5` |

### 推送到 edgetunnel `[push]`

将结果推送到 [edgetunnel](https://github.com/cmliu/edgetunnel) 的 KV 存储。

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `ENABLED` | 是否启用 | `false` |
| `ACCOUNT_ID` | CF Account ID | |
| `API_TOKEN` | CF API Token（需 KV:Edit 权限） | |
| `KV_NAMESPACE_ID` | KV 命名空间 ID | |
| `INPUT_FILE` | 推送源文件 | `best_ips.txt` |
| `EXTRA_ENABLED` | 合并额外地址文件 | `false` |
| `EXTRA_FILE` | 额外地址文件路径 | `add.txt` |

也可单独运行：`python push_proxyip.py`

### 推送到 Cloudflare DNS `[dns]`

从测速结果中筛选高速节点，批量更新 DNS A 记录实现负载均衡。

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `ENABLED` | 是否启用 | `false` |
| `ZONE_ID` | CF Zone ID | |
| `API_TOKEN` | CF API Token（需 DNS:Edit 权限） | |
| `RECORD_NAME` | DNS 记录名（如 `proxy.example.com`） | |
| `TTL` | TTL（秒） | `120` |
| `PROXIED` | 启用代理（橙色云朵） | `false` |
| `TARGET_COUNT` | A 记录数量上限 | `3` |
| `BLOCKED_REGIONS` | 地区过滤列表 | `[]` |
| `REGIONS_WHITELIST` | 白名单模式 | `false` |
| `PING_CHECK` | 推送前 ping 检查 | `true` |

也可单独运行：`python push_dns.py`

### 推送到 GitHub `[github]`

将结果文件同步到 GitHub 仓库。

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `ENABLED` | 是否启用 | `false` |
| `REPO` | 仓库地址（HTTPS） | |
| `BRANCH` | 目标分支 | `main` |
| `TOKEN` | GitHub Token | |
| `PROXY` | 代理地址（http/https/socks5） | |
| `FALLBACK_NO_PROXY` | 代理失败时尝试直连 | `true` |

也可单独运行：`python push_github.py`

## 项目结构

```
├── main.py              # 入口，4 阶段流水线
├── push_proxyip.py      # 推送到 edgetunnel KV
├── push_dns.py          # 推送到 Cloudflare DNS
├── push_github.py       # 推送到 GitHub
├── config.toml          # 配置文件
├── src/
│   ├── config.py        # 配置加载（TOML → dataclass）
│   ├── models.py        # 数据结构（Node, TcpResult, SpeedResult）
│   ├── parser.py        # 节点行解析（IP:Port#Region）
│   ├── sources.py       # 远程/本地数据源拉取与去重
│   ├── tcp.py           # TCP 延迟测试 + 候选筛选
│   ├── speed.py         # curl 下载速度测试
│   └── output.py        # 结果写入 + 统计摘要
├── full_ips.txt         # 完整测速结果（运行后生成）
├── best_ips.txt         # 精选节点（运行后生成）
└── add.txt              # 额外地址（可选，追加到精选结果）
```
