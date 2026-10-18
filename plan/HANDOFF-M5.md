# HANDOFF-M5 续接快照

> 用法：新对话以 `/goal 读取 "<项目绝对路径>\plan\HANDOFF-M5.md" 继续完成任务` 启动。
> 库内一律相对路径；绝对路径只出现在用户侧启动命令里。

**上一棒**：M4 经理与规模（2026-10-18 完成）
**本棒目标**：M5 季报与合规门禁（`report` 三产物同源 + 单文件 HTML 零外链 + 合规词表硬门禁 + `run` 一条命令全流程）
**当前状态**：仓库可用，`watch` / `window` / `fetch` / `diff` / `managers` / `scale` / `selftest` 真实可用；配置与 fixtures 已冻结并有双层守门；report / run 仍为显式 exit 3。

---

## 一、当前进度 + 证据（M4）

### 已完成

| 项 | 证据位置 | 怎么验的 |
|---|---|---|
| `jjjl` 页面解析 | `src/funddiff/managers.py::parse_managers_html` | 表头列定位（起始期/截止期/基金经理）+ 日期归一 + 多经理一行拆分；「现任基金经理简介」的「上任日期」按姓名关联（`start`）；解析失败抛 `ManagerParseError` 附页面快照 |
| `change_class` 四类判定 | `managers.classify_change` | 区间由冻结配置 `quarters.*` 推导（本季 `window_for_period`，上季 `previous_period`），不读系统时钟；`in_period / prior_period / none / unparsed`；区间外历史记录不计入（不是 unparsed） |
| `unparsed` 留证不猜 | `managers.unparsed_record` | 附 `snapshot{kind,raw_text,sha256}` + `unparsed_reason`；单行字段坏只 unparsed 该行；与"无变更"（空列表 + `summary.none=1`）严格分开 |
| 产物 `funddiff/managers@1` | `managers.build` | 基金代码升序、记录按 change_date 升序（null 最后）；`totals` 四类计数；`generated_at` 取当天日期，同日双跑字节一致 |
| `gmbd` 六字段解析 | `src/funddiff/scale.py::parse_scale_html` | 表头括号读单位原样记录（万元不换算），申购/净资产单位缺失即解析失败；`0.00` 真实零申赎、破折号/暂无 → null；三个流量字段全缺失 → `baseline=no_prev_baseline` 且金额必须 null |
| 产物 `funddiff/scale@1` | `scale.build` | 六字段 + `units_from_header` + `baseline`；`totals{available,no_prev_baseline,zero_flow}`；同输入双跑字节一致 |
| 真值对齐 | `tests/test_managers.py` / `tests/test_scale.py` | 输出与 `data/fixtures/truth/events_truth.json` 逐条断言（四类经理 + 六字段规模） |
| 退役 stub + 退出码 | `cli.cmd_managers` / `cli.cmd_scale` | `--fund/--period/--json`；产物落 `snapshots/q<period>/managers.json`、`scale.json`；0 成功 / 1 清单空·不在清单·缺事件快照 / 2 报告期非法；台账与配置区间漂移 → 5 |
| K3 延伸门禁 | `scale._validate_scale` | `no_prev_baseline` 时流量字段不得补 0（测试 `test_product_rejects_zero_where_baseline_is_missing`）；单位缺失 → 内部一致性错误 |

### 本轮实跑过的命令与结论

```
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 py -3.8  -X utf8 -m pytest   # 193 passed
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 py -3.12 -X utf8 -m pytest   # 193 passed
py -3.12 -X utf8 tools/ci_smoke.py              # PASS（managers/scale 退役 stub：真实跑 8 只合成基金 + 分类断言 + 0/null 断言 + 退出码矩阵）
py -3.12 -X utf8 tools/freeze_config.py --check  # PASS
py -3.12 -X utf8 tools/gen_fixtures.py --check   # PASS
py -3.12 -X utf8 tools/mutate_diff.py            # PASS（M3 5 处全红）
py -3.12 -X utf8 tools/mutate_events.py          # PASS（M4 5 处全红，还原后 193 全绿）
PYTHONPATH=src py -3.12 -X utf8 -m funddiff --data-dir data selftest  # 10 项全 PASS
```

### M4 新增门禁的变异验证（5 处全红 → 还原后 193 全绿）

