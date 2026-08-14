"""
DiscoveryProvider 抽象基类

自定义渠道只需继承 `DiscoveryProvider` 并实现 `search()` 方法，
然后调用 `register_discovery()` 注册即可被 CLI 和 API 自动发现。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class DiscoveryResult:
    """统一搜索结果格式"""
    title: str
    """媒体标题"""
    link_url: str
    """资源链接 (115share/magnet/quark/...)"""
    link_type: str
    """链接类型: 115share / magnet / quark / aliyun / ..."""
    source_name: str = ""
    """来源名称（显示用）"""
    quality: str = ""
    """画质: 4K / 1080p / 720p / 未知"""
    year: str = ""
    """年份"""
    receive_code: str = ""
    """提取码"""
    extra: Dict[str, Any] = field(default_factory=dict)
    """额外信息（备用）"""


class DiscoveryProvider(ABC):
    """资源发现提供者基类"""

    name: str = ""
    """唯一标识，如 'my_telegram'"""
    label: str = ""
    """显示名称，如 '我的TG频道'"""

    @abstractmethod
    def search(self, keyword: str, **kwargs) -> List[DiscoveryResult]:
        """
        搜索资源，返回候选列表。
        
        Args:
            keyword: 搜索关键词
            **kwargs: 扩展参数（如 limit, quality 等）
        
        Returns:
            搜索结果列表
        """
        ...

    def validate(self) -> bool:
        """检测配置是否有效（如 Cookie 是否过期）"""
        return True

    @property
    def config_fields(self) -> List[Dict[str, Any]]:
        """
        配置字段定义，用于 Web UI 动态渲染。
        返回格式: [{"key": "field_name", "label": "显示名", "type": "text|password|url"}]
        """
        return []
