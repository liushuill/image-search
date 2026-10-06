"""
IQDB 搜索引擎实现

IQDB (https://iqdb.org) 是一个**聚合**以图搜图服务，索引了
Danbooru / Konachan / yande.re / Gelbooru / Sankaku Channel /
e-shuushuu / Zerochan / Anime-Pictures。免费、无需 API Key。

与内置 ``danbooru`` 引擎的区别（两者都叫 IQDB，但不是一回事）：
  - ``danbooru`` 引擎走 Danbooru 官方 JSON API（``iqdb_queries.json``），**需要账号**
  - 本引擎直连 iqdb.org 的公开表单，**无需凭据**，覆盖图库更多

服务编号（实测抓自 iqdb.org 首页表单，默认全选）::

  1=Danbooru   2=Konachan   3=yande.re   4=Gelbooru
  5=Sankaku Channel   6=e-shuushuu   11=Zerochan   13=Anime-Pictures

⚠️ IQDB 不索引 Pixiv，也不做动画截图溯源 —— 这两件事分别交给
   sauceNAO / ascii2d 与 traceMoe。
"""

import io
import re
from pathlib import Path
from urllib.parse import urlparse
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup
from PIL import Image

from imgsearch.engines.base import SearchEngine, SearchResult
from imgsearch.engines.schema import COMMON_SCHEMA, STR, Field, Schema

# iqdb.org 首页表单默认勾选的服务
DEFAULT_SERVICES = "1,2,3,4,5,6,11,13"

# 结果表标题：命中程度不同，措辞不同
_MATCH_HEADERS = {"possible match", "best match"}

_SIM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*similarity", re.I)
_DIM_RE = re.compile(r"(\d+)\s*[x×]\s*(\d+)")

# 各图库的帖子 ID 出现在这些位置，逐个尝试
_ID_PATTERNS = (
    re.compile(r"/posts?/(\d+)"),
    re.compile(r"/post/show/(\d+)"),
    re.compile(r"/pictures/view_post/(\d+)"),
    re.compile(r"/image/(\d+)"),
    re.compile(r"[?&]id=(\d+)"),
    re.compile(r"/(\d+)/?$"),
)

# 命中链接的主机 → 图库标识。
# 用**主机名**判定归属，而不是用页面上显示的服务名 ——
# IQDB 有时把 Danbooru 与 Gelbooru 放在同一格里，
# 显示文本会连成 "DanbooruGelbooru"，据此生成的键不可靠。
# 主机 → 展示用名称（服务名的可靠来源是链接主机，不是页面上的单元格文本 ——
# IQDB 会把 Danbooru 与 Gelbooru 放进同一格，文本会连成 "DanbooruGelbooru"）
_SERVICE_LABELS = {
    "danbooru": "Danbooru",
    "gelbooru": "Gelbooru",
    "yande_re": "yande.re",
    "konachan": "Konachan",
    "sankaku": "Sankaku Channel",
    "e_shuushuu": "e-shuushuu",
    "zerochan": "Zerochan",
    "anime_pictures": "Anime-Pictures",
}

_SERVICE_HOSTS = {
    "danbooru.donmai.us": "danbooru",
    "gelbooru.com": "gelbooru",
    "yande.re": "yande_re",
    "konachan.com": "konachan",
    "konachan.net": "konachan",
    "sankakucomplex.com": "sankaku",
    "e-shuushuu.net": "e_shuushuu",
    "zerochan.net": "zerochan",
    "anime-pictures.net": "anime_pictures",
}


