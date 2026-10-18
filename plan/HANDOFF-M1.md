# HANDOFF-M1 续接快照

> 用法：新对话以 `/goal 读取 "<项目绝对路径>\plan\HANDOFF-M1.md" 继续完成任务` 启动。
> 库内一律相对路径；绝对路径只出现在用户侧启动命令里。

**上一棒**：M0 骨架与契约（2026-10-18 完成）
**本棒目标**：M1 数据先行（冻结配置包 + 合成两季快照 + 真值 + coverage + eid 接入）
**当前状态**：仓库可用，`watch` / `window` / `selftest` 三条命令真实可用；M2–M5 为显式 exit 3。

---

## 一、当前进度 + 证据

### 已完成

| 项 | 证据位置 | 怎么验的 |
|---|---|---|
| 包结构与入口 | `pyproject.toml`、`src/funddiff/__init__.py`、`__main__.py` | `python -m funddiff --help`、`funddiff --version` 两条通路都实跑 |
| 退出码契约 0/1/2/3/4/5 | `src/funddiff/cli.py` 顶部常量；`tests/test_cli.py` | 逐码参数化断言；`tools/ci_smoke.py` 18 项矩阵 |
| 确定性写盘单点 | `src/funddiff/serialize.py` | `tests/test_serialize.py`：排序/中文不转义/LF 结尾/无 CR/无临时文件残留/覆盖写 |
| 配置加载与校验 | `src/funddiff/config.py`、`data/config/app.json` | `tests/test_config.py`：缺键/非法 mode/空词表/缺页脚/坏 JSON 全部报错 |
| 自选清单（幂等） | `src/funddiff/store.py` | `tests/test_store.py`：重复添加 1 条、升序、remove 谓词、非法代码、损坏文件 |
| 报告窗口与三态 | `src/funddiff/window.py`、`src/funddiff/eid.py` | `tests/test_window.py`：季度边界、跨年截止日、`--as-of` 不读系统时钟（today 打桩成炸弹）、三态 |
| 合规扫描器 | `src/funddiff/compliance.py` | `tests/test_compliance.py`：阴性/阳性对照、全半角、空白折叠、行号定位 |
| 自检可证伪 | `src/funddiff/selftest.py` | 数据目录不可用 → exit 2（`tests/test_cli.py::test_selftest_fails_when_data_dir_broken`，冒烟里也有一条）；`store.no_side_effects` 当轮抓出"只读也写盘"缺陷 |
| 桩哨兵扫描 | `tests/test_sentinels.py` | 扫 src/tools/tests 无 `NotImple…` / `TODO: 实现` / `place…`；骨架期用 `errors.NotReady` 表达"未落地" |
| 零网络门禁 | `tests/test_no_network.py` | AST 扫描 + 相对导入形态 + 注入自证；**变异验证：往 `selftest.py` 插 `import urllib.request` → 必红** |
| README 指令面门禁 | `tests/test_readme_gate.py` | README 出现未注册命令 → 红（已变异验证）；注册表未写进 README → 红 |
| CLI 冒烟矩阵 | `tools/ci_smoke.py` | 18 项 + 1 项"数据目录损坏 selftest 必须非零"全绿 |
| CI workflow | `.github/workflows/ci.yml` | **未推送 = 未跑过 CI**（诚实口径） |
| 安装面实测 | — | editable 安装：仓库根 `funddiff selftest` 与 `python -m funddiff selftest` 都 exit 0；非 editable 安装到仓库外：无 `--data-dir` → exit 1 并给出明确提示，带 `--data-dir` → exit 0 |
| 计划文档 | `plan/02`–`06` | 已落盘并回写 `plan/00` |

### 本轮实跑过的命令与结论

```
py -3.12 -X utf8 -m pytest -q          # 全绿（77 项）
py -3.8  -X utf8 -m pytest -q          # 全绿（同一套测试，3.8 语法兼容）
py -3.12 -X utf8 tools/ci_smoke.py     # PASS (0 failure)
```

测试分布（收集数，随实现增长，不写死为承诺）：cli 21 / compliance 7 / config 9 /
no_network 5 / readme_gate 8 / sentinels 5 / serialize 7 / store 16 / window 23。

### 自检当场抓到的真实缺陷（保留作纪律样本）

`store.list_all()` 原来写成 `return self.save(self.load())["funds"]`——**只读操作也会写盘并建目录**。
这个缺陷被新加的 `selftest` 检查 `store.no_side_effects` 当轮抓红（读一个不存在的嵌套路径后，
文件被创建了），已修为"只读不写 + 返回副本"，并补两条测试：
`test_list_all_does_not_write` / `test_list_all_returns_copy`。