复跑入口：`py -3.12 -X utf8 tools/mutate_events.py`（每处变异先 grep 验证命中再跑测试）。

| 变异 | 打红它的测试 |
|---|---|
| `managers.py` 本季内区间硬编码（K10） | `test_cli_managers_runs_and_writes_product` |
| `managers.py` unparsed 快照留证被丢弃 | `test_unparsed_product_entry_carries_snapshot` |
| `managers.py` 区间外历史误标 in_period | `test_parse_prior_period_and_no_change` |
| `scale.py` 缺失补 0（K3） | `test_parse_no_prev_baseline_is_null_not_zero` |
| `scale.py` 单位硬编码不读表头（K10） | `test_units_are_read_not_converted` |

### M4 设计要点（M5 要接住的事实）

- `managers@1` 顶层：`schema/report_period/period_start/period_end/generated_at/funds/totals`；fund 层 `fund_code/fund_name/inputs.events/managers/summary{in_period,prior_period,none,unparsed}`。
- manager 条目字段：`name/start/end/change_date/in_period/change_class/source/raw_text`；unparsed 条目额外有 `snapshot{kind:"page_text",raw_text,sha256}` + `unparsed_reason`。
- `scale@1` fund 层 `scale` 与 events 台账同形（六字段 + baseline + units_from_header + source:"gmbd" + raw_sha256）。
- 事件台账读取统一走 `events.load_events(data_dir, period, code)`（`fixtures/q<period>/events/<code>.json`）+ `events.validate_events`（schema/报告期/代码一致性 → ValueError = exit 5）。
- 报告期起止来自 `window.window_for_period(config, period)` 的 `period_start/period_end`（与 M3 diff 同源）。
- 合规红线已内建：经理字段只有事件主体（姓名/日期/分类），无任何评分/排名/业绩归因键。

---

## 二、下一棒待办（M5，按顺序）

1. **`report.py`**：三产物同源（`report.md` + `report.html` + `report_data.json`，schema `funddiff/report@1`，内存模型一份渲染三份）；页眉口径（diff 口径 + 阈值 + 报告窗口 + as_of）；按基金分组（披露状态 / 变动摘要 / 变动明细 / 经理变更 / 规模变动 / 口径冲突）；`--prev-report` 对比；固定页脚（配置 `compliance.footer`，不可关闭）。
2. **零外链单文件 HTML**：内联 CSS；静态扫描 `<script src` / `<link` / `http(s)://` / `src="//` / 外链 `url(`，0 命中才 exit 0。
3. **合规词表硬门禁**：词表来自冻结配置（唯一来源），扫描 `report.md` 正文 + `report.html` 可见文本 + `report_data.json` 展示字段；归一（大小写 + 全半角 + 空白）；命中 → exit 1 + `文件:行:命中词`；`--check-compliance` 只查不生成；`report` 默认生成后即检查。
4. **`run` 一条命令**：`--as-of`/`--out-dir`；离线全流程（watch 状态 → diff → managers → scale → report）；断网可复现；全程产物双跑字节一致。
5. **零判定渲染 AST 守门**：`report.py` 不 import diff/managers/scale 判定函数、无 `if … status ==` 类分支（plan/03 §6.5；M0 立的规则，M5 落测试）。
6. **收尾**：双解释器全量 pytest + `ci_smoke`（补 report/run 真实跑 + 断网）+ 两条 `--check` + 三份变异脚本；回写 plan/00、05、06、README；写 `plan/HANDOFF-M6.md` → commit。

---

## 三、既定口径清单（K 编号；动了会打挂测试）

见 `plan/HANDOFF-M1.md §三`（K1–K12）、`HANDOFF-M2.md §三`（K13–K16），全部仍有效。M5 特别相关：

| 编号 | 约定 |
|---|---|
| K1 | 所有 JSON 产物走 `serialize.write_json`（单点写盘） |
| K2 | 确定性：同输入双跑字节一致（`serialize.dumps` 排序键；时间戳字段固定格式并单列） |
| K3 | 数值 Decimal 字符串；缺失 `null` ≠ `0` |
| K5 | 退出码：0 成功 / 1 门禁（含合规命中）/ 2 用法 / 3 未就绪 / 4 上游不可用 / 5 内部一致性 |
| K10 | 口径全部来自冻结配置（词表、页脚、阈值、标签），代码零硬编码 |
| — | `report.py` 零判定渲染：判定只来自 model，不得 import 判定函数（plan/03 §6.5，AST 守门） |
| — | 合规：`change_class` 是事件分类不是能力评价；报告字段禁出现评分/排名/业绩归因类键 |

