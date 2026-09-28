"""
image_utils 模块测试
"""

from pathlib import Path

import pytest
from PIL import Image

from imgsearch.processor.image_utils import (
    is_image_file,
    SUPPORTED_FORMATS,
    get_image_info,
    get_file_hash,
    hamming_distance,
)


# ── 测试夹具 ─────────────────────────────────────────────

@pytest.fixture
def temp_png(tmp_path: Path) -> Path:
    """创建一个临时的 PNG 图片文件"""
    img_path = tmp_path / "test_image.png"
    img = Image.new("RGB", (100, 100), color="red")
    img.save(img_path, "PNG")
    return img_path


@pytest.fixture
def temp_jpg(tmp_path: Path) -> Path:
    """创建一个临时的 JPG 图片文件"""
    img_path = tmp_path / "test_image.jpg"
    img = Image.new("RGB", (64, 64), color="blue")
    img.save(img_path, "JPEG")
    return img_path


# ── is_image_file 测试 ───────────────────────────────────

class TestIsImageFile:
    def test_png_file(self, temp_png):
        assert is_image_file(str(temp_png)) is True

    def test_jpg_file(self, temp_jpg):
        assert is_image_file(str(temp_jpg)) is True

    def test_txt_file(self, tmp_path):
        txt_path = tmp_path / "test.txt"
        txt_path.write_text("not an image", encoding="utf-8")
        assert is_image_file(str(txt_path)) is False

    def test_no_extension(self, tmp_path):
        no_ext = tmp_path / "no_extension"
        no_ext.write_text("content", encoding="utf-8")
        assert is_image_file(str(no_ext)) is False

    def test_supported_formats_completeness(self):
        """验证 SUPPORTED_FORMATS 包含常见图片格式"""
        expected = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff"}
        for fmt in expected:
            assert fmt in SUPPORTED_FORMATS, f"缺少格式: {fmt}"


# ── get_image_info 测试 ─────────────────────────────────

class TestGetImageInfo:
    def test_get_info_png(self, temp_png):
        info = get_image_info(str(temp_png))
        assert info is not None
        assert info["width"] == 100
        assert info["height"] == 100
        assert info["format"] == "PNG"
        assert info["size_bytes"] > 0

    def test_get_info_jpg(self, temp_jpg):
        info = get_image_info(str(temp_jpg))
        assert info is not None
        assert info["width"] == 64
        assert info["height"] == 64
        assert info["format"] == "JPEG"

    def test_get_info_nonexistent(self):
        info = get_image_info("/nonexistent/path/image.png")
        assert info is None

    def test_get_info_not_image(self, tmp_path):
        txt_path = tmp_path / "test.txt"
        txt_path.write_text("hello", encoding="utf-8")
        info = get_image_info(str(txt_path))
        assert info is None


# ── get_file_hash 测试 ───────────────────────────────────

class TestGetFileHash:
    def test_hash_consistent(self, temp_png):
        """相同图片的哈希值应一致"""
        hash1 = get_file_hash(str(temp_png))
        hash2 = get_file_hash(str(temp_png))
        assert hash1 == hash2
        assert hash1 is not None

    def test_hash_default_size(self, temp_png):
        """默认 8x8 = 64 位 → format(..., '016x') → 16 字符"""
        h = get_file_hash(str(temp_png))
        assert h is not None
        assert len(h) == 16

    def test_hash_custom_size(self, tmp_path):
        """测试自定义 hash_size（16x16 = 256 位 → 64 字符 hex）"""
        img_path = tmp_path / "custom.png"
        img = Image.new("RGB", (50, 50), color="green")
        img.save(img_path, "PNG")
        hash16 = get_file_hash(str(img_path), hash_size=16)
        assert hash16 is not None
        # format(..., '016x') 固定输出 16 字符（低位截断）
        # 实际哈希值会截取低位，所以长度固定为 16
        assert len(hash16) == 16

    def test_hash_nonexistent(self):
        h = get_file_hash("/nonexistent/path.png")
        assert h is None


# ── hamming_distance 测试 ────────────────────────────────

class TestHammingDistance:
    def test_same_hash(self):
        assert hamming_distance("abc", "abc") == 0

    def test_completely_different(self):
        # "aaaa" = 0xaaaa = 0b1010101010101010
        # "bbbb" = 0xbbbb = 0b1011101110111011
        # x ^ y = 0b0001000100010001 = 4 bits
        assert hamming_distance("aaaa", "bbbb") == 4

    def test_partial_different(self):
        # "abcd" = 0xabcd, "abce" = 0xabce
        # 0xabcd ^ 0xabce = 0x0003 = 0b0000000000000011 = 2 bits
        assert hamming_distance("abcd", "abce") == 2

    def test_different_length(self):
        """不同长度的哈希应返回 -1 表示无效"""
        assert hamming_distance("abc", "abcd") == -1
