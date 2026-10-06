"""
TraceMoe 搜索引擎实现

专长：**动画截图溯源** —— 上传一张截图，回答「出自哪部动画、第几集、第几秒」。
数据源是 AniList，免费、无需 API Key。

API: https://api.trace.moe/search
  - POST multipart（字段名 ``image``），或 ``?url=<图片地址>``
  - ``anilistInfo`` 参数可附带 AniList 元数据（标题 / 集数 / 站点链接）
  - ``cutBorders`` 参数可忽略截图黑边（对带黑边的截图很有用）

限流：实测响应头 ``ratelimit-limit: 100``，窗口 60 秒。

⚠️ 定位互补，不是替代：本引擎只对**动画画面**有效，
   对 Pixiv 插画 / 同人图基本无能为力 —— 那类图请用 sauceNAO / ascii2d / iqdb。
"""

import io
from pathlib import Path
from typing import Dict, List, Optional

import requests
from PIL import Image

from imgsearch.engines.base import SearchEngine, SearchResult
from imgsearch.engines.quota import QuotaExceeded, SlidingWindowQuota
from imgsearch.engines.schema import BOOL, COMMON_SCHEMA, INT, Field, Schema
from imgsearch.utils.network import create_session

# TraceMoe 实测限额：100 次 / 60 秒
DEFAULT_LIMIT = 100
DEFAULT_WINDOW = 60