class Iqdb(SearchEngine):
    """IQDB 聚合以图搜图引擎"""

    NAME = "iqdb"
    DISPLAY_NAME = "IQDB（多图库聚合）"
    DEFAULT_API_URL = "https://iqdb.org/"
    DEFAULT_ORDER = 20

    # 免费无凭据，开箱可用
    ENABLED_BY_DEFAULT = True

    CONFIG_SCHEMA = COMMON_SCHEMA.extend(
        Schema(
            Field("services", "搜索的图库", STR, DEFAULT_SERVICES,
                  help="IQDB 服务编号，逗号分隔。"
                       "1=Danbooru 2=Konachan 3=yande.re 4=Gelbooru "
                       "5=Sankaku 6=e-shuushuu 11=Zerochan 13=Anime-Pictures",
                  placeholder=DEFAULT_SERVICES),
            # 实测校准（10 张真实待查图）：IQDB 的相似度呈双峰 ——
            # 真实命中集中在 87–97%，噪声在 34–44%，50–86% 完全空白。
            # 因此阈值取 65%：落在空白带内，既能收下全部真实命中，
            # 又不会把 44% 的噪声当成答案（那种弱候选仍会以
            # 「低置信度」形式在最终兜底时呈现，不会丢信息）。
            Field("min_similarity", "最低相似度", "int", 65,
                  help="IQDB 的相似度呈双峰：真实命中多在 87–97%，噪声在 45% 以下。"
                       "默认 65% 落在两者的空白带内；低于此值会自动搜索下一个引擎",
                  minimum=0, maximum=100, unit="%"),
        ),
    )

    # ── 搜索 ────────────────────────────────────

    def search(self, image_path: str) -> List[SearchResult]:
        """上传图片文件搜索"""
        file_path = Path(image_path)
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {image_path}")

        try:
            with Image.open(image_path) as img:
                buf = io.BytesIO()
                img.convert("RGB").save(buf, format="JPEG", quality=95)
                buf.seek(0)
                files = {"file": ("image.jpg", buf, "image/jpeg")}
                return self._post(files=files)
        except (OSError, ValueError) as e:
            raise ValueError(f"无法读取图片: {image_path}\n{e}")

    def search_by_url(self, image_url: str) -> List[SearchResult]:
        """通过图片 URL 搜索（IQDB 表单的 url 字段）"""
        return self._post(data={"url": image_url})

    def _post(self, files: dict = None, data: dict = None) -> List[SearchResult]:
        session = self.make_session()

        # IQDB 用 service[] 这个重复字段名勾选图库，requests 需要传 list of tuples
        payload = [(k, v) for k, v in (data or {}).items()]
        for sid in self._service_ids():
            payload.append(("service[]", sid))

        try:
            resp = session.post(
                self.api_url or self.DEFAULT_API_URL,
                files=files,
                data=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            html = resp.text
        except requests.RequestException as e:
            raise ConnectionError(f"IQDB 请求失败: {e}")
        finally:
            session.close()

        return self._parse_results(html)

    def _service_ids(self) -> List[str]:
        raw = str(self.opt("services", DEFAULT_SERVICES) or "")
        ids = [p.strip() for p in re.split(r"[,\s]+", raw) if p.strip().isdigit()]
        return ids or [p for p in DEFAULT_SERVICES.split(",")]

    # ── 解析 ────────────────────────────────────

    def _parse_results(self, html: str) -> List[SearchResult]:
        soup = BeautifulSoup(html, "lxml")
        pages = soup.find(id="pages")
        if pages is None:
            return []

        results: List[SearchResult] = []

        for table in pages.find_all("table"):
            header = table.find("th")
            if header is None:
                continue
            if header.get_text(strip=True).lower() not in _MATCH_HEADERS:
                continue

            parsed = self._parse_match_table(table)
            if parsed is not None:
                results.append(parsed)

        results.sort(key=lambda r: r.similarity, reverse=True)
        return results

    def _parse_match_table(self, table) -> Optional[SearchResult]:
        """解析单个 'Possible match' 表格"""
        # 缩略图与外链
        image_cell = table.find("td", class_="image")
        source_url = ""
        thumbnail = None
        if image_cell is not None:
            link = image_cell.find("a")
            if link and link.get("href"):
                # IQDB 用的是协议相对地址（//konachan.com/...），
                # 必须补全成 https 才是可用链接
                source_url = _absolute(str(link["href"]))
            img = image_cell.find("img")
            if img and img.get("src"):
                thumbnail = _absolute(str(img["src"]))

        # 服务名：所在单元格里有 .service-icon
        service = ""
        for td in table.find_all("td"):
            if td.find("img", class_="service-icon") is not None:
                service = td.get_text(strip=True)
                break

        text = table.get_text(" ", strip=True)

        sim_match = _SIM_RE.search(text)
        similarity = float(sim_match.group(1)) if sim_match else 0.0

        dim_match = _DIM_RE.search(text)
        dimensions = f"{dim_match.group(1)}x{dim_match.group(2)}" if dim_match else ""

        if not source_url and not thumbnail:
            return None

        # ID 归属由链接主机判定（见 _extract_ids），与显示文本无关
        extra_ids = _extract_ids(source_url)
        danbooru_id = extra_ids.pop("danbooru", None)
        gelbooru_id = extra_ids.pop("gelbooru", None)

        # 用主机推导的名称替代单元格文本，避免 "DanbooruGelbooru" 这类拼接名
        label = _SERVICE_LABELS.get(_service_from_url(source_url)) or service
        detail_bits = [b for b in (label, dimensions) if b]

        return SearchResult(
            source="IQDB",
            similarity=similarity,
            artist=None,
            title=None,
            ext_urls=[source_url] if source_url else [],
            highres_url=source_url or thumbnail,
            thumbnail=thumbnail,
            material=None,
            danbooru_id=danbooru_id,
            gelbooru_id=gelbooru_id,
            extra_ids=extra_ids,
            detail=" | ".join(detail_bits) or None,
        )


def _absolute(src: str) -> str:
    """IQDB 用协议相对或站内路径，补全成绝对地址"""
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("/"):
        return "https://iqdb.org" + src
    return src


def _service_key(service: str) -> str:
    """服务名归一成适合做字典键的形式：Sankaku Channel → sankaku_channel"""
    key = re.sub(r"[^a-z0-9]+", "_", (service or "").strip().lower())
    return key.strip("_") or "unknown"


def _service_from_url(url: str) -> str:
    """按链接主机判断它属于哪个图库；认不出来返回空串"""
    if not url:
        return ""
    host = urlparse(url).netloc.lower()
    for suffix, key in _SERVICE_HOSTS.items():
        if host == suffix or host.endswith("." + suffix):
            return key
    return ""


def _extract_ids(url: str) -> Dict[str, str]:
    """
    从命中链接里抠出帖子 ID。

    归属由**主机名**决定（见 _SERVICE_HOSTS），ID 由 _ID_PATTERNS 尝试。
    抠不到就返回空字典 —— 这是尽力而为的增强信息，不该影响主流程。
    """
    service = _service_from_url(url)
    if not service:
        return {}
    for pattern in _ID_PATTERNS:
        m = pattern.search(url)
        if m:
            return {service: m.group(1)}
    return {}
