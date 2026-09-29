"""
启动引导测试

分发出去的是「解压后直接 ./run.sh 或 run.bat 就能用」，所以引导逻辑
本身也是要保证的代码 —— 而不是一段没跑过的脚本。

把逻辑放进 Python（而不是各写一份 sh/bat）正是为了能在这里被真实测试。
"""

import os
from pathlib import Path

import pytest

import bootstrap


class TestTargets:
    def test_known_targets(self):
        assert set(bootstrap.TARGETS) == {"cli", "gui"}
        assert bootstrap.TARGETS["cli"]["module"] == "imgsearch"
        assert bootstrap.TARGETS["gui"]["module"] == "imgsearch_gui"

    def test_requirements_files_exist(self):
        """回归：改了 requirements 文件名却没改这里，分发出去就装不上"""
        for spec in bootstrap.TARGETS.values():
            path = bootstrap.REPO_DIR / spec["requirements"]
            assert path.is_file(), f"找不到 {path}"

    def test_gui_requirements_include_core(self):
        """GUI 依赖必须包含核心依赖，否则图形界面装好了但搜索跑不起来"""
        text = (bootstrap.REPO_DIR / "requirements-gui.txt").read_text(encoding="utf-8")
        assert "-r requirements.txt" in text

    def test_sentinel_matches_requirements(self):
        cli = (bootstrap.REPO_DIR / "requirements.txt").read_text(encoding="utf-8").lower()
        assert bootstrap.TARGETS["cli"]["sentinel"] in cli
        gui = (bootstrap.REPO_DIR / "requirements-gui.txt").read_text(encoding="utf-8").lower()
        assert bootstrap.TARGETS["gui"]["sentinel"].lower() in gui


class TestVenvLayout:
    def test_posix_layout(self, monkeypatch):
        monkeypatch.setattr(bootstrap, "IS_WINDOWS", False)
        assert bootstrap.venv_python() == bootstrap.VENV_DIR / "bin" / "python"

    def test_windows_layout(self, monkeypatch):
        monkeypatch.setattr(bootstrap, "IS_WINDOWS", True)
        assert bootstrap.venv_python() == bootstrap.VENV_DIR / "Scripts" / "python.exe"

    def test_existing_venv_is_reused(self, tmp_path, monkeypatch):
        monkeypatch.setattr(bootstrap, "IS_WINDOWS", False)
        monkeypatch.setattr(bootstrap, "VENV_DIR", tmp_path / ".venv")
        target = tmp_path / ".venv" / "bin" / "python"
        target.parent.mkdir(parents=True)
        target.write_text("", encoding="utf-8")
        # 已存在时不该再去创建
        assert bootstrap.ensure_venv() == target

    def test_failure_explains_how_to_fix(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(bootstrap, "VENV_DIR", tmp_path / "nope")
        monkeypatch.setattr(bootstrap, "venv_python",
                            lambda: tmp_path / "nope" / "bin" / "python")
        monkeypatch.setattr(bootstrap.subprocess, "run",
                            lambda *a, **k: type("R", (), {"returncode": 1})())
        with pytest.raises(SystemExit):
            bootstrap.ensure_venv()
        err = capsys.readouterr().err
        assert "python3-venv" in err          # Debian 的提示
        assert "PATH" in err                  # Windows 的提示


class TestDependencyCheck:
    def test_skips_install_when_sentinel_present(self, monkeypatch):
        calls = []
        monkeypatch.setattr(bootstrap, "has_module", lambda py, mod: True)
        monkeypatch.setattr(bootstrap, "pip", lambda *a: calls.append(a) or 0)
        bootstrap.ensure_dependencies(Path("py"), bootstrap.TARGETS["cli"])
        assert calls == [], "依赖齐备时不该装任何东西"

    def test_installs_when_sentinel_missing(self, monkeypatch):
        calls = []
        monkeypatch.setattr(bootstrap, "has_module", lambda py, mod: False)
        monkeypatch.setattr(bootstrap, "pip", lambda *a: calls.append(a) or 0)
        bootstrap.ensure_dependencies(Path("py"), bootstrap.TARGETS["gui"])
        joined = [" ".join(map(str, c)) for c in calls]
        assert any("requirements-gui.txt" in j for j in joined)
        assert any("--upgrade" in j and "pip" in j for j in joined)

    def test_install_failure_exits_with_hint(self, monkeypatch, capsys):
        monkeypatch.setattr(bootstrap, "has_module", lambda py, mod: False)

        def fake_pip(py, *args):
            return 1 if "-r" in args else 0

        monkeypatch.setattr(bootstrap, "pip", fake_pip)
        with pytest.raises(SystemExit):
            bootstrap.ensure_dependencies(Path("py"), bootstrap.TARGETS["cli"])
        err = capsys.readouterr().err
        assert "代理" in err or "网络" in err


class TestEnvironment:
    def test_pythonpath_points_at_repo(self, monkeypatch):
        monkeypatch.delenv("PYTHONPATH", raising=False)
        env = bootstrap.build_env()
        assert str(bootstrap.REPO_DIR) in env["PYTHONPATH"].split(os.pathsep)

    def test_existing_pythonpath_preserved(self, monkeypatch):
        monkeypatch.setenv("PYTHONPATH", "/somewhere/else")
        env = bootstrap.build_env()
        parts = env["PYTHONPATH"].split(os.pathsep)
        assert str(bootstrap.REPO_DIR) in parts
        assert "/somewhere/else" in parts

    def test_does_not_change_cwd(self):
        """用 PYTHONPATH 而不是 chdir —— 否则调用者传的相对路径会指向别处"""
        before = os.getcwd()
        bootstrap.build_env()
        assert os.getcwd() == before


class TestMain:
    def test_no_args_prints_usage(self, capsys):
        assert bootstrap.main([]) == 2
        assert "bootstrap.py cli" in capsys.readouterr().out

    def test_unknown_target(self, capsys):
        assert bootstrap.main(["nope"]) == 2

    def test_dispatches_to_target_module(self, monkeypatch):
        recorded = {}
        monkeypatch.setattr(bootstrap, "ensure_venv", lambda: Path("py"))
        monkeypatch.setattr(bootstrap, "ensure_dependencies", lambda py, spec: None)

        def fake_run(cmd, env=None):
            recorded["cmd"] = cmd
            recorded["env"] = env
            return type("R", (), {"returncode": 7})()

        monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)
        rc = bootstrap.main(["cli", "search", "a.jpg"])

        assert rc == 7
        assert recorded["cmd"][1:4] == ["-m", "imgsearch", "search"]
        assert "a.jpg" in recorded["cmd"]
        assert str(bootstrap.REPO_DIR) in recorded["env"]["PYTHONPATH"]

    def test_gui_target_uses_gui_module(self, monkeypatch):
        recorded = {}
        monkeypatch.setattr(bootstrap, "ensure_venv", lambda: Path("py"))
        monkeypatch.setattr(bootstrap, "ensure_dependencies", lambda py, spec: None)
        monkeypatch.setattr(bootstrap.subprocess, "run",
                            lambda cmd, env=None: recorded.update(cmd=cmd)
                            or type("R", (), {"returncode": 0})())
        bootstrap.main(["gui"])
        assert recorded["cmd"][1:] == ["-m", "imgsearch_gui"]


