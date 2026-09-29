"""
SauceNAO 搜索引擎实现

SauceNAO 是最强大的二次元以图搜图引擎，支持 Pixiv、Danbooru、yande.re 等大量图站。
需要注册获取免费 API Key: https://saucenao.com/

免费版限额:
  - 短期: 4次/30秒 (short_remaining)
  - 长期: 100次/24小时 (long_remaining，滑动窗口)
"""

import io
from pathlib import Path
from typing import List, Optional

import requests
from PIL import Image

from imgsearch import secrets
from imgsearch.engines.base import SearchEngine, SearchResult
from imgsearch.engines.quota import SlidingWindowQuota
from imgsearch.engines.schema import (
    COMMON_SCHEMA, INT, Field, RATE_LIMIT_SCHEMA, Schema,
)
from imgsearch.config import PROJECT_DIR
from imgsearch.utils.network import create_session


class SauceNAO(SearchEngine):
    """SauceNAO 搜索引擎"""

    NAME = "sauceNAO"
    DISPLAY_NAME = "SauceNAO（Pixiv 覆盖最好）"
    DEFAULT_API_URL = "https://saucenao.com/search.php"
    DEFAULT_ORDER = 10

    # 滑动窗口限额追踪文件
    _QUOTA_FILE = PROJECT_DIR / "data" / "saucenao_quota.json"

    # 默认窗口时长（秒）
    SHORT_WINDOW = 30        # 30 秒
    LONG_WINDOW = 86400      # 24 小时

    # 默认限额
    SHORT_LIMIT = 4
    LONG_LIMIT = 100

    # 常用数据库索引
    DB_NAMES = {
        5: "Pixiv",
        9: "Danbooru",
        15: "yande.re / Gelbooru",
        21: "Anime (动画截图)",
        22: "H-Magazines",
        25: "H-Misc",
        34: "nijie.info",
        35: "Imdb/TV",
        37: "FANZA",
        38: "Pixiv - Historical",
    }

    CONFIG_SCHEMA = COMMON_SCHEMA.extend(
        RATE_LIMIT_SCHEMA,
        Schema(
            # db 原本藏在「自定义查询参数」里，用户根本不知道要填什么。
            # 提升为独立字段后，界面上有标签和说明，也能做类型校验。
            Field("db", "数据库索引", INT, 999,
                  help="999 = 全部数据库；5 = Pixiv，9 = Danbooru，15 = yande.re/Gelbooru",
                  minimum=0),
            # 凭据只存 .env；界面上的值由「凭据」页维护
            Field("api_key", "API Key", "secret", "",
                  help="留空时从 .env 的 SAUCENAO_KEY 读取",
                  env_var="SAUCENAO_KEY"),
            Field("numres", "返回结果数", INT, 5,
                  help="让 SauceNAO 最多返回多少条结果", minimum=1, maximum=50,
                  advanced=True),
        ),
    )

    def __init__(self, **options):
        super().__init__(**options)

        # 留空则回退到 .env 中的 SAUCENAO_KEY
        self.api_key = self.api_key or secrets.get("SAUCENAO_KEY", "") or ""
        if not self.api_key:
            raise ValueError(
                "SauceNAO API Key 未配置！\n"
                "  1. 到 https://saucenao.com/user.php?page=account 获取免费 Key\n"
                "  2. 写入 .env：SAUCENAO_KEY=你的KEY\n"
                "     （或执行  imgsearch config set saucenao_key 你的KEY）"
            )

        # 限额：0 表示「无限制」，因此不能用 `or 默认值` 兜底
        self._long_limit = self.opt_int("long_limit", self.LONG_LIMIT)
        self._short_limit = self.opt_int("short_limit", self.SHORT_LIMIT)
        self._long_window = self.opt_int("long_window", self.LONG_WINDOW)
        self._short_window = self.opt_int("short_window", self.SHORT_WINDOW)

        # 加载配额时间戳列表
        # 限流：滑动窗口计数（实现见 engines/quota.py，与 TraceMoe 共用）
        # 沿用既有的 saucenao_quota.json 文件名，不丢历史计数。
        self._quota = SlidingWindowQuota(
            name="saucenao",
            limit=self._long_limit,
            window=self._long_window,
            path=self._QUOTA_FILE,
            label="SauceNAO",
        )

    # ---- 配额追踪（委托给共享的滑动窗口计数器）----

    def _check_daily_quota(self):
        """检查滑动窗口限额是否耗尽（Raise QuotaExceeded）"""
        self._quota.check()

    def _increment_quota(self):
        """记录一次成功的 API 调用"""
        self._quota.record()

    def search(self, image_path: str) -> List[SearchResult]:
        """
        通过文件上传搜索

        Args:
            image_path: 图片文件路径

        Returns:
            相似度降序排列的搜索结果
        """
        file_path = Path(image_path)
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {image_path}")

        # 读取图片并检查格式
        try:
            with Image.open(image_path) as img:
                # 转 JPEG 压缩上传
                buf = io.BytesIO()
                img.convert("RGB").save(buf, format="JPEG", quality=95)
                buf.seek(0)
                files = {"file": ("image.jpg", buf, "image/jpeg")}
        except Exception as e:
            raise ValueError(f"无法读取图片: {image_path}\n{e}")

        return self._call_api(files=files)

    def search_by_url(self, image_url: str) -> List[SearchResult]:
        """通过图片 URL 搜索"""
        return self._call_api(params={"url": image_url})

    def _call_api(
        self,
        files: dict = None,
        params: dict = None,
    ) -> List[SearchResult]:
        """调用 SauceNAO API"""
        # 检查每日限额
        self._check_daily_quota()

        session = create_session(
            proxies=self.proxies,
            timeout=self.timeout,
        )

        data = {
            "api_key": self.api_key,
            "output_type": 2,  # JSON
            "db": self.opt_int("db", 999),          # 999 = 全部数据库
            "numres": self.opt_int("numres", 5),    # 最多返回结果数
        }

        try:
            api_url = self.api_url or self.DEFAULT_API_URL
            resp = session.post(
                api_url,
                data=data,
                files=files,
                params=params,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            result = resp.json()
        except requests.RequestException as e:
            raise ConnectionError(f"SauceNAO API 请求失败: {e}")
        finally:
            session.close()

        # 检查 API 错误
        if result.get("header", {}).get("status") != 0:
            msg = result.get("header", {}).get("message", "未知错误")
            raise RuntimeError(f"SauceNAO API 返回错误: {msg}")

        # 记录本次成功调用
        self._increment_quota()

        return self._parse_results(result)

    def _parse_results(self, data: dict) -> List[SearchResult]:
        """解析 API 返回的 JSON 结果"""
        results = []
        header = data.get("header", {})
        # 账户信息
        account = header.get("account", {})
        long_remaining = account.get("long_remaining", -1)
        short_remaining = account.get("short_remaining", -1)

        raw_results = data.get("results", [])

        for raw in raw_results:
            header_raw = raw.get("header", {})
            data_raw = raw.get("data", {})

            similarity = float(header_raw.get("similarity", 0))

            # 提取外部 URL
            ext_urls = data_raw.get("ext_urls", [])

            # 提取 Pixiv 信息
            pixiv_id = str(data_raw.get("pixiv_id", "")) or None

            # 提取 Pixiv 页码（多图作品区分 p0/p1/p2...）
            pixiv_page = int(data_raw.get("pixiv_page", 0))

            result = SearchResult(
                source="SauceNAO",
                similarity=similarity,
                pixiv_id=pixiv_id,
                pixiv_page=pixiv_page,
                artist=data_raw.get("member_name") or data_raw.get("creator"),
                artist_id=str(data_raw.get("member_id", "")) or None,
                title=data_raw.get("title") or data_raw.get("material"),
                ext_urls=ext_urls,
                highres_url=data_raw.get("source") or (
                    f"https://i.pximg.net/img-original/img/"
                    f"{self._pixiv_id_to_path(pixiv_id)}"
                    if pixiv_id else None
                ),
                thumbnail=header_raw.get("thumbnail"),
                material=data_raw.get("material"),
                danbooru_id=str(data_raw.get("danbooru_id", "")) or None,
                gelbooru_id=str(data_raw.get("gelbooru_id", "")) or None,
                twitter_id=str(data_raw.get("twitter_user_id", "")) or None,
            )

            # 补充 Pixiv 高清原图 URL
            if pixiv_id and not result.highres_url:
                result.highres_url = self._build_pixiv_url(data_raw, pixiv_id)

            results.append(result)

        # 按相似度降序排列
        results.sort(key=lambda r: r.similarity, reverse=True)

        # 打印配额信息
        if results:
            _print_quota(long_remaining, short_remaining)

        return results

    def _build_pixiv_url(self, data_raw: dict, pixiv_id: str) -> Optional[str]:
        """构建 Pixiv 原图直链 URL"""
        # 先尝试从返回数据中提取
        for url in data_raw.get("ext_urls", []):
            if "i.pximg.net" in url:
                return url

        # 从 ext_urls 中的作品页 URL 推测原图 URL
        for url in data_raw.get("ext_urls", []):
            if "pixiv.net" in url and "/artworks/" in url:
                # 提取作品 ID 和页码
                try:
                    pid = url.split("/artworks/")[-1].split("?")[0]
                    # Pixiv 原图 URL 含日期路径，无法仅由 ID 推导，
                    # 因此这里只能返回作品页地址。
                    # https://i.pximg.net/img-original/img/YYYY/MM/DD/HH/MM/SS/pid_p0.jpg
                    # 但我们无法直接构造，需要从 Pixiv 页面获取
                    # 这里直接返回 Pixiv 作品页面 URL
                    return f"https://www.pixiv.net/artworks/{pid}"
                except Exception:
                    pass

        return None

    @staticmethod
    def _pixiv_id_to_path(pixiv_id: str) -> str:
        """Pixiv ID 转存储路径（简化处理）"""
        # 实际 Pixiv 存储路径包含日期信息，无法仅从 ID 推导
        # 这里仅作占位
        return f"{pixiv_id}_p0.jpg"


def _print_quota(long_remaining: int, short_remaining: int):
    """打印 API 配额信息"""
    if long_remaining >= 0 or short_remaining >= 0:
        print(
            f"  [SauceNAO 配额] 今日剩余: {long_remaining} 次 | "
            f"30秒内剩余: {short_remaining} 次"
        )
