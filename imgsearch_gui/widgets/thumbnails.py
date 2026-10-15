"""
后台缩略图加载器

两个用途共用：搜索结果里的匹配缩略图、图库浏览的缩略图墙。

## 为什么要有这个
界面不能同步去读图/下载图 —— 几百张会直接卡死。所以放后台线程，
按需生成，并落盘缓存（第二次打开几乎瞬时）。

## ⚠️ QPixmap 只能在 GUI 线程创建
工作线程因此只产出**字节**，由接收方在 GUI 线程里 `loadFromData`。
这是 Qt 的硬性约束，绕不过去。

## 缓存策略
- 本地文件：复用 `imgsearch.library.thumbs`（按内容 dHash 命名，
  与其他功能共用同一份缓存，不会各存一份）
- 远程 URL：存到 `data/cache/urlthumbs/`，按 URL 哈希命名
"""

import hashlib
import queue
import threading
import weakref
from pathlib import Path
from typing import Optional

from PySide6 import QtCore

from imgsearch.config import CACHE_DIR

URL_THUMB_DIR = CACHE_DIR / "urlthumbs"

# 所有活着的加载器。用于在退出/测试收尾时统一停线程 ——
# QThread 还在跑就被销毁，Qt 会直接 abort 整个进程（实测 exit 134）。
_LOADERS: "weakref.WeakSet" = weakref.WeakSet()


def stop_all_loaders() -> None:
    """
    停掉所有后台缩略图线程。

    应用退出时由 aboutToQuit 触发；**测试收尾也必须调** ——
    pytest 不会让 QApplication 正常退出，光靠 aboutToQuit 收不到。
    """
    for loader in list(_LOADERS):
        try:
            loader.stop()
        except Exception:                                 # noqa: BLE001
            pass
# 远程缩略图的磁盘缓存上限：单张 1.5MB，够放原图也不会把缓存撑爆
MAX_DOWNLOAD_BYTES = 1536 * 1024


class _ThumbWorker(QtCore.QThread):
    """真正干活的线程：一次处理一个请求，产出字节"""

    ready = QtCore.Signal(str, bytes)
    failed = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: "queue.Queue" = queue.Queue()
        self._stopping = False

    def submit(self, key: str, spec: dict) -> None:
        self._queue.put((key, spec))

    def stop(self) -> None:
        self._stopping = True
        self._queue.put(None)

    def run(self) -> None:  # noqa: D102
        while not self._stopping:
            item = self._queue.get()
            if item is None:
                break
            key, spec = item
            try:
                data = self._produce(spec)
            except Exception:                             # noqa: BLE001
                # 缩略图失败不该影响任何主流程，静默跳过
                data = None
            if self._stopping:
                continue
            if data:
                self.ready.emit(key, data)
            else:
                # 必须告诉界面「取不到」—— 否则占位会永远停在「…」，
                # 用户分不清是还在加载还是已经失败
                self.failed.emit(key)

    @staticmethod
    def _produce(spec: dict) -> Optional[bytes]:
        if spec.get("kind") == "url":
            cached = _url_cache_path(spec["url"])
            if cached.is_file():
                return cached.read_bytes()
            data = _download(spec["url"])
            if data is None:
                return None
            try:
                _url_cache_path(spec["url"]).write_bytes(data)
            except OSError:
                pass
            return data

        # 本地文件：优先用按内容命名的缩略图缓存
        path = spec.get("path") or ""
        dhash = spec.get("dhash") or ""
        if dhash:
            from imgsearch.library import thumbs
            try:
                if not thumbs.exists(dhash) and path and Path(path).is_file():
                    thumbs.ensure(dhash, path)
                if thumbs.exists(dhash):
                    return thumbs.path_for(dhash).read_bytes()
            except Exception:                             # noqa: BLE001
                pass
        if path and Path(path).is_file():
            return _shrink(path, spec.get("size", 160))
        return None


def _shrink(path: str, size: int) -> Optional[bytes]:
    """把本地图缩到 <=size，返回 JPEG 字节（缓存缺失时的兜底路径）"""
    try:
        from PIL import Image
        with Image.open(path) as img:
            img = img.convert("RGB")
            img.thumbnail((size, size))
            import io as _io
            buf = _io.BytesIO()
            img.save(buf, format="JPEG", quality=82)
            return buf.getvalue()
    except Exception:                                     # noqa: BLE001
        return None


# 先直连再走代理：不同图源的可达性正好相反，实测 ——
#   iqdb.org 的缩略图：直连 200，走代理失败
#   i.pximg.net 的缩略图：直连超时，必须走代理
# 所以两条路都要试。直连用较短超时，免得遇到需要代理的站点白等太久。
DIRECT_TIMEOUT = 8
PROXY_TIMEOUT = 15


