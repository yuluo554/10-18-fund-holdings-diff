"""桩哨兵扫描：骨架期不许留下"看着做了其实没做"的痕迹。

扫描面：src / tools / tests。
被扫的三类标记在源码里以**运行时拼接**形式构造，避免扫描器自身成为命中源。
骨架期用 `errors.NotReady`（CLI 映射为退出码 3）表达"未落地"，它是显式契约，不是哨兵。

第四类（静态面，D2 加固）不扫文本而扫语法树：src/**/*.py 里任何被读取却从未在
可见作用域绑定的名字都算缺陷——`cmd_stub` 引用未定义的 `STUB_STAGES` 就是被这一层抓住的。
"""

import ast
import builtins
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("src", "tools", "tests")
SELF = Path(__file__).resolve()

SENTINELS = (
    "NotImple" + "mentedError",
    "TO" + "DO: 实现",
    "place" + "holder",
)


def iter_files():
    for name in SCAN_DIRS:
        for path in sorted((ROOT / name).rglob("*.py")):
            if path.resolve() == SELF:
                continue
            yield path


def test_scan_surface_is_not_empty():
    assert len(list(iter_files())) >= 12


def test_scanner_has_real_markers():
    assert len(SENTINELS) == 3
    assert all(marker for marker in SENTINELS)


def test_no_sentinel_markers():
    hits = []
    for path in iter_files():
        text = path.read_text(encoding="utf-8")
        for marker in SENTINELS:
            if marker in text:
                hits.append((str(path.relative_to(ROOT)), marker))
    assert not hits, "发现桩哨兵：%s" % hits


def test_not_ready_carries_stage():
    from funddiff.errors import NotReady

    exc = NotReady("某能力", "M2")
    assert exc.stage == "M2"
    assert "M2" in str(exc)


def test_stub_network_modules_use_not_ready():
    import pytest

    from funddiff.errors import NotReady
    from funddiff.net import csrc

    with pytest.raises(NotReady):
        csrc.fetch_public_metadata({})


# ---------- 静态面哨兵（D2 加固）----------
# 上面三类是**文本匹配**，抓不到"引用了模块里不存在的全局名"这类死码：
# 退役期留下的 cmd_stub() 引用从未赋值的 STUB_STAGES，文本面一个哨兵都不命中。
# 这里用 ast 做一层作用域感知扫描：任何 Name(Load) 都必须在
# "内建名 | 模块级绑定 | 逐层外层函数绑定" 里找得到，否则记一处缺陷。


def _arg_names(args):
    names = [arg.arg for arg in getattr(args, "posonlyargs", [])]
    names += [arg.arg for arg in args.args]
    names += [arg.arg for arg in args.kwonlyargs]
    if args.vararg:
        names.append(args.vararg.arg)
    if args.kwarg:
        names.append(args.kwarg.arg)
    return set(names)


def _bindings_in_scope(body):
    """这一层作用域里被绑定过的名字；不进入嵌套函数/类内部（它们的局部量不算外层）。"""
    names = set()
    stack = list(body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
            continue  # 子作用域单独扫
        if isinstance(node, ast.Lambda):
            continue
        if isinstance(node, ast.arguments):
            names.update(_arg_names(node))
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            names.add(node.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            names.update(node.names)
        stack.extend(ast.iter_child_nodes(node))
    return names


def undefined_globals(tree):
    """返回 [(name, lineno), ...]：模块里被读取却从未在任何可见作用域绑定的名字。"""
    module_names = _bindings_in_scope(tree.body)
    module_names |= {"__name__", "__file__", "__doc__", "__package__", "__spec__",
                     "__loader__", "__builtins__", "__path__", "__all__"}
    module_names |= set(dir(builtins))
    problems = []

    def check_exprs(nodes, bound):
        for node in nodes:
            if node is None:
                continue
            scan([node], bound)

    def scan(body, bound):
        stack = list(body)
        while stack:
            node = stack.pop()
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # 装饰器与默认值在外层作用域求值
                check_exprs(list(node.decorator_list) + list(node.args.defaults)
                            + [d for d in node.args.kw_defaults if d is not None], bound)
                inner = bound | _arg_names(node.args) | _bindings_in_scope(node.body)
                scan(node.body, inner)
                continue
            if isinstance(node, ast.Lambda):
                check_exprs(list(node.args.defaults)
                            + [d for d in node.args.kw_defaults if d is not None], bound)
                scan([node.body], bound | _arg_names(node.args))
                continue
            if isinstance(node, ast.ClassDef):
                check_exprs(list(node.decorator_list), bound)
                scan(node.body, bound | {node.name} | _bindings_in_scope(node.body))
                continue
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                if node.id not in bound:
                    problems.append((node.id, node.lineno))
                continue
            stack.extend(ast.iter_child_nodes(node))

    scan(tree.body, module_names)
    return problems


def test_static_sentinel_detects_undefined_global():
    """负控：扫描器必须能抓住 D2 那一类缺陷（否则它只是个装饰）。"""
    tree = ast.parse("LIMIT = 1\n\ndef f():\n    return LIMIT + MISSING_NAME\n")
    assert undefined_globals(tree) == [("MISSING_NAME", 4)]


def test_static_sentinel_accepts_normal_scoping():
    """正控：局部量、参数、闭包、推导式变量、内建名都不得误报。"""
    source = (
        "import os\n"
        "TOP = 1\n"
        "class K:\n"
        "    ATTR = 2\n"
        "    def m(self, x):\n"
        "        return [y for y in range(x)] + [self.ATTR, TOP, len(os.sep)]\n"
        "def outer(a):\n"
        "    def inner(b):\n"
        "        return a + b + TOP\n"
        "    return inner\n"
    )
    assert undefined_globals(ast.parse(source)) == []


def test_no_reference_to_undefined_module_globals():
    """src/**/*.py 里不得引用任何可见作用域都没绑定的名字（cmd_stub/STUB_STAGES 就是这类）。"""
    offenders = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for name, lineno in undefined_globals(tree):
            offenders.append("%s:%d: %s" % (path.relative_to(ROOT), lineno, name))
    assert not offenders, "引用了未定义的名字：%s" % offenders
