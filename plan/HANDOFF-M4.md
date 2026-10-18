# HANDOFF-M4 续接快照

> 用法：新对话以 `/goal 读取 "<项目绝对路径>\plan\HANDOFF-M4.md" 继续完成任务` 启动。
> 库内一律相对路径；绝对路径只出现在用户侧启动命令里。

**上一棒**：M3 Q/Q diff（2026-10-18 完成）
**本棒目标**：M4 经理与规模（`jjjl` 经理变动解析 + "本季内变更"判定 + `gmbd` 规模六字段 + 缺失 ≠ 0）
**当前状态**：仓库可用，`watch` / `window` / `fetch` / `diff` / `selftest` 真实可用；配置与 fixtures 已冻结并有双层守门；managers / scale / report / run 仍为显式 exit 3。

---

## 一、当前进度 + 证据（M3）

### 已完成

| 项 | 证据位置 | 怎么验的 |
|---|---|---|
| `diff.py` 五态状态机 | `src/funddiff/diff.py` | stock_code 主键 Q/Q 对齐；新进/退出/加仓/减仓/不变 + `待确认`；`ratio`/`change_pct` 全程 Decimal（K3）；阈值/标签/排序键全部来自冻结配置（K10），改配置必改行为 |
| 双口径 provider/computed | `diff.diff_fund(mode=…)` | provider 直接采信上游 `PCTNVCHGTYPE`（delta 用 `change_pct`），computed 由两季 ratio 自算；缺省取配置冻结 `diff.mode`，`--mode` 显式覆盖 |
| 冲突清单 | `diff@1` 产物 `conflicts[]` | provider 标识与 computed 结论不一致 → 逐条入清单（fund_code/stock_code/双口径状态与差额/两季 ratio），**不静默合并、不猜谁对**；条目本身保持 computed 结论 |
| 失败季处理 | `diff.diff_fund` | 任一季 `status=failed` → 基金整体 `insufficient_data`、entries 空；与空仓（`ok` + 0 条，如 990003 ETF 联接）严格区分；上季失败 + 本季 ok 有专测 |
| 双季溯源 | 条目级 `source_quarters.prev/cur` + 产物级 `inputs.prev/cur` | 每条变动可回指两季快照文件 |
| 确定性排序 | `diff.sort_entries` | `cur_ratio` 降序（null 最后）→ `stock_code`；键序来自冻结配置 `ordering.ledger`；基金按代码升序；`generated_at` 取当天日期，同日双跑字节一致 |
| `diff` 子命令退役 stub | `src/funddiff/cli.py::cmd_diff` | `--fund`/`--period`/`--mode`/`--json`；产物 `funddiff/diff@1` 落 `snapshots/q<period>/diff.json`；退出码：0 成功 / 1 清单空·不在清单·缺快照 / 2 口径或报告期非法 / 5 配置一致性 |
| 真值对齐 | `tests/test_diff.py` | 输出与 `data/fixtures/truth/diff_truth.json` 八只基金逐条（prev_ratio/cur_ratio/delta/status/basis/summary）断言相等 |

### 本轮实跑过的命令与结论

```
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 py -3.8  -X utf8 -m pytest   # 165 passed
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 py -3.12 -X utf8 -m pytest   # 165 passed
py -3.12 -X utf8 tools/ci_smoke.py              # PASS（diff 退役 stub：真实跑 8 只合成基金 + 空清单/非法口径/非法期用例）
py -3.12 -X utf8 tools/freeze_config.py --check  # PASS
py -3.12 -X utf8 tools/gen_fixtures.py --check   # PASS
py -3.12 -X utf8 tools/mutate_diff.py            # PASS（5 处变异全红，还原后全绿）
PYTHONPATH=src py -3.12 -X utf8 -m funddiff --data-dir data selftest  # 10 项全 PASS
```

### M3 新增门禁的变异验证（5 处全红 → 还原后 165 全绿）

复跑入口：`py -3.12 -X utf8 tools/mutate_diff.py`（每处变异先 grep 验证命中再跑测试）。

