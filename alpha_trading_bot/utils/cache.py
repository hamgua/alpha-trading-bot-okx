"""
缓存管理器 - 提供统一的缓存接口
"""

import json
import time
import logging
from typing import Dict, Any, Optional, Union
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class CacheManager:
    """缓存管理器"""

    def __init__(self, default_ttl: int = 3600):
        """初始化缓存管理器"""
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.default_ttl = default_ttl

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """设置缓存"""
        ttl = ttl or self.default_ttl
        expire_time = time.time() + ttl

        self.cache[key] = {
            'value': value,
            'expire_time': expire_time,
            'created_at': time.time()
        }

        logger.debug(f"缓存已设置: {key} (TTL: {ttl}s)")

    def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        if key not in self.cache:
            return None

        cache_item = self.cache[key]
        current_time = time.time()

        # 检查是否过期
        if current_time > cache_item['expire_time']:
            del self.cache[key]
            logger.debug(f"缓存已过期: {key}")
            return None

        logger.debug(f"缓存命中: {key}")
        return cache_item['value']

    def delete(self, key: str) -> bool:
        """删除缓存"""
        if key in self.cache:
            del self.cache[key]
            logger.debug(f"缓存已删除: {key}")
            return True
        return False

    def exists(self, key: str) -> bool:
        """检查缓存是否存在"""
        return self.get(key) is not None

    def clear(self) -> None:
        """清空所有缓存"""
        self.cache.clear()
        logger.info("所有缓存已清空")

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        total_keys = len(self.cache)
        expired_keys = 0
        current_time = time.time()

        for key, item in self.cache.items():
            if current_time > item['expire_time']:
                expired_keys += 1

        return {
            'total_keys': total_keys,
            'expired_keys': expired_keys,
            'active_keys': total_keys - expired_keys,
            'default_ttl': self.default_ttl
        }

    def cleanup_expired(self) -> int:
        """清理过期缓存"""
        expired_keys = []
        current_time = time.time()

        for key, item in list(self.cache.items()):
            if current_time > item['expire_time']:
                expired_keys.append(key)

        for key in expired_keys:
            del self.cache[key]

        if expired_keys:
            logger.info(f"已清理 {len(expired_keys)} 个过期缓存")

        return len(expired_keys)

class MemoryCache:
    """内存缓存（兼容旧代码）"""

    def __init__(self):
        self.cache = CacheManager()

    def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        """设置缓存"""
        self.cache.set(key, value, ttl)

    def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        return self.cache.get(key)

    def delete(self, key: str) -> bool:
        """删除缓存"""
        return self.cache.delete(key)

    def clear(self) -> None:
        """清空缓存"""
        self.cache.clear()

# 全局缓存实例
cache_manager = CacheManager()
memory_cache = MemoryCache()