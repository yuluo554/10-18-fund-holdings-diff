"""发布终态门：tag / 附件 / 树同源 / 包形态 / 脱敏，逐条 PASS/FAIL。

两种模式：

  --mode release（默认）  发布后跑。tag 存在且 annotated、tag 指向当前 HEAD、
                          附件 sha256 与 SHA256SUMS 一致、附件解包树与
                          `git archive <tag>` 逐字节同源、包形态清单、脱敏、工作树干净。
  --mode metadata         CI 与发布前跑。只验"不依赖发布物"的项：
                          版本号单源、MANIFEST 覆盖、发布物不得入仓、脱敏、包内约定。

本仓的发布形态是**手工源码包**（`git archive` + `gzip -9n`，落在 `dist-release/`），
不走 PyPI，所以"包形态"校验的对象就是随 Release 发出的那个 tarball。

退出码：0 全 PASS；1 有 FAIL；2 用法/环境错误（例如不在 git 仓库里）。

`--mutation`：可证伪探针。对每一条检查注入一个"坏世界"，断言该条必红、其余条不变。
探针数必须等于检查数——少了就是有检查没被验证过，直接 FAIL。
"""

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST_RELEASE = ROOT / "dist-release"

REQUIRED_SDIST_PATHS = (
    "MANIFEST.in",
    "README.md",
    "LICENSE",
    "pyproject.toml",
    "data/README.md",
    "src/funddiff/__init__.py",
    "src/funddiff/cli.py",
    "tests/conftest.py",
    "tools/ci_smoke.py",
)

REQUIRED_SDIST_PREFIXES = (
    # 下限取"发布物里实测到的文件数"（git archive v0.1.0：config 2 / fixtures 40 /
    # plan 14 / tests 17 / tools 6）；把门槛设成实测值，删文件即红，加文件不会误报。
    ("data/config", ".json", 2),
    ("data/fixtures", ".json", 40),
    ("plan", ".md", 14),
    ("tests", ".py", 17),
    ("tools", ".py", 6),
)

# 脱敏面：本机绝对路径（必须是**真路径**：目录前缀 + 至少一个实际路径段）、
# 署名机器名出现在路径里、明显的凭据形态。
# 精度很重要：留档里会**记录扫描用的模式串**（例如 `C:\\Users\|...|ASUS`），
# 那种"模式串文档"不是泄漏，不能被打红——所以每条都要求带真实路径段。
#
# 自扫豁免：本文件自己的**正则与样例**天然长得像目标（这正是"守门人"的宿命）。
# 处理方式与 tests/test_sentinels.py 同源——把敏感字面拆成运行时拼接，
# 让源文件里不出现完整形态；样例则从**片段拼装**，不在源码里留真路径。
SANITIZE_RULES = (
    (re.compile(r"[A-Za-z]:\\+Us" + r"ers\\+[A-Za-z0-9._-]+"), "Windows 用户目录绝对路径",
     "见 " + "C:\\Us" + "ers\\alice\\Desktop\\x.py"),
    (re.compile(r"[A-Za-z]:/+Us" + r"ers/+[A-Za-z0-9._-]+"), "Windows 用户目录绝对路径（正斜杠）",
     "见 " + "C:/Us" + "ers/alice/Desktop/x.py"),
    (re.compile(r"[A-Za-z]:\\+[Pp]rog" + r"ram[A-Za-z]*\\+[A-Za-z0-9._-]+"), "本机程序目录绝对路径",
     "见 " + "D:\\pro" + "grams\\zcode\\bin"),
    (re.compile(r"/ho" + r"me/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+"), "Linux 家目录绝对路径",
     "见 " + "/ho" + "me/alice/work/x.py"),
    (re.compile(r"(?:Us" + r"ers|ho" + r"me)[\\/]+AS" + r"US(?:[\\/]|$)"), "本机机器名出现在绝对路径里",
     "见 " + "C:\\Us" + "ers\\AS" + "US\\x.py"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIV" + r"ATE KEY-----"), "私钥",
     "-----BEGIN RSA " + "PRIV" + "ATE KEY-----"),
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}"), "GitHub token",
     "ghp_" + "a" * 24),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key",
     "AKIA" + "Q" * 16),
)