| 变异 | 打红它的测试 |
|---|---|
| `diff.py` ratio 缺失当 0（K3 违反） | `test_missing_ratio_is_pending_not_zero` |
| `diff.py` 冲突清单静默跳过 | `test_conflicting_provider_label_goes_to_conflict_list` |
| `diff.py` 失败季不标 insufficient_data | `test_failed_prev_quarter_only_also_insufficient` |
| `diff.py` 排序倒置（null 优先 + 升序） | `test_sorting_is_deterministic_ratio_desc_then_code` |
| `diff.py` 阈值硬编码 0.001（K10 违反） | `test_threshold_comes_from_config_not_code` |

### M3 设计要点（M4 要接住的事实）

- `diff` 产物 schema `funddiff/diff@1`：顶层 `mode/threshold/report_period/prev_period/generated_at/conflicts/funds/totals`；fund 层 `status`（ok | insufficient_data）/ `entries` / `summary` / `inputs`。
- entry 层字段：`stock_code/stock_name/industry/prev_ratio/cur_ratio/delta/status/basis/anomalies/source_quarters`。`status` 取值即配置 `diff.status_labels` + `待确认`；`anomalies` 与 fixtures 覆盖矩阵同名（ratio_null / invalid_stock_code / change_type_missing）。
- 快照读取走 `diff.load_holdings(data_dir, period, code)`（`fixtures/q<period>/holdings/<code>.json`，与 fetch 产物同形）。**M4 读 events fixtures 应仿照此模式**（`q<period>/events/<code>.json`，见 fixtures 树与 `events_truth.json`）。
- 异常条目策略：`insufficient_data`（任一侧 ratio null）→ `待确认`；`invalid_stock_code` 不拦截只标注（`anomalies`）。
- `test_fixtures.py::test_diff_truth_can_be_recomputed_from_inputs` 是 M1 独立复算测试，M3 引擎与它互为反向校验，二者必须同时绿。

---

## 二、下一棒待办（M4，按顺序）

1. **`managers.py`**：解析 `jjjl_{code}.html`（变动一览 + 上任日期）；`change_class` 四类判定（in_period / prior_period / none / unparsed），"本季内"区间来自冻结配置；`unparsed` 必须附页面快照（留证，不猜）。
2. **`scale.py`**：`gmbd` 六字段解析，**单位读表头**（万元/亿万元换算不许拍脑袋）；`0` 申赎 vs `null` 缺失可区分（K3 延伸）；`no_prev_baseline` / `零申赎` 口径齐备。
3. **双口径纪律同 M3**：数据字段缺失一律 null，不补 0、不猜；`unparsed` 与"无变更"分开。
4. **`managers` / `scale` 子命令退役 stub**：`--fund`/`--period`；产物 schema 按 plan/03 台账（`funddiff/managers@1` / `funddiff/scale@1`）；确定性排序（K2）。
5. **真值对齐**：输出与 `data/fixtures/truth/events_truth.json` 逐条对齐（`tests/test_fixtures.py::test_events_truth_matches_inputs` 已有独立复算，引擎做反向校验）。
6. **收尾**：双解释器全量 pytest + `ci_smoke` + 两条 `--check` + `mutate_diff.py`（或 M4 专属变异脚本）；回写 plan/00、05、06、README；写 `plan/HANDOFF-M5.md` → commit。

---

## 三、既定口径清单（K 编号；动了会打挂测试）

见 `plan/HANDOFF-M1.md §三`（K1–K12）、`HANDOFF-M2.md §三`（K13–K16），全部仍有效。M4 特别相关：

| 编号 | 约定 |
|---|---|
| K2 | 确定性：同输入双跑字节一致（`serialize.dumps` 排序键） |
| K3 | 数值字符串十进制（Decimal），缺失 `null` ≠ `0`（规模"0 申赎"与"无数据"必须可区分） |
| K5 | 退出码契约：0 成功 / 1 门禁 / 2 用法 / 3 未就绪 / 4 上游不可用 / 5 内部一致性 |
| K10 | 参数同源纪律：区间/阈值/口径全来自冻结配置，代码零硬编码 |

