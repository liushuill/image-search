"""
拖拽分类：拖进来但用不了时，必须说清原因

什么都不发生是最糟的反馈 —— 用户分不清"卡住了"还是"拖错了"。
四种实测遇到的情况：多张、文件夹、网页链接、非图片文件。
"""

import pytest

pytest.importorskip("PySide6")

from imgsearch_gui.widgets import drop_area          # noqa: E402


class FakeUrl:
    def __init__(self, path="", local=True):
        self._path = path
        self._local = local

    def isLocalFile(self):
        return self._local

    def toLocalFile(self):
        return self._path


class FakeMime:
    def __init__(self, urls=None):
        self._urls = urls or []

    def hasUrls(self):
        return bool(self._urls)

    def urls(self):
        return list(self._urls)


def mime_of(*urls):
    return FakeMime(list(urls))


class TestClassifyDrop:
    def test_single_image_is_silent(self, tmp_path):
        f = tmp_path / "a.png"
        f.write_bytes(b"x")
        paths, note = drop_area.classify_drop(mime_of(FakeUrl(str(f))))
        assert paths == [str(f)]
        assert note == ""

    def test_multiple_images_says_only_first(self, tmp_path):
        files = []
        for i in range(3):
            f = tmp_path / f"{i}.jpg"
            f.write_bytes(b"x")
            files.append(FakeUrl(str(f)))
        paths, note = drop_area.classify_drop(mime_of(*files))
        assert len(paths) == 3          # 全部收下，由界面决定只用第一张
        assert "只处理第一张" in note and "3" in note

    def test_folder_points_to_library_page(self, tmp_path):
        d = tmp_path / "pics"
        d.mkdir()
        paths, note = drop_area.classify_drop(mime_of(FakeUrl(str(d))))
        assert paths == []
        assert "图库" in note and "文件夹" in note

    def test_remote_url_asks_to_download(self):
        """从网页拖图：拖来的是链接 —— 原则是不下载，所以只能提示先下载"""
        paths, note = drop_area.classify_drop(
            mime_of(FakeUrl("https://i.pximg.net/a.jpg", local=False)))
        assert paths == []
        assert "下载" in note

    def test_html_file_from_pixiv_is_not_an_image(self, tmp_path):
        """Pixiv 没加载完时，拖到资源管理器会变成一个 html —— 不能当图片"""
        f = tmp_path / "page.html"
        f.write_text("<html></html>", encoding="utf-8")
        paths, note = drop_area.classify_drop(mime_of(FakeUrl(str(f))))
        assert paths == []
        assert "格式" in note

    def test_no_urls(self):
        paths, note = drop_area.classify_drop(FakeMime())
        assert paths == []
        assert note

    def test_mixed_prefers_images(self, tmp_path):
        """同时拖了图片和文件夹 —— 图片优先，不提示"""
        f = tmp_path / "a.png"
        f.write_bytes(b"x")
        d = tmp_path / "pics"
        d.mkdir()
        paths, note = drop_area.classify_drop(
            mime_of(FakeUrl(str(f)), FakeUrl(str(d))))
        assert paths == [str(f)]
        assert note == ""
