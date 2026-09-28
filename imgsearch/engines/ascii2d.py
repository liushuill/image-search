"""
Ascii2D 搜索引擎实现

Ascii2D 是日本以图搜图引擎，无需 API Key，可作为 SauceNAO 的备选。
特别擅长搜索日本画师作品，在 Pixiv 来源上有较好的覆盖。

Ascii2D 的搜索流程：
1. 先将图片上传到临时图床（如 imgur 或直接使用 Ascii2D 的 color 搜索）
2. 然后从结果页面解析匹配信息

注意：Ascii2D 的 /search/multi/ 端点有反爬机制，
推荐使用 /search/url/ 端点（需要图片已在线），
或使用 color 搜索（直接上传，但结果质量略低）。
"""

import re
import time
import io
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image

from imgsearch.engines.base import SearchEngine, SearchResult
from imgsearch.config import get, get_proxies
from imgsearch.utils.network import create_session


# 临时图床 API（用于 Ascii2D 无法直接上传的备选方案）
# 使用 catbox.moe 免费图床，无需注册
CATBOX_UPLOAD_URL = "https://catbox.moe/user/api.php"


class Ascii2D(SearchEngine):
    """Ascii2D 搜索引擎"""

    SEARCH_URL = "https://ascii2d.net/search/url/"
    COLOR_SEARCH_URL = "https://ascii2d.net/search/color/"

    def __init__(self, timeout: int = 30, proxies: dict = None,
                 api_url: str = "", headers: dict = None, params: dict = None,
                 api_key: str = "", bypass_cfw: bool = False):
        super().__init__(timeout=timeout, proxies=proxies,
                         api_url=api_url, headers=headers, params=params,
                         api_key=api_key)
        self.bypass_cfw = bypass_cfw

    def search(self, image_path: str) -> List[SearchResult]:
        """
        通过上传图片文件搜索

        策略：
        1. 尝试直接使用 Ascii2D 的 color 搜索上传
        2. 如果失败，先上传到临时图床，再用 URL 搜索

        Args:
            image_path: 图片文件路径

        Returns:
            搜索结果列表
        """
        file_path = Path(image_path)
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {image_path}")

        # 策略1: 尝试直接使用 color search 上传
        try:
            return self._search_by_upload(file_path)
        except Exception as e:
            print(f"    Ascii2D 直接上传失败，尝试通过图床: {e}")

        # 策略2: 上传到 catbox 再用 URL 搜索
        try:
            image_url = self._upload_to_catbox(file_path)
            return self.search_by_url(image_url)
        except Exception as e:
            raise ConnectionError(f"Ascii2D 搜索失败: {e}")

    def _search_by_upload(self, file_path: Path) -> List[SearchResult]:
        """
        通过 color search 直接上传图片

        Ascii2D 的 /search/color/ 端点接受文件上传，
        虽然结果是按颜色匹配的，但后续可以切换到 detail 视图。
        """
        session = create_session(
            proxies=self.proxies or get_proxies(),
            timeout=self.timeout,
            use_cloudscraper=self.bypass_cfw,
        )

        try:
            with open(file_path, "rb") as f:
                files = {"file": (file_path.name, f, "image/jpeg")}
                resp = session.post(
                    self.COLOR_SEARCH_URL,
                    files=files,
                    timeout=self.timeout,
                )
                resp.raise_for_status()

            result_url = resp.url
            if not result_url or "/search/color/" in result_url:
                raise RuntimeError("未获取到有效结果页面")

            # 等待处理
            time.sleep(1)
            return self._parse_result_page(result_url)

        finally:
            session.close()

    def _upload_to_catbox(self, file_path: Path) -> str:
        """
        将图片上传到 catbox.moe 临时图床

        Returns:
            图片的公开 URL
        """
        session = create_session(
            proxies=self.proxies or get_proxies(),
            timeout=self.timeout,
            use_cloudscraper=self.bypass_cfw,
        )

        try:
            # catbox.moe 要求 files 参数和 reqtype=fileupload
            with open(file_path, "rb") as f:
                files = {"fileToUpload": (file_path.name, f, "image/jpeg")}
                data = {"reqtype": "fileupload"}
                resp = session.post(
                    CATBOX_UPLOAD_URL,
                    data=data,
                    files=files,
                    timeout=60,
                )
                resp.raise_for_status()

            image_url = resp.text.strip()
            if not image_url.startswith("http"):
                raise RuntimeError(f"图床上传失败: {image_url}")

            return image_url

        finally:
            session.close()

    def search_by_url(self, image_url: str) -> List[SearchResult]:
        """
        通过图片 URL 搜索

        Args:
            image_url: 图片的 URL

        Returns:
            搜索结果列表
        """
        session = create_session(
            proxies=self.proxies or get_proxies(),
            timeout=self.timeout,
            use_cloudscraper=self.bypass_cfw,
        )

        try:
            encoded_url = quote(image_url, safe="")
            search_url = f"{self.SEARCH_URL}{encoded_url}"
            resp = session.get(
                search_url,
                timeout=self.timeout,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "ja,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
                },
            )
            resp.raise_for_status()

            # 切换到 detail 视图以获得更准确结果
            result_url = resp.url
            time.sleep(0.5)

            return self._parse_result_page(result_url)

        except requests.RequestException as e:
            raise ConnectionError(f"Ascii2D 请求失败: {e}")
        finally:
            session.close()

    def _parse_result_page(self, page_url: str) -> List[SearchResult]:
        """解析 Ascii2D 结果页面"""
        results = []
        session = create_session(
            proxies=self.proxies or get_proxies(),
            timeout=self.timeout,
            use_cloudscraper=self.bypass_cfw,
        )

        try:
            resp = session.get(page_url, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise ConnectionError(f"无法获取 Ascii2D 结果页面: {e}")
        finally:
            session.close()

        soup = BeautifulSoup(resp.text, "html.parser")

        # 多层选择器链，适应 Ascii2D 页面结构变化
        # Ascii2D 页面结构可能为：
        #   - .detail-box（旧版结果卡片）
        #   - .row.mt-2（新版行容器）
        #   - .col-xs-6 > a[href]（新版网格）
        #   - .card, .result-item（其他可能的结构）
        result_items = (
            soup.select(".detail-box")
            or soup.select(".row.mt-2")
            or soup.select(".col-xs-6 > a[href*='pixiv'], .col-xs-6 > a[href*='twitter']")
            or soup.select(".card, .result-item")
        )

        if not result_items:
            # 兜底：扫描所有指向已知图站的链接
            result_items = soup.find_all("a", href=re.compile(
                r"(pixiv\.net|twitter\.com|danbooru\.donmai|yande\.re|sankaku)"
            ))

        if not result_items:
            # 仍未找到任何结果 → 返回空列表而非报错
            print("    ⚠️ Ascii2D 页面未识别出任何结果项（页面结构可能已变更）")
            return results

        seen_urls = set()
        for item in result_items:
            result = self._parse_result_item(item, soup)
            if result and result.is_valid():
                # 去重：优先用 pixiv_id，其次用第一个外部 URL
                key = result.pixiv_id or (result.ext_urls[0] if result.ext_urls else None)
                if key and key not in seen_urls:
                    seen_urls.add(key)
                    result.source = "Ascii2D"
                    results.append(result)

        if not results:
            print(f"    ⚠️ Ascii2D 解析到 {len(result_items)} 个候选元素，但未能提取有效结果")

        return results

    def _parse_result_item(self, item, soup: BeautifulSoup) -> Optional[SearchResult]:
        """解析单个结果项"""
        # 如果 item 是 a 标签，交给 _parse_link 处理
        if item.name == "a":
            return self._parse_link(item)

        # 如果 item 是容器元素，查找其中的链接
        try:
            links = item.select("a[href]")
        except Exception:
            links = []

        pixiv_id = None
        artist = None
        title = None
        ext_urls = []

        for link in links:
            try:
                href = link.get("href", "")
                if "pixiv.net" in href:
                    ext_urls.append(href)
                    # 提取 Pixiv ID
                    m = re.search(r"/artworks/(\d+)", href)
                    if m:
                        pixiv_id = m.group(1)
                elif "twitter.com" in href or "x.com" in href:
                    ext_urls.append(href)
                elif "danbooru.donmai" in href:
                    ext_urls.append(href)
            except Exception:
                continue

        # 从容器文本中提取画师和标题
        try:
            text_content = item.get_text(" ", strip=True)
        except Exception:
            text_content = ""

        if not pixiv_id and text_content:
            m = re.search(r"(\d{6,})", text_content)
            if m:
                pixiv_id = m.group(1)

        # Ascii2D 的文本格式通常为: "画师名 / 作品标题"
        # 或 "画师名 / 作品标题 #hash"
        text_parts = text_content.split(" / ")
        if len(text_parts) >= 2:
            if not artist:
                artist = text_parts[0].strip()
            if not title:
                # 如果有 #hash 则去除
                title_part = text_parts[1].strip()
                hash_idx = title_part.find(" #")
                if hash_idx > 0:
                    title_part = title_part[:hash_idx]
                title = title_part
        elif len(text_parts) == 1 and text_parts[0] and not title:
            title = text_parts[0].strip()

        if pixiv_id or artist or ext_urls:
            highres_url = (
                f"https://www.pixiv.net/artworks/{pixiv_id}"
                if pixiv_id else None
            )
            return SearchResult(
                source="Ascii2D",
                similarity=0,
                pixiv_id=pixiv_id,
                artist=artist or (
                    text_content.split("/")[0].strip()
                    if "/" in text_content else None
                ),
                title=title,
                ext_urls=ext_urls,
                highres_url=highres_url,
            )

        return None

    def _parse_link(self, link) -> Optional[SearchResult]:
        """解析单个链接元素（支持 pixiv / twitter / danbooru 等链接）"""
        href = link.get("href", "")
        link_text = link.get_text(strip=True)

        pixiv_id = None
        artist = None
        title = None
        ext_urls = []

        # --- Pixiv 链接 ---
        if "pixiv.net" in href:
            ext_urls.append(href)
            m = re.search(r"/artworks/(\d+)", href)
            if m:
                pixiv_id = m.group(1)

            # 从父元素获取画师/标题文本
            parent = link.parent
            if parent:
                try:
                    parent_text = parent.get_text(" ", strip=True)
                except Exception:
                    parent_text = link_text
            else:
                parent_text = link_text

            parts = parent_text.split(" / ")
            if len(parts) >= 2:
                artist = parts[0].strip()
                title_part = parts[1].strip()
                hash_idx = title_part.find(" #")
                if hash_idx > 0:
                    title_part = title_part[:hash_idx]
                title = title_part
            else:
                # 如果文本中没有 " / "，检查是否有数字作为 pixiv_id
                if re.search(r"\d{6,}", parent_text):
                    title = link_text or None
                else:
                    title = parent_text

            return SearchResult(
                source="Ascii2D",
                similarity=0,
                pixiv_id=pixiv_id,
                artist=artist,
                title=title,
                ext_urls=ext_urls,
                highres_url=(
                    f"https://www.pixiv.net/artworks/{pixiv_id}"
                    if pixiv_id else None
                ),
            )

        # --- Twitter / X 链接 ---
        if "twitter.com" in href or "x.com" in href:
            ext_urls.append(href)
            # 提取推文 ID 作为参考标识
            m = re.search(r"/status/(\d+)", href)
            tweet_id = m.group(1) if m else None
            # 尝试从父元素提取文本
            parent = link.parent
            title = None
            if parent:
                try:
                    title = parent.get_text(" ", strip=True)[:200]
                except Exception:
                    title = link_text
            return SearchResult(
                source="Ascii2D",
                similarity=0,
                pixiv_id=None,
                artist=None,
                title=title or f"Twitter post {tweet_id}" if tweet_id else "Twitter post",
                ext_urls=ext_urls,
                highres_url=None,
            )

        # --- Danbooru / 其他图站链接 ---
        if any(domain in href for domain in ("danbooru", "yande", "sankaku")):
            ext_urls.append(href)
            parent = link.parent
            title = None
            if parent:
                try:
                    title = parent.get_text(" ", strip=True)[:200]
                except Exception:
                    title = link_text
            return SearchResult(
                source="Ascii2D",
                similarity=0,
                pixiv_id=None,
                artist=None,
                title=title or link_text,
                ext_urls=ext_urls,
                highres_url=None,
            )

        return None
