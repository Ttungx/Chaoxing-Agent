"""ConfigHolder — 配置热更持有者。

只允许白名单字段运行时更新，其他字段需要重启 session。
"""
import asyncio
import copy
import json
import logging
from pathlib import Path
from typing import Optional

from chaoxing_agent import paths

log = logging.getLogger(__name__)

CONFIG_PATH = paths.runtime_config_dir() / "config.json"

# 热更白名单（运行时改后下次 step 生效）
HOT_FIELDS = {"timing", "thresholds", "runtime", "selected"}


class ConfigHolder:
    def __init__(self, initial: dict, config_path: Optional[Path] = None):
        self._data = copy.deepcopy(initial)
        self._lock = asyncio.Lock()
        self._config_path = config_path or CONFIG_PATH

    def get(self, key: str) -> dict:
        """返回配置片段。"""
        return self._data.get(key, {})

    def snapshot(self) -> dict:
        """返回完整配置快照（用于 emit config_changed 事件）。"""
        return copy.deepcopy(self._data)

    async def update(self, patch: dict) -> list[str]:
        """异步热更：只接受白名单字段。

        Returns: 被热更的字段名列表
        """
        async with self._lock:
            hot = []
            for k, v in patch.items():
                if k in HOT_FIELDS:
                    self._data[k] = v
                    hot.append(k)
            self._save_to_disk()
            return hot

    def _save_to_disk(self) -> None:
        """写盘。"""
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.error(f"save config failed: {e}")