SANITIZE_PATTERNS = tuple((pattern, label) for pattern, label, _sample in SANITIZE_RULES)

TEXT_SUFFIXES = {".py", ".md", ".toml", ".json", ".yml", ".yaml", ".in", ".txt",
                 ".cfg", ".ini", ".sh", ".bat", ".html", ".css", ".js", ""}


class GateError(Exception):
    pass


def git(*args, check=True):
    proc = subprocess.run(["git"] + list(args), cwd=str(ROOT), stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE)
    if check and proc.returncode != 0:
        raise GateError("git %s 失败：%s" % (" ".join(args),
                                            proc.stderr.decode("utf-8", "replace").strip()))
    return proc


def git_text(*args, check=True):
    return git(*args, check=check).stdout.decode("utf-8", "replace")


def tar_entries(payload):
    """tar 字节流 → {路径: sha256}（跳过目录项）。"""
    entries = {}
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            handle = archive.extractfile(member)
            data = handle.read() if handle else b""
            entries[member.name] = hashlib.sha256(data).hexdigest()
    return entries


def normalize(entries, prefix):
    normalized = {}
    for name, digest in entries.items():
        if name == prefix or name.startswith(prefix + "/"):
            normalized[name[len(prefix) + 1:]] = digest
        else:
            normalized[name] = digest
    return normalized


