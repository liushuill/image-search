"""
缩略图缓存

## 为什么按内容（dHash）存放，而不是按路径

用户的图会在目录间移动。若缩略图按源文件路径存放：

  - 文件一移走，缩略图就失效，得重新生成
  - 同一张图出现在两个目录时会被存两份

所以文件名就是内容哈希：``thumbs/<dhash 前两位>/<dhash>.jpg``
（前两位分桶，避免单目录塞进几万个小文件）。

按根路径清理时，只需查出该路径名下记录的 dhash 再删对应文件即可 ——
不会误伤别的路径的缓存。
"""

from pathlib import Path
from typing import Iterable, List, Optional, Set

import hashlib

from imgsearch.config import THUMBS_DIR
from imgsearch.library.errors import LibraryError

# 缩略图尺寸与质量（够 GUI 列表与 HTML 报告用，且体积可控）
THUMB_SIZE = 256
THUMB_QUALITY = 82

IMAGE_SUFFIX = ".jpg"


def thumbs_dir() -> Path:
    """缩略图根目录（确保存在）"""
    d = Path(THUMBS_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def path_for(dhash: str) -> Path:
    """某个内容哈希对应的缩略图路径（不保证存在）"""
    if not dhash:
        raise LibraryError("dHash 为空，无法定位缩略图")
    key = dhash.strip()
    return thumbs_dir() / key[:2] / (key + IMAGE_SUFFIX)


def exists(dhash: str) -> bool:
    try:
        return path_for(dhash).is_file()
    except LibraryError:
        return False


def ensure(dhash: str, source_path: str,
           size: int = THUMB_SIZE) -> Optional[Path]:
    """
    确保缩略图存在，必要时从源文件生成。

    Returns:
        缩略图路径；生成失败返回 None（缩略图只是缓存，失败不应中断主流程）
    """
    target = path_for(dhash)
    if target.is_file() and target.stat().st_size > 0:
        return target

    src = Path(source_path)
    if not src.is_file():
        return None

    try:
        from PIL import Image
        target.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as img:
            img = img.convert("RGB")
            img.thumbnail((size, size), Image.LANCZOS)
            tmp = target.with_suffix(".tmp")
            img.save(tmp, format="JPEG", quality=THUMB_QUALITY, optimize=True)
        tmp.replace(target)
        return target
    except Exception:
        # 缓存生成失败不影响搜索主流程
        try:
            if target.with_suffix(".tmp").exists():
                target.with_suffix(".tmp").unlink()
        except OSError:
            pass
        return None


def remove(dhash: str) -> bool:
    """删除某个内容的缩略图；顺带清掉空的桶目录"""
    try:
        target = path_for(dhash)
    except LibraryError:
        return False
    if not target.is_file():
        return False
    try:
        target.unlink()
    except OSError:
        return False
    try:
        bucket = target.parent
        if bucket.is_dir() and not any(bucket.iterdir()):
            bucket.rmdir()
    except OSError:
        pass
    return True


def remove_many(dhashes: Iterable[str]) -> int:
    """批量删除，返回实际删除数"""
    return sum(1 for d in dhashes if remove(d))


def iter_files() -> List[Path]:
    """列出所有缩略图文件"""
    root = Path(THUMBS_DIR)
    if not root.is_dir():
        return []
    return [p for p in root.rglob("*" + IMAGE_SUFFIX) if p.is_file()]


def stats() -> dict:
    """缩略图缓存的条数与占用"""
    files = iter_files()
    total = 0
    for f in files:
        try:
            total += f.stat().st_size
        except OSError:
            pass
    return {"count": len(files), "bytes": total}


def purge_all() -> int:
    """清空整个缩略图缓存（目录结构保留），返回删除文件数"""
    removed = 0
    for f in iter_files():
        try:
            f.unlink()
            removed += 1
        except OSError:
            pass
    # 清掉空的桶目录
    root = Path(THUMBS_DIR)
    if root.is_dir():
        for bucket in root.iterdir():
            if bucket.is_dir():
                try:
                    if not any(bucket.iterdir()):
                        bucket.rmdir()
                except OSError:
                    pass
    return removed


def purge_orphans(known_dhashes: Set[str]) -> int:
    """
    删除数据库里已不存在的孤立缩略图。

    用于「搜索结果记录被清理后，残留的缩略图」这类情况。
    """
    removed = 0
    for f in iter_files():
        key = f.stem
        if key not in known_dhashes:
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass
    return removed


# ──────────────────────────────────────────────
#  图源缩略图（从搜索引擎给的链接下载的那一批）
# ──────────────────────────────────────────────
#
# 与本地图缩略图的区别：
#   · 本地图缩略图按**内容 dHash** 命名，与路径无关
#   · 图源缩略图按**来源 URL** 命名，同一张图重新搜索会得到不同带令牌的
#     URL，但路径部分是稳定的，所以缓存键取去掉查询串的部分
#
# ⚠️ 这是整套缓存里**唯一会无界增长**的东西：每看一次新图的结果就多几条。
# 因此有容量上限与 LRU 淘汰，并且「清理」页可以手动清。

# 默认上限（MB）；0 表示不限制
DEFAULT_URL_CACHE_MB = 100


def url_thumb_dir() -> Path:
    """
    图源缩略图缓存目录。

    ⚠️ 必须做成**函数**而不是模块级常量：常量在导入时就定死了，
    之后改配置（含测试里的隔离）都不再生效 ——
    实测后果是测试把文件写进了仓库里真实的 data/cache/urlthumbs。
    这里每次都从 config 现读，跟随当前配置。
    """
    from imgsearch.config import CACHE_DIR as cache_dir
    d = Path(cache_dir) / "urlthumbs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def stable_url_key(url: str) -> str:
    """
    URL 的稳定标识（去掉查询串与片段）。

    ⚠️ 必需，不是优化。实测：SauceNAO 的缩略图地址带 ``?auth=…&exp=…``，
    当场取有效、过一会儿再取 **403**；而路径部分稳定。
    按稳定部分做键，重新搜索同一张图就能命中缓存。
    """
    return (url or "").split("?", 1)[0].split("#", 1)[0]


def url_thumb_path(url: str) -> Path:
    """某个来源 URL 对应的缓存文件路径（不保证存在）"""
    digest = hashlib.sha1(stable_url_key(url).encode("utf-8")).hexdigest()
    return url_thumb_dir() / f"{digest}.img"


def iter_url_files() -> List[Path]:
    """遍历缓存文件（跳过临时文件）"""
    return [f for f in url_thumb_dir().iterdir()
            if f.is_file() and not f.name.endswith(".tmp")]


def url_stats() -> dict:
    """图源缩略图缓存的条数与占用"""
    total = 0
    files = iter_url_files()
    for f in files:
        try:
            total += f.stat().st_size
        except OSError:
            pass
    return {"count": len(files), "bytes": total}


def trim_url_cache(max_bytes: Optional[int] = None) -> dict:
    """
    超出上限时按「最久未使用」淘汰。

    依据 ``st_atime``（访问时间）排序 —— 命中缓存时会读文件，
    因此访问时间是有的。文件系统若挂载了 ``noatime`` 则退化为修改时间
    （那样淘汰顺序会接近 FIFO，仍然安全，只是不够精确）。

    Args:
        max_bytes: 上限字节数；None 时读配置；<=0 表示不限制

    Returns:
        ``{"removed": n, "freed": bytes, "kept": n, "bytes": bytes}``
    """
    if max_bytes is None:
        from imgsearch.config import get
        try:
            mb = float(get("url_thumb_cache_mb", DEFAULT_URL_CACHE_MB) or 0)
        except (TypeError, ValueError):
            mb = DEFAULT_URL_CACHE_MB
        max_bytes = int(mb * 1024 * 1024)

    files = iter_url_files()
    entries = []
    total = 0
    for f in files:
        try:
            st = f.stat()
        except OSError:
            continue
        used = getattr(st, "st_atime", st.st_mtime) or st.st_mtime
        entries.append((used, st.st_mtime, st.st_size, f))
        total += st.st_size

    if max_bytes is None or max_bytes <= 0 or total <= max_bytes:
        return {"removed": 0, "freed": 0, "kept": len(entries), "bytes": total}

    entries.sort(key=lambda e: (e[0], e[1]))          # 最久未用的排前面
    removed = freed = 0
    for _atime, _mtime, size, path in entries:
        if total <= max_bytes:
            break
        try:
            path.unlink()
            removed += 1
            freed += size
            total -= size
        except OSError:
            pass
    return {"removed": removed, "freed": freed,
            "kept": len(entries) - removed, "bytes": total}


def purge_url_cache(urls: Optional[Iterable[str]] = None) -> dict:
    """
    删除图源缩略图缓存。

    Args:
        urls: 只删这些 URL 对应的缓存；None 表示全清

    Returns:
        ``{"removed": n, "freed": bytes}``
    """
    if urls is None:
        targets = iter_url_files()
    else:
        targets = []
        for url in urls:
            path = url_thumb_path(url)
            if path.is_file():
                targets.append(path)

    removed = freed = 0
    for path in targets:
        try:
            size = path.stat().st_size
            path.unlink()
            removed += 1
            freed += size
        except OSError:
            pass
    return {"removed": removed, "freed": freed}
