"""
引擎的凭据需求：统一模板（AUTH_MODE + 「使用 API Key」开关）

设计背景：用户希望「所有引擎共用一套标准模板配置」，并且能在配置页
用布尔开关决定是否使用 API Key。

统一约定的三个类属性（**每个引擎都必须声明**）：
    NAME / DISPLAY_NAME / DEFAULT_API_URL / DEFAULT_ORDER
    ENABLED_BY_DEFAULT / AUTH_MODE / CONFIG_SCHEMA
"""

import pytest

from imgsearch.engines.schema import COMMON_SCHEMA

BUILTIN = ("sauceNAO", "iqdb", "ascii2d", "traceMoe", "danbooru")
VALID_MODES = ("required", "optional", "none")


class TestStandardTemplate:
    """所有引擎形状一致 —— 这是「同一套标准模板」的字面要求"""

    @pytest.mark.parametrize("name", BUILTIN)
    def test_declares_standard_attributes(self, name):
        from imgsearch.engines.store import get_store
        from imgsearch.engines.registry import resolve_engine_class

        cls = resolve_engine_class(get_store().get(name))
        assert cls is not None
        for attr in ("NAME", "DISPLAY_NAME", "DEFAULT_API_URL",
                     "DEFAULT_ORDER", "ENABLED_BY_DEFAULT"):
            assert hasattr(cls, attr), f"{name} 缺少 {attr}"
        assert cls.NAME, f"{name} 的 NAME 不能为空"
        assert cls.DISPLAY_NAME, f"{name} 的 DISPLAY_NAME 不能为空"

    @pytest.mark.parametrize("name", BUILTIN)
    def test_declares_valid_auth_mode(self, name):
        from imgsearch.engines.store import get_store
        from imgsearch.engines.registry import resolve_engine_class

        cls = resolve_engine_class(get_store().get(name))
        assert getattr(cls, "AUTH_MODE", None) in VALID_MODES, (
            f"{name} 的 AUTH_MODE 必须是 {VALID_MODES} 之一")

    @pytest.mark.parametrize("name", BUILTIN)
    def test_has_config_schema(self, name):
        from imgsearch.engines.store import get_store
        assert len(get_store().get(name).schema()) >= len(COMMON_SCHEMA)

    def test_scaffold_template_matches_standard(self):
        """脚手架生成的模板必须体现同一套标准模板"""
        from imgsearch.cli import _CUSTOM_ENGINE_TEMPLATE

        src = _CUSTOM_ENGINE_TEMPLATE.format(name="mysite", cls="Mysite")
        compile(src, "<template>", "exec")            # 语法必须正确
        for attr in ("NAME", "DISPLAY_NAME", "DEFAULT_API_URL",
                     "ENABLED_BY_DEFAULT", "AUTH_MODE", "CONFIG_SCHEMA"):
            assert attr in src, f"模板缺少 {attr}"
        assert 'AUTH_MODE = "none"' in src


class TestUseApiKeyField:
    def test_field_is_common(self):
        """放在 COMMON_SCHEMA 里，所有引擎都有 —— 这是"统一模板"的体现"""
        keys = [f.key for f in COMMON_SCHEMA]
        assert "use_api_key" in keys

    def test_defaults_to_true(self):
        from tests.legacy.iqdb import Iqdb
        assert Iqdb().opt_bool("use_api_key", True) is True

    def test_auth_label_is_human_readable(self):
        from tests.legacy.danbooru import Danbooru
        from tests.legacy.iqdb import Iqdb
        from tests.legacy.saucenao import SauceNAO

        assert SauceNAO(api_key="k").auth_label == "必须凭据"
        assert Danbooru(login="u", api_key="k").auth_label == "可选凭据"
        assert Iqdb().auth_label == "无需凭据"