class TraceMoe(SearchEngine):
    """TraceMoe 动画截图溯源引擎"""

    NAME = "traceMoe"
    DISPLAY_NAME = "TraceMoe（动画截图）"
    DEFAULT_API_URL = "https://api.trace.moe/search"
    DEFAULT_ORDER = 40

    # ⚠️ 默认禁用：它只为动画截图设计，对 Pixiv 插画会给出高分误报
    # （实测一张插画被匹配到某动画 80.3%）。需要时用 `-e traceMoe` 手动调用。
    ENABLED_BY_DEFAULT = False

    CONFIG_SCHEMA = COMMON_SCHEMA.extend(
        Schema(
            Field("long_limit", "限额", INT, DEFAULT_LIMIT,
                  help="窗口内最多请求次数；0 = 无限制", minimum=0, unit="次"),
            Field("long_window", "限流窗口", INT, DEFAULT_WINDOW,
                  help="实测 TraceMoe 为 100 次 / 60 秒", minimum=0, unit="秒"),
            Field("short_limit", "短期限额", INT, 0,
                  help="0 = 无限制", minimum=0, unit="次", advanced=True),
            Field("short_window", "短期窗口", INT, 0,
                  help="0 = 不限制", minimum=0, unit="秒", advanced=True),
            Field("cut_borders", "忽略黑边", BOOL, True,
                  help="裁掉截图四周黑边后再比对，带黑边的截图命中率明显更高"),
            Field("anilist_info", "附带 AniList 信息", BOOL, True,
                  help="返回作品标题、集数、AniList/MAL 链接等元数据"),
            Field("min_similarity", "最低相似度", INT, 85,
                  help="只为动画截图设计，对插画易误报，因此默认阈值较高（85%）；"
                       "低于此值会自动搜索下一个引擎",
                  minimum=0, maximum=100, unit="%"),
        ),
    )

    def __init__(self, **options):
        super().__init__(**options)
        self._quota = SlidingWindowQuota(
            name="tracemoe",
            limit=self.opt_int("long_limit", DEFAULT_LIMIT),
            window=self.opt_int("long_window", DEFAULT_WINDOW),
            label="TraceMoe",
        )

    # ── 搜索 ────────────────────────────────────

    def quota_state(self):
        return [self._quota.state()]

    def search(self, image_path: str) -> List[SearchResult]:
        """通过上传图片文件搜索"""
        file_path = Path(image_path)
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {image_path}")

        try:
            with Image.open(image_path) as img:
                buf = io.BytesIO()
                # PNG 的透明通道会让 JPEG 保存失败，统一转 RGB
                img.convert("RGB").save(buf, format="JPEG", quality=95)
                buf.seek(0)
                files = {"image": ("image.jpg", buf, "image/jpeg")}
                return self._call_api(files=files)
        except (OSError, ValueError) as e:
            raise ValueError(f"无法读取图片: {image_path}\n{e}")

    def search_by_url(self, image_url: str) -> List[SearchResult]:
        """通过图片 URL 搜索"""
        return self._call_api(params={"url": image_url})

    def _call_api(self, files: dict = None, params: dict = None) -> List[SearchResult]:
        self._quota.check()

        query: Dict[str, object] = dict(params or {})
        if self.opt_bool("anilist_info", True):
            query["anilistInfo"] = ""
        if self.opt_bool("cut_borders", True):
            query["cutBorders"] = ""

        session = create_session(
            proxies=self.proxies,
            timeout=self.timeout,
        )
        try:
            resp = session.post(
                self.api_url or self.DEFAULT_API_URL,
                files=files,
                params=query,
                timeout=self.timeout,
            )
            if resp.status_code == 429:
                raise QuotaExceeded(
                    "\n❌ TraceMoe 返回 429（请求过于频繁）\n"
                    "   请稍后重试，或在引擎配置中调大「限流窗口」。"
                )
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException as e:
            raise ConnectionError(f"TraceMoe API 请求失败: {e}")
        finally:
            session.close()

        # 只有请求真正成功才计数，避免失败也吃掉配额
        self._quota.record()
        return self._parse_results(payload)

    # ── 解析 ────────────────────────────────────

    def _parse_results(self, payload: dict) -> List[SearchResult]:
        error = payload.get("error")
        if error:
            raise RuntimeError(f"TraceMoe 返回错误: {error}")

        results: List[SearchResult] = []

        for item in payload.get("result") or []:
            # TraceMoe 的 similarity 是 0–1 的小数，统一换算成百分比
            similarity = float(item.get("similarity") or 0.0) * 100.0

            anilist = item.get("anilist") or {}
            titles = anilist.get("title") or {}
            work = (titles.get("chinese") or titles.get("native")
                    or titles.get("romaji") or titles.get("english"))

            episode = item.get("episode")
            at_sec = item.get("from")

            title_parts = []
            if episode:
                title_parts.append(f"第 {episode} 集")
            if at_sec is not None:
                title_parts.append(_fmt_time(at_sec))

            ext_urls: List[str] = []
            if anilist.get("siteUrl"):
                ext_urls.append(anilist["siteUrl"])
            if item.get("video"):
                ext_urls.append(item["video"])

            extra_ids: Dict[str, str] = {}
            if anilist.get("id"):
                extra_ids["anilist"] = str(anilist["id"])
            if anilist.get("idMal"):
                extra_ids["mal"] = str(anilist["idMal"])

            detail_bits = []
            if item.get("filename"):
                detail_bits.append(str(item["filename"]))
            if anilist.get("format"):
                detail_bits.append(str(anilist["format"]))

            results.append(SearchResult(
                source="TraceMoe",
                similarity=similarity,
                title=" @ ".join(title_parts) or None,
                material=work,
                artist=_main_studio(anilist),
                ext_urls=ext_urls,
                highres_url=item.get("image"),
                thumbnail=item.get("image"),
                extra_ids=extra_ids,
                detail=" | ".join(detail_bits) or None,
            ))

        results.sort(key=lambda r: r.similarity, reverse=True)
        return results


def _main_studio(anilist: dict) -> Optional[str]:
    """取 AniList 里的主制作公司"""
    edges = ((anilist.get("studios") or {}).get("edges")) or []
    for edge in edges:
        if edge.get("isMain"):
            node = edge.get("node") or {}
            if node.get("name"):
                return str(node["name"])
    for edge in edges:
        node = edge.get("node") or {}
        if node.get("name"):
            return str(node["name"])
    return None


def _fmt_time(seconds) -> str:
    """147.6 秒 → 02:27"""
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return ""
    return f"{total // 60:02d}:{total % 60:02d}"
