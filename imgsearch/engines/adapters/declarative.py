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
from urllib.parse import urlparse

from imgsearch.engines.base import SearchEngine, SearchResult
from imgsearch.engines.schema import Field, Schema, STR

# 相似度量纲：各站点的刻度完全不同，必须显式声明
SCALES = ("0-100", "0-1", "percent-text", "rank", "none")

# 默认的「按排名估算」分值表（Danbooru 这类站点不返回相似度，只有排名）
DEFAULT_RANK_SCORES = "100,95,90,85,80,75,70,65,60,55"

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
    ("field_danbooru_id", "Danbooru ID", "id", ""),
    ("field_gelbooru_id", "Gelbooru ID", "", ""),
    ("field_twitter_id", "Twitter ID", "", ""),
    ("field_artist_id", "画师 ID", "member_id", ""),
    ("field_pixiv_page", "Pixiv 页码", "pixiv_page", ""),
)


def apply_transforms(value: str, transforms: List[str]) -> str:
    """
    对取到的值做变换。写法：``path~strip_prefix:artist:``

    支持的变换（够把现有引擎表达出来，且语法一眼能懂）：
        strip_prefix:X   去掉前缀 X
        strip_suffix:X   去掉后缀 X
        regex:PATTERN    取第一个分组（没有分组则取整个匹配）
    """
    text = value or ""
    for raw in transforms:
        step = (raw or "").strip()
        if not step:
            continue
        name, _, arg = step.partition(":")
        name = name.strip().lower()
        if name == "strip_prefix" and text.startswith(arg):
            text = text[len(arg):]
        elif name == "strip_suffix" and arg and text.endswith(arg):
            text = text[: -len(arg)]
        elif name == "tags_title":
            # "blonde_hair blue_eyes artist:xxx copyright:yyy" →
            # 去掉带前缀的标签、下划线换成空格、取前 N 个
            try:
                count = int(arg) if arg else 5
            except ValueError:
                count = 5
            words = []
            for token in text.split():
                if ":" in token:            # artist:/copyright:/character: 等
                    continue
                words.append(token.replace("_", " "))
                if len(words) >= count:
                    break
            text = ", ".join(words)
        elif name == "regex":
            try:
                found = re.search(arg, text)
            except re.error:
                continue
            if not found:
                text = ""
            elif found.groups():
                text = found.group(1) or ""
            else:
                text = found.group(0)
        text = text.strip()
    return text


def format_clock(raw: str) -> str:
    """秒数 → mm:ss（与手写引擎一致：147.6 → 02:27）"""
    try:
        total = int(float(raw))
    except (TypeError, ValueError):
        return ""
    return f"{total // 60:02d}:{total % 60:02d}"


def render_template(template: str, lookup) -> str:
    """
    渲染 ``第 {episode} 集 @ {from:time}`` 这样的模板。

    ``{路径}`` 取该路径的文本；``{路径:time}`` 把秒数格式化成 mm:ss。
    用处：把几个字段拼成一句人读的标题（TraceMoe 的「第 5 集 @ 15:48」）。

    ⚠️ 刻意只支持「取值 + 时间格式」——真正的计算逻辑请写引擎文件。
    """
    # 按 " @ " 分段：某一段里有占位符取不到值，就**整段丢掉** ——
    # 否则「第 {episode} 集」会变成「第  集」。
    # 这与手写引擎「只拼存在的部分」的行为一致。
    parts = []
    for segment in template.split(" @ "):
        missing = {"hit": False}

        def replace(match, _missing=missing):
            expr = match.group(1)
            # ⚠️ 从右边切，且只有 **:time** 才当格式说明 ——
            # 否则 CSS 选择器里的冒号（`td:has(img)`）会被误拆
            name, _, fmt = expr.rpartition(":")
            if fmt.strip().lower() != "time":
                name, fmt = expr, ""
            value = lookup(name.strip())
            if fmt.strip().lower() == "time":
                value = format_clock(value)
            if not value:
                _missing["hit"] = True
                return ""
            return value

        rendered = re.sub(r"\{([^{}]+)\}", replace, segment).strip(" ·-|,，。　")
        if missing["hit"] or not rendered:
            continue
        parts.append(rendered)
    return " @ ".join(parts)


