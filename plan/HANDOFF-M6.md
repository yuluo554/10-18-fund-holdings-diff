# HANDOFF-M6 续接快照（✅ 已收官：M6 完成，2026-10-18）

> **收官说明**：M6 已完成并经验证，项目 M0–M6 全部收官。本文件保留原续接快照内容作历史记录；完成证据见下"收官记录"与 `plan/RELEASE-M6.md`。无后续接力棒。
>
> **收官记录（2026-10-18）**：
> - 仓库：https://github.com/yuluo554/10-18-fund-holdings-diff（公开，署名 yuluo554）
> - CI 首跑全绿：run 39103686550（py3.8/py3.12 × windows/ubuntu 四 job ✓）
> - 三件套：tag `v0.1.0` + Release（附件 funddiff-0.1.0.tar.gz + SHA256SUMS，真下载 sha256 OK）+ `plan/RELEASE-M6.md`（commit `6fec541` 早于 tag，随 tag 进 tag 树）
> - 发布物本体复核：解包树与 tag 树 `diff -r` 为空；中立目录新 venv 内 selftest 10 项 / 双 --check / 双解释器 219 passed / ci_smoke 全绿
> - 干净 clone + 新 venv 四矩阵：219 passed（3.8）/ 219 passed（3.12）/ ci_smoke PASS / 双 --check PASS
> - 脱敏：本机路径/密钥/临时产物 0 命中；署名统一 yuluo554
> - 版本定版：0.1.0.dev0 → 0.1.0（`pyproject.toml` + `src/funddiff/__init__.py`，四处一致）

> 用法：新对话以 `/goal 读取 "<项目绝对路径>\plan\HANDOFF-M6.md" 继续完成任务`。
> 库内一律相对路径；绝对路径只出现在用户侧启动命令里。

**上一棒**：M5 季报与合规门禁（2026-10-18 完成）
**本棒目标**：M6 发布（GitHub 公开仓库 + tag + Release 三件套 + 发布留档 + 干净 clone 复跑 + 脱敏）
**当前状态**：仓库功能面全部完成——九个子命令（watch/window/fetch/diff/managers/scale/report/run/selftest）真实可用，stub 全退役；配置与 fixtures 冻结双层守门；三份变异脚本全红验证可复跑。

---

## 一、当前进度 + 证据（M5）

### 已完成

| 项 | 证据位置 | 怎么验的 |
|---|---|---|
| 三产物同源 | `src/funddiff/report.py`（零判定渲染）+ `src/funddiff/presentation.py`（组装） | `presentation.assemble` 组装一份 `funddiff/report@1` 内存模型 → `build_report_products` 渲染 report.md / report.html / report_data.json；测试断言 JSON 里的每个数字在 md/html 里都能找到 |
| 页眉口径 + 六段 + 页脚 | `presentation.assemble` / `report.render_*` | 页眉：diff 口径 + 阈值 + 报告窗口 + as_of + 抓取时间戳；按基金六段（披露状态/变动摘要/变动明细/经理变更/规模变动/口径冲突）；页脚来自冻结配置 `compliance.footer`（变异验证改空即红） |
| 零外链单文件 HTML | `report.py::scan_external_links` | 6 形态（`<script src`/`<link`/`http://`/`https://`/`src="//`/`url(`）扫描 0 命中才 exit 0；CSS 内联；测试逐形态命中断言 |
| 合规词表硬门禁 | `compliance.py`（M0 已有）+ `cli.cmd_report` 接线 | 词表唯一来源=冻结配置（测试断言源码零硬编码词）；`report` 生成后即检查；`--check-compliance` 只查不生成；命中 exit 1 + `文件:行:命中词` |
| `run` 一条命令 | `cli.cmd_run` | watch 状态 → diff → managers → scale → report 全离线；中间产物 + 三报告写同一目录；测试把传输层打死（`_urllib_transport` 抛 AssertionError）仍成功 |
| 零判定渲染 AST 守门 | `tests/test_report.py::TestZeroJudgmentRendering` | report.py 禁 import diff/managers/scale/presentation；禁 `if … status ==` 类比较分支；渲染层不出现 SECTION_ 分派 |
| 确定性 | `tests/test_report.py` 双跑字节一致 | report 三产物 + run 六文件同输入双跑 read_bytes 相等 |
| 上期报告对比 | `--prev-report` | 读上期 `report_data.json`；schema/报告期校验（同报告期/非上一报告期 → exit 1）；逐基金 `prev_report_note`（新增基金/无变动/分态变化） |

