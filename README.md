# GeoNode-Spider

轻量级 Python 地名与行政区划爬虫项目，从官方渠道抓取行政区划、标准地名及经纬度坐标，统一沉淀为本地可查询、可导出的数据资产。

## 项目目标

- 按层级抓取行政区划数据，覆盖省、市、区县、乡镇
- 从民政部地名平台抓取标准地名与基础属性
- 将同一份标准化数据导出为多种本地格式，方便分析、校验和复用


## 项目结构

```text
GeoNode-Spider/
├── config/                    # 本地 YAML 配置模板与任务 JSON
├── data/
│   ├── raw/                   # 原始抓取响应与探测结果
│   ├── chars/                 # 汉字字频分段文件
│   ├── id/                    # source_id 导出文件
│   ├── interim/               # 中间处理结果（如 worker 临时库）
│   ├── processed/             # 本地 SQLite 主库、进度库、总库
│   └── exports/               # json/csv/db 导出产物
├── src/
│   ├── dmfw_places_spider/    # 地名列表采集（listPub 接口）
│   │   ├── config/            # 配置加载
│   │   ├── crawler/           # 请求会话、代理、限速、UA
│   │   ├── exporters/         # 多格式导出
│   │   ├── geo/               # 地理编码 provider
│   │   ├── models/            # 统一数据模型
│   │   ├── pipelines/         # 抓取流水线
│   │   ├── services/          # 项目级编排
│   │   ├── sources/           # 数据源适配器
│   │   ├── storage/           # SQLite schema 与仓储
│   │   └── utils/             # 通用工具
│   ├── dmfw_details_spider/   # 地名详情采集（detailsPub 接口）
│   └── xzqh_spider/           # 行政区划代码采集
├── logs/                      # 运行日志（运行时生成）
├── scripts/                   # 辅助脚本
├── tests/                     # 单元 / 集成测试
```

## 三个子包概览

| 包 | CLI 入口 | 数据源 | 功能 |
|---|---|---|---|
| `dmfw_places_spider` | `dmfw-places` | dmfw.mca.gov.cn listPub | 按汉字 + 省份搜索地名列表 |
| `dmfw_details_spider` | `dmfw-detail` | dmfw.mca.gov.cn detailsPub | 逐条获取地名详情 |
| `xzqh_spider` | `xzqh-spider` | tool.51yww.com | 爬取全国行政区划代码（省/市/区县/乡镇） |

三个包各自独立运行，通过数据文件衔接：`dmfw_places_spider` 产生地名列表 → 导出 source_id → `dmfw_details_spider` 逐条获取详情；`xzqh_spider` 提供独立的行政区划代码参考数据。

## 技术栈

- Python 3.11+
- `requests`、`beautifulsoup4`
- `sqlite3` 标准库
- `PyYAML`、`python-dotenv`
- `openpyxl`（Excel 导出）
- `pytest`

可选解析依赖：`lxml`

## 快速开始

### 1. 安装

```bash
python3 -m pip install -e ".[dev]"
```

需要 `lxml` 解析：

```bash
python3 -m pip install -e ".[dev,parser]"
```

### 2. 初始化配置

```bash
cp .env.example .env
cp config/settings.example.yaml config/settings.yaml
```

配置优先级：`环境变量 > .env > config/settings.yaml > 代码默认值`

### 3. 初始化数据库

```bash
dmfw-places init-db
```

---

## dmfw_places_spider — 地名列表采集

通过民政部地名服务 `listPub` 接口，以汉字为关键词逐省搜索地名列表，结果写入 SQLite。

### 数据流

```
汉字集 → listPub 接口（逐省逐页）→ 原始 JSON → SQLite run 库 → total 库（去重）
```

### 命令一览

```bash
dmfw-places init-db              # 初始化 SQLite schema
dmfw-places show-config          # 查看合并后的运行时配置
dmfw-places export --format all  # 从 SQLite 导出数据
dmfw-places run-pipeline --source mock --export all  # 用 mock 数据跑通流程
dmfw-places sync-dmfw-divisions  # 同步省级行政区代码到本地缓存
dmfw-places run-dmfw-chars ...   # 核心命令：汉字集搜索
```

### 核心用法：run-dmfw-chars

**最简命令**（单字模糊搜索，结果写入总库）：

```bash
dmfw-places run-dmfw-chars \
  --chars 村 \
  --match-mode contain \
  --write-total-db \
  --total-db-path data/processed/dmfw_places_total.db \
  --resume
```

**通过 JSON 任务文件**（适合批跑多个字频段）：

```json
{
  "chars": "村",
  "match_mode": "contain",
  "province_codes": ["11", "12"],
  "resume": true,
  "flush_batch_size": 5000,
  "sync_divisions_first": true,
  "no_write_run_db": true,
  "write_total_db": true,
  "total_db_path": "data/processed/dmfw_places_total.db"
}
```

