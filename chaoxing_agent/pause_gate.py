"""PauseGate — 异步同步原语，替换 StateMachine 中的 input() 阻塞。

用法：
    gate = PauseGate()
    # 状态机侧：
    decision = await gate.wait(step, reason)
    # RPC handler 侧（前端发 pause_decision 时调用）：
    gate.resolve(decision)

内部维护 waiter 队列：每个 resolve() 只唤醒一个 waiter，且不会把“过期决策”
残留到下一次暂停。
"""
import asyncio
from collections import deque
from typing import Deque


class PauseGate:
    def __init__(self):
        self._waiters: Deque[asyncio.Future[str]] = deque()
        self._buffered_decisions: Deque[str] = deque()

    async def wait(self, step: int, reason: str) -> str:
        """状态机调用：阻塞等待前端发决策。"""
        if self._buffered_decisions:
            return self._buffered_decisions.popleft()
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        self._waiters.append(future)
        try:
            return await future
        finally:
            try:
                self._waiters.remove(future)
            except ValueError:
                pass

    def resolve(self, decision: str) -> None:
        """RPC handler 调用：解除阻塞。"""
        while self._waiters:
            future = self._waiters.popleft()
            if not future.done():
                future.set_result(decision)
                return
        self._buffered_decisions.append(decision)

    def is_pending(self) -> bool:
        """前端用：当前是否在等决策。"""
        return any(not future.done() for future in self._waiters)