### 本轮实跑过的命令与结论

```
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 py -3.8  -X utf8 -m pytest   # 219 passed
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 py -3.12 -X utf8 -m pytest   # 219 passed
py -3.12 -X utf8 tools/ci_smoke.py              # PASS（report/run 真实跑 + 退出码矩阵 + 产物断言）
py -3.12 -X utf8 tools/freeze_config.py --check  # PASS
py -3.12 -X utf8 tools/gen_fixtures.py --check   # PASS
py -3.12 -X utf8 tools/mutate_diff.py            # PASS（M3 5 处全红）
py -3.12 -X utf8 tools/mutate_events.py          # PASS（M4 5 处全红）
py -3.12 -X utf8 tools/mutate_report.py          # PASS（M5 5 处全红，还原后 219 全绿）
PYTHONPATH=src py -3.12 -X utf8 -m funddiff --data-dir data selftest  # 10 项全 PASS
```

### M5 变异验证（`py -3.12 -X utf8 tools/mutate_report.py`，5 处全红）

| 变异 | 打红它的测试 |
|---|---|
| `presentation.py` 页脚改空（K10 违反） | `test_footer_disabled_does_not_remove_it` |
| `presentation.py` insufficient_data 段被绕过（与空仓混淆） | `test_failed_quarters_get_insufficient_section_not_empty` |
| `report.py` 零外链扫描器掏空（http:// 不命中） | `test_scanner_catches_each_forbidden_pattern`（经 run 产物断言传导） |
| `report.py` import 判定模块（零判定渲染破坏） | `test_report_py_does_not_import_judgment_modules` |

### M5 设计要点（M6 发布须知）

- `report.py` 与 `presentation.py` 分层是刻意的：**判定只在 presentation**，report 只消费 label/rows/hits；改报告样式不要把 diff/managers/scale import 进 report.py（AST 测试会打挂）。
- `report_data.json` 顶层：`schema/meta{diff_mode,threshold,report_period,period_start,period_end,as_of,fetched_at,data_notes,generated_fields}/funds[{fund_code,name,disclosure,sections,prev_report_note}]/totals{funds,disclosed,pending,no_data,changes}/compliance/footer`。
- section 形状：`{title, rows[[cell...]], notes[]}`；insufficient_data 基金的「变动明细」段是一行 `insufficient_data` 说明，不与空仓混淆。
- `--out-dir` 缺省落 `snapshots/q<period>/`（gitignore）；显式传则用 `paths.resolve_out_dir`。
- `run` 不做 fetch（离线契约）；入口校验只有清单空/快照缺失门禁。
- `report --as-of` 缺省取 `window.today_iso()`（同日双跑稳定）。

---

## 二、下一棒待办（M6，按 plan/05 §M6 与 HANDOFF-M5 §五执行）

1. **脱敏四步 + 提交面扫描**：按 plan/05 M6 清单（本机路径/署名/密钥/临时目录）；`git status` 干净再建仓。
2. **干净 clone + 新 venv**：`py -3.12 -m venv .venv && ./.venv/Scripts/python.exe -m pip install -e ".[dev]"`；按 README 快速开始逐条跑通（含 `--data-dir` 显式路径）；四矩阵（双解释器 pytest + ci_smoke + 两条 --check）。
3. **GitHub 公开仓库（署名 `yuluo554`）**：建仓 → 首推 → CI 首跑全绿（M0 的 workflow 在有远端后才真正验证）。
4. **发布三件套（缺一即未达成）**：① git tag；② GitHub Release 附产物（≥1 个手工上传附件，本地留副本 + sha256 可复验）；③ `plan/RELEASE-M6.md` 发布留档（**必须在 tag 之前落盘进 tag 树**）。
5. **发布物本体复核**：真下载 Release 附件 + 中立目录解包复跑基准。
6. **收尾**：plan/00、05、06 状态回写 M6 完成；HANDOFF-M6 更新或收官说明；commit。

---

## 三、既定口径清单（K 编号；动了会打挂测试）

见 `plan/HANDOFF-M1.md §三`（K1–K12）、`HANDOFF-M2.md §三`（K13–K16），全部仍有效。M5 特别相关：

