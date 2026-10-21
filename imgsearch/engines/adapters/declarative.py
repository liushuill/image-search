"""
声明式适配器的公共基类

把「请求怎么发、凭据怎么带、相似度怎么换算」这三件与站点无关的事收在这里；
子类只负责「从响应里把钱取出来」（JSON 走路径、HTML 走选择器）。

⚠️ 故意不支持的（这些请写一个普通引擎文件）：
    · 多步流程（POST → 重定向 → 再 GET）
    · Cloudflare 反爬
    · 需要计算/拼接的字段（如由 ID 推导原图地址）
"""

import re
from typing import List, Optional, Tuple

from imgsearch.engines.base import SearchEngine, SearchResult
from imgsearch.engines.schema import Field, Schema, STR

# 相似度量纲：各站点的刻度完全不同，必须显式声明
SCALES = ("0-100", "0-1", "percent-text", "none")

# 字段映射的键（JSON 路径 / HTML 选择器 共用同一组名字）
MAPPED_FIELDS = (
    ("field_similarity", "相似度", "header.similarity", "td.match"),
    ("field_pixiv_id", "Pixiv ID", "data.pixiv_id", "a@href"),
    ("field_artist", "画师", "data.creator", "td.artist"),
    ("field_title", "标题", "data.title", "td.title"),
    ("field_material", "作品", "data.material", ""),
    ("field_urls", "来源链接", "data.ext_urls", "td.image a@href"),
    ("field_highres", "高清直链", "", ""),
    ("field_thumbnail", "缩略图", "header.thumbnail", "td.image img@src"),
    ("field_detail", "备注", "", ""),
)


def _absolute_url(url: str) -> str:
    """把协议相对地址补全"""
    text = (url or "").strip()
    if text.startswith("//"):
        return "https:" + text
    return text


def mapping_schema(kind: str) -> Schema:
    """
    公共的「字段映射」配置。

    Args:
        kind: ``"json"`` 时帮助文本讲路径；``"html"`` 时讲选择器
    """
    if kind == "json":
        help_text = ("JSON 里的取值路径，点号分隔，如 `data.creator`；数组下标用 "
                     "`results[0].x`。留空表示不取这个字段")
    else:
        help_text = ("CSS 选择器，取文本；加 `@属性` 取属性，如 `td.image a@href`。"
                     "留空表示不取这个字段")
    return Schema(
        *[Field(key, label, STR, example, help=help_text, advanced=True)
          for key, label, example, _ in MAPPED_FIELDS]
    )