class TestLaunchers:
    """薄封装必须真的指向 bootstrap，且 batch 保持纯 ASCII"""

    def test_run_scripts_call_bootstrap(self):
        for name in ("run.sh", "run-gui.sh"):
            text = (bootstrap.REPO_DIR / name).read_text(encoding="utf-8")
            assert "bootstrap.py" in text, name

    @pytest.mark.parametrize("name", ["run.bat", "run-gui.bat", "start_gui.bat"])
    def test_batch_files_are_ascii_only(self, name):
        """
        cmd.exe 按当前代码页逐行解析批处理文件，中文在 if 块里容易出错。
        所有面向用户的消息都交给 Python 打印，batch 保持纯 ASCII。
        """
        raw = (bootstrap.REPO_DIR / name).read_bytes()
        assert all(b < 128 for b in raw), f"{name} 含非 ASCII 字节"

    def test_batch_supports_py_launcher(self):
        """Windows 上 `python` 未必在 PATH，但 `py` 通常有"""
        for name in ("run.bat", "run-gui.bat"):
            text = (bootstrap.REPO_DIR / name).read_text(encoding="ascii")
            assert "where py" in text and "py -3" in text
            assert "where python" in text

    def test_batch_has_no_bom(self):
        """UTF-8 BOM 会让 cmd 把第一行当成乱码命令"""
        for name in ("run.bat", "run-gui.bat", "start_gui.bat"):
            assert not (bootstrap.REPO_DIR / name).read_bytes().startswith(b"\xef\xbb\xbf")

    def test_start_gui_delegates_to_new_gui(self):
        """旧入口原先启动 tkinter 版，现在应转交 Qt6 版"""
        text = (bootstrap.REPO_DIR / "start_gui.bat").read_text(encoding="ascii")
        assert "run-gui.bat" in text

    def test_shell_scripts_handle_missing_python(self):
        for name in ("run.sh", "run-gui.sh"):
            text = (bootstrap.REPO_DIR / name).read_text(encoding="utf-8")
            assert "python3" in text and "找不到 Python" in text