---

## 四、本机环境坑（在 HANDOFF-M1/M2/M3/M4 §四基础上追加）

1. M1–M4 既有坑全部有效（`py` 而非 `python`、`-X utf8`、3.8 语法底线、`PYTHONPATH=src`、非 editable 必须 `--data-dir`）。
2. **Git Bash heredoc 写文件不可靠**：`py - <<'PYEOF'` 写仓库内文件可能静默不生效；本轮用 `py -3.12 -X utf8 - <<'EOF'` 写 README/plan 文档实测**成功**（与 M3 记录的 `py -` 失败不同，稳妥起见大文件写完后仍要 grep 复核）。源码一律用编辑器类工具。
3. README 是 CRLF 行尾：脚本替换模式必须带 `\r\n`（本轮实测，不带会 MISS）。
4. 临时改 fixtures 做实验后必须还原；`gen_fixtures --check` 会逐字节比对重生成。
5. 变异脚本判定"打红"要同时看 returncode 与 stdout/stderr；`tools/mutate_events.py` 是 M4 的可复跑样例（备份目录 + finally 还原）。
6. `snapshots_dir` 相对**当前工作目录**（不是 data_dir）：CLI 冒烟在仓库根跑没问题；测试断言产物路径时用仓库根拼 `snapshots/`。
7. M4 新增测试里 CLI 真实跑会把产物写进仓库 `snapshots/`（gitignore，可留可删）。

---

## 五、DoD 逐项 checklist（M5）

- [ ] `report.py` 三产物同源（一份内存模型渲染 md/html/json）
- [ ] 页眉口径 + 按基金分组六段 + 固定页脚（配置 footer，不可关闭）
- [ ] 单文件 HTML：内联 CSS；零外链扫描 0 命中
- [ ] 合规词表硬门禁：命中 exit 1 + `文件:行:命中词`；`--check-compliance` 只查不生成
- [ ] `run` 一条命令断网全流程；三产物双跑字节一致
- [ ] 零判定渲染 AST 守门测试落地
- [ ] 新增门禁变异验证 ≥3 道（可复跑脚本）
- [ ] 双解释器 pytest 全绿 + `ci_smoke` 全绿（含 report/run 真实跑）+ 两条 `--check` 绿
- [ ] plan/00、05、06、README 状态回写
- [ ] `plan/HANDOFF-M6.md` 落盘并 commit

---

## 六、关键命令速查

```bash
# 测试（双解释器）
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 py -3.8  -X utf8 -m pytest -q
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 py -3.12 -X utf8 -m pytest -q

# 冒烟矩阵（自带 PYTHONPATH，头部含两条 --check）
py -3.12 -X utf8 tools/ci_smoke.py

# 冻结产物校验 / 变异门禁复跑（M3 + M4 两份）
py -3.12 -X utf8 tools/freeze_config.py --check
py -3.12 -X utf8 tools/gen_fixtures.py --check
py -3.12 -X utf8 tools/mutate_diff.py
py -3.12 -X utf8 tools/mutate_events.py

# 真实命令（M4 末态；产物落 ./snapshots/，gitignore）
PYTHONPATH=src py -3.12 -X utf8 -m funddiff --data-dir data selftest
PYTHONPATH=src py -3.12 -X utf8 -m funddiff --data-dir data --store local_data/watchlist.json diff --period 2026Q3 --json
PYTHONPATH=src py -3.12 -X utf8 -m funddiff --data-dir data --store local_data/watchlist.json managers --period 2026Q3 --json
PYTHONPATH=src py -3.12 -X utf8 -m funddiff --data-dir data --store local_data/watchlist.json scale --period 2026Q3 --json

# 改配置/改生成器后的重冻结
py -3.12 -X utf8 tools/freeze_config.py
py -3.12 -X utf8 tools/gen_fixtures.py

# 安装（干净环境）
py -3.12 -m venv .venv && ./.venv/Scripts/python.exe -m pip install -e ".[dev]"
```

> `local_data/`、`snapshots/`、`out/` 已被 `.gitignore` 隔离；演示与测试一律显式传 `--store` / `--out-dir`。