class DeclarativeEngine(SearchEngine):
    """两个适配器共用的骨架"""

    AUTH_MODE = "none"
    ENABLED_BY_DEFAULT = False
    # 子类声明自己的响应类型，仅用于日志与提示
    RESPONSE_KIND = "json"

    # ── 配置读取 ────────────────────────────────

    def _endpoint(self) -> str:
        base = (self.api_url or self.DEFAULT_API_URL).rstrip("/")
        endpoint = str(self.opt("endpoint", "") or "").strip()
        if not endpoint:
            return base
        if endpoint.startswith(("http://", "https://")):
            return endpoint
        return f"{base}/{endpoint.lstrip('/')}"

    def _method(self) -> str:
        method = str(self.opt("method", "POST") or "POST").strip().upper()
        return method if method in ("GET", "POST") else "POST"

    def _image_field(self) -> str:
        return str(self.opt("image_field", "file") or "file").strip() or "file"

    def _url_field(self) -> str:
        return str(self.opt("url_field", "url") or "url").strip() or "url"

    # ── 相似度 ──────────────────────────────────

    def _scale(self) -> str:
        scale = str(self.opt("similarity_scale", "0-100") or "0-100").strip()
        return scale if scale in SCALES else "0-100"

    def _scale_similarity(self, raw: str) -> float:
        """
        把站点给的原始值换算成统一的 0–100。

        各站点刻度不同（同一张图 IQDB 报 53%、SauceNAO 报 95%、TraceMoe 报 0.97），
        所以**必须由配置声明**，不能统一假设。
        """
        scale = self._scale()
        if scale == "none":
            return 0.0

        text = (raw or "").strip()
        if not text:
            return 0.0
        if scale == "percent-text":
            # 文本里可能混着别的数字（IQDB 的行里还有 "1500x2100"），
            # 所以优先找**带百分号**的那个，没有再退回第一个数字
            found = (re.search(r"(\d+(?:\.\d+)?)\s*%", text)
                     or re.search(r"(\d+(?:\.\d+)?)", text))
            if not found:
                return 0.0
            try:
                return max(0.0, min(100.0, float(found.group(1))))
            except ValueError:
                return 0.0
        try:
            value = float(text)
        except ValueError:
            return 0.0
        if scale == "0-1":
            value *= 100.0
        return max(0.0, min(100.0, value))

    # ── 请求 ────────────────────────────────────

    def _auth_parts(self) -> Tuple[dict, Optional[tuple]]:
        """
        返回 (要并入查询参数的凭据, BasicAuth 用户名密码或 None)。

        三档：none / query / basic —— 都在配置里选，不需要写代码。
        """
        mode = str(self.opt("auth_mode", "none") or "none").strip().lower()
        if mode == "none":
            return {}, None

        api_key = str(self.opt("api_key", "") or "").strip()
        login = str(self.opt("login", "") or "").strip()
        if mode == "basic":
            return {}, (login, api_key) if login and api_key else None
        # query（默认把有值的都带上）
        params = {}
        if api_key:
            params["api_key"] = api_key
        if login:
            params["login"] = login
        return params, None

    def _request(self, *, image_path: str = "", image_url: str = ""):
        """发一次请求，返回 (响应的解析结果, 会话已关闭的原始文本)"""
        method = self._method()
        endpoint = self._endpoint()
        extra_params, basic = self._auth_parts()
        payload = dict(extra_params)
        payload.update(dict(self.params or {}))

        files = data = None
        if image_path:
            field = self._image_field()
            if method == "GET":
                raise ValueError(
                    f"{self.DISPLAY_NAME} 配置为 GET，但 GET 无法上传本地文件。"
                    "请把「请求方法」改成 POST，或用「通过 URL 搜索」")
            try:
                with open(image_path, "rb") as fh:
                    content = fh.read()
            except OSError as e:
                raise ValueError(f"无法读取图片: {image_path}\n{e}") from e
            files = {field: ("image", content)}
            data = dict(self.opt("form_params", {}) or {})
        else:
            payload[self._url_field()] = image_url

        session = self.make_session()
        if basic is not None:
            from requests.auth import HTTPBasicAuth
            session.auth = HTTPBasicAuth(*basic)
        try:
            if method == "GET":
                resp = session.get(endpoint, params=payload,
                                   timeout=self.timeout)
            else:
                resp = session.post(endpoint, params=payload or None,
                                    files=files, data=data or None,
                                    timeout=self.timeout)
            resp.raise_for_status()
            return resp.text
        except Exception as e:                            # noqa: BLE001
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (401, 403):
                raise ConnectionError(
                    f"{self.DISPLAY_NAME} 拒绝访问（{status}）。\n"
                    "  · 若站点需要凭据：把「鉴权方式」设为 query/basic 并填好 API Key\n"
                    "  · 若站点只是要特定的请求头：在「站点适配」里加，"
                    "例如 Referer / User-Agent\n"
                    "  · 也可能是该出口 IP 被限制"
                ) from e
            raise ConnectionError(f"{self.DISPLAY_NAME} 请求失败: {e}") from e
        finally:
            session.close()

    # ── 结果组装 ────────────────────────────────

    def _make_result(self, get_text, get_links) -> Optional[SearchResult]:
        """
        从一条记录里组装 SearchResult。

        Args:
            get_text: ``(配置键) -> 文本``
            get_links: ``(配置键) -> list[str]``
        """
        raw_sim = get_text("field_similarity")
        similarity = self._scale_similarity(raw_sim)

        # 协议相对地址（``//konachan.com/x``）补成 https —— 很多图库这么写，
        # 不补的话在结果表里点不开
        links = [_absolute_url(u) for u in get_links("field_urls") if u]
        pixiv_id = get_text("field_pixiv_id")
        # 有些站点只给 URL，不给 pixiv_id —— 交给 SearchResult 的归一化去补
        result = SearchResult(
            source=self.DISPLAY_NAME,
            similarity=similarity,
            pixiv_id=pixiv_id or None,
            artist=get_text("field_artist") or None,
            title=get_text("field_title") or None,
            material=get_text("field_material") or None,
            ext_urls=links,
            highres_url=_absolute_url(get_text("field_highres")) or None,
            thumbnail=_absolute_url(get_text("field_thumbnail")) or None,
            detail=get_text("field_detail") or None,
        )
        # 一条结果都没有任何有用信息时丢弃，避免污染结果表
        if not (result.artist or result.title or result.ext_urls
                or result.thumbnail or result.highres_url):
            return None
        return result

    # ── 接口 ────────────────────────────────────

    def search(self, image_path: str) -> List[SearchResult]:
        return self._parse(self._request(image_path=image_path))

    def search_by_url(self, image_url: str) -> List[SearchResult]:
        return self._parse(self._request(image_url=image_url))

    def _parse(self, raw: str) -> List[SearchResult]:     # pragma: no cover
        raise NotImplementedError
