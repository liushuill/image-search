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