def sha256_file(path):
    digest = hashlib.sha256()
    with open(str(path), "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_version(root):
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    if not match:
        raise GateError("pyproject.toml 里找不到字面量 version")
    init_text = (root / "src" / "funddiff" / "__init__.py").read_text(encoding="utf-8")
    init_match = re.search(r'__version__\s*=\s*"([^"]+)"', init_text)
    if not init_match:
        raise GateError("src/funddiff/__init__.py 里找不到 __version__")
    return match.group(1), init_match.group(1)


# ---------------------------------------------------------------- facts

def collect_facts(root=ROOT, mode="release", tag=None):
    """把检查要用到的事实一次性取齐；checks 只读这个 dict（探针靠改它注入坏世界）。"""
    pyproject_version, dunder_version = read_version(root)
    tag = tag or ("v" + pyproject_version)
    tags = [line.strip() for line in git_text(
        "tag", "--sort=-v:refname", check=False).splitlines() if line.strip()]

    facts = {
        "mode": mode,
        "root": root,
        "version_pyproject": pyproject_version,
        "version_dunder": dunder_version,
        "tag": tag,
        "latest_tag": tags[0] if tags else "",
        "all_tags": tags,
        "tag_type": "",
        "tag_exists": False,
        "tag_ahead_count": None,
        "asset_name": "funddiff-%s.tar.gz" % pyproject_version,
        "asset_exists": False,
        "asset_size": 0,
        "asset_digest": "",
        "sums_exists": False,
        "sums_text": "",
        "sums_digest": "",
        "asset_entries": {},
        "archive_entries": {},
        "manifest_text": "",
        "tracked_files": [],
        "worktree_status": [],
        "sanitize_hits": [],
        "release_artifacts_tracked": [],
    }

    manifest_path = root / "MANIFEST.in"
    if manifest_path.is_file():
        facts["manifest_text"] = manifest_path.read_text(encoding="utf-8")
    facts["tracked_files"] = [line for line in git_text("ls-files").splitlines() if line]
    facts["release_artifacts_tracked"] = [
        name for name in facts["tracked_files"]
        if name.startswith("dist-release/") or name.startswith("dist/")]
    facts["worktree_status"] = [line for line in
                                git_text("status", "--porcelain").splitlines() if line]

    # 脱敏：只扫已跟踪的文本文件（追踪面 = 会随 Release 发出的那一面）
    hits = []
    for name in facts["tracked_files"]:
        if Path(name).suffix.lower() not in TEXT_SUFFIXES:
            continue
        path = root / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pattern, label in SANITIZE_PATTERNS:
            if pattern.search(text):
                hits.append("%s: %s" % (name, label))
    facts["sanitize_hits"] = hits
    facts["sanitize_rules"] = [(label, pattern, sample)
                               for pattern, label, sample in SANITIZE_RULES]

    if mode == "release":
        if git("rev-parse", "--verify", "--quiet", "refs/tags/%s" % tag,
               check=False).returncode == 0:
            facts["tag_exists"] = True
            facts["tag_type"] = git_text("cat-file", "-t", tag).strip()
            ahead = git_text("rev-list", "--count", "%s..HEAD" % tag).strip()
            facts["tag_ahead_count"] = int(ahead or 0)
            payload = git("archive", "--format=tar", tag).stdout
            facts["archive_entries"] = tar_entries(payload)

        asset = DIST_RELEASE / facts["asset_name"]
        sums = DIST_RELEASE / "SHA256SUMS"
        if asset.is_file():
            facts["asset_exists"] = True
            facts["asset_size"] = asset.stat().st_size
            facts["asset_digest"] = sha256_file(asset)
            raw = asset.read_bytes()
            facts["asset_entries"] = normalize(
                tar_entries(raw), "funddiff-%s" % pyproject_version)
        if sums.is_file():
            facts["sums_exists"] = True
            facts["sums_text"] = sums.read_text(encoding="utf-8")
            facts["sums_digest"] = sha256_file(sums)

    return facts


# ---------------------------------------------------------------- checks
# 每条：(名称, 判定函数)。函数入参是 facts，返回 (ok, detail)。
#
# 一条检查只判**一个属性**。当它的前置不成立（例如 tag 不存在时谈不上"是不是
# annotated"），返回 N/A 而**不是**再报一次 FAIL——否则一个坏世界会同时打红两条，
# 变异探针就分不清是谁在守门。整体结论不会因此变绿：前置项自己会红。

def _na(reason):
    return True, "N/A：%s（由前置项负责）" % reason


def check_version_single_source(facts):
    a, b = facts["version_pyproject"], facts["version_dunder"]
    return a == b, "pyproject=%s __version__=%s" % (a, b)


def _version_key(text):
    """把 '0.1.1' / 'v0.1.1' 变成可比较的整数元组；解析不了的段按 0。"""
    text = text[1:] if text.startswith("v") else text
    parts = []
    for chunk in text.split("."):
        digits = re.match(r"\d+", chunk)
        parts.append(int(digits.group(0)) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def check_tag_matches_version(facts):
    """版本号与"最新那个 tag"必须对上：tag 不得比版本号新。

    metadata 模式（发版前的 main）不能要求 tag 已存在——那时版本号本来就领先 tag。
    所以这条只判一件事：**最新 tag 不得比版本号更新**（tag 新而版本旧 = 版本号没跟上）。
    release 模式下 tag 是否存在/是否指向 HEAD 由 TAG_EXISTS / TAG_AT_HEAD 分别判。
    """
    latest = facts.get("latest_tag", "")
    if not latest:
        return _na("仓库里还没有任何 tag")
    ok = _version_key(latest) <= _version_key(facts["version_pyproject"])
    return ok, "最新 tag=%s，版本=%s%s" % (
        latest, facts["version_pyproject"],
        "" if ok else "（tag 比版本新，版本号没跟上）")


def check_tag_exists(facts):
    return bool(facts["tag_exists"]), "refs/tags/%s %s" % (
        facts["tag"], "存在" if facts["tag_exists"] else "不存在")


def check_tag_annotated(facts):
    if not facts["tag_exists"]:
        return _na("tag 不存在")
    kind = facts["tag_type"]
    return kind == "tag", "git cat-file -t %s → %s（annotated 需为 tag）" % (
        facts["tag"], kind or "<无>")


def check_tag_at_head(facts):
    if not facts["tag_exists"]:
        return _na("tag 不存在")
    count = facts["tag_ahead_count"]
    return count == 0, "%s..HEAD 落后 %s 个提交" % (facts["tag"], count)


def check_asset_exists(facts):
    detail = "%s %s（%d B）" % (facts["asset_name"],
                              "存在" if facts["asset_exists"] else "缺失",
                              facts["asset_size"])
    return bool(facts["asset_exists"]) and facts["asset_size"] > 0, detail


def check_sums_exists(facts):
    return bool(facts["sums_exists"]), "SHA256SUMS %s" % (
        "存在" if facts["sums_exists"] else "缺失")


def check_asset_digest_matches_sums(facts):
    if not (facts["asset_exists"] and facts["sums_exists"]):
        return _na("附件或 SHA256SUMS 缺失")
    recorded = None
    for line in facts["sums_text"].splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].lstrip("*") == facts["asset_name"]:
            recorded = parts[0]
            break
    if recorded is None:
        return False, "SHA256SUMS 未登记 %s" % facts["asset_name"]
    return recorded == facts["asset_digest"], "登记=%s 实算=%s" % (
        recorded, facts["asset_digest"])


def check_asset_tree_matches_tag(facts):
    if not facts["tag_exists"]:
        return _na("tag 不存在")
    if not facts["asset_exists"]:
        return _na("附件不存在")
    if not facts["archive_entries"]:
        return False, "tag 树为空（tag 存在但取不到树）"
    if not facts["asset_entries"]:
        return False, "附件解包为空"
    archive = facts["archive_entries"]
    asset = facts["asset_entries"]
    missing = sorted(set(archive) - set(asset))[:5]
    extra = sorted(set(asset) - set(archive))[:5]
    changed = sorted(name for name in set(archive) & set(asset)
                     if archive[name] != asset[name])[:5]
    ok = not (missing or extra or changed)
    return ok, "共 %d 条；missing=%s extra=%s changed=%s" % (
        len(archive), missing, extra, changed)


def check_sdist_shape(facts):
    if not facts["asset_exists"]:
        return _na("附件不存在")
    names = list(facts["asset_entries"])
    missing = [path for path in REQUIRED_SDIST_PATHS if path not in names]
    short = []
    for prefix, suffix, minimum in REQUIRED_SDIST_PREFIXES:
        count = sum(1 for name in names
                    if name.startswith(prefix + "/") and name.endswith(suffix))
        if count < minimum:
            short.append("%s: %d < %d" % (prefix, count, minimum))
    ok = not (missing or short)
    return ok, "缺文件=%s 数量不足=%s" % (missing, short)


def check_manifest_covers_data(facts):
    text = facts["manifest_text"]
    if not text:
        return False, "MANIFEST.in 不存在或为空"
    required = ("recursive-include data/config *.json",
                "recursive-include data/fixtures *.json",
                "recursive-include tests *.py",
                "recursive-include tools *.py",
                "include LICENSE")
    missing = [line for line in required if line not in text]
    return not missing, "MANIFEST.in 缺：%s" % missing


def check_no_release_artifacts_tracked(facts):
    tracked = facts["release_artifacts_tracked"]
    return not tracked, "跟踪面出现发布产物：%s" % tracked


def check_sanitize(facts):
    hits = facts["sanitize_hits"]
    return not hits, "脱敏命中：%s" % hits


def check_sanitize_patterns_live(facts):
    """正则本身必须还活着：每条都能抓住自己的样例。改松正则换绿会在这里变红。"""
    dead = []
    for label, pattern, sample in facts["sanitize_rules"]:
        if not pattern.search(sample):
            dead.append(label)
    return not dead, "抓不住样例的脱敏规则：%s" % dead


def check_worktree_clean(facts):
    status = facts["worktree_status"]
    return not status, "工作树未清理：%s" % status


RELEASE_CHECKS = (
    ("VERSION_SINGLE_SOURCE", check_version_single_source),
    ("TAG_MATCHES_VERSION", check_tag_matches_version),
    ("TAG_EXISTS", check_tag_exists),
    ("TAG_ANNOTATED", check_tag_annotated),
    ("TAG_AT_HEAD", check_tag_at_head),
    ("ASSET_EXISTS", check_asset_exists),
    ("SHA256SUMS_EXISTS", check_sums_exists),
    ("ASSET_DIGEST_MATCHES_SUMS", check_asset_digest_matches_sums),
    ("ASSET_TREE_MATCHES_TAG", check_asset_tree_matches_tag),
    ("SDIST_SHAPE", check_sdist_shape),
    ("MANIFEST_COVERS_DATA", check_manifest_covers_data),
    ("NO_RELEASE_ARTIFACTS_TRACKED", check_no_release_artifacts_tracked),
    ("SANITIZE_TRACKED", check_sanitize),
    ("SANITIZE_RULES_LIVE", check_sanitize_patterns_live),
    ("WORKTREE_CLEAN", check_worktree_clean),
)

METADATA_CHECKS = (
    ("VERSION_SINGLE_SOURCE", check_version_single_source),
    ("TAG_MATCHES_VERSION", check_tag_matches_version),
    ("MANIFEST_COVERS_DATA", check_manifest_covers_data),
    ("NO_RELEASE_ARTIFACTS_TRACKED", check_no_release_artifacts_tracked),
    ("SANITIZE_TRACKED", check_sanitize),
    ("SANITIZE_RULES_LIVE", check_sanitize_patterns_live),
)


def run_checks(facts, checks):
    results = []
    for name, func in checks:
        try:
            ok, detail = func(facts)
        except Exception as exc:            # 探针/坏世界导致的异常也算 FAIL
            ok, detail = False, "%s: %s" % (type(exc).__name__, exc)
        results.append((name, bool(ok), detail))
    return results


# ---------------------------------------------------------------- mutation

def _fake_tar(entries):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, payload in entries.items():
            info = tarfile.TarInfo(name)
            data = payload.encode("utf-8")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return {name: hashlib.sha256(payload.encode("utf-8")).hexdigest()
            for name, payload in entries.items()}


def _mutation_specs(facts):
    """每条检查一个"坏世界"：{检查名: (facts 修改函数, 期望被打红的检查名)}。

    坏世界都在内存里构造，不动仓库、不写盘、不联网。
    """
    def break_version(f):
        f = dict(f)
        f["version_dunder"] = "9.9.9"
        return f

    def break_tag_name(f):
        # 坏世界：最新 tag 比版本号新（版本号没跟上）
        f = dict(f)
        f["latest_tag"] = "v9.9.9"
        return f

    def break_tag_missing(f):
        f = dict(f)
        f["tag_exists"] = False
        f["tag_type"] = ""
        return f

    def break_tag_lightweight(f):
        f = dict(f)
        f["tag_type"] = "commit"
        return f

    def break_tag_behind(f):
        f = dict(f)
        f["tag_ahead_count"] = 1
        return f

    def break_asset_missing(f):
        f = dict(f)
        f["asset_exists"] = False
        f["asset_size"] = 0
        f["asset_digest"] = ""
        f["asset_entries"] = {}
        return f

    def break_sums_missing(f):
        f = dict(f)
        f["sums_exists"] = False
        f["sums_text"] = ""
        return f

    def break_digest(f):
        f = dict(f)
        f["asset_digest"] = "0" * 64
        recorded = f["asset_name"]
        f["sums_text"] = "%s  %s\n" % ("1" * 64, recorded)
        return f

    def break_tree(f):
        f = dict(f)
        entries = dict(f["asset_entries"])
        if entries:
            victim = sorted(entries)[0]
            entries[victim] = "0" * 64
        f["asset_entries"] = entries
        return f

    def break_shape(f):
        # 坏世界：打出来的包里根本没有 fixtures（同时把 tag 侧也对齐，
        # 这样只有"形态"该红，"树同源"保持绿）
        f = dict(f)
        for key in ("asset_entries", "archive_entries"):
            entries = dict(f[key])
            for name in list(entries):
                if name.startswith("data/fixtures/"):
                    del entries[name]
            f[key] = entries
        return f

    def break_manifest(f):
        f = dict(f)
        f["manifest_text"] = f["manifest_text"].replace(
            "recursive-include data/fixtures *.json\n", "")
        return f

    def break_artifacts(f):
        f = dict(f)
        f["release_artifacts_tracked"] = ["dist-release/funddiff-0.0.0.tar.gz"]
        return f

    def break_sanitize(f):
        f = dict(f)
        f["sanitize_hits"] = ["README.md: 本机机器名"]
        return f

    def break_sanitize_rules(f):
        # 把一条规则改松（永远不命中），其余保持——只有"规则还活着"这一条该红
        f = dict(f)
        rules = list(f["sanitize_rules"])
        label, _pattern, sample = rules[0]
        rules[0] = (label, re.compile(r"(?!x)x"), sample)   # 永不匹配
        f["sanitize_rules"] = rules
        return f

    def break_worktree(f):
        f = dict(f)
        f["worktree_status"] = [" M src/funddiff/cli.py"]
        return f

    return {
        "VERSION_SINGLE_SOURCE": break_version,
        "TAG_MATCHES_VERSION": break_tag_name,
        "TAG_EXISTS": break_tag_missing,
        "TAG_ANNOTATED": break_tag_lightweight,
        "TAG_AT_HEAD": break_tag_behind,
        "ASSET_EXISTS": break_asset_missing,
        "SHA256SUMS_EXISTS": break_sums_missing,
        "ASSET_DIGEST_MATCHES_SUMS": break_digest,
        "ASSET_TREE_MATCHES_TAG": break_tree,
        "SDIST_SHAPE": break_shape,
        "MANIFEST_COVERS_DATA": break_manifest,
        "NO_RELEASE_ARTIFACTS_TRACKED": break_artifacts,
        "SANITIZE_TRACKED": break_sanitize,
        "SANITIZE_RULES_LIVE": break_sanitize_rules,
        "WORKTREE_CLEAN": break_worktree,
    }


def _synthetic_facts():
    """给探针用的干净世界：所有检查都应当 PASS（不依赖真实 tag/附件）。"""
    files = {
        "MANIFEST.in": "x",
        "README.md": "x",
        "LICENSE": "x",
        "pyproject.toml": "x",
        "data/README.md": "x",
        "src/funddiff/__init__.py": "x",
        "src/funddiff/cli.py": "x",
        "tests/conftest.py": "x",
        "tools/ci_smoke.py": "x",
    }
    for index in range(3):
        files["data/config/c%d.json" % index] = "x"
    for index in range(48):
        files["data/fixtures/f%d.json" % index] = "x"
    for index in range(15):
        files["plan/p%d.md" % index] = "x"
    for index in range(17):
        files["tests/t%d.py" % index] = "x"
    for index in range(7):
        files["tools/t%d.py" % index] = "x"
    digest_map = _fake_tar(files)
    return {
        "mode": "release",
        "root": ROOT,
        "version_pyproject": "1.2.3",
        "version_dunder": "1.2.3",
        "tag": "v1.2.3",
        "latest_tag": "v1.2.3",
        "all_tags": ["v1.2.3"],
        "tag_type": "tag",
        "tag_exists": True,
        "tag_ahead_count": 0,
        "asset_name": "funddiff-1.2.3.tar.gz",
        "asset_exists": True,
        "asset_size": 123456,
        "asset_digest": "a" * 64,
        "sums_exists": True,
        "sums_text": "%s *funddiff-1.2.3.tar.gz\n" % ("a" * 64),
        "sums_digest": "b" * 64,
        "asset_entries": dict(digest_map),
        "archive_entries": dict(digest_map),
        "manifest_text": (
            "include README.md\ninclude LICENSE\ninclude MANIFEST.in\n"
            "recursive-include data/config *.json\n"
            "recursive-include data/fixtures *.json\n"
            "recursive-include plan *.md\n"
            "recursive-include src/funddiff *.py\n"
            "recursive-include tests *.py\n"
            "recursive-include tools *.py\n"),
        "tracked_files": sorted(files),
        "worktree_status": [],
        "sanitize_hits": [],
        "sanitize_rules": [(label, pattern, sample)
                           for pattern, label, sample in SANITIZE_RULES],
        "release_artifacts_tracked": [],
    }


def mutation_probe():
    """对每条检查注入坏世界，断言：该条必红，其余条保持原色。"""
    checks = RELEASE_CHECKS
    base = _synthetic_facts()
    baseline = run_checks(base, checks)
    baseline_failures = [name for name, ok, _ in baseline if not ok]
    if baseline_failures:
        print("[FAIL] 合成干净世界本身不干净：%s" % baseline_failures)
        return 1

    specs = _mutation_specs(base)
    covered = set(specs)
    expected_names = {name for name, _ in checks}
    uncovered = sorted(expected_names - covered)
    if uncovered:
        print("[FAIL] 以下检查没有变异探针（=没被验证过）：%s" % uncovered)
        return 1

    failures = 0
    for name, _func in checks:
        mutate = specs[name]
        broken = mutate(dict(base))
        results = run_checks(broken, checks)
        reds = [entry for entry in results if not entry[1]]
        red_names = [entry[0] for entry in reds]
        if red_names == [name]:
            print("[ok] probe %-28s → 恰好 %s 变红" % (name, name))
        else:
            print("[FAIL] probe %-26s → 变红集合=%s（期望仅 %s）" % (name, red_names, name))
            failures += 1

    print("check_release: mutation %d/%d probe(s) red exactly once; %d failure(s)" % (
        len(checks) - failures, len(checks), failures))
    return 0 if failures == 0 else 1


# ---------------------------------------------------------------- main

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="check_release.py",
        description="发布终态门：tag / 附件 / 树同源 / 包形态 / 脱敏（逐条 PASS/FAIL）")
    parser.add_argument("--mode", choices=("release", "metadata"), default="release",
                        help="release=验已发布产物（默认）；metadata=只验不依赖发布物的项")
    parser.add_argument("--tag", default=None, help="覆盖 tag 名（默认 v<pyproject version>）")
    parser.add_argument("--mutation", action="store_true",
                        help="跑可证伪探针：每条检查注入坏世界，必红且只红它自己")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出检查结果")
    args = parser.parse_args(argv)

    if args.mutation:
        return mutation_probe()

    try:
        if git("rev-parse", "--is-inside-work-tree", check=False).returncode != 0:
            raise GateError("不在 git 工作树内，无法校验 tag/树同源")
        facts = collect_facts(ROOT, mode=args.mode, tag=args.tag)
    except GateError as exc:
        print("[FAIL] %s" % exc)
        return 2

    checks = METADATA_CHECKS if args.mode == "metadata" else RELEASE_CHECKS
    results = run_checks(facts, checks)

    if args.json:
        print(json.dumps({
            "mode": args.mode,
            "tag": facts["tag"],
            "checks": [{"name": name, "ok": ok, "detail": detail}
                       for name, ok, detail in results],
            "failed": sum(1 for _, ok, _ in results if not ok),
        }, ensure_ascii=False, indent=2))
    else:
        for name, ok, detail in results:
            print("[%s] %-28s %s" % ("PASS" if ok else "FAIL", name, detail))

    failed = sum(1 for _, ok, _ in results if not ok)
    print("check_release: %s (mode=%s, tag=%s, %d/%d PASS, %d FAIL)" % (
        "PASS" if failed == 0 else "FAIL", args.mode, facts["tag"],
        len(results) - failed, len(results), failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
