#!/bin/bash
# 测试不同 worker 数的实际吞吐量
cd /Users/jengzang/CodeProject/geo/GeoNode-Spider
PY=.venv/bin/python
CONFIG=src/dmfw_details_spider/config.example.yaml

echo "=============================================="
echo "worker/QPS 测试 (每轮60秒, per_worker_qps=5)"
echo "=============================================="

for W in 5 10 15 20 30; do
    echo ""
    echo "--- 测试 workers=$W ---"

    # 改配置
    $PY -c "
import yaml
with open('$CONFIG') as f:
    c = yaml.safe_load(f)
c['workers'] = $W
with open('$CONFIG', 'w') as f:
    yaml.dump(c, f, allow_unicode=True)
"

    # 清理
    pkill -f "dmfw_details_spider" 2>/dev/null
    sleep 2
    find src/dmfw_details_spider -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
    rm -rf crawler_output/workers/run_* 2>/dev/null

    # 释放claimed
    $PY -c "
from dmfw_details_spider.state_db import StateDB
StateDB('crawler_state/details_progress.sqlite').release_all_claimed()
" 2>/dev/null

    # 记下当前 done 数
    DONE_BEFORE=$($PY -c "
from dmfw_details_spider.state_db import StateDB
print(StateDB('crawler_state/details_progress.sqlite').get_stats()['done'])
")

    # 启动，跑60秒
    nohup $PY -m dmfw_details_spider.launch --config $CONFIG > logs/dmfw_details_spider/launch.log 2>&1 &
    PID=$!

    sleep 75  # 给10秒启动+分配时间

    # 停止
    kill $PID 2>/dev/null
    pkill -f "dmfw_details_spider" 2>/dev/null
    sleep 3

    # 统计
    DONE_AFTER=$($PY -c "
from dmfw_details_spider.state_db import StateDB
print(StateDB('crawler_state/details_progress.sqlite').get_stats()['done'])
")

    NEW=$((DONE_AFTER - DONE_BEFORE))

    TOTAL=$(/bin/cat logs/dmfw_details_spider/launch.log | wc -l)
    ERR500=$(/bin/cat logs/dmfw_details_spider/launch.log | grep -c "HTTP 50[02]")
    SUCCESS=$(/bin/cat logs/dmfw_details_spider/launch.log | grep -c "success=")

    echo "  结果: new_done=$NEW  errors=$ERR500  rate=$(echo "scale=1; $NEW/60" | bc)/s"

    # 合并
    $PY -c "
from dmfw_details_spider.output_db import MasterDB, merge_run_directory
import os, glob
run_dirs = glob.glob('crawler_output/workers/run_*')
if run_dirs:
    master = MasterDB('crawler_output/dmfw_place_details_master.sqlite')
    master.initialize()
    for d in run_dirs:
        merge_run_directory(d, master, os.path.basename(d), delete_after=True)
    print(f'  已合并')
" 2>/dev/null

    rm -rf crawler_output/workers/run_* 2>/dev/null
done

# 恢复默认配置
$PY -c "
import yaml
with open('$CONFIG') as f:
    c = yaml.safe_load(f)
c['workers'] = 10
with open('$CONFIG', 'w') as f:
    yaml.dump(c, f, allow_unicode=True)
"
echo ""
echo "=== 测试完成 ==="
