# DMFW Details Spider

逐条请求民政部 `stname/detailsPub` 接口，获取地名详情数据。

## 背景

已有 `src/dmfw_places_spider/` 通过关键词搜索 `stname/listPub` 获取地名列表（~1144 万条），写入 `data/processed/dmfw_places_total.db`。
本项目从该总库导出的 `source_id` 出发，逐条请求详情接口。

## 依赖

```bash
pip install requests
```

## 实际操作流程

### 第一步：导出 source_id（已导出则跳过）

```bash
python3 scripts/export_source_ids.py
```

生成 `data/id/dmfw_places_single.txt`（934 万条）和 `data/id/dmfw_places_multi.txt`（210 万条）。

### 第二步：同步 ID 到进度库

```bash
python3 -m dmfw_details_spider.sync_ids \
  --id-file data/id/dmfw_places_single.txt \
  --id-file data/id/dmfw_places_multi.txt \
  --state-db data/processed/details_progress.sqlite
```

输出新增/已存在/各状态计数。重复运行只插入新增 ID。

### 第三步：QPS 探测（推荐）

```bash
python3 -m dmfw_details_spider.calibrate \
  --id-file data/id/dmfw_places_single.txt \
  --sample-size 100 \
  --qps-levels 1,2,5,10,20 \
  --duration-per-level 30
```

阶梯测试，输出建议安全 QPS。

### 第四步：小规模验证

先 dry-run 验证流程：

```bash
python3 -m dmfw_details_spider.launch \
  --workers 1 \
  --state-db data/processed/details_progress.sqlite \
  --master-db data/processed/dmfw_place_details_master.sqlite \
  --worker-output-dir data/interim/details_workers \
  --global-qps 2 \
  --sample-limit 20 \
  --dry-run
```

去掉 `--dry-run` 发起真实请求验证接口：

```bash
python3 -m dmfw_details_spider.launch \
  --workers 1 \
  --state-db data/processed/details_progress.sqlite \
  --master-db data/processed/dmfw_place_details_master.sqlite \
  --worker-output-dir data/interim/details_workers \
  --global-qps 2 \
  --sample-limit 20
```

### 第五步：正式采集

```bash
python3 -m dmfw_details_spider.launch \
  --workers 20 \
  --state-db data/processed/details_progress.sqlite \
  --master-db data/processed/dmfw_place_details_master.sqlite \
  --worker-output-dir data/interim/details_workers \
  --global-qps 80 \
  --batch-size 100 \
  --request-timeout 10 \
  --max-retries 3 \
  --merge-after-finish
```

### 查看进度

```bash
python3 -m dmfw_details_spider.status \
  --state-db data/processed/details_progress.sqlite \
  --master-db data/processed/dmfw_place_details_master.sqlite
```

### 中断后续跑

Ctrl+C 退出后，直接重新执行相同 launch 命令即可续跑。超时未完成的 claimed ID 会被自动回收（默认 30 分钟）。

### 手动汇总 worker 临时库

```bash
python3 -m dmfw_details_spider.merge_outputs \
  --worker-output-dir data/interim/details_workers/run_20260704_153000 \
  --master-db data/processed/dmfw_place_details_master.sqlite
```

加 `--delete-worker-db-after-merge` 汇总后删除临时库。

## 命令一览

| 命令 | 用途 |
|---|---|
| `sync_ids` | 同步 ID 文件到进度库 |
| `calibrate` | QPS 阶梯探测 |
| `worker` | 启动单个 worker |
| `launch` | 启动多个 worker（推荐） |
| `merge_outputs` | 汇总 worker 临时库到总库 |
| `status` | 查看采集进度 |

## 主要配置项

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--workers` | 1 | worker 数量 |
| `--global-qps` | 10 | 全局 QPS 上限 |
| `--request-interval` | 0 | 每请求间隔秒（优先级高于 QPS 自动计算） |
| `--jitter-min / --jitter-max` | 0.05 / 0.3 | 请求间隔随机抖动 |
| `--request-timeout` | 10 | 请求超时秒数 |
| `--max-retries` | 3 | 最大重试次数 |
| `--batch-size` | 100 | 每批领取 ID 数 |
| `--claim-timeout-minutes` | 30 | claimed 超时回收分钟数 |
| `--sample-limit` | 0 | 限制处理条数（0=不限制） |
| `--dry-run` | false | 干跑模式，不发 HTTP 请求 |
| `--merge-after-finish` | false | worker 结束后自动汇总 |
| `--delete-worker-db-after-merge` | false | 汇总后删除 worker 临时库 |

## 数据库文件

| 文件 | 说明 |
|---|---|
| `data/processed/details_progress.sqlite` | 共享进度库，只有 `id_tasks` 表 |
| `data/interim/details_workers/<run_id>/worker_NNN.sqlite` | worker 临时库，每次运行新建 |
| `data/processed/dmfw_place_details_master.sqlite` | 长期累加总库，永不删除 |

## 注意事项

- 探测结果：QPS≤2 成功率 100%，QPS≥3 约 20% 随机 5xx，3 次重试后有效率 ~99%。无限速/反爬
- 遇到 429/403 自动退避降速，请勿绕过
- Worker 临时库汇总前不要删除
- 总库只累加，不删除
- 先 dry-run → 小规模 sample-limit → 正式采集
