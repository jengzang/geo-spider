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

```bash
python3 -m geonode_spider run-dmfw-chars --chars 尾村坑山 --export all --resume
```

说明：

- `--chars`：输入一个汉字集，程序会逐字执行 contain 查询
- `--resume`：从 `data/raw/` 下的进度文件断点续跑
- 程序会在结果过多时自动按行政区 `code` 分片，再在本地 SQLite 中按 `source_id` 去重

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
python3 -m geonode_spider run-dmfw-chars --chars 尾村坑山 --export all --resume
```

### 脚本入口

```bash
python3 scripts/bootstrap_sample_data.py
python3 scripts/export_data.py --format all
python3 scripts/run_spider.py --source mock --export all
python3 scripts/run_dmfw_chars.py --chars 尾村坑山 --export all --resume
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

当前 SQLite 以三张核心表为主：

- `regions`：行政区划与标准地名主数据
- `dmfw_places`：民政部地名查询结果去重主表
- `crawl_runs`：每次抓取任务的运行记录

这样设计的目标是：

- 先把数据规范化落地
- 再从统一数据层导出多种格式
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
