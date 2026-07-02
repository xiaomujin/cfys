# Cloudflare IP 优选工具

异步 Cloudflare CDN 节点测速工具，通过 TCP 延迟 + 下载带宽双重筛选，输出最优节点列表。

## 工作流程

```
拉取数据源 → TCP 延迟测试 → 下载速度测试 → 写入结果 → 推送到 edgetunnel
```

1. **数据源拉取** — 从多个远程 URL 获取节点列表，与本地文件合并去重
2. **TCP 延迟测试** — asyncio 并发 TCP 连接，按地区保留延迟最低的候选
3. **下载速度测试** — curl 子进程下载 2MB 测速文件，标记高速节点
4. **结果输出** — 写入完整列表和按地区精选列表
5. **推送** — 可选，将结果推送到 edgetunnel 的 KV 存储

## 安装

```bash
pip install requests tqdm
```

- Python 3.10+
- 系统 `curl`（速度测试依赖）

## 使用

```bash
cd cf-optimizer

# 编辑 config.toml 配置数据源和参数
python main.py
```

## 配置

所有配置在 `config.toml` 中，分为以下部分：

### 数据源 `[app]`

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `INPUT_FILE` | 本地节点文件路径 | `ips.txt` |

远程源通过 `[[ADDITIONAL_SOURCES]]` 数组配置：

```toml
[[ADDITIONAL_SOURCES]]
url = "https://example.com/nodes.txt"
enabled = true
```

节点格式：`IP:Port#Region`，例如 `1.2.3.4:443#US`

### TCP 测试 `[tcp]`

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `TIMEOUT` | 单次连接超时（秒） | `1.5` |
| `WORKERS` | 并发数 | `500` |
| `TOP_PER_REGION` | 每地区保留候选数 | `10` |

### 速度测试 `[speed]`

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `TIMEOUT` | curl 下载超时（秒） | `6.0` |
| `PROCESS_BUFFER` | 进程额外缓冲时间（秒） | `8.0` |
| `WORKERS` | 并发数 | `16` |
| `MIN_MBPS` | 高速标记阈值（Mbps） | `10.0` |

### 地区筛选 `[regions]`

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `LIST` | 筛选的地区代码列表 | `["HK","JP","KR","US","TW"]` |
| `PREFER_FAST` | 精选时优先选高速节点 | `true` |
| `MAX_PER_REGION` | 每地区最多保留数 | `5` |

### 拉取设置 `[fetch]`

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `MAX_RETRIES` | 最大重试次数 | `3` |
| `RETRY_DELAY` | 重试间隔（秒） | `3` |
| `TIMEOUT` | HTTP 响应超时（秒） | `10` |
| `CONNECT_TIMEOUT` | HTTP 连接超时（秒） | `5` |

### 输出 `[output]`

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `FULL_FILE` | 完整结果文件 | `full_ips.txt` |
| `BEST_FILE` | 精选结果文件 | `best_ips.txt` |

### 推送到 edgetunnel `[push]`

将测速结果推送到 [edgetunnel](https://github.com/cmliu/edgetunnel) 的 KV 存储，自动更新优选 IP。

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `ENABLED` | 是否启用推送 | `false` |
| `ACCOUNT_ID` | Cloudflare Account ID | `""` |
| `API_TOKEN` | CF API Token（需要 KV:Edit 权限） | `""` |
| `KV_NAMESPACE_ID` | KV 命名空间 ID | `""` |
| `INPUT_FILE` | 推送的源文件 | `best_ips.txt` |

启用后 `main.py` 跑完自动推送，也可单独运行：

```bash
python push_proxyip.py
```

## 输出示例

```
1.2.3.4:443#US [优选高速 32.5ms | 45.2Mbps]
5.6.7.8:443#JP [128.3ms | 8.1Mbps]
```

## 项目结构

```
cf-optimizer/
├── main.py              # 入口，4 阶段流水线
├── push_proxyip.py      # 推送优选 IP 到 edgetunnel KV
├── config.toml          # 配置文件
├── src/
│   ├── config.py        # 配置加载（TOML → AppConfig + PushConfig）
│   ├── models.py        # 数据结构（Node, TcpResult, SpeedResult）
│   ├── parser.py        # 节点行解析（IP:Port#Region）
│   ├── sources.py       # 远程/本地数据源拉取与去重
│   ├── tcp.py           # TCP 延迟测试 + 候选筛选
│   ├── speed.py         # curl 下载速度测试
│   └── output.py        # 结果写入 + 统计摘要
├── full_ips.txt         # 完整测速结果（运行后生成）
└── best_ips.txt         # 精选节点（运行后生成）
```

## 来源

合并自 `优选IP/update.py` 和 `cfnb-main/main.py`，重构为模块化架构。相比原版：

- 配置格式从 JSON 改为 TOML
- TCP 测试使用 asyncio 异步（原 `cfnb-main` 用线程池）
- 移除了 DNS 更新、GitHub 同步、微信通知功能
- 输出从 4 份文件精简为 2 份
