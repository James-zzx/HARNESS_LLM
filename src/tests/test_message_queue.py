import threading
import time

from harness.message_queue import MessageQueue


def test_push_and_pop_all():
    queue = MessageQueue(task_id="task-1")
    queue.push({"role": "user", "content": "hello"})
    messages = queue.pop_all()
    assert messages == [{"role": "user", "content": "hello"}]
    assert queue.pop_all() == []
    assert queue.has_pending() is False


def test_has_pending():
    queue = MessageQueue(task_id="task-2")
    assert queue.has_pending() is False
    queue.push({"role": "user", "content": "hi"})
    assert queue.has_pending() is True
    queue.pop_all()
    assert queue.has_pending() is False


def test_wait_returns_on_push():
    queue = MessageQueue(task_id="task-3")

    def pusher():
        time.sleep(0.05)
        queue.push({"role": "user", "content": "wake up"})

    thread = threading.Thread(target=pusher)
    thread.start()
    start = time.monotonic()
    messages = queue.wait_for_message(timeout=2.0)
    elapsed = time.monotonic() - start
    thread.join()
    assert messages == [{"role": "user", "content": "wake up"}]
    assert elapsed < 1.0


def test_wait_timeout_returns_empty():
    queue = MessageQueue(task_id="task-4")
    start = time.monotonic()
    messages = queue.wait_for_message(timeout=0.2)
    elapsed = time.monotonic() - start
    assert messages == []
    assert elapsed < 1.0


def test_concurrent_push_pop():
    queue = MessageQueue(task_id="task-5")
    n_push = 8
    per_push = 50
    total = n_push * per_push
    collected = []
    collected_lock = threading.Lock()

    def pusher(index):
        for i in range(per_push):
            queue.push({"role": "user", "content": f"m-{index}-{i}"})

    def popper():
        while True:
            messages = queue.wait_for_message(timeout=0.2)
            with collected_lock:
                collected.extend(m["content"] for m in messages)
                if len(collected) >= total:
                    return

    push_threads = [threading.Thread(target=pusher, args=(i,)) for i in range(n_push)]
    pop_threads = [threading.Thread(target=popper) for _ in range(3)]
    for thread in push_threads + pop_threads:
        thread.start()
    for thread in push_threads:
        thread.join()
    for thread in pop_threads:
        thread.join(timeout=10)
    expected = sorted(f"m-{i}-{j}" for i in range(n_push) for j in range(per_push))
    assert sorted(collected) == expected


def test_reset_clears_pending():
    queue = MessageQueue(task_id="task-6")
    queue.push({"role": "user", "content": "x"})
    queue.reset()
    assert queue.has_pending() is False
    assert queue.wait_for_message(timeout=0.1) == []