> 教训：**"看一眼清单"必须零副作用**；`selftest` 的价值就在于它会去干用户会干的事（这里只是读）。

变异验证（6 道门逐个弄坏 → 全部变红 → 还原后全绿）：

| 变异 | 打红它的测试 |
|---|---|
| `serialize` 的 `ensure_ascii` 改 `True` | `test_serialize.py` |
| stub 的 `EXIT_NOT_READY` 改 `0` | `test_cli.py` |
| README 加一条不存在的子命令 | `test_readme_gate.py` |
| `store` 幂等分支改成 `if True` | `test_store.py` + `test_cli.py` |
| `window` 季度边界 `>=` 改 `>` | `test_window.py` |
| `config` 删掉 mode 校验 | `test_config.py` |
| `compliance` 命中判断改 `if False` | `test_compliance.py` |
| 非 net 模块注入 `import urllib.request` | `test_no_network.py` |

> 变异脚本一次性执行（未入仓）；如需复跑，按上表逐条手改 + pytest 即可。

---

## 二、下一棒待办（M1，按顺序）

1. **冻结配置包**
   - `data/config/app.json` 已存在（M0 雏形）。M1 需补：来源注册表是否缺项、`rate_limit` 参数是否够用、`diff.threshold` 取值定稿。
   - 写 `tools/freeze_config.py`：生成 `data/config/MANIFEST.json`（逐文件 sha256 + `config_version`）；`--check` 重算比对，不符 exit 1。
   - 纪律：配置是冻结产物，禁手改；改配置必须重生成。

2. **按法规原文核对季度披露期限**
   - 现状：Q1/Q2/Q4 标 `unverified: true`（`data/config/app.json`）。
   - 需查《公开募集证券投资基金信息披露管理办法》原文，把"工作日起算方式"写成配置值；核对不到就保持 `unverified` 并在 README 说明（**不许猜**）。
   - 三处同步：配置 / `data/README.md §4.2` / `plan/01` 引用处。

3. **合成两季快照生成器**
   - `tools/gen_fixtures.py`：splitmix64 自研 RNG、固定 seed、禁 stdlib `random`/set 迭代序/系统时钟。
   - 产出 `data/fixtures/q2026q2/`、`q2026q3/`、`truth/`（见 `plan/04 §2.2`）。
   - 覆盖矩阵（`plan/04 §2.1`）：五态变动 / 四类经理 / 三类规模 / 四类结构差异 / 五类异常。
   - `--check` 位级一致（两层：冻结产物形态 + 重生成比对）。

4. **eid 元数据接入**
   - 离线快照优先（`data/fixtures/disclosure.json` 已有骨架）；M1 可把快照扩到覆盖三类状态。
   - 在线抓取放 M2 的 `net/csrc.py`；M1 若要接，只允许"抓一次 → 冻结成合成结构"的方式，**不把真实响应提交**。

5. **收尾**
   - 双解释器全量 pytest + `ci_smoke` + `freeze_config --check` + `gen_fixtures --check`。
   - 回写 `plan/00` 台账与里程碑、`plan/05` DoD、`plan/06` 证据列。
   - 写 `plan/HANDOFF-M2.md` → commit。

---

## 三、既定口径清单（K 编号；动了会打挂测试）

| 编号 | 约定 | 位置 |
|---|---|---|
| K1 | `serialize.write_json` 是唯一写盘出口；`sort_keys` + `ensure_ascii=False` + `indent=2` + LF + 结尾换行 + 原子替换 | `src/funddiff/serialize.py` |
| K2 | 产物不含生成时间戳；必须有时只允许 `YYYY-MM-DDTHH:MM:SSZ` 并单列 | `plan/03 §六` |
| K3 | 数值型台账字段用字符串十进制（`Decimal` 入内存）；`null` ≠ `0` | `plan/03 §1` |
| K4 | 业务逻辑不读系统时钟；`--as-of` 决定窗口 | `src/funddiff/window.py` |
| K5 | 退出码 0/1/2/3/4/5 语义 | `src/funddiff/cli.py`、README 命令表 |
| K6 | 网络 import 只允许出现在 `funddiff/net/` | `tests/test_no_network.py` |
| K7 | 配置必须显式给 `diff.mode`（`provider`/`computed`），无缺省推断 | `src/funddiff/config.py` |
| K8 | 台账排序：基金代码 → 本季占比降序 → 股票代码 | `data/config/app.json.ordering` |
| K9 | 五态闭合 + `待确认` 计数，无第六态 | `plan/03 §四` |
| K10 | 合规词表只在配置中定义，代码零硬编码 | `data/config/app.json.compliance` |
| K11 | 报告零判定：判定在 model，渲染只消费 | `plan/03 §6.5`（M5 落 AST 守门） |
| K12 | HTML 零外链（含 `//` 协议相对） | `plan/03 §6.4`（M5 落扫描） |

