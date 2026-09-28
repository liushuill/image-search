"""
网络请求工具模块
"""

import time
from typing import Optional, Set

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 已提示过的降级原因（避免每条请求都刷屏）
_warned: Set[str] = set()


def _warn_once(key: str, message: str) -> None:
    if key not in _warned:
        _warned.add(key)
        print(f"  ⚠️ {message}")


def create_session(
    proxies: dict = None,
    timeout: int = 30,
    max_retries: int = 3,
    user_agent: Optional[str] = None,
    use_cloudscraper: bool = False,
) -> requests.Session:
    """
    创建配置好的 requests Session

    ⚠️ **cloudscraper 与代理不兼容**：它自带一套自定义 SSL 上下文以模仿浏览器
    指纹，经代理隧道时会直接在 TLS 握手阶段失败
    （实测 `SSLV3_ALERT_HANDSHAKE_FAILURE`，且无论用 session.proxies
    还是每次请求显式传 proxies= 都一样）。

    因此当同时需要「代理」和「CF 绕过」时，**优先保代理** ——
    能连上比绕过重要；何况 cloudscraper 也打不过现代 Cloudflare WAF
    （实测对 ascii2d 的上传端点无论直连/代理/换请求头，一律 403）。

    Args:
        proxies: 代理配置
        timeout: 超时时间(秒)
        max_retries: 最大重试次数
        user_agent: 自定义 User-Agent
        use_cloudscraper: 是否使用 cloudscraper 绕过 Cloudflare 反爬

    Returns:
        配置好的 Session
    """
    if use_cloudscraper and proxies:
        _warn_once(
            "cloudscraper+proxy",
            "cloudscraper 与代理不兼容（TLS 握手会失败），本次改用普通请求",
        )
        use_cloudscraper = False

    if use_cloudscraper:
        try:
            import cloudscraper
            session = cloudscraper.create_scraper()
        except ImportError:
            _warn_once("no-cloudscraper", "cloudscraper 未安装，降级为普通 requests.Session")
            use_cloudscraper = False
            session = requests.Session()
    else:
        session = requests.Session()

    if not use_cloudscraper:
        # 普通 Session：挂载重试适配器 + 设置默认 UA
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        # User-Agent
        if user_agent:
            session.headers.update({"User-Agent": user_agent})
        else:
            session.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            })

    # 代理（仅非 cloudscraper 时设置，或 cloudscraper 有代理需要时）
    if proxies:
        session.proxies.update(proxies)

    return session


def download_file(
    url: str,
    save_path: str,
    proxies: dict = None,
    timeout: int = 60,
    max_retries: int = 3,
    headers: dict = None,
) -> bool:
    """
    下载文件

    Args:
        url: 文件 URL
        save_path: 保存路径
        proxies: 代理配置
        timeout: 超时时间(秒)
        max_retries: 最大重试次数
        headers: 自定义请求头

    Returns:
        是否下载成功
    """
    session = create_session(proxies=proxies, timeout=timeout, max_retries=max_retries)
    if headers:
        session.headers.update(headers)

    for attempt in range(max_retries):
        try:
            resp = session.get(url, stream=True, timeout=timeout)
            resp.raise_for_status()

            with open(save_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            return True

        except requests.RequestException:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                time.sleep(wait)
                continue
            raise
        finally:
            session.close()

    return False
