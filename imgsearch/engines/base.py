"""
搜索引擎基类与统一结果模型
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from imgsearch.engines.quota import QuotaState

# 从来源链接里认出 Pixiv 作品 ID 的两种写法：
#   新式  https://www.pixiv.net/artworks/74267012
#   旧式  https://www.pixiv.net/member_illust.php?mode=medium&illust_id=74267012
_PIXIV_ID_RE = re.compile(r"(?:artworks/|illust_id=)(\d+)")

from imgsearch.engines.schema import COMMON_SCHEMA, Schema


def _as_text(value) -> Optional[str]:
    """
    把可能是列表的字段归一成字符串。

    SauceNAO 在不同索引下会把 ``creator`` / ``material`` 这类字段返回成
    **列表**（如 ``["aldehyde"]``）。不归一的话：
      - 写进 SQLite 会报 "type 'list' is not supported"（图库入库整个失败）
      - CSV/GUI 里会显示成 ``['aldehyde']`` 这种带括号引号的怪样子
    """
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        parts = [str(v).strip() for v in value if v is not None and str(v).strip()]
        return ", ".join(parts) or None
    text = str(value).strip()
    return text or None


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

    def __post_init__(self) -> None:
        """
        在数据类自身的边界上做归一化。

        放在这里而不是各个引擎里，是因为「结果是这个形状」属于 SearchResult
        自己的约定 —— 任何引擎（含用户自定义的）构造出来的实例都自动成立。
        起因是一个真实 bug：SauceNAO 返回的 artist 是列表，
        写进 SQLite 时抛 "type 'list' is not supported"，图库入库整个失败。
        """
        for name in ("pixiv_id", "artist", "artist_id", "title", "material",
                     "highres_url", "thumbnail", "danbooru_id", "gelbooru_id",
                     "twitter_id", "detail"):
            setattr(self, name, _as_text(getattr(self, name)))

        # 列表类字段统一成 str 列表 / str→str 字典
        urls = self.ext_urls or []
        if isinstance(urls, str):
            urls = [urls]
        self.ext_urls = [str(u).strip() for u in urls if u and str(u).strip()]

        ids = self.extra_ids or {}
        self.extra_ids = ({str(k): str(v) for k, v in ids.items()}
                          if isinstance(ids, dict) else {})

        try:
            self.pixiv_page = int(self.pixiv_page or 0)
        except (TypeError, ValueError):
            self.pixiv_page = 0
        try:
            self.similarity = float(self.similarity or 0)
        except (TypeError, ValueError):
            self.similarity = 0.0

        # ⚠️ pixiv_id 缺失时从来源链接里补出来。
        # 实测：SauceNAO 命中 Danbooru/Gelbooru 索引时，data 里没有 pixiv_id 字段，
        # 但 ext_urls 里带着旧式的 member_illust.php?...illust_id=NNN。
        # 不补的话这个 ID 就丢了 —— 而它正是生成 pixiv.re / pixiv.cat
        # 下载直链（AriaNg 批量下载）所必需的东西。
        if not self.pixiv_id:
            for url in self.ext_urls:
                found = _PIXIV_ID_RE.search(url)
                if found:
                    self.pixiv_id = found.group(1)
                    break

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
        # ⚠️ 代理**只**用调用方传入的值，引擎自己不读配置。
        # 曾经这里写成 `self.proxies or get_proxies()`，导致上层
        # 已经判定「代理不可用、本次直连」并传 None 之后，
        # 引擎又去读配置把那个坏代理捡回来 —— 自动降级被彻底架空。
        # 代理该不该用由调用方（search_image / EngineStore）决定。
        self.proxies = proxies
        # api_url 留空时回退到引擎内置默认地址
        self.api_url = api_url or self.DEFAULT_API_URL or ""
        self.headers = dict(headers or {})
        self.params = dict(params or {})
        self.bypass_cfw = bool(bypass_cfw)
        self.request_delay = (
            float(request_delay) if request_delay not in (None, "") else 8.0
        )
        # 配置里的名字（不是类的 NAME）—— 同一个适配器类挂多个实例时，
        # 配额文件、错误提示都该用它，否则界面会显示成「genericJson」
        self.engine_name = str(options.pop("engine_name", "") or "")
        # 配置里的显示名（不是类的 DISPLAY_NAME）—— 搜索结果里
        # 「引擎」这一列、批量日志的「已识别 … <引擎>」都用它。
        # 同一个适配器类挂多个实例时，只有这个值能区分它们。
        self.display_name = str(options.pop("display_name", "") or "")
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

    # ── 请求构造 ──────────────────────────────────────────────

    def user_agent(self) -> str:
        """
        本引擎应使用的 User-Agent；返回空串表示用全局默认。

        ⚠️ 全局默认是一个**伪造的浏览器 UA**（为了绕过部分站点的 Cloudflare）。
        但有些站点明确要求客户端表明身份，甚至会拒掉伪造 UA ——
        例如 Danbooru 实测：伪造 UA 走代理得到 403，诚实 UA 得到 200。
        这类引擎覆写本方法。
        """
        return ""

    def make_session(self, **kwargs):
        """
        建会话，并应用「自定义请求头」。

        ⚠️ 之前各引擎直接调 create_session，`headers` 配置项只被存下来、
        从未被用 —— GUI 里能填、写着"自定义请求头"，实际毫无作用。
        """
        from imgsearch.utils.network import create_session

        session = create_session(
            proxies=self.proxies,
            timeout=self.timeout,
            user_agent=self.user_agent() or None,
            **kwargs,
        )
        if self.headers:
            session.headers.update(
                {str(k): str(v) for k, v in self.headers.items()})
        return session

    def merge_params(self, payload: dict) -> dict:
        """
        并入「自定义查询参数」。

        同名的键**以引擎自身的为准** —— 否则用户一次手滑覆盖了 url/limit，
        搜索会静默地搜错东西，比"没生效"更难排查。
        """
        if not self.params:
            return dict(payload)
        merged = {str(k): str(v) for k, v in self.params.items()}
        merged.update(payload)
        return merged

    @classmethod
    def auth_mode_for(cls, settings: dict = None) -> str:
        """
        凭据需求的**实际值**。

        默认就是类属性 ``AUTH_MODE``；声明式适配器会覆盖它 ——
        因为同一个适配器类挂不同实例时，凭据需求由**实例配置**决定
        （auth_mode=none 还是 query/basic），类属性说不准。
        """
        return cls.AUTH_MODE

    def _settings_view(self) -> dict:
        """给 auth_mode_for 用的「我这份配置」"""
        return dict(self.options)

    @property
    def uses_api_key(self) -> bool:
        """
        本次是否要使用凭据。

        配置里「使用 API Key」关掉 → False（引擎应跳过凭据、按匿名处理）。
        ``AUTH_MODE == "none"`` 的引擎恒为 False —— 它本来就没有凭据可发。
        """
        if self.auth_mode_for(self._settings_view()) == "none":
            return False
        return self.opt_bool("use_api_key", True)

    @property
    def auth_label(self) -> str:
        """给界面显示的一句话"""
        mode = self.auth_mode_for(self._settings_view())
        return {"required": "必须凭据", "optional": "可选凭据",
                "none": "无需凭据"}.get(mode, mode)

    def quota_state(self) -> List[QuotaState]:
        """
        本引擎当前的额度状态；默认表示「无限制」。

        有滑动窗口限额的引擎覆写它（见 SauceNAO / TraceMoe）。
        ⚠️ 必须由**引擎自己**报，不能在外面重建计数器：
        配额文件是按引擎各自命名的（SauceNAO 沿用历史文件名
        `saucenao_quota.json`），外面重建会读到另一个空文件，
        于是"剩余 100 次"永远不变。批量识别靠这个在联网前判断能否继续。
        """
        return []

    def request_interval(self) -> float:
        """
        两次请求之间至少间隔多少秒；0 表示未声明。

        用于批量识别**逐张节流**。为什么需要它：短期速率限制（如 SauceNAO
        的 4 次/30 秒）是服务端判定的，超了会返回 429；而 auto 模式的引擎循环
        把异常兜掉后换下一个引擎 —— 于是批量连续跑时，第 5 张起就被
        **静默降级**到覆盖差很多的引擎，尽管当天额度还剩一大半。

        批量按这个值放慢速度，就能让主引擎真的被每一张用到。
        """
        return 0.0

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

    # 凭据需求，三档统一约定（所有引擎都声明它，即使值是 none）：
    #   required —— 没有凭据就完全不能用（如 SauceNAO）
    #   optional —— 没有凭据能用一部分（如 Danbooru：只能搜公网 URL）
    #   none     —— 本来就不需要凭据（如 IQDB / Ascii2D / TraceMoe）
    AUTH_MODE = "required"

    # 使用须知：启用这个引擎前需要满足的前提条件。
    # 会在 `engines list` 的备注列、`engines show` 与 GUI 引擎页显示 ——
    # 目的是让「为什么用不了」在启用之前就看得见，而不是等搜索时撞报错。
    USAGE_NOTE = ""

    @classmethod
    def describe(cls) -> str:
        """单行描述，供引擎列表展示"""
        return cls.DISPLAY_NAME or cls.NAME or cls.__name__
