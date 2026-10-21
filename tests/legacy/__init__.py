"""
迁移前的 Python 引擎实现 —— **仅作对照**，不参与运行。

实验分支 experiment/declarative-only 把这些引擎改成了配置预设
（见 imgsearch/engines/adapters/presets.py）。
这几位保留下来是为了让 `tests/test_declarative_migration.py` 里的
「新旧双跑对比」能一直跑：同一个响应，配置版与手写版的结果必须一致。

⚠️ 它们已从 `imgsearch.engines` 移出，不再被注册表发现，
也不会被 `import imgsearch.engines` 加载。
"""