class TestAuthModeBehaviour:
    def test_none_mode_never_uses_key(self):
        """AUTH_MODE=none 的引擎恒为 False —— 它本来就没有凭据可发"""
        from tests.legacy.iqdb import Iqdb
        assert Iqdb().uses_api_key is False

    def test_required_engine_refuses_when_key_disabled(self):
        """
        必须凭据的引擎关掉开关后要**立刻明确报错**，
        而不是构造成功然后在请求时给个莫名的 HTTP 错误。
        """
        from tests.legacy.saucenao import SauceNAO

        with pytest.raises(ValueError) as ei:
            SauceNAO(api_key="k", use_api_key=False)
        msg = str(ei.value)
        assert "必须使用 API Key" in msg
        assert "使用 API Key" in msg            # 告诉用户去哪个开关打开

    def test_required_engine_still_requires_key_when_enabled(self):
        from tests.legacy.saucenao import SauceNAO
        with pytest.raises(ValueError, match="未配置"):
            SauceNAO(api_key="", use_api_key=True)

    def test_optional_engine_builds_anonymously(self):
        """
        AUTH_MODE=optional（Danbooru）：关掉开关后**能构造**，
        并且不带凭据 —— 此时只能搜公网 URL（上传需认证）。
        """
        from tests.legacy.danbooru import Danbooru

        eng = Danbooru(login="someone", api_key="k" * 32, use_api_key=False)
        assert eng.uses_api_key is False
        assert eng.login == "" and eng.api_key == ""
        session = eng.make_session()
        try:
            assert session.auth is None, "匿名模式不该挂 BasicAuth"
        finally:
            session.close()

    def test_optional_engine_uses_key_when_enabled(self):
        """
        ⚠️ BasicAuth 是在 `_call_api` 里挂的（每请求一次），不在 make_session 里 ——
        所以要在请求构造这一层测，测 make_session 测不到。
        """
        from tests.legacy.danbooru import Danbooru

        eng = Danbooru(login="someone", api_key="k" * 32, use_api_key=True)
        assert eng.uses_api_key is True

        spy = _SpySession()
        eng.make_session = lambda **k: spy          # type: ignore[assignment]
        with pytest.raises(RuntimeError, match="到此为止"):
            eng._call_api(data={"url": "https://example.com/x.jpg"})
        # session.auth 存的是 HTTPBasicAuth 实例，不是元组
        assert spy.auth is not None, "开启时应当挂上凭据"
        assert spy.auth.username == "someone"
        assert spy.auth.password == "k" * 32

    def test_optional_engine_omits_auth_when_disabled(self):
        from tests.legacy.danbooru import Danbooru

        eng = Danbooru(login="someone", api_key="k" * 32, use_api_key=False)
        spy = _SpySession()
        eng.make_session = lambda **k: spy          # type: ignore[assignment]
        with pytest.raises(RuntimeError, match="到此为止"):
            eng._call_api(data={"url": "https://example.com/x.jpg"})
        assert spy.auth is None, "匿名模式不该挂 BasicAuth"

    def test_optional_engine_still_needs_credentials_when_enabled(self):
        from tests.legacy.danbooru import Danbooru
        with pytest.raises(ValueError, match="用户名未配置"):
            Danbooru(login="", api_key="k" * 32, use_api_key=True)


class _SpySession:
    """拦住真实请求，只记录到底有没有挂凭据"""

    def __init__(self):
        self.auth = None
        self.headers: dict = {}

    def post(self, *a, **k):
        raise RuntimeError("到此为止")

    def get(self, *a, **k):
        raise RuntimeError("到此为止")

    def close(self):
        pass


class TestCredentialsPageDerivation:
    def test_disabled_key_hides_that_engine_credentials(self, store):
        """关掉开关 = 「我不打算给这个引擎填凭据」，凭据页就不该占位置"""
        from imgsearch.service import declared_secrets

        store.update_settings("danbooru", {"use_api_key": False})
        names = [c.env_name for c in declared_secrets()]
        assert "DANBOORU_API_KEY" not in names
        assert "DANBOORU_LOGIN" not in names
        # 其他引擎不受影响
        assert "SAUCENAO_KEY" in names

    def test_enabled_key_shows_them_again(self, store):
        from imgsearch.service import declared_secrets

        store.update_settings("danbooru", {"use_api_key": True})
        names = [c.env_name for c in declared_secrets()]
        assert "DANBOORU_API_KEY" in names
        assert "DANBOORU_LOGIN" in names

    def test_each_credential_knows_its_engine(self, store):
        """凭据页按引擎分组，所以每条凭据必须知道归属"""
        from imgsearch.service import declared_secrets

        specs = {c.env_name: c for c in declared_secrets()}
        assert "Danbooru" in specs["DANBOORU_API_KEY"].group
        assert "SauceNAO" in specs["SAUCENAO_KEY"].group

    def test_engines_without_credentials_contribute_nothing(self, store):
        from imgsearch.service import declared_secrets

        names = [c.env_name for c in declared_secrets()]
        for engine in ("IQDB", "Ascii2D", "TraceMoe"):
            assert not any(engine.upper() in n for n in names)
