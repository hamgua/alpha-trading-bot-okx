"""OKX raw endpoint executor.

集中处理 ccxt raw 方法查找和线程池执行，避免各服务重复编写
``get_callable + run_in_executor``。该执行器不改变请求参数和解析逻辑。
"""

import asyncio
from typing import Any, Callable, Optional, TypeVar

from .okx_raw import get_callable

T = TypeVar("T")


class OkxRawExecutor:
    """执行 OKX raw endpoint 调用。"""

    def __init__(self, exchange: Any):
        self.exchange = exchange

    def get_method(self, snake_name: str, camel_name: str):
        """按 ccxt 新旧命名风格获取 raw 方法。"""
        return get_callable(self.exchange, snake_name, camel_name)

    async def call(
        self,
        snake_name: str,
        camel_name: str,
        payload: Any,
        parser: Optional[Callable[[Any], T]] = None,
        unavailable_message: str = "OKX raw endpoint is unavailable",
    ) -> T:
        """在线程池中执行 raw 方法并解析响应。"""
        method = self.get_method(snake_name, camel_name)
        if method is None:
            raise RuntimeError(unavailable_message)

        def _invoke():
            response = method(payload)
            return parser(response) if parser else response

        return await asyncio.get_event_loop().run_in_executor(None, _invoke)
