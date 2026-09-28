"""
SauceNAO 搜索引擎实现

SauceNAO 是最强大的二次元以图搜图引擎，支持 Pixiv、Danbooru、yande.re 等大量图站。
需要注册获取免费 API Key: https://saucenao.com/

免费版限额:
  - 短期: 4次/30秒 (short_remaining)
  - 长期: 100次/24小时 (long_remaining，滑动窗口)
"""

import io
import json
import time
from pathlib import Path
from typing import List, Optional

import requests
from PIL import Image

from imgsearch.engines.base import SearchEngine, SearchResult
from imgsearch.config import get, get_proxies, PROJECT_DIR
from imgsearch.utils.network import create_session, download_file


class SauceNAO(SearchEngine):
    """SauceNAO 搜索引擎"""

    API_URL = "https://saucenao.com/search.php"
    # 滑动窗口限额追踪文件
    _QUOTA_FILE = PROJECT_DIR / "data" / "saucenao_quota.json"

    # 默认窗口时长（秒，可通过构造参数覆盖）
    SHORT_WINDOW = 30        # 30 秒
    LONG_WINDOW = 86400      # 24 小时

    # 默认限额（可通过构造参数覆盖）
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

    def __init__(self, api_key: str = None, timeout: int = 30, proxies: dict = None,
                 long_limit: int = None, short_limit: int = None,
                 long_window: int = None, short_window: int = None,
                 api_url: str = "", headers: dict = None, params: dict = None,
                 bypass_cfw: bool = False):
        super().__init__(timeout=timeout, proxies=proxies,
                         api_url=api_url, headers=headers, params=params,
                         api_key=api_key, bypass_cfw=bypass_cfw)
        self.api_key = api_key or get("saucenao_key", "")
        if not self.api_key:
            raise ValueError(
                "SauceNAO API Key 未配置！\n"
                "请先注册 https://saucenao.com/ 获取免费的 API Key，\n"
                "然后运行: python main.py config set saucenao_key YOUR_KEY"
            )
        # 使用引擎配置的限额（如果有），否则用类默认值
        self._long_limit = long_limit if long_limit is not None else self.LONG_LIMIT
        self._short_limit = short_limit if short_limit is not None else self.SHORT_LIMIT
        # 使用引擎配置的窗口时长（如果有），否则用类默认值
        self._long_window = long_window if long_window is not None else self.LONG_WINDOW
        self._short_window = short_window if short_window is not None else self.SHORT_WINDOW
        # 加载配额时间戳列表
        self._timestamps: List[float] = []
        self._load_quota()

    # ---- 配额追踪（滑动窗口） ----

    def _load_quota(self):
        """加载时间戳列表，清除已过期的记录"""
        if self._QUOTA_FILE.exists():
            try:
                with open(self._QUOTA_FILE, "r") as f:
                    data = json.load(f)
                self._timestamps = data.get("timestamps", [])
            except (json.JSONDecodeError, IOError):
                self._timestamps = []

        # 清理超过 long_window 的旧时间戳
        self._prune_old_timestamps()

    def _save_quota(self):
        """保存时间戳列表"""
        try:
            self._QUOTA_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(self._QUOTA_FILE, "w") as f:
                json.dump({"timestamps": self._timestamps}, f)
        except IOError as e:
            print(f"  ⚠️ 无法保存配额文件 {self._QUOTA_FILE}: {e}")

    def _prune_old_timestamps(self):
        """移除超出长期窗口的时间戳"""
        if self._long_window <= 0:
            return  # 无窗口限制
        cutoff = time.time() - self._long_window
        before = len(self._timestamps)
        self._timestamps = [t for t in self._timestamps if t > cutoff]
        if len(self._timestamps) != before:
            self._save_quota()

    def _check_daily_quota(self):
        """检查滑动窗口限额是否耗尽"""
        # long_limit <= 0 表示无限制
        if self._long_limit <= 0:
            return
        self._prune_old_timestamps()
        used = len(self._timestamps)
        if used >= self._long_limit:
            # 计算最早的时间戳何时过期
            oldest = min(self._timestamps)
            reset_in = int(self._long_window - (time.time() - oldest))
            reset_min = reset_in // 60
            window_hours = self._long_window // 3600
            raise RuntimeError(
                f"\n❌ SauceNAO 限额 ({self._long_limit}次/{window_hours}h) 已用尽！\n"
                f"   当前窗口内已用: {used} 次\n"
                f"   最早请求在约 {reset_min} 分钟后过期释放\n"
                f"   💡 提示: 可在引擎配置中调整限额和时间窗口"
            )

    def _increment_quota(self):
        """记录一次 API 调用的时间戳"""
        self._timestamps.append(time.time())
        self._save_quota()

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
            proxies=self.proxies or get_proxies(),
            timeout=self.timeout,
        )

        data = {
            "api_key": self.api_key,
            "output_type": 2,  # JSON
            "db": self.params.get("db", 999),  # 优先使用引擎配置的 db 参数
            "numres": 5,  # 最多返回结果数
        }

        try:
            api_url = self.api_url or self.API_URL
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
            index_id = header_raw.get("index_id", 0)

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
                    page = data_raw.get("pixiv_page", 0) or 0
                    ext = "png" if data_raw.get("pixiv_ugoira", False) else "jpg"
                    # Pixiv 原图 URL 格式：
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

    def download_highres(
        self,
        pixiv_id: str,
        save_dir: str,
        referer: str = None,
    ) -> Optional[str]:
        """
        从 Pixiv 下载高清原图

        注意：Pixiv 对 i.pximg.net 有 Referer 防盗链限制，
        必须设置 Referer: https://www.pixiv.net/

        Args:
            pixiv_id: Pixiv 作品 ID
            save_dir: 保存目录
            referer: Referer（默认使用 Pixiv 作品页）

        Returns:
            保存的文件路径，失败返回 None
        """
        if not referer:
            referer = f"https://www.pixiv.net/artworks/{pixiv_id}"

        headers = {"Referer": referer}

        # Pixiv 原图 URL 模式
        urls_to_try = [
            f"https://i.pximg.net/img-original/img/0000/00/00/00/00/00/{pixiv_id}_p0.jpg",
            f"https://i.pximg.net/img-original/img/0000/00/00/00/00/00/{pixiv_id}_p0.png",
            f"https://i.pximg.net/c/384x584/img-master/img/0000/00/00/00/00/00/{pixiv_id}_p0_master1200.jpg",
        ]

        save_dir_path = Path(save_dir)
        save_dir_path.mkdir(parents=True, exist_ok=True)

        # 由于无法直接构造路径，返回 None 让用户通过 Pixiv 作品页自行下载
        _print_pixiv_download_guide(pixiv_id)
        return None


def _print_quota(long_remaining: int, short_remaining: int):
    """打印 API 配额信息"""
    if long_remaining >= 0 or short_remaining >= 0:
        print(
            f"  [SauceNAO 配额] 今日剩余: {long_remaining} 次 | "
            f"30秒内剩余: {short_remaining} 次"
        )


def _print_pixiv_download_guide(pixiv_id: str):
    """打印 Pixiv 原图下载指引"""
    print(f"\n  📌 Pixiv 作品页: https://www.pixiv.net/artworks/{pixiv_id}")
    print(f"  💡 提示: 打开上方链接后，可在图片上右键 -> 另存为 获取原图")
    print(f"  🔧 后续版本将支持自动下载 Pixiv 原图 (需处理 Cookie 认证)")
