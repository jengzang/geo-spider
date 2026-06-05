# GeoNode-Spider

轻量级 Python 地名与行政区划爬虫项目，面向个人自用场景，主要用于从官方渠道抓取行政区划、标准地名及经纬度坐标，并统一沉淀为本地可查询、可导出的数据资产。

当前仓库已经完成一套适合长期演进的项目骨架，重点放在：

- 官方数据抓取的标准化工程结构
- 反爬请求层的抽象能力
- SQLite / JSON / CSV / Excel 四种本地输出
- 可扩展的数据源适配器与地理编码接口
- `CLI + scripts` 双入口

## 项目目标

- 按层级抓取行政区划数据，覆盖省、市、区县、乡镇等结构
- 从官方地名平台抓取标准地名与基础属性
- 结合地图服务补充经纬度
- 将同一份标准化数据导出为多种本地格式，方便分析、校验和复用

## 当前状态

当前版本是 `0.1.0`，已完成：

- 标准 `src` 包结构
- `.env + YAML` 双通道配置
- SQLite 主库存储与运行记录表
- JSON / CSV / Excel / SQLite 导出器
- 随机 UA、代理池、限速、重试等请求层骨架
- `mock` 数据源与 `mock` 地理编码器
- 民政部 `dmfw` 汉字集 contain 抓取正式模式
- 基础测试骨架

当前已经内置第一个真实站点模式：

- 民政部地名信息服务平台 `dmfw.mca.gov.cn`

后续仍可继续接入：

- 统计局行政区划数据
- 高德 / 百度 / 腾讯地图地理编码服务

## 技术栈

- Python 3.11+
- `requests`
- `beautifulsoup4`
- `sqlite3` 标准库
- `PyYAML`
- `python-dotenv`
- `openpyxl`
- `pytest`

可选解析依赖：

- `lxml`

## 项目结构

```text
GeoNode-Spider/
├── config/                    # 本地 YAML 配置模板
├── data/
│   ├── raw/                   # 原始抓取响应与探测结果
│   ├── interim/               # 中间处理结果
│   ├── processed/             # 本地 SQLite 主库等处理结果
│   └── exports/               # json/csv/xlsx/db 导出产物
├── logs/                      # 运行日志
├── scripts/                   # 薄脚本入口
├── src/geonode_spider/
│   ├── config/                # 配置加载
│   ├── crawler/               # 请求会话、代理、限速、UA
│   ├── exporters/             # 多格式导出
│   ├── geo/                   # 地理编码 provider
│   ├── models/                # 统一数据模型
│   ├── pipelines/             # 抓取流水线
│   ├── services/              # 项目级编排
│   ├── sources/               # 官方数据源适配器
│   ├── storage/               # SQLite schema 与仓储
│   └── utils/                 # 通用工具
├── tests/                     # 单元 / 集成测试
└── workflow/                  # 项目工作流参考文档
```

## 快速开始

### 1. 安装

```bash
python3 -m pip install -e ".[dev]"
```

如果需要 `lxml` 解析支持：

```bash
python3 -m pip install -e ".[dev,parser]"
```

### 2. 初始化本地配置

```bash
cp .env.example .env
cp config/settings.example.yaml config/settings.yaml
```

推荐把：

- API Key
- 代理地址
- 本机目录差异

写在 `.env` 中；把更稳定的项目级参数写在 `config/settings.yaml` 中。

配置优先级：

`环境变量 > .env > config/settings.yaml > 代码默认值`

### 3. 初始化数据库

```bash
python3 -m geonode_spider init-db
```

### 4. 运行示例流水线

```bash
python3 -m geonode_spider run-pipeline --source mock --export all
```

### 5. 运行民政部汉字集抓取

先同步并缓存省级行政区 code：

```bash
python3 -m geonode_spider sync-dmfw-divisions
```

推荐直接写入累计总库且只导出 db 的正式模式命令：

```bash
python3 -m geonode_spider run-dmfw-chars \
  --chars 村 \
  --match-mode contain \
  --write-total-db \
  --total-db-path data/processed/dmfw_places_total.db \
  --resume
```

也可以使用任务级 JSON（示例配置默认也只导出 db；如需 json/csv/xlsx，请在 JSON 中显式添加 `export`）：

```bash
python3 -m geonode_spider run-dmfw-chars --json config/dmfw-task.example.json
```

说明：