```bash
dmfw-places run-dmfw-chars --json config/config.json
```

**并行跑多个任务**：

```bash
dmfw-places run-dmfw-chars \
  --json config/task_a.json \
  --json config/task_b.json \
  --workers 2
```

### 关键参数

| 参数 | 说明 |
|---|---|
| `--chars` | 汉字集字符串，如 `村` 或 `村屯寨`；也可以传文件路径 |
| `--match-mode` | `contain`（模糊）或 `exact`（精确） |
| `--province-codes` | 逗号分隔的省份代码，如 `11,12`；不传则遍历全部 |
| `--resume` | 从 `data/raw/` 下的进度文件断点续跑 |
| `--flush-batch-size` | 增量落库批次大小，默认 1000 |
| `--write-total-db` | 结果写入累计总库（按 source_id upsert 去重） |
| `--total-db-path` | 总库路径，默认 `data/processed/dmfw_places_total.db` |
| `--no-write-run-db` | 不写运行库，只维护总库 |
| `--max-runtime-seconds` | 运行时长上限，默认不限 |
| `--sync-divisions-first` | 跑之前先刷新省份缓存 |

### 分片策略

程序先请求第一页读取 `total` 总数，若单省结果过多，自动按行政区代码递归分片；每个分片内按页翻取直到最后一页。当前站点的超界页不会返回空，而是重复返回最后一页，因此翻页终止不依赖"翻到空页"，而是依赖第一页返回的 `total` 精确计算总页数。

以 `村` 字验证：全国 `code=''` 查询得到的 `total` 与 33 个标准省级 code 累加结果一致，逐省起步策略不存在 total 级遗漏。

### 数据库表

| 表 | 说明 |
|---|---|
| `dmfw_places`（run 库） | 保留完整抓取上下文、geometry_type、coordinates_json |
| `dmfw_places_single`（total 库） | 单点坐标记录，含 longitude/latitude |
| `dmfw_places_multi`（total 库） | 多点几何记录，含 geometry_type + coordinates_json |

几何处理规则：

- 若坐标仅一个点，写入 `longitude` / `latitude`
- 若坐标有多个点（如 linestring），完整坐标数组进入 `coordinates_json`，不再只取第一个点
- total 库按坐标数量自动分流到 `dmfw_places_single` / `dmfw_places_multi`，均按 `source_id` upsert 去重

---

## dmfw_details_spider — 地名详情采集

独立的多进程详情采集器，从 `dmfw_places_spider` 产生的 source_id 出发，逐个请求 `detailsPub` 接口获取每一条地名的完整字段。

### 数据流

```
source_id 文件 → 同步到进度库 → 多 worker 并发请求 → worker 临时库 → 合并到 master 总库
```

### 架构

- **进度库**（state_db）：`data/processed/details_progress.sqlite`，跟踪每个 ID 的状态（pending/claimed/done/retry/failed）
- **Worker 临时库**：`data/interim/details_workers/<run_id>/worker_NNN.sqlite`，每个 worker 独立写入
- **Master 总库**：`data/processed/dmfw_place_details_master.sqlite`，长期累加，永不删除
- 启动时 round-robin 分配 ID 给各 worker，退出时自动 flush 进度 → 合并 → 释放未处理 claimed

### 完整操作流程

#### 第一步：导出 source_id

从 `dmfw_places_spider` 的总库导出待采集的 source_id：

```bash
python3 scripts/export_source_ids.py
```

生成 `data/id/dmfw_places_single.txt` 和 `data/id/dmfw_places_multi.txt`。

#### 第二步：同步 ID 到进度库

```bash
python3 -m dmfw_details_spider.sync_ids \
  --id-file data/id/dmfw_places_single.txt \
  --id-file data/id/dmfw_places_multi.txt \
  --state-db data/processed/details_progress.sqlite
```

重复运行只插入新增 ID，已有 ID 不受影响。

#### 第三步：QPS 探测（推荐）

```bash
python3 -m dmfw_details_spider.calibrate \
  --id-file data/id/dmfw_places_single.txt \
  --sample-size 100 \
  --qps-levels 1,2,5,10,20 \
  --duration-per-level 30
```

阶梯测试，输出各 QPS 级别的成功率。

#### 第四步：小规模验证

```bash
# dry-run 验证流程
dmfw-detail --config src/dmfw_details_spider/config.example.yaml \
  --sample-limit 20 --dry-run

# 真实请求验证
dmfw-detail --config src/dmfw_details_spider/config.example.yaml \
  --sample-limit 20
```

#### 第五步：正式采集

```bash
dmfw-detail --config src/dmfw_details_spider/config.example.yaml
```

后台运行：

```bash
nohup dmfw-detail --config src/dmfw_details_spider/config.example.yaml \
  > logs/dmfw_details_spider/launch.log 2>&1 &
```

