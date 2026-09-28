"""
搜索引擎基类
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class SearchResult:
    """搜索结果数据类"""
    source: str                       # 搜索引擎名称: sauceNAO / ascii2d
    similarity: float                 # 相似度百分比 0-100
    pixiv_id: Optional[str] = None    # Pixiv 作品 ID
    pixiv_page: int = 0               # Pixiv 多图页码 (p0, p1, p2...)
    artist: Optional[str] = None      # 画师名
    artist_id: Optional[str] = None   # 画师用户 ID
    title: Optional[str] = None       # 作品标题
    ext_urls: List[str] = field(default_factory=list)   # 来源 URL 列表
    highres_url: Optional[str] = None # 高清原图 URL
    thumbnail: Optional[str] = None   # 缩略图 URL
    material: Optional[str] = None    # 出处作品名（如游戏/动画）
    danbooru_id: Optional[str] = None # Danbooru ID
    gelbooru_id: Optional[str] = None # Gelbooru ID
    twitter_id: Optional[str] = None  # Twitter 推文 ID

    def is_valid(self) -> bool:
        """判断结果是否有可用信息"""
        return self.similarity > 0 or bool(self.pixiv_id or self.ext_urls)

    def short_summary(self) -> str:
        """生成简短摘要"""
        parts = []
        if self.pixiv_id:
            parts.append(f"Pixiv ID: {self.pixiv_id}")
        if self.artist:
            parts.append(f"画师: {self.artist}")
        if self.title:
            parts.append(f"标题: {self.title}")
        if self.similarity > 0:
            parts.append(f"相似度: {self.similarity:.1f}%")
        return " | ".join(parts) if parts else "未找到匹配结果"

    def pixiv_image_id(self) -> Optional[str]:
        """
        返回带页码的 Pixiv 文件名格式，如 74267012_p0.jpg

        如果 pixiv_id 为空返回 None，否则返回 {pixiv_id}_p{pixiv_page}.jpg
        """
        if not self.pixiv_id:
            return None
        return f"{self.pixiv_id}_p{self.pixiv_page}.jpg"


class SearchEngine:
    """搜索引擎基类"""

    def __init__(self, timeout: int = 30, proxies: dict = None,
                 api_url: str = "", headers: dict = None, params: dict = None,
                 api_key: str = "", bypass_cfw: bool = False):
        self.timeout = timeout
        self.proxies = proxies
        self.api_url = api_url
        self.headers = headers or {}
        self.params = params or {}
        self.api_key = api_key
        self.bypass_cfw = bypass_cfw

    def search(self, image_path: str) -> List[SearchResult]:
        """
        以图搜图

        Args:
            image_path: 图片文件路径

        Returns:
            搜索结果列表，按相似度降序排列
        """
        raise NotImplementedError

    def search_by_url(self, image_url: str) -> List[SearchResult]:
        """
        通过图片 URL 搜索

        Args:
            image_url: 图片 URL

        Returns:
            搜索结果列表
        """
        raise NotImplementedError

    def name(self) -> str:
        """引擎名称"""
        return self.__class__.__name__
