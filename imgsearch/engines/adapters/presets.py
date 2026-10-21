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


PRESETS = (
    DANBOORU,
)


def by_name(name: str):
    """按名称找预设（大小写不敏感）"""
    key = (name or "").strip().lower()
    for preset in PRESETS:
        if preset.name.lower() == key:
            return preset
    return None
