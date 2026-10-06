"""
引擎配置字段的声明式 Schema

设计目标：**新增一个引擎只需写一个文件**。

每个引擎类声明自己的 ``CONFIG_SCHEMA``（一串 :class:`Field`），
于是：类型转换、默认值、校验、敏感字段回退、以及 GUI 表单渲染
全部由 schema 驱动，各引擎不必再自己解析字符串。

这直接针对旧版的几类缺陷：
  - 值被界面强制成字符串（``db: 999`` 变 ``"999"``）
  - ``0`` 被 ``or 100`` 吞掉（"0=无限制"名不副实）
  - 校验只在「保存」时弹一个框，错误定位不到字段
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

# ── 字段类型 ────────────────────────────────────────────────
STR = "str"
INT = "int"
FLOAT = "float"
BOOL = "bool"
SECRET = "secret"   # 可留空，留空时回退到 env_var（.env / 环境变量）
KV = "kv"           # 键值对，如 headers / params
TEXT = "text"       # 多行文本

BOOL_TRUE = {"1", "true", "yes", "y", "on", "是", "启用", "开"}


class ConfigError(ValueError):
    """配置值非法。消息面向用户，可直接展示。"""


@dataclass(frozen=True)
class Field:
    """一个可配置字段的声明"""

    key: str
    label: str
    type: str = STR
    default: Any = ""
    help: str = ""
    required: bool = False
    # 仅对 type="secret" 有意义：是否在界面上打码显示。
    # 为什么需要它：secret 表达的是「这份值存 .env、只在凭据页编辑」，
    # 而用户名这类值虽然也存 .env，却**没有隐藏的必要**（打码后
    # 用户没法核对自己有没有打错）。把两件事分开，就不必为了"能看"
    # 而把它挪回引擎页、造成两个编辑入口。
    mask: bool = True
    env_var: str = ""            # 值为空时从此环境变量 / .env 回退读取
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    choices: Optional[Tuple[str, ...]] = None   # 枚举取值（仅 str 类型）
    placeholder: str = ""
    advanced: bool = False       # 界面上折叠进「高级」
    unit: str = ""               # 展示用单位，如 "秒" / "次"

    @property
    def is_secret(self) -> bool:
        return self.type == SECRET

    @property
    def is_structured(self) -> bool:
        return self.type == KV


# ── 类型转换与校验 ──────────────────────────────────────────


def env_var_for(engine_name: str, field: "Field") -> str:
    """
    SECRET 字段对应的环境变量名（也就是它在 .env 里的落点）。

    优先用字段自己声明的 ``env_var``；没有就按
    ``IMGSEARCH_<引擎>_<字段>`` 派生 —— 目的是让**任何**密钥字段都有
    一个稳定去处，而不是被写进 config.json。
    """
    if field.env_var:
        return field.env_var

    def _norm(text: str) -> str:
        return re.sub(r"[^0-9A-Za-z]+", "_", text or "").strip("_").upper()

    return f"IMGSEARCH_{_norm(engine_name)}_{_norm(field.key)}"


def legacy_env_var_for(engine_name: str, field: "Field") -> str:
    """
    早期版本派生出的环境变量名（``IMGSEARCH_<引擎>_<字段>``）。

    那时字段没声明 env_var，而引擎代码里读的是自己的固定名字（如
    ``SAUCENAO_KEY``），于是凭据「搬过去了却读不到」。迁移时要把它
    挪到正确的名字上。
    """
    def _norm(text: str) -> str:
        return re.sub(r"[^0-9A-Za-z]+", "_", text or "").strip("_").upper()

    return f"IMGSEARCH_{_norm(engine_name)}_{_norm(field.key)}"


def coerce(f: Field, raw: Any) -> Any:
    """
    把任意输入转换成字段声明的类型。

    空值（None / ""）返回字段默认值（再转换一次），
    因此「清空输入框」等价于「恢复默认」，不会留下错误的空串。
    """
    if raw is None or raw == "":
        raw = f.default

    if f.type == BOOL:
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)):
            return bool(raw)
        return str(raw).strip().lower() in BOOL_TRUE

    if f.type == INT:
        if isinstance(raw, bool):
            return int(raw)
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            raise ConfigError(f"{f.label} 必须是整数，当前为：{raw!r}")

    if f.type == FLOAT:
        try:
            return float(str(raw).strip())
        except (TypeError, ValueError):
            raise ConfigError(f"{f.label} 必须是数字，当前为：{raw!r}")

    if f.type == KV:
        if isinstance(raw, dict):
            # 统一成 str→str，避免 JSON 里混入非字符串
            return {str(k): ("" if v is None else str(v)) for k, v in raw.items() if str(k)}
        if isinstance(raw, str):
            out: Dict[str, str] = {}
            for line in raw.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    raise ConfigError(f"{f.label} 每行应为 key=value 格式：{line!r}")
                k, v = line.split("=", 1)
                if k.strip():
                    out[k.strip()] = v.strip()
            return out
        raise ConfigError(f"{f.label} 需要键值对，当前为：{type(raw).__name__}")

    # STR / SECRET / TEXT
    return str(raw)


def validate(f: Field, value: Any) -> None:
    """
    校验已转换的值。不合法时抛 :class:`ConfigError`（消息可直接展示给用户）。
    """
    if f.required and not f.is_secret and (value is None or value == ""):
        raise ConfigError(f"{f.label} 不能为空")

    if f.choices and value not in f.choices:
        raise ConfigError(
            f"{f.label} 只能是以下之一：{', '.join(f.choices)}（当前：{value!r}）"
        )

    if f.type in (INT, FLOAT) and value != "":
        if f.minimum is not None and value < f.minimum:
            raise ConfigError(f"{f.label} 不能小于 {_num(f.minimum)}")
        if f.maximum is not None and value > f.maximum:
            raise ConfigError(f"{f.label} 不能大于 {_num(f.maximum)}")


def _num(v: float) -> str:
    """把 8.0 显示成 8，把 8.5 显示成 8.5"""
    return str(int(v)) if float(v).is_integer() else str(v)


# ── Schema 容器 ─────────────────────────────────────────────


class Schema:
    """一组字段声明的有序集合"""

    def __init__(self, *fields: Field):
        self.fields: List[Field] = []
        self._by_key: Dict[str, Field] = {}
        for f in fields:
            self._add(f)

    def _add(self, f: Field) -> None:
        if f.key in self._by_key:
            # 后声明者覆盖先声明者，便于引擎覆写通用字段的默认值
            self.fields[self.fields.index(self._by_key[f.key])] = f
        else:
            self.fields.append(f)
        self._by_key[f.key] = f

    def extend(self, *others: "Schema") -> "Schema":
        """派生一个新 Schema（不改动自身）"""
        out = Schema(*self.fields)
        for other in others:
            for f in other:
                out._add(f)
        return out

    def __iter__(self):
        return iter(self.fields)

    def __len__(self) -> int:
        return len(self.fields)

    def __contains__(self, key: object) -> bool:
        return key in self._by_key

    def get(self, key: str) -> Optional[Field]:
        return self._by_key.get(key)

    def keys(self) -> List[str]:
        return [f.key for f in self.fields]

    def defaults(self) -> Dict[str, Any]:
        return {f.key: coerce(f, f.default) for f in self.fields}

    def coerce_all(self, raw: Dict[str, Any], *, strict: bool = True) -> Dict[str, Any]:
        """
        按 schema 转换并校验一整份配置。

        Args:
            raw: 原始键值对
            strict: True 时未知键会被保留（不做类型转换），非法值抛异常

        Returns:
            转换后的配置字典（含所有 schema 字段的默认值）
        """
        out = self.defaults()
        for key, value in (raw or {}).items():
            f = self._by_key.get(key)
            if f is None:
                out[key] = value          # 未知键原样保留，便于自定义引擎
                continue
            converted = coerce(f, value)
            validate(f, converted)
            out[key] = converted
        return out


COMMON_SCHEMA = Schema(
    Field("enabled", "启用", BOOL, True,
          help="关闭后按顺序搜索时会跳过该引擎"),
    Field("api_url", "API 地址", STR, "",
          help="留空则使用引擎内置的默认地址",
          placeholder="https://example.com/search"),
    # 注意：api_key 刻意**不放在通用 schema 里** —— 只有真正需要凭据的引擎
    # 才声明它，并且必须写清 env_var。否则 env_var_for() 会派生出一个
    # 与引擎代码里读取的名字不同的变量，凭据就"搬过去但读不到"。
    Field("min_similarity", "最低相似度", INT, 60,
          help="低于此值视为不可信，自动搜索会继续尝试下一个引擎。"
               "⚠️ 各引擎的相似度量纲不同（同一张图 IQDB 报 53%、SauceNAO 报 95%），"
               "默认值已按各引擎校准，通常无需修改",
          minimum=0, maximum=100, unit="%"),
    Field("proxy_mode", "代理", STR, "auto",
          help="auto = 跟随全局设置（不可用时自动直连）；"
               "on = 强制走代理（如 Pixiv / catbox 这类境内不可达的服务）；"
               "off = 强制直连（如 saucenao / iqdb 直连即可）",
          choices=("auto", "on", "off")),
    Field("request_delay", "请求间隔", FLOAT, 8.0,
          help="每次请求后等待，避免触发限流", minimum=0, unit="秒"),
    Field("timeout", "超时", INT, 30,
          help="单次请求超时", minimum=1, unit="秒", advanced=True),
    Field("headers", "自定义请求头", KV, {},
          help="逐行 key=value", advanced=True),
    Field("params", "自定义查询参数", KV, {},
          help="逐行 key=value", advanced=True),
)

RATE_LIMIT_SCHEMA = Schema(
    Field("long_limit", "长期限额", INT, 100,
          help="窗口内最多请求次数；0 = 无限制", minimum=0, unit="次"),
    Field("long_window", "长期窗口", INT, 86400,
          help="默认 86400 秒 = 24 小时；0 = 不做过期清理", minimum=0, unit="秒"),
    Field("short_limit", "短期限额", INT, 4,
          help="0 = 无限制", minimum=0, unit="次"),
    Field("short_window", "短期窗口", INT, 30,
          help="默认 30 秒", minimum=0, unit="秒"),
)


def check_cross_fields(schema: Schema, values: Dict[str, Any]) -> None:
    """
    跨字段一致性校验。

    目前只查一条真实存在的坑：限额 > 0 但窗口 = 0 时，
    请求次数会永久累计，用满之后**永远不会释放**。

    只在该引擎的 schema **确实声明了这两个字段**时才检查 ——
    否则会拿旧配置里遗留的、该引擎根本用不到的键去误伤无关的编辑
    （例如 ascii2d 没有限流逻辑，却因旧版存下的 long_limit/long_window
     组合被拒绝保存任何修改）。
    """
    if "long_limit" not in schema or "long_window" not in schema:
        return

    limit = values.get("long_limit")
    window = values.get("long_window")
    if isinstance(limit, int) and isinstance(window, int) and limit > 0 and window <= 0:
        raise ConfigError(
            "长期限额大于 0 时，长期窗口必须大于 0\n"
            "（否则次数只增不减，用满后不会自动释放）\n"
            f"当前：限额 {limit} 次，窗口 {window} 秒"
        )
