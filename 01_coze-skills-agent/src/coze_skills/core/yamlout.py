"""确定性 YAML 1.2 序列化 (仅标准库, 不引入 PyYAML 运行时依赖).

为什么自己写而不是 ``yaml.dump``:
1. 插件网关跑在最小镜像里, 为一份导出文件多拖一个第三方包不划算;
2. ``yaml.dump`` 的键序、别名锚点 (``&id001``) 和多行折叠策略随版本漂移,
   而这份文件要**进 git diff**、要被 CI 逐字节比对 —— 只有自研才能保证稳定;
3. 所有字符串一律走 ``json.dumps`` 的双引号标量形态: JSON 字符串是合法的
   YAML 双引号标量, 因此冒号、井号、中文、换行、前导空格都不需要额外斟酌转义规则.

配套的往返校验 (``yaml.safe_load(to_yaml(doc)) == doc``) 放在
``tests/test_openapi_yaml.py`` 里用 PyYAML 做 —— 开发期借第三方验证, 运行期零依赖.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

#: 导出文件头注释: 声明来源与"请勿手改" (YAML 注释不影响解析)
DEFAULT_HEADER = "# coze_skills 自动生成 —— 源头是 ToolSpec 注册表, 请勿手工编辑"


def _scalar(value: Any) -> str:
    """把标量渲染成 YAML 文本 (数字/布尔/null 裸写, 字符串一律 JSON 双引号).

    :param value: ``None`` / ``bool`` / ``int`` / ``float`` / ``str``.
    :returns: 标量文本.
    :raises TypeError: 传入非 JSON 标量类型 (说明调用方塞进了不可序列化对象).
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    raise TypeError(f"无法序列化为 YAML 标量: {type(value).__name__}")


#: 空容器的行内写法 (YAML flow 形态, 避免下一层缩进产生歧义)
EMPTY_MAPPING = "{}"
EMPTY_SEQUENCE = "[]"

#: 可以裸写 (不加引号) 的键名形态: 字母开头、仅含 YAML 安全字符.
#: 注意刻意排除了数字开头 ("/tools/..." 与 "200" 这类键由 json 排序后自然落到引号分支),
#: 因为裸写 ``200:`` 会被解析成整数键, 破坏 ``safe_load(round_trip) == doc`` 这一硬约束.
_PLAIN_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.\-/]*$")

#: 虽然形态安全、但会被 YAML 做类型解析的词 (布尔/空值别名).
_RESERVED_PLAIN = frozenset({"true", "false", "null", "yes", "no", "on", "off", "y", "n"})


def _key(value: str) -> str:
    """渲染映射键: 安全形态裸写, 其余走 JSON 双引号.

    :param value: 键名.
    :returns: 可紧跟 ``:`` 的键文本.
    """
    if _PLAIN_KEY_RE.match(value) and value.lower() not in _RESERVED_PLAIN:
        return value
    return json.dumps(value, ensure_ascii=False)


def _dump(value: Any, indent: int) -> List[str]:
    """递归产出行列表.

    :param value: 任意 JSON 形态数据.
    :param indent: 当前缩进空格数.
    :returns: 已带缩进、未带结尾换行的行列表.
    """
    pad = " " * indent
    if isinstance(value, dict):
        rows: List[str] = []
        for key, sub in value.items():
            label = _key(str(key))
            if isinstance(sub, dict) and not sub:
                rows.append(f"{pad}{label}: {EMPTY_MAPPING}")
            elif isinstance(sub, list) and not sub:
                rows.append(f"{pad}{label}: {EMPTY_SEQUENCE}")
            elif isinstance(sub, (dict, list)):
                rows.append(f"{pad}{label}:")
                rows.extend(_dump(sub, indent + 2))
            else:
                rows.append(f"{pad}{label}: {_scalar(sub)}")
        return rows
    if isinstance(value, list):
        rows = []
        for item in value:
            if isinstance(item, dict) and not item:
                rows.append(f"{pad}- {EMPTY_MAPPING}")
            elif isinstance(item, list) and not item:
                rows.append(f"{pad}- {EMPTY_SEQUENCE}")
            elif isinstance(item, (dict, list)):
                block = _dump(item, indent + 2)
                # 首个子行折进列表短横线, 保持 YAML 块序列的标准缩进形态
                rows.append(f"{pad}- {block[0][indent + 2:]}")
                rows.extend(block[1:])
            else:
                rows.append(f"{pad}- {_scalar(item)}")
        return rows
    return [f"{pad}{_scalar(value)}"]


def to_yaml(document: Any, *, header: str = DEFAULT_HEADER) -> str:
    """把 JSON 形态的文档序列化为确定性 YAML 文本.

    :param document: dict / list / 标量 (OpenAPI 文档就是 dict).
    :param header: 文件头注释; 传空串则不输出注释.
    :returns: 以换行结尾的 YAML 文本; 相同输入永远得到相同字节序列.
    """
    lines = _dump(document, 0)
    if header:
        lines = [header] + lines
    return "\n".join(lines) + "\n"


def sorted_document(doc: Dict[str, Any]) -> Dict[str, Any]:
    """按键名字典序归一化文档, 让 YAML 与 ``json.dumps(sort_keys=True)`` 同源可 diff.

    :param doc: 任意 JSON 形态 dict.
    :returns: 经 JSON 往返后的新 dict (所有层级键按字典序排列).
    """
    return json.loads(json.dumps(doc, sort_keys=True))
