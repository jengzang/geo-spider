"""测试不同 worker/QPS 组合的实际吞吐和错误率。"""
import time, requests, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
import threading

URL = "https://dmfw.mca.gov.cn/stname/detailsPub"
TIMEOUT = 10
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
TEST_IDS = [f"1100000000{i:02d}" for i in range(100)]


def bench(workers, per_qps, duration=30):
    """N 个并发 worker，每个独立 per_qps QPS。"""
    bucket_interval = 1.0 / per_qps if per_qps > 0 else 0
    results = []
    stop = threading.Event()
    idx_lock = threading.Lock()
    idx = [0]
    last_acquire = [time.monotonic()]

    def worker(worker_id):
        s = requests.Session()
        s.headers["User-Agent"] = UA
        while not stop.is_set():
            # TokenBucket per worker
            if per_qps > 0:
                now = time.monotonic()
                next_slot = last_acquire[0] + bucket_interval
                if now < next_slot:
                    time.sleep(next_slot - now)
                last_acquire[0] = max(now, next_slot)

            with idx_lock:
                i = idx[0]
                idx[0] = (i + 1) % len(TEST_IDS)
            id_val = TEST_IDS[i]

            start = time.monotonic()
            try:
                resp = s.post(URL, data={"id": id_val}, timeout=TIMEOUT)
                results.append((worker_id, resp.status_code, time.monotonic() - start))
            except Exception as e:
                results.append((worker_id, f"err:{e}", time.monotonic() - start))

    threads = []
    start_time = time.monotonic()
    for i in range(workers):
        t = threading.Thread(target=worker, args=(i,), daemon=True)
        t.start()
        threads.append(t)

    time.sleep(duration)
    stop.set()
    for t in threads:
        t.join(timeout=2)

    elapsed = time.monotonic() - start_time
    statuses = Counter(r[1] for r in results)
    total = len(results)
    ok = statuses.get(200, 0)
    bad = sum(v for k, v in statuses.items() if k != 200)

    print(f"workers={workers:2d}  per_qps={per_qps}  "
          f"total={total:5d}  200={ok:5d}  err={bad:5d}  "
          f"有效QPS={ok/elapsed:.1f}  错误率={bad/total*100:.0f}%")
    return ok / elapsed


if __name__ == "__main__":
    configs = [
        (5, 3),
        (5, 5),
        (10, 3),
        (10, 5),
        (15, 3),
        (15, 5),
        (20, 3),
        (20, 5),
        (30, 3),
        (30, 5),
    ]

    print(f"{'workers':>8} {'per_qps':>8} {'total':>6} {'200':>6} {'err':>6} {'有效QPS':>8} {'错误率':>6}")
    print("-" * 65)

    best = (0, 0, 0)
    for w, q in configs:
        try:
            r = bench(w, q, duration=30)
            if r > best[2]:
                best = (w, q, r)
        except KeyboardInterrupt:
            break
        time.sleep(3)

    print("-" * 65)
    print(f"最优: workers={best[0]} per_qps={best[1]} 有效QPS={best[2]:.1f}")
