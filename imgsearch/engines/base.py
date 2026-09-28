"""
搜索引擎基类与统一结果模型
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from imgsearch.engines.schema import COMMON_SCHEMA, Schema


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
    extra_ids: Dict[str, str] = field(default_factory=dict)  # 其他站点的 ID
    detail: Optional[str] = None      # 补充说明（如 TraceMoe 的片源文件名、命中时间点）

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
    """
    搜索引擎基类

    子类通过类属性声明自己：

      NAME            : 配置里使用的稳定标识（如 "sauceNAO"）
      DISPLAY_NAME    : 给人看的名字（如 "SauceNAO"）
      CONFIG_SCHEMA   : 该引擎可配置的字段（:class:`~imgsearch.engines.schema.Field`）
      DEFAULT_API_URL : 未配置 api_url 时使用的地址

    配置以关键字参数传入，**未识别的字段进入 ``self.options``**，
    因此给 schema 加字段不需要改动任何 ``__init__`` 签名。
    """

    NAME: str = ""
    DISPLAY_NAME: str = ""
    DEFAULT_API_URL: str = ""
    # 出厂默认列表里的排序权重（小的在前）。显式声明，
    # 避免依赖模块发现顺序（那只是字母序，排出来的搜索顺序没道理）。
    DEFAULT_ORDER: int = 100
    # 是否在出厂默认列表里启用
    ENABLED_BY_DEFAULT: bool = True
    CONFIG_SCHEMA: Schema = COMMON_SCHEMA

    def __init__(self, api_key: str = "", timeout: int = 30, proxies: dict = None,
                 api_url: str = "", headers: dict = None, params: dict = None,
                 bypass_cfw: bool = False, request_delay: float = 8.0,
                 **options):
        self.api_key = api_key or ""
        self.timeout = int(timeout) if timeout else 30
        self.proxies = proxies
        # api_url 留空时回退到引擎内置默认地址
        self.api_url = api_url or self.DEFAULT_API_URL or ""
        self.headers = dict(headers or {})
        self.params = dict(params or {})
        self.bypass_cfw = bool(bypass_cfw)
        self.request_delay = (
            float(request_delay) if request_delay not in (None, "") else 8.0
        )
        # 引擎特有字段（由 CONFIG_SCHEMA 声明，如 long_limit / login）
        self.options: Dict[str, Any] = dict(options)

    # ── 选项读取（集中处理，避免各引擎重复写 int() / or 默认值）──

    def opt(self, key: str, default: Any = None) -> Any:
        """读取引擎特有选项；未设置或空串时返回默认值"""
        v = self.options.get(key)
        if v is None or v == "":
            return default
        return v

    def opt_int(self, key: str, default: int) -> int:
        """
        读取整数选项。

        ⚠️ 刻意不用 ``value or default`` —— 那会把合法的 ``0``
        （多个限额字段用它表示「无限制」）错误地换成默认值。
        """
        v = self.options.get(key)
        if v is None or v == "":
            return default
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    def opt_float(self, key: str, default: float) -> float:
        """读取浮点选项（同样保留合法的 0）"""
        v = self.options.get(key)
        if v is None or v == "":
            return default
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    def opt_bool(self, key: str, default: bool = False) -> bool:
        """读取布尔选项"""
        v = self.options.get(key)
        if v is None or v == "":
            return default
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in {"1", "true", "yes", "y", "on", "是", "启用"}

    # ── 接口 ──────────────────────────────────────────────────

    def search(self, image_path: str) -> List[SearchResult]:
        """
        以图搜图

        Args:
            image_path: 图片路径

        Returns:
            搜索结果列表
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
        """引擎名称（优先用注册名，便于配置与日志一致）"""
        return self.NAME or self.__class__.__name__

    @classmethod
    def describe(cls) -> str:
        """单行描述，供引擎列表展示"""
        return cls.DISPLAY_NAME or cls.NAME or cls.__name__