| 编号 | 约定 |
|---|---|
| K1 | 所有 JSON 产物走 `serialize.write_json`/`write_text`（单点写盘） |
| K2 | 确定性：同输入双跑字节一致（三产物 + run 六文件已入测试） |
| K3 | 数值 Decimal 字符串；缺失 `null` ≠ 0（报告里显示 `null` 字面量） |
| K5 | 退出码：0 成功 / 1 门禁（含合规、零外链命中）/ 2 用法 / 3 未就绪（已无未退役命令）/ 4 上游不可用 / 5 内部一致性 |
| K10 | 口径全部来自冻结配置（词表、页脚、阈值、标签、来源标注），代码零硬编码 |
| — | `report.py` 零判定渲染：判定只在 presentation，AST 守门测试已落地 |

---

## 四、本机环境坑（在 HANDOFF-M1–M5 §四基础上追加）

1. M1–M5 既有坑全部有效（`py` 而非 `python`、`-X utf8`、3.8 语法底线、`PYTHONPATH=src`、非 editable 必须 `--data-dir`）。
2. **`snapshots_dir`/`resolve_out_dir` 相对当前工作目录**：跑完 CLI 若在仓库根产生 `snapshots/`、`out/`、`local_data/`，提交前 `rm -rf local_data snapshots out`（全部 gitignore，但干净面好看）；ci_smoke 会把 `local_data` 污染判 FAIL。
3. **`--prev-report` 校验顺序**：文件缺失 → schema → 同报告期 → 与上一报告期一致，四道都是 exit 1；测试"伪造 2026Q2 上期报告"的做法是复制现产物后改 `meta.report_period`。
4. `pytest -q` 尾行截断统计：确认计数用 `pytest 2>&1 | grep passed`。
5. 变异脚本判定"打红"要同时看 returncode 与 stdout/stderr；`tools/mutate_report.py` 是 M5 的可复跑样例（备份目录 + finally 还原）。
6. README 是 CRLF 行尾；plan/00 也是。批量替换脚本要同时尝试 `\n` 与 `\r\n` 模式并断言命中。

---

## 五、DoD 逐项 checklist（M6）

- [ ] 脱敏四步 + 提交面扫描通过
- [ ] 干净 clone + 新 venv 按 README 逐条跑通（含 `--data-dir`）
- [ ] 四矩阵全绿（双解释器 pytest / ci_smoke / 两条 --check）
- [ ] GitHub 公开仓库建立（署名 `yuluo554`），CI 首跑全绿
- [ ] `plan/RELEASE-M6.md` 在 tag 之前落盘
- [ ] git tag + GitHub Release（手工附件 + sha256 复验）
- [ ] 发布物本体复核（真下载 + 中立目录复跑基准）
- [ ] plan/00、05、06 状态回写；commit

---

## 六、关键命令速查

```bash
# 测试（双解释器）
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 py -3.8  -X utf8 -m pytest -q
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 py -3.12 -X utf8 -m pytest -q

# 冒烟矩阵 / 冻结校验 / 变异门禁（三份）
py -3.12 -X utf8 tools/ci_smoke.py
py -3.12 -X utf8 tools/freeze_config.py --check
py -3.12 -X utf8 tools/gen_fixtures.py --check
py -3.12 -X utf8 tools/mutate_diff.py
py -3.12 -X utf8 tools/mutate_events.py
py -3.12 -X utf8 tools/mutate_report.py

# 真实命令（M5 末态）
PYTHONPATH=src py -3.12 -X utf8 -m funddiff --data-dir data selftest
PYTHONPATH=src py -3.12 -X utf8 -m funddiff --data-dir data --store local_data/w.json watch add 990001 --name 样例稳健股票
PYTHONPATH=src py -3.12 -X utf8 -m funddiff --data-dir data --store local_data/w.json run --as-of 2026-10-18 --out-dir out/rep
PYTHONPATH=src py -3.12 -X utf8 -m funddiff --data-dir data --store local_data/w.json report --period 2026Q3 --check-compliance
PYTHONPATH=src py -3.12 -X utf8 -m funddiff --data-dir data --store local_data/w.json report --period 2026Q3 --prev-report out/rep --out-dir out/rep2

# 安装（干净环境，M6 复跑用）
py -3.12 -m venv .venv && ./.venv/Scripts/python.exe -m pip install -e ".[dev]"
```

> `local_data/`、`snapshots/`、`out/` 已被 `.gitignore` 隔离；演示与测试一律显式传 `--store` / `--out-dir`。