---

## 四、本机环境坑（在 HANDOFF-M1/M2/M3 §四基础上追加）

1. M1/M2 既有坑全部有效（`py` 而非 `python`、`-X utf8`、3.8 语法底线、`PYTHONPATH=src`、非 editable 必须 `--data-dir`）。
2. **Git Bash heredoc 写文件不可靠**：`py - <<'PYEOF'` 里 `open(path,"w").write(...)` 对仓库内文件可能**静默不生效**（读正常、写丢失）。改源码/文档一律用编辑器类工具；批量替换用 `tools/mutate_diff.py` 这种**落盘脚本 + 命中断言**的方式。README 是 CRLF 行尾，脚本替换时模式里要带 `\r\n`。
3. **临时改 fixtures 做实验后必须 `git checkout --` 还原**，否则 `gen_fixtures --check`、selftest、test_fixtures 全线打红（M3 曾踩：990001.json 留痕 → selftest SHA256 门红）。
4. 变异脚本判定"测试打红"要同时看 returncode 与 stdout/stderr（pytest -q 的 FAILED 摘要在 stdout）。
5. 其余 M1/M2 坑照旧：patch 网络层打模块全局 `funddiff.net.http._urllib_transport`；capsys 先清缓冲；`_APIDATA_RE` 以 `[,}]` 收尾。

---

## 五、DoD 逐项 checklist（M4）

- [ ] `managers.py` `jjjl` 解析（变动一览 + 上任日期），`change_class` 四类判定，区间来自配置
- [ ] `unparsed` 附页面快照，与"无变更"分开
- [ ] `scale.py` `gmbd` 六字段解析，单位读表头；`0` vs `null` 可区分
- [ ] `managers` / `scale` 子命令退役 exit 3，产物 `funddiff/managers@1` / `funddiff/scale@1`
- [ ] 输出与 `data/fixtures/truth/events_truth.json` 逐条对齐
- [ ] 确定性：同输入双跑字节一致
- [ ] 新增门禁变异验证 ≥3 道（可复跑脚本）
- [ ] 双解释器 pytest 全绿 + `ci_smoke` 全绿 + 两条 `--check` 绿
- [ ] plan/00、05、06、README 状态回写
- [ ] `plan/HANDOFF-M5.md` 落盘并 commit

---

## 六、关键命令速查

```bash
# 测试（双解释器）
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 py -3.8  -X utf8 -m pytest -q
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 py -3.12 -X utf8 -m pytest -q

# 冒烟矩阵（自带 PYTHONPATH，头部含两条 --check）
py -3.12 -X utf8 tools/ci_smoke.py

# 冻结产物校验 / M3 变异门禁复跑
py -3.12 -X utf8 tools/freeze_config.py --check
py -3.12 -X utf8 tools/gen_fixtures.py --check
py -3.12 -X utf8 tools/mutate_diff.py

# 真实命令（M3 末态；diff 产物落 ./snapshots/，gitignore）
PYTHONPATH=src py -3.12 -X utf8 -m funddiff --data-dir data selftest
PYTHONPATH=src py -3.12 -X utf8 -m funddiff --data-dir data --store local_data/watchlist.json watch add 990001 --name 样例基金甲
PYTHONPATH=src py -3.12 -X utf8 -m funddiff --data-dir data --store local_data/watchlist.json diff --period 2026Q3 --json
PYTHONPATH=src py -3.12 -X utf8 -m funddiff --data-dir data --store local_data/watchlist.json diff --period 2026Q3 --mode provider

# 改配置/改生成器后的重冻结
py -3.12 -X utf8 tools/freeze_config.py
py -3.12 -X utf8 tools/gen_fixtures.py

# 安装（干净环境）
py -3.12 -m venv .venv && ./.venv/Scripts/python.exe -m pip install -e ".[dev]"
```

> `local_data/`、`snapshots/`、`out/` 已被 `.gitignore` 隔离；演示与测试一律显式传 `--store` / `--out-dir`。
