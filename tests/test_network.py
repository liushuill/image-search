"""
network 工具模块测试

测试 session 创建和 download_file 功能。
使用 mock 避免真实 HTTP 请求。
"""

from unittest.mock import patch, MagicMock

import pytest
import requests

from imgsearch.utils.network import create_session, download_file


class TestCreateSession:
    """create_session 测试"""

    def test_default_session(self):
        """测试创建默认 Session"""
        session = create_session()
        assert session is not None
        assert isinstance(session, requests.Session)

        ua = session.headers.get("User-Agent", "")
        assert len(ua) > 0

        session.close()

    def test_with_proxies(self):
        """测试代理配置"""
        proxies = {"http": "http://proxy:8080", "https": "http://proxy:8080"}
        session = create_session(proxies=proxies)
        assert session.proxies.get("http") == "http://proxy:8080"
        assert session.proxies.get("https") == "http://proxy:8080"
        session.close()

    def test_with_timeout(self):
        """测试超时设置"""
        session = create_session(timeout=60)
        assert session is not None
        session.close()

    def test_cloudscraper_disabled(self):
        """测试未启用 cloudscraper"""
        session = create_session(use_cloudscraper=False)
        assert session is not None
        assert isinstance(session, requests.Session)
        session.close()

    def test_cloudscraper_import_error(self):
        """测试 cloudscraper 未安装时降级"""
        with patch.dict("sys.modules", {"cloudscraper": None}):
            session = create_session(use_cloudscraper=True)
            assert session is not None
            assert isinstance(session, requests.Session)
            session.close()


class TestCloudscraperProxyIncompatibility:
    """
    回归：cloudscraper 的自定义 SSL 上下文与代理隧道不兼容。

    实测（Clash 7897）：一旦经代理，无论用 session.proxies 还是每次请求
    显式传 proxies=，都会在 TLS 握手阶段抛 SSLV3_ALERT_HANDSHAKE_FAILURE。
    因此同时需要「代理 + CF 绕过」时必须优先保代理，改用普通请求。
    """

    PROXY = {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}

    def test_proxy_forces_plain_session(self):
        pytest.importorskip("cloudscraper")
        session = create_session(proxies=self.PROXY, use_cloudscraper=True)
        assert type(session).__name__ == "Session", \
            "有代理时不该用 cloudscraper（会握手失败）"
        assert session.proxies.get("https") == self.PROXY["https"]
        session.close()

    def test_without_proxy_still_uses_cloudscraper(self):
        pytest.importorskip("cloudscraper")
        session = create_session(use_cloudscraper=True)
        assert type(session).__name__ == "CloudScraper"
        session.close()

    def test_proxy_applied_to_plain_session(self):
        session = create_session(proxies=self.PROXY)
        assert session.proxies.get("http") == self.PROXY["http"]
        assert session.proxies.get("https") == self.PROXY["https"]
        session.close()

    def test_warning_is_emitted_only_once(self, capsys):
        """降级提示不该每条请求都刷屏"""
        import imgsearch.utils.network as net
        net._warned.clear()
        for _ in range(3):
            create_session(proxies=self.PROXY, use_cloudscraper=True).close()
        captured = capsys.readouterr().out
        assert captured.count("cloudscraper 与代理不兼容") == 1
        net._warned.clear()


class TestDownloadFile:
    """download_file 测试"""

    def test_download_success(self, tmp_path):
        """测试下载成功"""
        save_path = tmp_path / "test.jpg"

        with patch("imgsearch.utils.network.create_session") as mock_create:
            mock_session = MagicMock(spec=requests.Session)
            mock_create.return_value = mock_session

            mock_resp = MagicMock()
            mock_resp.__enter__.return_value = mock_resp
            mock_resp.iter_content.return_value = [b"data1", b"data2"]
            mock_resp.raise_for_status.return_value = None

            mock_session.get.return_value = mock_resp

            result = download_file("https://example.com/img.jpg", str(save_path), timeout=30)
            assert result is True
            assert save_path.read_bytes() == b"data1data2"

    def test_download_request_error(self, tmp_path):
        """测试下载失败时应抛出异常（重试耗尽后）"""
        with patch("imgsearch.utils.network.create_session") as mock_create:
            mock_session = MagicMock(spec=requests.Session)
            mock_create.return_value = mock_session

            mock_resp = MagicMock()
            mock_resp.__enter__.return_value = mock_resp
            mock_resp.raise_for_status.side_effect = requests.RequestException("连接失败")

            mock_session.get.return_value = mock_resp

            save_path = tmp_path / "fail.jpg"
            with pytest.raises(requests.RequestException):
                download_file("https://example.com/img.jpg", str(save_path), timeout=30, max_retries=1)

    def test_download_timeout(self, tmp_path):
        """测试下载超时时应抛出异常"""
        with patch("imgsearch.utils.network.create_session") as mock_create:
            mock_session = MagicMock(spec=requests.Session)
            mock_create.return_value = mock_session

            mock_resp = MagicMock()
            mock_resp.__enter__.return_value = mock_resp
            mock_resp.raise_for_status.side_effect = requests.Timeout("超时")

            mock_session.get.return_value = mock_resp

            save_path = tmp_path / "timeout.jpg"
            with pytest.raises(requests.Timeout):
                download_file("https://example.com/img.jpg", str(save_path), timeout=5, max_retries=1)
