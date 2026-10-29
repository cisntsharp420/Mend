"""Search index rebuild job. (Fault injection: runs away and saturates CPU.)"""
import multiprocessing
import time


def rebuild(shard):
    x = 0
    while True:
        x = (x * 31 + shard) % 1_000_003


if __name__ == "__main__":
    procs = [multiprocessing.Process(target=rebuild, args=(i,)) for i in range(8)]
    for p in procs:
        p.start()
    while True:
        time.sleep(60)
