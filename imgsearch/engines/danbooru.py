"""
Danbooru 搜索引擎实现

Danbooru 使用 IQDB (Image Query Database) 进行以图搜图。
需要注册获取 API Key: https://danbooru.donmai.us/
需要同时提供 login（用户名）和 api_key（API 密钥）。

认证方式：
  - HTTP Basic Auth（login:api_key）
  - 或在 URL 参数中传递 login + api_key

API 文档：https://danbooru.donmai.us/wiki_pages/help:api
"""

import io
from pathlib import Path
from typing import List

import requests
from requests.auth import HTTPBasicAuth
from PIL import Image

from imgsearch import secrets
from imgsearch.engines.base import SearchEngine, SearchResult
from imgsearch.engines.schema import COMMON_SCHEMA, Field, Schema


class Danbooru(SearchEngine):
    """Danbooru 搜索引擎"""

    NAME = "danbooru"
    DISPLAY_NAME = "Danbooru"
    DEFAULT_API_URL = "https://danbooru.donmai.us"
    DEFAULT_ORDER = 50
    # 需要账号才能用，默认不启用，避免开箱即报错
    ENABLED_BY_DEFAULT = False

    CONFIG_SCHEMA = COMMON_SCHEMA.extend(
        Schema(
            # 原本要求用户去「自定义查询参数」里手填 login，隐蔽且易错。
            # 现在是独立字段，且有 .env 回退。
            Field("api_key", "API Key", "secret", "",
                  help="留空时从 .env 的 DANBOORU_API_KEY 读取",
                  # 引擎在缺这个值时直接报错，因此界面上必须标成必填 ——
                  # 否则用户看到「可选」跳过去，然后撞上运行时报错。
                  required=True, env_var="DANBOORU_API_KEY"),
            # 类型是 secret：存 .env、只在「凭据」页编辑 ——
            # 否则引擎页和凭据页都能改却不互通（之前就是这个 bug）。
            # 但 mask=False：用户名打码后没法核对自己有没有打错。
            Field("login", "用户名", "secret", "",
                  help="Danbooru 账号名（不是邮箱）。"
                       "注：IQDB 引擎无需账号也能查 Danbooru 的帖子",
                  env_var="DANBOORU_LOGIN", required=True, mask=False,
                  placeholder="your_username"),
        ),
    )

    def __init__(self, **options):
        super().__init__(**options)

        # 用户名：配置优先，其次 .env
        self.login = (
            str(self.opt("login", "") or "").strip()
            or (secrets.get("DANBOORU_LOGIN", "") or "")
        )
        # API Key：配置里始终为空（凭据只存 .env），这里从 .env 回退
        self.api_key = (
            self.api_key or secrets.get("DANBOORU_API_KEY", "") or ""
        )

        if not self.login:
            raise ValueError(
                "Danbooru 用户名未配置！\n"
                "  1. 在引擎配置的「用户名」字段填入 Danbooru 账号\n"
                "  2. 或写入 .env：DANBOORU_LOGIN=你的用户名"
            )
        if not self.api_key:
            raise ValueError(
                "Danbooru API Key 未配置！\n"
                "  1. https://danbooru.donmai.us/profile → API Key\n"
                "  2. 写入 .env：DANBOORU_API_KEY=你的KEY"
            )

    def user_agent(self) -> str:
        """
        Danbooru 要求客户端表明身份。

        其文档原文：**"Don't impersonate browsers"**，
        而且它真的会执行 —— 实测同一代理、同一端点、只改 UA：

            伪造 Chrome UA → HTTP 403
            诚实 UA        → HTTP 200

        也就是说全局那个伪造浏览器 UA 会让 Danbooru 引擎**必然 403**。
        带上账号名，也便于对方在限流时联系而不是直接封禁。
        """
        return f"image-search/1.0 (user {self.login or 'anonymous'})"

    def search(self, image_path: str) -> List[SearchResult]:
        """
        通过上传图片搜索

        Args:
            image_path: 图片文件路径

        Returns:
            搜索结果列表
        """
        file_path = Path(image_path)
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {image_path}")

        # 读取并压缩图片
        try:
            with Image.open(image_path) as img:
                buf = io.BytesIO()
                img.convert("RGB").save(buf, format="JPEG", quality=95)
                buf.seek(0)
                files = {"file": ("image.jpg", buf, "image/jpeg")}
        except Exception as e:
            raise ValueError(f"无法读取图片: {image_path}\n{e}")

        return self._call_api(files=files)

    def search_by_url(self, image_url: str) -> List[SearchResult]:
        """
        通过图片 URL 搜索

        Args:
            image_url: 图片 URL

        Returns:
            搜索结果列表
        """
        return self._call_api(data={"url": image_url})

    def _call_api(
        self,
        files: dict = None,
        data: dict = None,
    ) -> List[SearchResult]:
        """调用 Danbooru IQDB API"""
        session = self.make_session()

        # HTTP Basic Auth (login:api_key)
        session.auth = HTTPBasicAuth(self.login, self.api_key)

        api_url = (self.api_url or self.DEFAULT_API_URL).rstrip("/")
        endpoint = f"{api_url}/iqdb_queries.json"

        # 请求参数
        payload = {"limit": 20}
        if data:
            payload.update(data)
        payload = self.merge_params(payload)

        try:
            resp = session.post(endpoint, files=files, data=payload, timeout=self.timeout)
            resp.raise_for_status()
            posts = resp.json()
        except requests.RequestException as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status == 401:
                # 亲手把「填错哪个字段」说清楚 —— 这是用户最可能卡住的地方
                raise ConnectionError(
                    "Danbooru 认证失败（401）：用户名或 API Key 不正确。\n"
                    f"  当前用户名：{self.login or '（空）'}\n"
                    "  · 用户名填**账号名**（不是邮箱）—— 其文档原文："
                    "\"login is your username\"\n"
                    "  · API Key 在 https://danbooru.donmai.us/profile "
                    "→ 点 Generate API key\n"
                    "  两者都在「凭据」页填写。"
                ) from e
            if status == 403:
                body = ""
                if getattr(e, "response", None) is not None:
                    body = (e.response.text or "")[:200]
                # 两种 403 的成因完全不同，必须分开说 ——
                # 凭据有效但等级不够时是「Access denied」，
                # 而 UA 被判定为伪装/未认证时是 CSRF 那条。
                if "Access denied" in body:
                    raise ConnectionError(
                        "Danbooru 拒绝访问（403 Access denied）："
                        "**凭据是对的，但账号等级不够**。\n"
                        "  · 以图搜图（/iqdb_queries）不对普通 Member 账号开放，"
                        "需要 Gold 及以上（付费）\n"
                        "  · 替代方案：用 **IQDB 引擎** —— 它不需要任何账号"
                        "就能查 Danbooru 的帖子，覆盖率略低\n"
                        f"  Danbooru 原话：{body or '（无响应体）'}"
                    ) from e
                raise ConnectionError(
                    "Danbooru 拒绝了请求（403）：请求未被认可为已认证。\n"
                    f"  · User-Agent 是否被发现是伪装浏览器（当前："
                    f"{self.user_agent()}）\n"
                    "  · 可在引擎页「自定义请求头」里自行指定 User-Agent\n"
                    f"  · 也可能是该出口 IP 被限制\n"
                    f"  Danbooru 原话：{body or '（无响应体）'}"
                ) from e
            raise ConnectionError(f"Danbooru API 请求失败: {e}")
        finally:
            session.close()

        if not isinstance(posts, list):
            raise RuntimeError(f"Danbooru API 返回格式异常: {posts}")

        return self._parse_posts(posts)

    def _parse_posts(self, posts: list) -> List[SearchResult]:
        """
        解析 IQDB 返回的帖子列表为 SearchResult

        IQDB 返回的帖子按匹配度降序排列，但不提供具体相似度百分比，
        这里用排名位置估算相似度。
        """
        results = []

        for i, post in enumerate(posts):
            if not isinstance(post, dict):
                continue

            # 相似度估算：排名越靠前相似度越高
            if i == 0:
                similarity = 100.0
            elif i == 1:
                similarity = 95.0
            elif i == 2:
                similarity = 90.0
            elif i < 5:
                similarity = 85.0
            elif i < 10:
                similarity = 80.0
            else:
                similarity = 70.0

            # Pixiv ID
            pixiv_id = str(post.get("pixiv_id", "")) or None

            # 来源 URL
            ext_urls = []
            source = post.get("source", "")
            if source:
                ext_urls.append(source)
            file_url = post.get("file_url", "")
            if file_url:
                ext_urls.append(file_url)

            # 从 tag_string 中提取画师名
            # 格式: "blonde_hair blue_eyes artist:xxx copyright:yyy"
            artist = post.get("tag_string_artist", "")
            if artist.startswith("artist:"):
                artist = artist[len("artist:"):]
            elif not artist:
                artist = None

            # 提取作品出处（版权标签）
            material = post.get("tag_string_copyright", "")
            if material.startswith("copyright:"):
                material = material[len("copyright:"):]
            elif not material:
                material = None

            # 提取所有标签作为标题描述
            all_tags = post.get("tag_string", "")
            # 取前几个有意义的核心标签作为标题
            title_parts = []
            if all_tags:
                for tag in all_tags.split():
                    if not tag.startswith(("artist:", "copyright:", "character:", "rating:", "meta:")):
                        title_parts.append(tag.replace("_", " "))
                    if len(title_parts) >= 5:
                        break
            title = ", ".join(title_parts) if title_parts else None

            # 高清原图 URL
            highres_url = post.get("large_file_url") or file_url or None

            result = SearchResult(
                source="Danbooru",
                similarity=similarity,
                pixiv_id=pixiv_id,
                artist=artist,
                title=title,
                ext_urls=ext_urls,
                highres_url=highres_url,
                thumbnail=post.get("preview_file_url"),
                material=material,
                danbooru_id=str(post.get("id", "")),
                twitter_id=None,
            )

            results.append(result)

        return results
