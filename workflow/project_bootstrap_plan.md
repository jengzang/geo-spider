# Project Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 初始化一个可扩展的 Python 行政区划爬虫项目骨架，并让配置、SQLite、导出链路可直接跑通。

**Architecture:** 使用 `src` 标准包承载核心逻辑，`scripts/` 提供薄入口；以 SQLite 作为标准化数据层，其他格式导出围绕统一模型展开；反爬请求能力与数据源解析能力分层设计。

**Tech Stack:** Python 3.11+, requests, BeautifulSoup, sqlite3, openpyxl, PyYAML, python-dotenv, pytest

---

### Task 1: 仓库与项目级文件

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `config/settings.example.yaml`
- Modify: `README.md`
- Modify: `workflow/`

- [ ] Step 1: 整理根目录工作流参考文件到 `workflow/`
- [ ] Step 2: 建立项目依赖、测试配置与脚本入口
- [ ] Step 3: 更新 README，写入项目说明、目录结构、运行方式与更新日志

### Task 2: 配置与模型层

**Files:**
- Create: `src/dmfw_places_spider/config/settings.py`
- Create: `src/dmfw_places_spider/models/region.py`
- Create: `tests/unit/test_config.py`

- [ ] Step 1: 先写配置合并测试，明确 `.env` 与 YAML 的优先级
- [ ] Step 2: 运行测试并确认因为模块缺失而失败
- [ ] Step 3: 实现 `Settings` 与 `load_settings`
- [ ] Step 4: 补充基础数据模型
- [ ] Step 5: 重新运行测试并确认通过

### Task 3: SQLite 与导出层

**Files:**
- Create: `src/dmfw_places_spider/storage/sqlite.py`
- Create: `src/dmfw_places_spider/exporters/*.py`
- Create: `tests/unit/test_sqlite_repository.py`
- Create: `tests/integration/test_export_pipeline.py`

- [ ] Step 1: 先写仓储层与导出流水线测试
- [ ] Step 2: 运行测试并确认因为实现缺失而失败
- [ ] Step 3: 实现 SQLite schema、upsert 与读取
- [ ] Step 4: 实现 JSON / CSV / Excel / SQLite 导出器
- [ ] Step 5: 重新运行测试并确认通过

### Task 4: 请求层、流水线与入口

**Files:**
- Create: `src/dmfw_places_spider/crawler/*.py`
- Create: `src/dmfw_places_spider/sources/*.py`
- Create: `src/dmfw_places_spider/geo/*.py`
- Create: `src/dmfw_places_spider/pipelines/*.py`
- Create: `src/dmfw_places_spider/services/*.py`
- Create: `src/dmfw_places_spider/cli.py`
- Create: `scripts/*.py`

- [ ] Step 1: 实现随机 UA、代理池、限速与 `SpiderSession` 骨架
- [ ] Step 2: 提供 mock 数据源与 mock 地理编码器
- [ ] Step 3: 串起 `run-pipeline`、`init-db`、`show-config`、`export` 命令
- [ ] Step 4: 运行完整测试与 CLI 验证
