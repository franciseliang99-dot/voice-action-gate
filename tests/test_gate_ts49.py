"""TS-49 — turn A23's one-off census into a gate.

A23 (design_v3.md)普查了「还有没有别的解码器跑在 `canonicalize_text` 之前」并据此
论证 B-32 的一支已关闭.  A23.4 自己写明那**只是一次测量,不是一道闸**:

    「把 `_is_readable_digit_run` 改回 `isdecimal()`,本节的每个字仍然为真,
      而洞已经开了。」
    「明天加一个 decoder,这份结论对它**结构上不可见**。」

本文件就是那道闸.

────────────────────────────────────────────────────────────────────────────
期望值的来源(★ 这一节是本文件的承重墙)
────────────────────────────────────────────────────────────────────────────
下面每一个 `EXPECTED_*` 常量都**转录自设计文档**,不是从 `gate/` grep 出来的:

  * `EXPECTED_DECODER_CENSUS`      ← A23.2 第 1 行「一共有几个 decoder? **4 个,
                                     全在 `normalize.py`**」+ A23.2 各行逐个点名的
                                     `decode_span` / `decode_argument` /
                                     `decode_number_span` / `decode_currency_span`
  * `EXPECTED_ENTRY_POINTS`        ← A23.2 第 2 行「谁调它们? `decode_span` ←
                                     `witness.py`(转录侧)· `decode_argument` ←
                                     `decision.py`(提案侧)」
  * `EXPECTED_NUMBER_GROUNDERS`    ← A23.2 第 4 行「哪个 decoder 会 ground 出一个数?
                                     **只有 `decode_number_span`**」
  * `EXPECTED_INT_CALL_SITES`      ← A23.2 第 5 行「`decode_number_span` 里有几处
                                     `int()`? **恰好 1 处**」
  * `EXPECTED_GUARD_CALLS`         ← A23.2 第 5 行的逐字守卫
                                     `if len(tokens) == 1 and _is_readable_digit_run(tokens[0]):`
                                     (A24.6 更正后的名字;A24.1 的锚
                                      `if len(tokens) == 1 and _is_readable_digit_run` 与之一致)

⇒ **判别句:如果 `gate/` 今天是错的,本文件应当把它判红。** 期望值先写死,再跑。

────────────────────────────────────────────────────────────────────────────
TI-1(本项目既有纪律)
────────────────────────────────────────────────────────────────────────────
每一条断言都是「对一个**机械枚举出的投影**做**集合/列表相等**」,绝不是
「某某不在里面」.  非成员断言对**新增**的成员天然瞎 —— 明天多一个 decoder,
`assertNotIn` 照样绿.  故:

  * 普查的**总体是整个 `gate/*.py` 目录**(A23.1 的谓词),不是 `normalize.py` 一份 ——
    在别的文件里新开一个 decoder,本文件必须红;
  * 入口点、会 ground 出数的 decoder、`int()` 调用点,三者都做**全集相等**;
  * 总体塌成空(路径写错 / 目录搬家)时,集合相等会与非空期望值对不上 ⇒ 红,
    不会静默报绿。
"""

from __future__ import annotations

import ast
import os
import unittest

# ---------------------------------------------------------------------------
# 总体(A23.1 的谓词:`gate/` 目录下扩展名为 .py 的全部文件)
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_GATE_DIR = os.path.join(_REPO_ROOT, "gate")

#: A23.2 用的枚举谓词:函数名里含 `decode`。
DECODER_NAME_SUBSTRING = "decode"

# ---------------------------------------------------------------------------
# 期望值 —— 逐条转录自设计,见文件头
# ---------------------------------------------------------------------------

EXPECTED_DECODER_CENSUS: frozenset[tuple[str, str]] = frozenset(
    {
        ("normalize.py", "decode_span"),
        ("normalize.py", "decode_argument"),
        ("normalize.py", "decode_number_span"),
        ("normalize.py", "decode_currency_span"),
    }
)

EXPECTED_ENTRY_POINTS: frozenset[str] = frozenset({"decode_span", "decode_argument"})

EXPECTED_NUMBER_GROUNDERS: frozenset[str] = frozenset({"decode_number_span"})

EXPECTED_INT_CALL_SITES = 1

#: `if len(tokens) == 1 and _is_readable_digit_run(tokens[0]):` 里被调用的函数全集。
EXPECTED_GUARD_CALLS: frozenset[str] = frozenset({"len", "_is_readable_digit_run"})

NUMBER_DECODER = "decode_number_span"


