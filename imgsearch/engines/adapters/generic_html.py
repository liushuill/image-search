"""
HTML 适配器：站点返回 HTML 页面时，用 CSS 选择器接入

映射示例（IQDB 的形状）::

    endpoint            /
    method              POST
    image_field         file
    container_selector  #pages
    row_selector        table
    similarity_scale    percent-text
    field_similarity    td.match
    field_urls          td.image a@href
    field_thumbnail     td.image img@src

⚠️ 这类适配器最脆：站点改版会让选择器静默失效（返回 0 条而不报错）。
所以引擎页的「测试该引擎」必须能看到**原始响应片段**，否则没法排查。
真的调不动时，请写一个普通引擎文件。
"""

from typing import List

from imgsearch.engines.adapters import dom
from imgsearch.engines.adapters.declarative import (
    SCALES,
    DeclarativeEngine,
    mapping_schema,
    linking_schema,
    runtime_schema,
)
from imgsearch.engines.base import SearchResult
from imgsearch.engines.schema import COMMON_SCHEMA, STR, Field, Schema


class GenericHtml(DeclarativeEngine):
    """按 CSS 选择器解析 HTML 响应的通用引擎"""

    NAME = "genericHtml"
    DISPLAY_NAME = "HTML 适配器"
    DEFAULT_API_URL = ""
    DEFAULT_ORDER = 91
    ENABLED_BY_DEFAULT = False
    AUTH_MODE = "none"
    RESPONSE_KIND = "html"

    USAGE_NOTE = (
        "通用适配器：用 CSS 选择器从 HTML 页面里取结果，不用写代码。\n"
        "⚠️ 站点改版会让选择器静默失效（返回 0 条而不报错）——"
        "改完一定要用「测试该引擎」看原始响应。\n"
        "多步流程（上传后跳转到结果页）或 Cloudflare 反爬仍然要写引擎文件。"
    )

    CONFIG_SCHEMA = COMMON_SCHEMA.extend(
        Schema(
            Field("endpoint", "接口路径", STR, "",
                  help="相对 API 地址的路径；也可填完整 URL"),
            Field("method", "请求方法", STR, "POST", choices=("POST", "GET")),
            Field("image_field", "上传字段名", STR, "file",
                  help="本地文件上传时用的表单字段名"),
            Field("url_field", "URL 字段名", STR, "url",
                  help="「通过 URL 搜索」时用的参数名"),
            Field("url_in", "URL 放在", STR, "params",
                  choices=("params", "data"),
                  help="params = 查询参数（?url=…）；data = 表单字段",
                  advanced=True),
            Field("api_key", "API Key", "secret", "",
                  help="「鉴权方式」为 query/basic 时使用。"
                       "存在 .env 里（权限 0600），不进 config.json"),
            Field("login", "用户名", "secret", "", mask=False,
                  help="仅 basic 鉴权需要；query 鉴权下作为可选参数",
                  advanced=True),
            Field("auth_mode", "鉴权方式", STR, "none",
                  choices=("none", "query", "basic")),
            Field("container_selector", "结果容器", STR, "",
                  help="装所有结果的容器，如 `#pages`；留空则在整页里找"),
            Field("row_selector", "单条结果", STR, "",
                  help="每条结果的选择器，如 `table`（必填）"),
            Field("row_must_contain", "行必须包含", STR, "",
                  help="只保留文本里含这个词的行。用于排除「你的图片」这类"
                       "非结果块，例如填 `similarity`", advanced=True),
            Field("similarity_scale", "相似度量纲", STR, "percent-text",
                  choices=SCALES,
                  help="percent-text 会从 `89%` 这样的文本里取出数字"),
        ),
        mapping_schema("html"),
        runtime_schema("html"),
        linking_schema("html"),
    )

    def _parse(self, raw: str) -> List[SearchResult]:
        row_selector = str(self.opt("row_selector", "") or "").strip()
        if not row_selector:
            raise RuntimeError(
                f"{self.DISPLAY_NAME} 没有配置「单条结果」选择器，无法解析。\n"
                "  请在引擎页填写 row_selector（例如 `table` 或 `.result`）。"
            )

        soup = dom.parse_html(raw or "")
        container = dom.scoped(soup, str(self.opt("container_selector", "") or "").strip())
        raw_rows = dom.select_all(container, row_selector)
        # ⚠️ 一个元素都没找到 = 选择器错了或站点改版 → 必须报错，
        #    否则是「静默返回 0 条」，最难排查的一类问题
        if not raw_rows:
            # 诊断信息越具体越好：区分「选择器错」与「站点返回了别的页面」
            title = ""
            try:
                title = (soup.title.get_text(strip=True) if soup.title else "")
            except Exception:                             # noqa: BLE001
                pass
            container_spec = str(self.opt("container_selector", "") or "").strip()
            head = (raw or "")[:200].replace("\n", " ")
            raise RuntimeError(
                f"{self.DISPLAY_NAME} 在响应里找不到任何匹配 `{row_selector}` 的元素。\n"
                f"  页面标题：{title or '（无）'}\n"
                f"  容器 `{container_spec or '（未设置）'}` 是否找到："
                f"{'是' if (container is not None and container is not soup) or not container_spec else '否'}\n"
                f"  整页 table 数：{len(dom.select_all(soup, 'table'))}\n"
                "  · 若标题是正常结果页 → 多半是选择器写错或站点改版\n"
                "  · 若标题是错误/限流页 → 该站点暂时拒绝了请求（稍后重试或走代理）\n"
                f"  响应前 200 字：{head}"
            )

        # 按文本过滤：IQDB 页面里「Your image」「No relevant matches」
        # 也是 table，不过滤会多出噪声行
        needle = str(self.opt("row_must_contain", "") or "").strip().lower()
        rows = raw_rows
        if needle:
            rows = [n for n in raw_rows if needle in n.get_text(" ", strip=True).lower()]

        # ⚠️ 有元素但全被过滤掉 = 站点确实没有匹配结果，这是**正常情况**，
        #    返回空列表即可。误报成「选择器写错」会把正常结果当成故障。
        if not rows:
            return []

        results: List[SearchResult] = []
        seen: set = set()
        for index, node in enumerate(rows):
            get_text = lambda spec, _n=node: dom.extract(_n, spec)        # noqa: E731
            get_links = lambda spec, _n=node: dom.extract_links(_n, spec)  # noqa: E731
            record = self._make_result(get_text, get_links, index)
            if record is None:
                continue
            key = self._dedupe_key(get_text, get_links)
            if key:
                if key in seen:
                    continue
                seen.add(key)
            results.append(record)
        results.sort(key=lambda r: r.similarity, reverse=True)
        return results