def split_transform(spec: str):
    """``"data.x~strip_prefix:a:"`` → ("data.x", ["strip_prefix:a:"])"""
    if not spec:
        return "", []
    parts = spec.split("~")
    return parts[0].strip(), [p for p in parts[1:]]


def _requests_error():
    """requests 的异常基类（延迟导入，避免模块导入期依赖）"""
    import requests
    return requests.RequestException


def _as_int(raw: str, default: int = 0) -> int:
    try:
        return int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return default


def _absolute_url(url: str, base: str = "") -> str:
    """
    补全相对地址。

    - ``//host/x``  → ``https://host/x``（协议相对，很多图库这么写）
    - ``/x``        → ``<base>/x``（站内路径，IQDB 的缩略图就是这样）
    """
    text = (url or "").strip()
    if text.startswith("//"):
        return "https:" + text
    if text.startswith("/") and base:
        return base.rstrip("/") + text
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


def linking_schema(kind: str) -> Schema:
    """结果链接的收窄规则（两个适配器共用）"""
    return Schema(
        Field("links_from_hosts", "只收这些主机的链接", STR, "",
              help="逗号分隔，如 `pixiv.net,twitter.com`。"
                   "结果页里常混着导航链接，用这个筛掉。留空 = 全收",
              advanced=True),
        Field("dedupe_by", "按此字段去重", STR, "",
              help="填一个映射字段名（如 `field_pixiv_id`）或 `field_urls`。"
                   "选择器并集可能把同一条结果匹配两次，用它去掉重复",
              advanced=True),
    )


def runtime_schema(kind: str) -> Schema:
    """两个适配器都需要的能力：限流、反爬、多步、按排名估算"""
    from imgsearch.engines.schema import BOOL, FLOAT, INT

    return Schema(
        Field("long_limit", "长期限额", INT, 0,
              help="窗口内最多请求次数；0 = 不限制", minimum=0, unit="次",
              advanced=True),
        Field("long_window", "长期窗口", INT, 86400,
              help="默认 86400 秒 = 24 小时", minimum=0, unit="秒", advanced=True),
        Field("short_limit", "短期限额", INT, 0,
              help="0 = 不限制。填了会自动得出「每张之间等多久」",
              minimum=0, unit="次", advanced=True),
        Field("short_window", "短期窗口", INT, 30,
              help="默认 30 秒", minimum=0, unit="秒", advanced=True),
        Field("cloudflare_bypass", "Cloudflare 绕过", BOOL, False,
              help="用 cloudscraper 发请求。仅当站点有 Cloudflare 反爬时需要",
              advanced=True),
        Field("follow_redirect", "跟随到结果页", BOOL, False,
              help="有些站点 POST 之后会重定向到结果页，必须再 GET 一次才有内容",
              advanced=True),
        Field("step2_delay", "第二步等待", FLOAT, 0.0,
              help="跟随到结果页之前等几秒（站点还在处理时用）",
              minimum=0, unit="秒", advanced=True),
        Field("rank_scores", "排名分值表", STR, DEFAULT_RANK_SCORES,
              help="仅当「相似度量纲」= rank 时有效：按第 1、2、3…名依次给分，"
                   "超出列表则用最后一个值", advanced=True),
    )


