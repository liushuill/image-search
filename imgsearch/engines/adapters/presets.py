"""
内置引擎的「配置预设」

分支 experiment/declarative-only 的目标：**没有 Python 引擎类，只有配置**。
这里放那些原本是 Python 文件的引擎，现在它们只是一份适配器配置。

每个预设声明：
    name        配置里的稳定标识
    display     界面显示名
    adapter     用哪个适配器类（模块路径 + 类名）
    order       排序种子（越小越靠前）
    enabled     默认是否启用
    settings    映射表
"""

from dataclasses import dataclass, field
from typing import Any, Dict

JSON_ADAPTER = ("imgsearch.engines.adapters.generic_json", "GenericJson")
HTML_ADAPTER = ("imgsearch.engines.adapters.generic_html", "GenericHtml")


@dataclass(frozen=True)
class Preset:
    name: str
    display: str
    adapter: tuple
    order: int
    settings: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = False
    # 字段 → 环境变量名。留空则按实例名派生（多实例各用各的）；
    # 这里显式指定是为了**沿用已有的变量名**，用户不必把 Key 再填一遍。
    env: Dict[str, str] = field(default_factory=dict)
    # 启用前的注意事项（显示在引擎页；等价于 Python 引擎的 USAGE_NOTE）
    usage_note: str = ""

    @property
    def module_path(self) -> str:
        return self.adapter[0]

    @property
    def class_name(self) -> str:
        return self.adapter[1]


# ──────────────────────────────────────────────
#  SauceNAO：原本 imgsearch/engines/saucenao.py（323 行）
# ──────────────────────────────────────────────
SAUCENAO = Preset(
    name="sauceNAO",
    display="SauceNAO（Pixiv 覆盖最好）",
    adapter=JSON_ADAPTER,
    order=10,
    enabled=True,
    settings={
        "api_url": "https://saucenao.com/search.php",
        "endpoint": "",
        "method": "POST",
        "image_field": "file",
        "url_field": "url",
        "url_in": "params",
        "auth_mode": "query",
        "results_path": "results",
        "similarity_scale": "0-100",
        "field_similarity": "header.similarity",
        "field_pixiv_id": "data.pixiv_id",
        "field_pixiv_page": "data.pixiv_page",
        "field_artist": "data.member_name|data.creator",
        "field_artist_id": "data.member_id",
        "field_title": "data.title|data.material",
        "field_material": "data.material",
        "field_urls": "data.ext_urls",
        "field_highres": "data.source",
        "field_thumbnail": "header.thumbnail",
        "field_danbooru_id": "data.danbooru_id",
        "field_gelbooru_id": "data.gelbooru_id",
        "field_twitter_id": "data.twitter_user_id",
        "long_limit": 100,
        "long_window": 86400,
        "short_limit": 4,
        "short_window": 30,
        "min_similarity": 60,
        "request_delay": 8.0,
        "params": {"output_type": 2, "db": 999, "numres": 5},
    },
    env={"api_key": "SAUCENAO_KEY"},
    usage_note="需要 SauceNAO API Key（免费申请）。每日 100 次、30 秒内 4 次。",
)


# ──────────────────────────────────────────────
#  Danbooru：原本 imgsearch/engines/danbooru.py（325 行）
#  现在只是「JSON 适配器 + 一张映射表」
# ──────────────────────────────────────────────
DANBOORU = Preset(
    name="danbooru",
    display="Danbooru",
    adapter=JSON_ADAPTER,
    order=50,
    enabled=False,          # 需要未受限的 API Key
    settings={
        "api_url": "https://danbooru.donmai.us",
        "endpoint": "/iqdb_queries.json",
        "method": "POST",
        "image_field": "file",
        "url_field": "url",
        # Danbooru 的 URL 搜索也走 POST 表单，不是查询参数
        "url_in": "data",
        "auth_mode": "basic",
        "results_path": "",            # 响应本身就是数组
        # 它不返回相似度，只能按排名估算
        "similarity_scale": "rank",
        "rank_scores": "100,95,90,85,80,75,70,65,60,55",
        "field_pixiv_id": "pixiv_id",
        "field_danbooru_id": "id",
        "field_artist": "tag_string_artist~strip_prefix:artist:",
        "field_material": "tag_string_copyright~strip_prefix:copyright:",
        "field_title": "tag_string~tags_title:5",
        "field_urls": "source|file_url",
        "field_highres": "large_file_url|file_url",
        "field_thumbnail": "preview_file_url",
        "min_similarity": 60,
        "request_delay": 8.0,
    },
    env={"api_key": "DANBOORU_API_KEY", "login": "DANBOORU_LOGIN"},
    usage_note=(
        "需要未受限的 API Key：Danbooru 会校验 Key 的 IP 允许列表与端点权限列表"
        "（默认都为空=不限制），任一被填过就必须匹配，否则所有端点都 403。"
        "走代理时出口 IP 随节点变化，填死 IP 很容易失效。"
        "不想折腾账号就用 IQDB 引擎 —— 它同样会搜 Danbooru 的帖子。"
    ),
)


