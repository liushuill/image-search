"""
JSON 适配器：站点返回 JSON 时，填一张映射表即可接入

映射示例（SauceNAO 的形状）::

    endpoint          /search.php
    method            POST
    image_field       file
    results_path      results
    similarity_scale  0-100
    field_similarity  header.similarity
    field_pixiv_id    data.pixiv_id
    field_artist      data.creator
    field_urls        data.ext_urls
    field_thumbnail   header.thumbnail

一个类可以挂多个实例（每个实例有自己的名字与配置），所以「A 站 + B 站」
只要加两条引擎配置，不需要写两个文件。
"""

from typing import List

from imgsearch.engines.adapters.declarative import (
    SCALES,
    DeclarativeEngine,
    mapping_schema,
    linking_schema,
    runtime_schema,
)
from imgsearch.engines.adapters.paths import dig_any, dig_links, dig_list
from imgsearch.engines.base import SearchResult
from imgsearch.engines.schema import COMMON_SCHEMA, STR, Field, Schema


class GenericJson(DeclarativeEngine):
    """按映射表解析 JSON 响应的通用引擎"""

    NAME = "genericJson"
    DISPLAY_NAME = "JSON 适配器"
    DEFAULT_API_URL = ""
    DEFAULT_ORDER = 90
    ENABLED_BY_DEFAULT = False
    AUTH_MODE = "none"
    RESPONSE_KIND = "json"

    USAGE_NOTE = (
        "通用适配器：填一张「字段映射」就能接一个新站点，不用写代码。\n"
        "适合单一请求 + JSON 响应。多步流程 / Cloudflare 反爬 / 需要计算的字段"
        "仍然要写一个普通引擎文件。"
    )

    CONFIG_SCHEMA = COMMON_SCHEMA.extend(
        Schema(
            Field("endpoint", "接口路径", STR, "",
                  help="相对 API 地址的路径（如 `/search.php`），也可填完整 URL"),
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
                  choices=("none", "query", "basic"),
                  help="none = 不需要；query = 把 api_key/login 加进查询参数；"
                       "basic = HTTP Basic Auth"),
            Field("results_path", "结果数组路径", STR, "",
                  help="结果数组在 JSON 里的位置，如 `results` / `result`；"
                       "留空表示响应本身就是数组"),
            Field("similarity_scale", "相似度量纲", STR, "0-100",
                  choices=SCALES,
                  help="站点给的分值是什么刻度。⚠️ 各站完全不同，"
                       "0-100 / 0-1 / percent-text / none（不返回相似度）"),
            Field("numres", "最多结果数", STR, "",
                  help="若站点支持条数参数，填它的参数名（如 numres / limit）；"
                       "留空则不传", advanced=True),
        ),
        mapping_schema("json"),
        runtime_schema("json"),
        linking_schema("json"),
    )

    def _parse(self, raw: str) -> List[SearchResult]:
        import json

        text = (raw or "").strip()
        if not text:
            return []
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"{self.DISPLAY_NAME} 返回的不是 JSON：{e}\n"
                f"  响应前 200 字：{text[:200]}"
            ) from e

        rows = self._rows(data)
        # 文本字段支持回退链（a|b|c），链接字段会把所有候选都收下
        get_text = lambda spec: dig_any(row, spec)       # noqa: E731
        get_links = lambda spec: dig_links(row, spec)    # noqa: E731

        results: List[SearchResult] = []
        seen: set = set()
        for index, row in enumerate(rows):
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

    def _rows(self, data) -> list:
        path = str(self.opt("results_path", "") or "").strip()
        if not path:
            if isinstance(data, list):
                return data
            # 少数站点把数组包在单键对象里：只有一个键且值是数组时用它
            if isinstance(data, dict) and len(data) == 1:
                only = next(iter(data.values()))
                if isinstance(only, list):
                    return only
            return []
        found = dig_list(data, path)
        return found