**配置包本身就是口径**：`data/config/app.json` 的所有数值（阈值 / 间隔 / 次数 / 词表）在 M1 冻结后，代码与测试一律引用，不得复制。

---

## 四、本机环境坑（只写实测过的）

1. **用 `py` 不用 `python`**（后者可能是商店占位符）。中文输出一律 `py -X utf8`。本机有两通道：3.8.8 / 3.12.10，pytest 分别是 7.4.4 / 8.4.2。
2. **3.8 语法底线**：不用 `dict | dict`、`list[int]`、`Path.write_text(newline=)`。当前代码已按 3.8 写，测试双解释器全绿。
3. **`python -m pytest` 需要 `PYTHONPATH=src`**（未安装时）；`python -m funddiff` 同理。`tools/ci_smoke.py` 自己加 `PYTHONPATH`，无需外部设置。
4. **pip 可能被系统代理污染**：装包用 `NO_PROXY="*" no_proxy="*" ... -i https://pypi.tuna.tsinghua.edu.cn/simple`（本轮实测可用）。
5. **venv 建在仓库内会被 `.gitignore` 的 `.venv/` 命中**；本轮探测用的是 `.venv-probe*`（用完已删）。若下次再建，用完立刻删，或建在仓库外临时目录。
6. **非 editable 安装实测结论**：`pip install <repo>` 后从仓库外运行，必须 `--data-dir`；不加时所有子命令（含 `selftest`）返回 **2** 并提示"请用 --data-dir 指向仓库的 data/ 目录"。`selftest` 的 1 只留给"检查跑了但结论不达标"，与"没跑起来"严格区分。
7. **Git Bash 中 `$TEMP` 可用**；仓库内临时脚本用工作区相对路径更稳。
8. **变异脚本注意**：`str.replace` 锚点必须 assert 存在、替换后 assert 字节已变、还原后 assert 字节一致——本轮已按此写，三次静默 no-op 都会让"测试仍绿"看起来像假门。

---

## 五、DoD 逐项 checklist（M1）

- [ ] `data/config/app.json` 冻结，字段齐全且经用户/法规核对；Q1/Q2/Q4 的 `unverified` 已按原文处理
- [ ] `tools/freeze_config.py` 存在，`--check` 位级一致；MANIFEST 含逐文件 sha256 + config_version
- [ ] `tools/gen_fixtures.py` 存在，固定 seed，两次运行逐字节一致；`--check` 绿
- [ ] 两季快照 + 真值 + coverage 落盘，`sample: synthetic` 标注齐备
- [ ] 覆盖矩阵：五态变动 / 四类经理 / 三类规模 / 四类结构差异 / 五类异常 各 ≥1
- [ ] 真值库无 `observed_*` 字段；期望值可由输入独立复算
- [ ] `window` 三态在 `--as-of` 历史日期下与快照一致
- [ ] 双解释器（3.8 / 3.12）全量 pytest 全绿
- [ ] `tools/ci_smoke.py` 全绿
- [ ] 新增门禁做过变异验证
- [ ] `plan/00`、`plan/05`、`plan/06` 状态回写
- [ ] `plan/HANDOFF-M2.md` 已落盘并 commit

---

## 六、关键命令速查

```bash
# 测试（双解释器）
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 py -3.8  -X utf8 -m pytest -q
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 py -3.12 -X utf8 -m pytest -q

# 冒烟矩阵（自带 PYTHONPATH）
py -3.12 -X utf8 tools/ci_smoke.py

# 真实命令（骨架期）
py -3.12 -X utf8 -m funddiff --help
py -3.12 -X utf8 -m funddiff --data-dir data selftest
py -3.12 -X utf8 -m funddiff --data-dir data --store local_data/watchlist.json watch add 990001 --name 样例甲
py -3.12 -X utf8 -m funddiff --data-dir data --store local_data/watchlist.json window --as-of 2026-10-18

# M1 将新增
py -3.12 -X utf8 tools/freeze_config.py --check
py -3.12 -X utf8 tools/gen_fixtures.py --check

# 安装（干净环境）
py -3.12 -m venv .venv && ./.venv/Scripts/python.exe -m pip install -e ".[dev]"
```

> `local_data/` 与 `out/` 已被 `.gitignore` 隔离；演示与测试一律显式传 `--store` / `--out-dir`，避免污染开发者本机。