# ──────────────────────────────────────────────
#  TraceMoe：原本 imgsearch/engines/tracemoe.py（221 行）
# ──────────────────────────────────────────────
TRACEMOE = Preset(
    name="traceMoe",
    display="TraceMoe（动画截图）",
    adapter=JSON_ADAPTER,
    order=40,
    enabled=False,
    settings={
        "api_url": "https://api.trace.moe/search",
        "endpoint": "",
        "method": "POST",
        "image_field": "image",
        "url_field": "url",
        "url_in": "params",
        "auth_mode": "none",
        "results_path": "result",
        # 它给的 similarity 是 0–1 的小数
        "similarity_scale": "0-1",
        "field_similarity": "similarity",
        # 手写版拼的是「第 5 集 @ 15:48」
        "field_title": "template:第 {episode} 集 @ {from:time}",
        "field_material": ("anilist.title.chinese|anilist.title.native|"
                           "anilist.title.romaji|anilist.title.english"),
        # 主制作公司 = studios 里 isMain 为真的那个
        "field_artist": "anilist.studios.edges[?isMain=true].node.name",
        "field_urls": "anilist.siteUrl|video",
        "field_highres": "image",
        "field_thumbnail": "image",
        "field_detail": "filename",
        # 手写版也传这两个查询参数，否则结果集不同
        "params": {"anilistInfo": "", "cutBorders": ""},
        "long_limit": 100,
        "long_window": 60,
        "min_similarity": 85,
        "request_delay": 8.0,
    },
    usage_note="动画截图专用：能定位到「第几集、第几分几秒」，但只对动画有效。",
)


# ──────────────────────────────────────────────
#  IQDB：原本 imgsearch/engines/iqdb.py（290 行）
# ──────────────────────────────────────────────
IQDB = Preset(
    name="iqdb",
    display="IQDB（多图库聚合）",
    adapter=HTML_ADAPTER,
    order=20,
    enabled=True,
    settings={
        "api_url": "https://iqdb.org",
        "endpoint": "/",
        "method": "POST",
        "image_field": "file",
        "url_field": "url",
        "url_in": "data",
        "auth_mode": "none",
        "container_selector": "#pages",
        "row_selector": "table",
        # 「Your image」「No relevant matches」也是 table，过滤掉
        "row_must_contain": "similarity",
        # 相似度写在整行文本里（"42% similarity"）
        "similarity_scale": "percent-text",
        "field_similarity": ":self",
        "field_urls": "td.image a@href",
        "field_thumbnail": "td.image img@src",
        "field_highres": "td.image a@href|td.image img@src",
        # 图库名就在单元格文本里，不用按主机名映射
        "field_detail": "td:has(img.service-icon)",
        # 抠帖子 ID：按主机名限定，避免把别人的数字当成 danbooru_id
        "field_danbooru_id": ("td.image a@href~"
                              r"regex:danbooru[^/]*/(?:posts|post/show)/(\d+)"),
        "field_gelbooru_id": ("td.image a@href~"
                              r"regex:gelbooru[^/]*/.*[?&]id=(\d+)"),
        "min_similarity": 65,
        "request_delay": 8.0,
    },
    usage_note="不需要账号，用来补 Danbooru 系图库的覆盖。",
)


# ──────────────────────────────────────────────
#  Ascii2D：原本 imgsearch/engines/ascii2d.py（433 行）
#  最难的一个：两步请求（POST 后重定向到结果页）+ Cloudflare
# ──────────────────────────────────────────────
ASCII2D = Preset(
    name="ascii2d",
    display="Ascii2D",
    adapter=HTML_ADAPTER,
    order=30,
    enabled=False,
    settings={
        "api_url": "https://ascii2d.net",
        # POST 到 /search/color/，服务端 302 到 /search/color/<hash>
        "endpoint": "/search/color/",
        "method": "POST",
        "image_field": "file",
        "url_field": "url",
        "url_in": "data",
        "auth_mode": "none",
        # ★ 两步：POST 之后必须再 GET 一次重定向后的结果页
        "follow_redirect": True,
        "step2_delay": 1.0,
        "cloudflare_bypass": True,
        "container_selector": "",
        # 站点改版过多次，用一个并集覆盖几种结构
        "row_selector": ".detail-box, .row.mt-2, .card, .result-item",
        # 它不返回相似度
        "similarity_scale": "none",
        "field_urls": "a[href]@href",
        # 结果页里混着导航链接，只认这几个图站
        "links_from_hosts": ("pixiv.net,twitter.com,x.com,"
                             "danbooru.donmai,yande.re,sankaku"),
        # 从 pixiv 链接里抠作品 ID
        "field_pixiv_id": r"a[href*='pixiv']@href~regex:artworks/(\d+)",
        # 选择器并集会把同一条匹配两次，按 pixiv_id 去重
        "dedupe_by": "field_pixiv_id",
        "min_similarity": 60,
        "request_delay": 3.0,
    },
    usage_note=("需要有 cloudscraper（`pip install cloudscraper`）绕过 Cloudflare。"
                "该站经常拦截自动请求，失败时可忽略。"),
)


PRESETS = (
    SAUCENAO,
    IQDB,
    ASCII2D,
    DANBOORU,
    TRACEMOE,
)


def by_name(name: str):
    """按名称找预设（大小写不敏感）"""
    key = (name or "").strip().lower()
    for preset in PRESETS:
        if preset.name.lower() == key:
            return preset
    return None
