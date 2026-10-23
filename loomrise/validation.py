# -*- coding: utf-8 -*-
"""保存前校验（纯函数，R1 配置器直接复用）。

**第九条：条件深度 ≤ 2 层。** 超过两层就没人能一眼看出这个条件在说什么，
配错了也测不出来——所以它是保存前的硬校验，不是代码风格建议。

三条口径：

1. **`llm` 叶不计层**。模型判据本身就是"让模型看着办"，把它算成一层会让
   所有带模型判据的条件凭空超限，于是大家只好把阈值调到 3 层。
2. **硬规则的 `when` 与路由边的 `condition` 共用同一套算子**。
   两套算子的结果是"同一个概念有两种写法"，配置器就得为它们各写一遍校验。
3. **能确定的在这里确定**：深度可算、结构可判。语义是否正确不归这里管。

本模块只做校验，不改任何配置，也不依赖 `contracts` 之外的东西。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

#: 允许的最大嵌套层数。改这个数等于改合同，必须同步文档。
MAX_CONDITION_DEPTH = 2

#: 组合算子。`not` 只接受单个子条件，`all`/`any` 接受列表。
COMPOSITE_KEYS = ("all", "any", "not")

#: 叶子算子的键名（任一出现即视为叶子，深度 1）。
LEAF_KEYS = ("field", "arg", "path")

#: 模型判据的键名。不计层。
LLM_KEYS = ("llm", "llm_judge")


@dataclass
class ConditionIssue:
    path: str
    depth: int
    message: str

    def __str__(self) -> str:  # pragma: no cover - 只为报错可读
        return f"{self.path}: {self.message}（实际 {self.depth} 层）"


def is_llm_leaf(node: Any) -> bool:
    return isinstance(node, dict) and any(k in node for k in LLM_KEYS)


def _composite_ops(node: Any) -> int:
    """组合算子的嵌套个数；纯叶子为 0，空或纯 `llm` 为 -1（不构成条件层）。

    "层"数的是**组合算子的嵌套**，不是节点的个数：`all:[A, B]` 是 1 层，
    `all:[A, any:[B, C]]` 才是 2 层。叶子与它所在的组合算同一层。
    """
    if not isinstance(node, dict) or not node:
        return -1
    if is_llm_leaf(node):
        return -1
    if any(k in node for k in COMPOSITE_KEYS):
        children: list[Any] = []
        for key in COMPOSITE_KEYS:
            if key not in node:
                continue
            value = node[key]
            children.extend(value if isinstance(value, list) else [value])
        return 1 + max((_composite_ops(c) for c in children), default=-1)
    return 0


def condition_depth(node: Any) -> int:
    """返回条件树的最大条件层数。

    空条件与纯 `llm` 叶返回 0：它们不构成一层确定性判断。
    """
    if not isinstance(node, dict) or not node:
        return 0
    if is_llm_leaf(node):
        return 0
    return max(1, _composite_ops(node))


def validate_condition_depth(
    conditions: Iterable[tuple[str, Any]],
    *,
    max_depth: int = MAX_CONDITION_DEPTH,
) -> list[ConditionIssue]:
    """逐条校验条件深度。返回空列表表示全部通过。

    `conditions` 是 `(路径标签, 条件树)` 的可迭代对象；路径只用于报错定位，
    调用方用 `rule_id` / `edge_id` 之类即可。
    """
    issues: list[ConditionIssue] = []
    for path, node in conditions:
        depth = condition_depth(node)
        if depth > max_depth:
            issues.append(
                ConditionIssue(
                    path=path,
                    depth=depth,
                    message=f"条件嵌套超过 {max_depth} 层",
                ),
            )
        elif _has_unknown_shape(node):
            issues.append(
                ConditionIssue(
                    path=path,
                    depth=depth,
                    message="条件结构无法识别（既不是组合算子也不是叶子算子）",
                ),
            )
    return issues


def _has_unknown_shape(node: Any) -> bool:
    """递归找出结构不合法的节点。空字典视为合法（无条件）。"""
    if not isinstance(node, dict):
        return False
    if not node:
        return False
    if is_llm_leaf(node):
        return False
    if any(k in node for k in COMPOSITE_KEYS):
        for key in COMPOSITE_KEYS:
            if key not in node:
                continue
            value = node[key]
            children = value if isinstance(value, list) else [value]
            if key == "not" and isinstance(value, list) and len(value) != 1:
                return True
            if any(_has_unknown_shape(c) for c in children):
                return True
        return False
    return not any(k in node for k in LEAF_KEYS)


def rule_conditions(rules: Iterable[Any]) -> list[tuple[str, Any]]:
    """把硬规则的 `when_arg_equals` 转成条件树，供深度校验。

    `when_arg_equals` 是平铺的"字段→值"，本身永远 1 层；转换的意义在于
    **它和路由边共用同一个校验入口**，未来换成嵌套 `when` 时不用改调用方。
    """
    out: list[tuple[str, Any]] = []
    for rule in rules:
        when = getattr(rule, "when_arg_equals", None) or {}
        if not when:
            continue
        tree = {"all": [{"arg": k, "equals": v} for k, v in when.items()]}
        out.append((getattr(rule, "rule_id", "?"), tree))
    return out


__all__ = [
    "MAX_CONDITION_DEPTH",
    "COMPOSITE_KEYS",
    "LEAF_KEYS",
    "LLM_KEYS",
    "ConditionIssue",
    "condition_depth",
    "validate_condition_depth",
    "rule_conditions",
    "is_llm_leaf",
]