# ---------------------------------------------------------------------------
# 机械枚举的原语
# ---------------------------------------------------------------------------


def _gate_sources() -> list[tuple[str, str]]:
    """`gate/` 下全部 `.py` 的 (basename, source)。总体在这里定义,只此一处。"""
    names = sorted(n for n in os.listdir(_GATE_DIR) if n.endswith(".py"))
    out = []
    for name in names:
        with open(os.path.join(_GATE_DIR, name), encoding="utf-8") as fh:
            out.append((name, fh.read()))
    return out


def _functions(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """整棵树里的每一个函数定义(含嵌套 —— 嵌套的 decoder 也是 decoder)。"""
    return [
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _called_names(node: ast.AST) -> set[str]:
    """node 子树里每一个 Call 的被调名(`f()` → 'f',`m.f()` → 'f')。"""
    names: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            fn = n.func
            if isinstance(fn, ast.Name):
                names.add(fn.id)
            elif isinstance(fn, ast.Attribute):
                names.add(fn.attr)
    return names


def _int_calls(node: ast.AST) -> list[ast.Call]:
    """node 子树里全部 `int(...)` 调用点,按源码位置排序(列表,不是集合)。"""
    calls = [
        n
        for n in ast.walk(node)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "int"
    ]
    return sorted(calls, key=lambda c: (c.lineno, c.col_offset))


def _parent_map(root: ast.AST) -> dict[int, ast.AST]:
    parents: dict[int, ast.AST] = {}
    for parent in ast.walk(root):
        for child in ast.iter_child_nodes(parent):
            parents[id(child)] = parent
    return parents


def _enclosing_ifs(node: ast.AST, root: ast.AST) -> list[ast.If]:
    """从最内层往外,node 所处的 `If` 语句链(只算 body/orelse 里的包含关系)。"""
    parents = _parent_map(root)
    chain: list[ast.If] = []
    cur: ast.AST | None = node
    while cur is not None and cur is not root:
        parent = parents.get(id(cur))
        if isinstance(parent, ast.If) and cur is not parent.test:
            chain.append(parent)
        cur = parent
    return chain


class _Fixture:
    """解析一次,给全部用例共用。"""

    sources: list[tuple[str, str]] = []
    trees: dict[str, ast.Module] = {}

    @classmethod
    def load(cls) -> None:
        if cls.sources:
            return
        cls.sources = _gate_sources()
        cls.trees = {
            name: ast.parse(src, filename=name) for name, src in cls.sources
        }


# ---------------------------------------------------------------------------
# TS-49
# ---------------------------------------------------------------------------
# 🔴 **Mutation (M1):** 在 `gate/normalize.py` 里加一个第 5 个 decoder
#   (`def decode_anything_span(...)`)。`test_the_decoder_census_is_exactly_the
#   _declared_set` 必须红 —— 这正是 A23.4 第 1 条说的「明天加一个 decoder」。
# 🔴 **Mutation (M2):** 把 `decode_number_span` 里那道守卫的谓词换成别的名字
#   (例如 `_is_number_shaped_token` 或 `str.isdecimal`)。
#   `test_the_single_int_call_site_is_guarded_by_the_ascii_predicate` 必须红。
# 🔴 **Mutation (M3):** 在 `decode_currency_span` 里加一处 `int(...)`。
#   `test_only_one_decoder_grounds_a_number` 必须红。
#
# ⇒ 三条变异各自打中一条独立的断言;A23 的那三句结论从此各有钉子。
class TestTS49DecoderCensusIsPinned(unittest.TestCase):
    """TS-49 — A23 的普查结论做成集合相等的结构闸。"""

    def setUp(self) -> None:
        _Fixture.load()
        self.assertTrue(
            _Fixture.sources,
            "总体塌成空:在 %r 下没有找到任何 .py。这是【没能检查】,不是【没问题】。"
            % (_GATE_DIR,),
        )

    # -- A23.2 第 1 行 ----------------------------------------------------
    def test_the_decoder_census_is_exactly_the_declared_set(self) -> None:
        """整个 `gate/*.py` 里名字含 `decode` 的函数定义 == 设计声明的那 4 个。

        总体是**整个目录**而不是 `normalize.py` 一份:A23.2 的结论里「全在
        normalize.py」这半句,只有在别处也扫过一遍时才被检验过。
        """
        census = {
            (name, fn.name)
            for name, tree in _Fixture.trees.items()
            for fn in _functions(tree)
            if DECODER_NAME_SUBSTRING in fn.name
        }
        self.assertEqual(
            census,
            set(EXPECTED_DECODER_CENSUS),
            "decoder 普查与设计 A23.2 声明的集合不等。"
            "多出来的:%r;少掉的:%r"
            % (
                sorted(census - set(EXPECTED_DECODER_CENSUS)),
                sorted(set(EXPECTED_DECODER_CENSUS) - census),
            ),
        )

    # -- A23.2 第 2 行 ----------------------------------------------------
    def test_the_entry_points_are_exactly_two(self) -> None:
        """`normalize.py` 之外调到的 decoder 全集 == {decode_span, decode_argument}。

        同样是集合相等:哪天 `witness.py` 直接调 `decode_number_span`(绕过
        `decode_span` 的三级串联,连带绕过它前面的那道闸),本条必须红。
        """
        declared = {fn for _mod, fn in EXPECTED_DECODER_CENSUS}
        observed: set[str] = set()
        for name, tree in _Fixture.trees.items():
            if name == "normalize.py":
                continue
            observed |= _called_names(tree) & declared
        self.assertEqual(
            observed,
            set(EXPECTED_ENTRY_POINTS),
            "跨文件 decoder 入口点与 A23.2 声明的集合不等。"
            "多出来的:%r;少掉的:%r"
            % (
                sorted(observed - set(EXPECTED_ENTRY_POINTS)),
                sorted(set(EXPECTED_ENTRY_POINTS) - observed),
            ),
        )

    # -- A23.2 第 4 行 ----------------------------------------------------
    def test_only_one_decoder_grounds_a_number(self) -> None:
        """会 ground 出一个数(= 函数体里有 `int()`)的 decoder 全集 == {decode_number_span}。"""
        tree = _Fixture.trees["normalize.py"]
        grounders = {
            fn.name
            for fn in _functions(tree)
            if DECODER_NAME_SUBSTRING in fn.name and _int_calls(fn)
        }
        self.assertEqual(
            grounders,
            set(EXPECTED_NUMBER_GROUNDERS),
            "会 ground 出一个数的 decoder 集合与 A23.2 声明不等:%r" % (sorted(grounders),),
        )

    # -- A23.2 第 5 行(上半)---------------------------------------------
    def test_the_number_decoder_has_exactly_one_int_call_site(self) -> None:
        tree = _Fixture.trees["normalize.py"]
        fns = [fn for fn in _functions(tree) if fn.name == NUMBER_DECODER]
        self.assertEqual(
            len(fns), 1, "`%s` 的定义不是恰好一个:%d" % (NUMBER_DECODER, len(fns))
        )
        calls = _int_calls(fns[0])
        self.assertEqual(
            len(calls),
            EXPECTED_INT_CALL_SITES,
            "`%s` 里的 `int()` 调用点数与 A23.2 声明的 %d 不等;实际在第 %r 行"
            % (NUMBER_DECODER, EXPECTED_INT_CALL_SITES, [c.lineno for c in calls]),
        )

    # -- A23.2 第 5 行(下半)---------------------------------------------
    def test_the_single_int_call_site_is_guarded_by_the_ascii_predicate(self) -> None:
        """那唯一一处 `int()` 被 A20.4 的 ASCII 守卫罩着。

        断言的是**最内层那个 `if` 的 test 里被调用的函数全集**与设计逐字写下的
        守卫相等 —— 于是「把谓词换成 `isdecimal()` / 换成宽的那个
        `_is_number_shaped_token` / 干脆把守卫拿掉」三种改法都会红。
        """
        tree = _Fixture.trees["normalize.py"]
        fn = next(f for f in _functions(tree) if f.name == NUMBER_DECODER)
        calls = _int_calls(fn)
        self.assertEqual(
            len(calls),
            EXPECTED_INT_CALL_SITES,
            "前置条件不成立:`int()` 调用点不是 %d 处而是 %d 处"
            % (EXPECTED_INT_CALL_SITES, len(calls)),
        )
        chain = _enclosing_ifs(calls[0], fn)
        self.assertTrue(
            chain,
            "那处 `int()` 根本不在任何 `if` 里 —— A20.4 的守卫不见了。",
        )
        guard = chain[0]
        self.assertEqual(
            _called_names(guard.test),
            set(EXPECTED_GUARD_CALLS),
            "最内层守卫调用的函数全集与 A23.2 逐字写下的 "
            "`if len(tokens) == 1 and _is_readable_digit_run(tokens[0]):` 不等;"
            "实际:%r" % (sorted(_called_names(guard.test)),),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