def _download(url: str) -> Optional[bytes]:
    if not url:
        return None
    from imgsearch.config import get

    proxy = (get("proxy", "") or "").strip()
    attempts = [(None, DIRECT_TIMEOUT)]
    if proxy:
        attempts.append(({"http": proxy, "https": proxy}, PROXY_TIMEOUT))
    for proxies, timeout in attempts:
        data = _fetch(url, proxies, timeout)
        if data:
            return data
    return None


def _fetch(url: str, proxies, timeout: int) -> Optional[bytes]:
    try:
        from imgsearch.utils.network import create_session

        session = create_session(proxies=proxies, timeout=timeout)
        try:
            resp = session.get(url, timeout=timeout, stream=True)
            resp.raise_for_status()
            chunks, size = [], 0
            for chunk in resp.iter_content(8192):
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_DOWNLOAD_BYTES:
                    break
            return b"".join(chunks) or None
        finally:
            session.close()
    except Exception:                                     # noqa: BLE001
        return None


def stable_url_key(url: str) -> str:
    """
    URL 的稳定标识（去掉查询串）。

    用于两件事：磁盘缓存的命名、以及界面上「同一个图源只请求一次」的去重。
    """
    return url.split("?", 1)[0].split("#", 1)[0]


def _url_cache_path(url: str) -> Path:
    """
    缓存位置：**按去掉查询串的 URL** 命名。

    ⚠️ 这是必需的，不是优化。实测：
      · 刚搜到的缩略图 URL 直连 200
      · 过了一会儿再用同一个 URL 取 → 403
    说明 `?auth=…&exp=…` 这类令牌会失效；而路径部分
    （…/<hash>_0.jpg）是稳定的。按稳定部分做键，
    重新搜索同一张图就能命中缓存，不必再下一次。
    """
    URL_THUMB_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(stable_url_key(url).encode("utf-8")).hexdigest()
    return URL_THUMB_DIR / f"{digest}.img"


class ThumbnailLoader(QtCore.QObject):
    """
    界面侧的门面：请求、去重、把字节变成 QPixmap。

    用法::

        loader = ThumbnailLoader()
        loader.ready.connect(self._on_thumb)         # (key, QPixmap)
        loader.request("row-3", url="https://…")     # 远程
        loader.request(dhash, path="/图.jpg", dhash=dhash)
    """

    ready = QtCore.Signal(str, object)          # key -> QPixmap
    failed = QtCore.Signal(str)                 # key -> 取不到（令牌过期/不可达）

    def __init__(self, parent=None):
        super().__init__(parent)
        # ⚠️ 线程**懒启动**：只有真的请求图片时才建。
        # 否则「构造一个结果表」就会起一个线程，而任何忘了收尾的地方
        # （比如测试）都会在对象被回收时触发 Qt 的
        # "QThread: Destroyed while thread is still running" → 进程 abort。
        self._worker: Optional[_ThumbWorker] = None
        self._asked: set = set()
        self._lock = threading.Lock()
        self._stopped = False

    def _ensure_worker(self) -> None:
        """第一次真正需要时才起线程，并挂上退出收尾"""
        if self._worker is not None:
            return
        self._worker = _ThumbWorker(self)
        self._worker.ready.connect(self._on_bytes)
        self._worker.failed.connect(self.failed)
        self._worker.start()
        _LOADERS.add(self)
        app = QtCore.QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.stop)

    def request(self, key: str, *, path: str = "", url: str = "",
                dhash: str = "", size: int = 160) -> None:
        """请求一张缩略图；同一个 key 只请求一次"""
        with self._lock:
            if key in self._asked:
                return
            self._asked.add(key)
        self._ensure_worker()
        if url:
            spec = {"kind": "url", "url": url}
        else:
            spec = {"kind": "file", "path": path, "dhash": dhash, "size": size}
        self._worker.submit(key, spec)

    def forget(self, key: str) -> None:
        """允许重新请求（例如换了筛选条件、内容变了）"""
        with self._lock:
            self._asked.discard(key)

    def clear(self) -> None:
        with self._lock:
            self._asked.clear()

    def _on_bytes(self, key: str, data: bytes) -> None:
        # 必须在这里（GUI 线程）才建 QPixmap
        from PySide6 import QtGui
        pixmap = QtGui.QPixmap()
        if not pixmap.loadFromData(data):
            return
        self.ready.emit(key, pixmap)

    def stop(self) -> None:
        """停止后台线程；可重复调用，没起过线程时是空操作"""
        if self._stopped:
            return
        self._stopped = True
        if self._worker is not None:
            self._worker.stop()
            self._worker.wait(3000)
