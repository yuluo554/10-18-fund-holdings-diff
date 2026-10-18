# RELEASE-M6 发布留档

> 三件套留档（plan/00 §四、plan/06 §五口径）。**分栏纪律**：发布前事实（tag 之前已存在、随 tag 落盘）与发布后事实（tag 之后产生：CI run id / 附件 sha256 / 下载复核）严格分栏；发布后事实以追加提交补记，不改写发布前栏。

**仓库**：https://github.com/yuluo554/10-18-fund-holdings-diff（公开，署名 `yuluo554`）
**tag**：`v0.1.0`（版本以实际能力定：0.1.0 而非 1.0.0，见 plan/06 §五判据；四处一致：`pyproject.toml` / `src/funddiff/__init__.py` / tag 名 / Release 名）
**发布物**：手工源码包 `funddiff-0.1.0.tar.gz`（`git archive` + `gzip -9n`）+ `SHA256SUMS`

---

## 一、发布前事实（tag 前落盘，随 tag 进 tag 树）

### 1.1 脱敏四步 + 提交面扫描（2026-10-18）

| 步骤 | 结果 |
|---|---|
| 本机路径扫描 | `git grep -l "C:\\Users\|D:\\program\|ASUS"`（跟踪文件）= 0 命中 |
| 署名检查 | 提交作者/邮箱唯一：`yuluo554 <282769740+yuluo554@users.noreply.github.com>`；`pyproject.toml` authors = `yuluo554` |
| 密钥/token 扫描 | `git grep -iE "secret\|password\|api[_-]?key"` 跟踪文件 = 0 真实命中（仅测试/冒烟里的局部变量名 `token`） |
| 临时目录产物 | `local_data/`、`snapshots/`、`out/`、`.venv/` 全部 gitignore；干净 clone `git status` 无未跟踪产物 |
| 真实数据红线 | 仓库内持仓/事件一律 `data/fixtures/` 合成快照（seed=20261018，可由生成器逐字节复现）；真实抓取产物不入仓（`data/README.md §ToS`） |

### 1.2 干净 clone + 新 venv 复跑（2026-10-18，中立目录 `$TMPDIR/funddiff-clone`）

- `py -3.12 -m venv .venv && .venv/Scripts/python.exe -m pip install -e ".[dev]"` 成功。
- README 快速开始逐条跑通（显式 `--data-dir data` / `--store` / `--out-dir`）：selftest 10 项全 PASS、watch 增删查幂等、window 三态与 `--as-of` 回放、diff 五态、managers 四类、scale 六字段、`run` 六产物、`report --check-compliance` 0 命中、`--prev-report` 上期对比 exit 0。
- 说明：`fetch` 需真实网络（东财上游），离线演示时用 fixtures 快照做 diff/run 入口数据；`--prev-report` 演示按测试同款做法（复制现产物改 `meta.report_period`）。
- 四矩阵全绿：
  - `py -3.8` pytest：**219 passed**（干净 clone 内）
  - `py -3.12` pytest：**219 passed**（干净 clone 内）
  - `tools/ci_smoke.py`：PASS（0 failure）
  - `freeze_config.py --check` / `gen_fixtures.py --check`：均 PASS

### 1.3 建仓与 CI 首跑

- 建仓：`gh repo create 10-18-fund-holdings-diff --public`（2026-10-18，yuluo554 名下）。
- 首推：`main` → `origin/main`（提交 `8e1f025` M5 末态 + `a47d8d4` 版本定版）。
- **CI 首跑全绿**：run id **39103686550**（4 job：py3.8/py3.12 × windows-latest/ubuntu-22.04 全 ✓）。M0 workflow 此前"未推送 = 未跑过 CI"的诚实口径就此补记。

### 1.4 版本定版

- `0.1.0.dev0` → `0.1.0`（`pyproject.toml` + `src/funddiff/__init__.py`），提交 `a47d8d4`；定版后双解释器 pytest 仍全绿。

---

## 二、发布后事实（tag 后追加，追加提交补记）

### 2.1 tag

- `v0.1.0`（annotated，2026-10-18）：tag 对象指向含 `plan/RELEASE-M6.md` 的提交树（本文件随 tag 落盘）；`git cat-file -t v0.1.0` = tag。版本四处一致：`pyproject.toml` = `__init__.py` = tag 名 = Release 名 = `0.1.0` / `v0.1.0`。

### 2.2 Release 附件与 sha256

- 附件：`funddiff-0.1.0.tar.gz`（git archive `v0.1.0` 树 + `gzip -9n`）、`SHA256SUMS`；本地留副本于 `dist-release/`（gitignore）。
- `funddiff-0.1.0.tar.gz` sha256 = `7b972bf27a80a3db505f1141585986daeacf39bfc9c665ae58456a0e48fce7b5`（170077 字节）；`SHA256SUMS` 与之逐条一致，真下载复核见 §2.3。

### 2.3 发布物本体复核（真下载 + 中立目录解包复跑）✅ 2026-10-18 已执行

- Release 地址：https://github.com/yuluo554/10-18-fund-holdings-diff/releases/tag/v0.1.0
- **真下载**：`gh release download v0.1.0` 至中立目录（`$TMPDIR/rel-verify`）；`sha256sum -c SHA256SUMS` → `funddiff-0.1.0.tar.gz: OK`（sha256 `7b972bf27a80…fce7b5`）。
- **解包树比对**：`git archive v0.1.0` 展开树与解包树 `diff -r` **为空**（TREE-DIFF-EMPTY）。
- **中立目录复跑**（解包树内新建 venv + `pip install -e ".[dev]"`）：
  - `selftest`：10 项全 PASS
  - `freeze_config --check` / `gen_fixtures --check`：均 PASS
  - `py -3.8` pytest：219 passed；`py -3.12` pytest：219 passed
  - `tools/ci_smoke.py`：PASS（0 failure）
- 复核后临时目录已清理；本地附件副本留 `dist-release/`（gitignore，不入仓）。