#### 查看进度

```bash
dmfw-detail-status
```

#### 中断续跑

Ctrl+C 或 `kill <pid>` 退出后，直接重新执行相同命令即可续跑。超时未完成的 claimed ID 会被自动回收（默认 30 分钟）。

### 配置

编辑 `src/dmfw_details_spider/config.example.yaml`：

```yaml
# ID 池
id_files: []  # 启动时自动同步的 ID 文件列表

# 路径
state_db: data/processed/details_progress.sqlite
master_db: data/processed/dmfw_place_details_master.sqlite
worker_output_dir: data/interim/details_workers

# 性能
workers: 20               # worker 进程数
per_worker_qps: 5         # 每个 worker 独立 QPS 上限
request_timeout: 10       # 请求超时秒数

# 重试
max_retries: 5
retry_base_delay: 0.3
retry_max_delay: 5.0

# 进度
progress_flush_interval: 2000   # 每 N 条写一次共享进度库
output_flush_interval: 100      # 每 N 条批量写自己的输出库

# 运行
merge_after_finish: true
merge_interval: 0               # 运行中定期合并间隔（0=仅退出时合并）
delete_worker_db_after_merge: true
log_level: INFO
```

### 子命令

| 命令 | 用途 |
|---|---|
| `dmfw-detail` | 启动多 worker 采集（launch） |
| `dmfw-detail-status` | 查看采集进度 |
| `python3 -m dmfw_details_spider.sync_ids` | 同步 ID 文件到进度库 |
| `python3 -m dmfw_details_spider.calibrate` | QPS 阶梯探测 |
| `python3 -m dmfw_details_spider.merge_outputs` | 手动汇总 worker 临时库到总库 |

### 数据库文件

| 文件 | 说明 |
|---|---|
| `data/processed/details_progress.sqlite` | 共享进度库，id_tasks 表 |
| `data/interim/details_workers/<run_id>/worker_NNN.sqlite` | worker 临时库，每次运行新建 |
| `data/processed/dmfw_place_details_master.sqlite` | 长期累加总库，永不删除 |

---

## xzqh_spider — 行政区划代码采集

从 tool.51yww.com 爬取全国行政区划代码，覆盖省/市/区县/乡镇四个层级，支持多线程并发、断点续跑。

### 数据流

```
种子页(北京) → 发现所有省份 → 并发逐页解析 → SQLite → 导出 json/csv/db
```

### 命令

```bash
# 爬取（默认 8 线程）
xzqh-spider crawl

# 自定义参数
xzqh-spider crawl \
  --workers 16 \
  --output data/processed/xzqh.db \
  --resume \
  --delay 0.5

# 导出
xzqh-spider export --format json
xzqh-spider export --format csv
xzqh-spider export --format db
```

### 关键参数

| 参数 | 说明 |
|---|---|
| `--workers` | 并发线程数，默认 8 |
| `--output` | SQLite 输出路径，默认 `data/processed/xzqh.db` |
| `--resume` | 从 checkpoint 文件断点续跑 |
| `--delay` | 每请求间隔秒数，默认 0 |
| `--sample-limit` | 限制抓取页数（0=不限制），用于测试 |

### 爬取策略

- 从北京（110000000000）种子页发现全部省级代码
- 多线程并发爬取，队列驱动
- 到区县级（district/town）停止递归，子级直接从页面解析
- 每 100 页自动保存 checkpoint
- 解析停用状态（`<span>` 标签内标记）

### 数据模型

12 位行政区划代码，字段包括：`code`、`name`、`short_code`、`parent_code`、`level`（province/city/district/town）、`status`（正常/停用）、`source_url`。

---

## 数据输出

项目以 SQLite 作为规范化主存储，支持导出为：

- SQLite（`.db`）
- JSON（`.json`）
- CSV（`.csv`）
- Excel（`.xlsx`）

目录约定：

| 目录 | 用途 |
|---|---|
| `data/raw/` | 原始抓取数据、进度文件 |
| `data/interim/` | 中间处理结果（worker 临时库等） |
| `data/processed/` | SQLite 主库、总库、进度库 |
| `data/exports/` | 导出文件 |

这些目录下的产物均在 `.gitignore` 中，不会提交到仓库。

## 反爬设计

请求层集中在 `src/dmfw_places_spider/crawler/` 下：

- 随机 User-Agent
- 代理池切换接口
- 请求重试与失败退避
- 随机休眠
- `requests.Session` 统一封装
- Token Bucket 限速（dmfw_details_spider）

## 测试

```bash
pytest -v
```

## 使用说明

- 本项目面向个人学习、研究和数据整理用途
- 请遵守官方站点服务条款与访问频率要求
- 建议使用温和限速策略，避免影响目标站点

## License

MIT