class DeclarativeEngine(SearchEngine):
    """两个适配器共用的骨架"""

    AUTH_MODE = "none"
    ENABLED_BY_DEFAULT = False
    # 适配器是「模板」，不是可用的引擎：
    # 它没有映射就什么都解析不出来，出现在引擎列表里只会让人困惑。
    # 引擎列表与默认配置据此跳过它们；向导/预设仍直接指向这些类。
    IS_ADAPTER = True
    # 子类声明自己的响应类型，仅用于日志与提示
    RESPONSE_KIND = "json"

    @classmethod
    def auth_mode_for(cls, settings: dict = None) -> str:
        """
        适配器的凭据需求由**实例配置**决定：

            auth_mode = none        → 无需凭据
            auth_mode = query/basic → 必须凭据

        否则同一类挂的多个实例会全都显示成「无需凭据」。
        """
        data = settings or {}
        mode = str(data.get("auth_mode", "none") or "none").strip().lower()
        return "required" if mode in ("query", "basic") else "none"

    def _settings_view(self) -> dict:
        view = dict(self.options)
        view.setdefault("auth_mode", str(self.opt("auth_mode", "none") or "none"))
        return view

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

    def _rank_similarity(self, index: int) -> float:
        """按排名估算相似度（站点不返回相似度时用）"""
        raw = str(self.opt("rank_scores", DEFAULT_RANK_SCORES) or "")
        scores = []
        for part in raw.split(","):
            try:
                scores.append(float(part.strip()))
            except ValueError:
                continue
        if not scores:
            return 0.0
        if index < len(scores):
            return scores[index]
        return scores[-1]

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

        # ⚠️ api_key 是 SearchEngine 的命名参数，不在 self.options 里 ——
        # 用 self.opt("api_key") 取会永远是空串
        api_key = str(getattr(self, "api_key", "") or "").strip()
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

    # ── 限流 ────────────────────────────────────

    def _quota_obj(self):
        """按引擎名建一个滑动窗口（跨进程有效，与内置引擎同一套实现）"""
        if getattr(self, "_quota", None) is None:
            from imgsearch.engines.quota import SlidingWindowQuota
            limit = int(self.opt_int("long_limit", 0) or 0)
            window = int(self.opt_int("long_window", 0) or 0)
            if limit > 0 and window > 0:
                # 用**配置里的名字**：同一个适配器类挂多个实例时，
                # 各实例要各有一份额度计数，界面也要显示各自的名字
                self._quota = SlidingWindowQuota(
                    self.engine_name or self.NAME, limit=limit, window=window)
            else:
                self._quota = None
        return self._quota

    def quota_state(self):
        quota = self._quota_obj()
        return [quota.state()] if quota is not None else []

    def request_interval(self) -> float:
        """短期速率换算成「每张之间等多久」"""
        limit = int(self.opt_int("short_limit", 0) or 0)
        window = int(self.opt_int("short_window", 0) or 0)
        if limit > 0 and window > 0:
            return window / limit
        return 0.0

    def _session(self):
        """按配置选普通会话还是 cloudscraper（绕 Cloudflare）"""
        if self.opt_bool("cloudflare_bypass", False):
            try:
                import cloudscraper
            except ImportError as e:
                raise RuntimeError(
                    "启用了「Cloudflare 绕过」但没装 cloudscraper。\n"
                    "  安装：pip install cloudscraper"
                ) from e
            scraper = cloudscraper.create_scraper()
            scraper.headers.update(self.headers or {})
            if self.proxies:
                scraper.proxies.update(self.proxies)
            return scraper
        return self.make_session()

    def _request(self, *, image_path: str = "", image_url: str = ""):
        """发一次请求，返回响应的原始文本"""
        quota = self._quota_obj()
        if quota is not None:
            quota.check()

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
            # 站点不同：有的要 ?url=（查询参数），有的要表单字段
            if str(self.opt("url_in", "params") or "params") == "data":
                data = {self._url_field(): image_url}
            else:
                payload[self._url_field()] = image_url

        session = self._session()
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

            # 多步：有些站点 POST 之后会重定向到结果页，必须再 GET 一次才有内容
            # （Ascii2D 就是这种：/search/file → /search/color/...）
            if self.opt_bool("follow_redirect", False):
                step2 = getattr(resp, "url", "") or ""
                if step2 and step2 != endpoint:
                    import time as _time
                    delay = float(self.opt_float("step2_delay", 0.0) or 0.0)
                    if delay > 0:
                        _time.sleep(delay)
                    resp = session.get(step2, timeout=self.timeout)
                    resp.raise_for_status()

            if quota is not None:
                quota.record()
            return resp.text
        except _requests_error() as e:
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

    def _field_text(self, get_text, key: str) -> str:
        """
        读一个文本字段。

        三种写法：
            path                    直接取
            path~strip_prefix:X     取值后做变换
            template:第 {a} 集 @ {b:time}   多个字段拼一句话
        """
        spec = str(self.opt(key, "") or "")
        if spec.startswith("template:"):
            return render_template(spec[len("template:"):], get_text)
        base, transforms = split_transform(spec)
        return apply_transforms(get_text(base), transforms)

    def _filter_hosts(self, links: List[str]) -> List[str]:
        """
        只保留指定主机上的链接。

        结果页里往往混着导航/广告链接；用手写版时是代码里写死
        「只认 pixiv/twitter/danbooru」，这里改成配置。
        """
        raw = str(self.opt("links_from_hosts", "") or "").strip()
        if not raw:
            return links
        allowed = [h.strip().lower() for h in raw.split(",") if h.strip()]
        if not allowed:
            return links
        kept = []
        for url in links:
            try:
                netloc = urlparse(url).netloc.lower()
            except Exception:                             # noqa: BLE001
                netloc = ""
            if any(host in netloc for host in allowed):
                kept.append(url)
        return kept

    def _dedupe_key(self, get_text, get_links) -> str:
        """
        去重用的键（配置 `dedupe_by` 指定取哪个映射字段）。

        选择器并集（`.a, .b`）可能把同一个结果匹配两次，
        手写版靠 pixiv_id 或首个链接去重，这里把它配置化。
        """
        spec = str(self.opt("dedupe_by", "") or "").strip()
        if not spec:
            return ""
        if spec == "field_urls":
            links = get_links(split_transform(
                str(self.opt("field_urls", "") or ""))[0])
            return links[0] if links else ""
        return self._field_text(get_text, spec)

    def _make_result(self, get_text, get_links, index: int = 0) -> Optional[SearchResult]:
        """
        从一条记录里组装 SearchResult。

        Args:
            get_text: ``(取值表达式) -> 文本``
            get_links: ``(取值表达式) -> list[str]``
            index: 第几条（``similarity_scale = rank`` 时用它查分值表）
        """
        if self._scale() == "rank":
            similarity = self._rank_similarity(index)
        else:
            raw_sim = self._field_text(get_text, "field_similarity")
            similarity = self._scale_similarity(raw_sim)

        # 协议相对地址（``//konachan.com/x``）补成 https —— 很多图库这么写，
        # 不补的话在结果表里点不开
        base = (self.api_url or self.DEFAULT_API_URL or "").strip()
        links = [_absolute_url(u, base) for u in get_links(
            split_transform(str(self.opt("field_urls", "") or ""))[0]) if u]
        links = self._filter_hosts(links)
        pixiv_id = self._field_text(get_text, "field_pixiv_id")
        # 有些站点只给 URL，不给 pixiv_id —— 交给 SearchResult 的归一化去补
        result = SearchResult(
            # 用**配置里的**显示名：批量日志里会显示成「已识别 … JSON 适配器」，
            # 用户根本不知道那指的是 SauceNAO
            source=self.display_name or self.DISPLAY_NAME,
            similarity=similarity,
            pixiv_id=pixiv_id or None,
            artist=self._field_text(get_text, "field_artist") or None,
            title=self._field_text(get_text, "field_title") or None,
            material=self._field_text(get_text, "field_material") or None,
            ext_urls=links,
            highres_url=_absolute_url(
                self._field_text(get_text, "field_highres"), base) or None,
            thumbnail=_absolute_url(
                self._field_text(get_text, "field_thumbnail"), base) or None,
            detail=self._field_text(get_text, "field_detail") or None,
            danbooru_id=self._field_text(get_text, "field_danbooru_id") or None,
            gelbooru_id=self._field_text(get_text, "field_gelbooru_id") or None,
            twitter_id=self._field_text(get_text, "field_twitter_id") or None,
            artist_id=self._field_text(get_text, "field_artist_id") or None,
            # 页码是整数；取不到就当 0（与手写引擎一致）
            pixiv_page=_as_int(self._field_text(get_text, "field_pixiv_page")),
        )
        # 一条结果都没有任何有用信息时丢弃，避免污染结果表
        if not (result.artist or result.title or result.ext_urls
                or result.thumbnail or result.highres_url
                or result.pixiv_id or result.danbooru_id
                or result.gelbooru_id or result.twitter_id):
            return None
        return result

    # ── 接口 ────────────────────────────────────

    def search(self, image_path: str) -> List[SearchResult]:
        return self._parse(self._request(image_path=image_path))

    def search_by_url(self, image_url: str) -> List[SearchResult]:
        return self._parse(self._request(image_url=image_url))

    def _parse(self, raw: str) -> List[SearchResult]:     # pragma: no cover
        raise NotImplementedError