- `sync-dmfw-divisions`：预先同步并缓存省级行政区 code
- `--chars`：输入一个汉字集，程序会逐字执行查询；例如传 `村` 就是全国“村”字模糊匹配
- `--match-mode`：支持 `contain` / `exact`，默认 `contain`
- `--province-codes`：可选，传一个或多个省份 code，限制抓取范围；不传则遍历全部已缓存省份
- `--export`：默认只导出 `db`；只有显式传 `json` / `csv` / `xlsx` / `all` 时才额外导出这些文件
- `--json`：读取 dmfw 任务级 JSON 配置，适合常态化跑批
- `--resume`：从 `data/raw/` 下的进度文件断点续跑
- `--flush-batch-size`：增量落库批次，默认每 `1000` 条落库一次
- `--max-runtime-seconds`：可选运行时长上限；不传则默认一直跑到完成
- `--write-total-db`：把结果累计写入总库，按 `source_id` 去重 upsert
- `--total-db-path`：指定总库路径；不传时默认写到 `data/processed/dmfw_places_total.db`
- `--no-write-run-db`：可选，不写默认运行库，只维护总库
- 程序使用 Python `requests` 直接请求 dmfw，不会调用本机 Chrome 浏览器
- 当前实现会先从已缓存省级 code 起步；对 `村` 的真实验证显示，全国 `code=''` 的 `total` 与 33 个标准省级 code 累加结果一致
- 程序会先请求第一页读取 `total`，若结果过多会自动按行政区 `code` 递归分片；分片后每个分片内部会自动按页抓取直到该分片的最后一页
- 当前站点的超界页行为不是报空，而是重复返回最后一页，因此项目不能依赖“翻到空页停止”，而是必须依赖第一页返回的 `total` 精确计算总页数；当前实现已经按这个方式处理
- run 库 `dmfw_places` 会保留 `geometry_type` 与 `coordinates_json`；total 库会把单点写入 `dmfw_places_single`，把多坐标 geometry 写入 `dmfw_places_multi`

### 6. 查看当前配置

```bash
python3 -m geonode_spider show-config
```

## 常用命令

### CLI 入口

```bash
python3 -m geonode_spider init-db
python3 -m geonode_spider show-config
python3 -m geonode_spider sample-data
python3 -m geonode_spider export --format all
python3 -m geonode_spider run-pipeline --source mock --export all
python3 -m geonode_spider run-dmfw-chars --chars 村 --match-mode contain --write-total-db --total-db-path data/processed/dmfw_places_total.db --resume
python3 -m geonode_spider run-dmfw-chars --json config/dmfw-task.example.json
```

### 脚本入口

```bash
python3 scripts/bootstrap_sample_data.py
python3 scripts/export_data.py --format all
python3 scripts/run_spider.py --source mock --export all
python3 scripts/run_dmfw_chars.py --chars 村 --match-mode contain --write-total-db --total-db-path data/processed/dmfw_places_total.db --resume
```

## 数据输出

项目以 SQLite 作为规范化主存储，并支持导出为：

- `SQLite (.db)`
- `JSON (.json)`
- `CSV (.csv)`
- `Excel (.xlsx)`

默认本地目录约定：

- `data/raw/`：原始抓取数据、接口探测结果
- `data/interim/`：中间处理结果
- `data/processed/`：SQLite 主库
- `data/exports/`：导出文件

这些目录默认只保留 `.gitkeep`，本地抓取产物不会提交到仓库。

## 反爬设计

请求层当前已经抽象出以下能力：

- 随机 `User-Agent`
- 代理池切换接口
- 请求重试
- 随机休眠
- 失败退避
- `requests.Session` 统一封装

这部分能力集中在 `src/geonode_spider/crawler/` 下，避免把反爬逻辑散落在具体脚本里。

## 数据模型与存储

当前 SQLite 以三类核心数据为主：

- `regions`：行政区划与标准地名主数据
- `dmfw_places`：dmfw 运行库，保留抓取上下文、原始响应字段映射与完整几何信息
- `crawl_runs`：每次抓取任务的运行记录

当启用 `--write-total-db` 时，累计总库会拆成两张表：

- `dmfw_places_single`：仅存单坐标记录，保留 `longitude` / `latitude`
- `dmfw_places_multi`：仅存多坐标记录，保留 `geometry_type` + `coordinates_json`

当前几何处理规则：

- run 库 `dmfw_places` 会保存 `geometry_type` 与 `coordinates_json`
- 若 `gdm.coordinates` 只有一个点，则额外写入 `longitude` / `latitude`
- 若 `gdm.coordinates` 有多个点（如 `linestring`），则不再只取第一个点；完整坐标数组进入 `coordinates_json`
- total 库会按坐标数量自动分流到 `dmfw_places_single` / `dmfw_places_multi`
- 单点 / 多点两张 total 表都按 `source_id` 做 upsert 去重

关于全国/逐省 total：

- 已用真实接口验证，`村` 字全国 `code=''` 查询得到的 `total` 与 33 个标准省级 code 累加结果一致
- 因此当前逐省起步策略在 `村` 这个样本上没有发现 total 级遗漏

这样设计的目标是：

- run 库保留完整抓取与调试上下文
- total 库只保留累计主数据，并且不丢失多坐标 geometry
- 后续新增数据源时尽量不改导出链路

## 测试

运行测试：

```bash
pytest -v
```

## 开发路线

- 接入统计局行政区划适配器
- 增加真实地图服务地理编码 provider
- 增加增量更新与版本化策略
- 增加更多查询与筛选导出能力

## 使用说明

- 本项目面向个人学习、研究和数据整理用途
- 请优先遵守官方站点服务条款与访问频率要求
- 建议始终使用温和限速与代理轮换策略，避免影响目标站点

## 工作流参考

仓库根目录下的 `workflow/` 保存了项目约定和协作文档，例如：

- `workflow/project_bootstrap_plan.md`
- `workflow/readme_update_protocol.md`
- `workflow/code_commit_protocol.md`

## License

MIT
