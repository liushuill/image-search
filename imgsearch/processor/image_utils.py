"""
图片处理工具模块
"""

from pathlib import Path
from typing import Optional

from PIL import Image, UnidentifiedImageError

# 支持的图片格式
SUPPORTED_FORMATS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff"}

# MIME 类型映射
MIME_MAP = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/gif": ".gif",
    "image/tiff": ".tiff",
}


def is_image_file(file_path: str) -> bool:
    """判断是否为支持的图片文件"""
    ext = Path(file_path).suffix.lower()
    return ext in SUPPORTED_FORMATS


def get_image_info(file_path: str) -> Optional[dict]:
    """
    获取图片基本信息

    Returns:
        dict with keys: width, height, format, mode, size_bytes
        如果无法读取返回 None
    """
    try:
        with Image.open(file_path) as img:
            return {
                "width": img.width,
                "height": img.height,
                "format": img.format,
                "mode": img.mode,
                "size_bytes": Path(file_path).stat().st_size,
            }
    except (FileNotFoundError, UnidentifiedImageError, OSError):
        return None


def get_file_hash(file_path: str, hash_size: int = 8) -> Optional[str]:
    """
    计算图片的 dHash（差异哈希），用于快速去重

    Args:
        file_path: 图片路径
        hash_size: 哈希尺寸（8 生成 64bit 哈希）

    Returns:
        十六进制哈希字符串，失败返回 None
    """
    try:
        with Image.open(file_path) as img:
            img = img.convert("L").resize((hash_size + 1, hash_size), Image.LANCZOS)
            diff = []
            for row in range(hash_size):
                for col in range(hash_size):
                    diff.append(img.getpixel((col, row)) > img.getpixel((col + 1, row)))
            # 将二进制转为十六进制
            hash_val = 0
            for i, bit in enumerate(diff):
                if bit:
                    hash_val |= 1 << (len(diff) - 1 - i)
            return format(hash_val, "016x")
    except Exception:
        return None


def hamming_distance(hash1: str, hash2: str) -> int:
    """计算两个 dHash 之间的汉明距离"""
    if len(hash1) != len(hash2):
        return -1
    h1 = int(hash1, 16)
    h2 = int(hash2, 16)
    return bin(h1 ^ h2).count("1")


def guess_output_filename(
    pixiv_id: str,
    artist: str = "",
    title: str = "",
    page: int = 0,
    ext: str = ".jpg",
) -> str:
    """
    根据元数据生成有意义的文件名

    Args:
        pixiv_id: Pixiv 作品 ID
        artist: 画师名
        title: 作品标题
        page: 页码
        ext: 扩展名

    Returns:
        文件名（不含路径）
    """
    parts = []
    if artist:
        parts.append(_sanitize_filename(artist))
    if title:
        parts.append(_sanitize_filename(title))
    parts.append(pixiv_id)
    if page > 0:
        parts.append(f"p{page}")

    return f"[{pixiv_id}] {' - '.join(parts)}{ext}"


def _sanitize_filename(name: str) -> str:
    """清理文件名中的非法字符"""
    illegal = r'<>:"/\|?*'
    for c in illegal:
        name = name.replace(c, "")
    return name.strip() or "untitled"
