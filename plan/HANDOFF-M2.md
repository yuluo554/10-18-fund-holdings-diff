# HANDOFF-M2 续接快照

> 用法：新对话以 `/goal 读取 "<项目绝对路径>\plan\HANDOFF-M2.md" 继续完成任务` 启动。
> 库内一律相对路径；绝对路径只出现在用户侧启动命令里。

**上一棒**：M1 数据先行（2026-10-18 完成）
**本棒目标**：M2 抓取与归一（双通道持仓抓取 + GBK 解码 + 字段归一 + 失败隔离 + 指数退避）
**当前状态**：仓库可用，`watch` / `window` / `selftest` 真实可用；配置与 fixtures 已冻结并有双层守门；M2–M5 仍为显式 exit 3。

---

## 一、当前进度 + 证据（M1）

### 已完成

| 项 | 证据位置 | 怎么验的 |
|---|---|---|
| 配置包冻结 + MANIFEST | `data/config/app.json`、`data/config/MANIFEST.json`、`tools/freeze_config.py` | `--check` 逐文件 SHA256；篡改/缺清单/未登记文件/坏配置四类用例（`tests/test_freeze_config.py`） |
| **披露期限法规化** | `data/config/app.json.disclosure_rule`、`src/funddiff/window.py`、`data/README.md §4.2` | 第十八条"季度结束之日起十五个工作日" + 2025/2026 国务院节假日日历（含调休上班日）进配置；7 个季度截止日程序推导；**2026Q4 缺 2027 日历 → `null + unverified`，不猜** |
| 两季合成快照 + 真值 + coverage | `data/fixtures/`（40 文件）、`tools/gen_fixtures.py` | splitmix64（seed=20261018）、`--check` 两层（MANIFEST SHA256 + 临时重生成逐字节一致） |
| 覆盖矩阵 | `data/fixtures/truth/coverage.json` | 六维：五态变动 / 四类经理（in_period、prior_period、none、unparsed）/ 三类规模（含真实 `"0.00"` 零申赎）/ 四类基金类型 / 五类异常 / 三态披露；note=抽样覆盖、非穷举 |
| 真值独立复算 | `tests/test_fixtures.py::test_diff_truth_can_be_recomputed_from_inputs` | 由持仓输入用独立规则重算五态 + delta + summary，不调用 diff 引擎；无 `observed_*` 字段（AST 外还做了递归断言） |
| eid 三态 + 历史回放 | `src/funddiff/eid.py`、`src/funddiff/window.py`、CLI `window` | 按季快照优先 → 聚合快照回落 → 缺失 = 无数据；`report_send_date <= as_of` 才算"当时已披露"；`available:false` 快照单独覆盖"无数据"态 |
| selftest 扩容 | `src/funddiff/selftest.py` | 新增 `config.manifest`、`fixtures.manifest` 两道检查（共 10 项） |
| ci_smoke 扩容 | `tools/ci_smoke.py` | 头部加 `freeze_config --check`、`gen_fixtures --check`（共 23 项） |
| 共享冻结逻辑 | `src/funddiff/frozen.py` | SHA256 / manifest 构建 / 校验 / 目录树逐字节比较，工具与 selftest 共用 |

### 本轮实跑过的命令与结论

```
PYTHONPATH=src py -3.12 -X utf8 -m pytest -q   # 128 passed
PYTHONPATH=src py -3.8  -X utf8 -m pytest -q   # 128 passed
py -3.12 -X utf8 tools/ci_smoke.py             # PASS（23 项，含两条 --check）
py -3.12 -X utf8 tools/freeze_config.py --check  # PASS
py -3.12 -X utf8 tools/gen_fixtures.py --check   # PASS
py -3.12 -X utf8 -m funddiff --data-dir data selftest  # 10 项全 PASS
```

### M1 新增门禁的变异验证（8 处全红 → 还原后全绿）

| 变异 | 打红它的测试 |
|---|---|
| `window` 工作日计数 `-=1` → `-=2` | `test_deadlines_follow_workday_rule` |
| `frozen.verify_manifest` SHA256 比对失效 | `test_tampered_config_fails_check` + `test_tampered_fixture_fails_check` |
| `frozen.iter_payload_files` 漏登记 990001 | `test_repo_fixture_manifest_check_passes`（未登记文件必红） |
| `frozen.compare_tree` 恒真 | `test_regeneration_is_byte_identical` / 篡改用例 |
| `eid` 忽略快照 `available:false` | `test_disclosure_snapshots_cover_three_states` |
| `gen_fixtures` 持仓行去排序 | `test_diff_truth_can_be_recomputed_from_inputs` |
| 真值 summary 与 entries 脱钩（同步刷 MANIFEST 模拟"冻结流程照跑"） | 同上（summary 独立复算断言） |
| `selftest` rng 门恒假 / RNG seed 扰动 | `test_selftest_passes_in_repo` / `test_repo_fixture_manifest_check_passes` |

> 教训：变异时"生成器与真值同源"的两侧会被同一处改动同时影响——先想清楚被测门禁守的是**哪一层**
> （生成器内部一致性 vs 真值对输入的独立性），否则会出现假绿。

---

## 二、下一棒待办（M2，按顺序）

1. **`net/http.py`**：超时、重定向、同域串行 + 固定最小间隔、指数退避。
   - 参数**全部来自配置** `rate_limit`（K10 同源纪律），代码零硬编码；
   - 命中 `stop_on`（http_429/403/captcha/login_redirect）→ 停止该域名后续请求，落台账，exit 4；
   - 网络库 import **只允许在 `src/funddiff/net/`**（K6，AST 门禁现成）。
2. **`net/eastmoney.py`**：
   - JSON 通道 `FundMNInverstPosition`（GPDM/GPJC/JZBL/PCTNVCHGTYPE/PCTNVCHG/INDEXNAME）优先；
   - 页面通道 `jjcc`（GBK + 内嵌 JS `var apidata={content:"…"}` 正则）回落；**回落必须留痕** `fallback_reason`；
   - GBK 严格解码，失败保存原始字节 + `error_kind=decode_error`，**禁止 `errors="ignore"`**。
3. **`normalize.py`**：字段归一（去 `%`、全角空格、保留符号；名称只做空白清洗）；`ratio`/`change_pct` 字符串十进制，缺失 `null` ≠ `0`（K3）；`industry` 缺失 → `null`；ETF 联接 → `status=empty + structural_note`。
4. **`fetch` 子命令退役 stub**：`--fund` / `--period` / `--as-of`；单只失败不影响其余（失败隔离）；产物落 `snapshots/`（gitignore，永不入仓）。
5. **fixtures 对齐**：`data/fixtures/q2026q*/holdings/*.json` 的形状就是 M2 归一目标（`funddiff/holdings@1` schema），M2 解析器输出应能与合成快照同形；990006（parse_error）/990007（timeout）是失败路径样本。
6. **收尾**：双解释器全量 pytest + `ci_smoke` + 两条 `--check`；回写 plan/00、05、06、README；写 `plan/HANDOFF-M3.md` → commit。

---

## 三、既定口径清单（K 编号；动了会打挂测试）

见 `plan/HANDOFF-M1.md §三`（K1–K12 全表仍然有效）。M1 新增/强化的口径：

| 编号 | 约定 | 位置 |
|---|---|---|
| K13 | 披露截止日 = 季度结束之日起第 `count` 个工作日（调休上班日计入、法定假日与周末不计）；所需年份日历缺失 → `deadline=null + unverified + unverified_reason=calendar_missing:<year>`，**禁止近似** | `data/config/app.json.disclosure_rule`、`src/funddiff/window.py` |
| K14 | `--as-of` 历史回放：只有 `report_send_date <= as_of` 的记录才算"当时已披露"；发送日缺失按"待披露" | `window.disclosure_status` |
| K15 | 配置与 fixtures 都是冻结产物：MANIFEST 逐文件 SHA256 + 未登记文件必红 + 重生成逐字节一致（两层） | `src/funddiff/frozen.py`、两个 tools |
| K16 | 合成 fixtures 全部 `sample: synthetic`；真值禁 `observed_*`；coverage 每维 `total/sampled` + note=抽样覆盖、非穷举 | `tools/gen_fixtures.py` |

---

## 四、本机环境坑（在 HANDOFF-M1 §四基础上追加）

1. 所有 M1 既有坑继续有效（`py` 而非 `python`、`-X utf8`、3.8 语法底线、`PYTHONPATH=src`、pip 代理、venv 命名、非 editable 必须 `--data-dir`、Git Bash `$TEMP`、变异脚本三段断言）。
2. **`tools/*.py` 的 `--out` / `--data-dir` 传 Windows 路径**：Git Bash 里 `/tmp/...` 会被 MSYS 转换，但 Python 内部拼路径用 `os.path`/`Path` 没问题；测试里断言路径后缀时先 `.replace("\\", "/")`。
3. **变异验证先分层**：同源双写（生成器 ↔ 真值）的字段被同处改动时两侧一起变，假绿；要么只改一侧，要么同步刷 MANIFEST 再验证独立复算层。
4. **pytest 子进程调用**需要完整 `os.environ` 拷贝后再改 `PYTHONPATH`；直接手搓最小 env 会缺 `SYSTEMROOT` 等 Windows 必需变量。

---

## 五、DoD 逐项 checklist（M2）

- [ ] `net/http.py`：限频 + 指数退避 + stop_on，参数全来自配置
- [ ] `net/eastmoney.py`：JSON 优先 / `jjcc` 页面回落，回落留痕
- [ ] GBK 严格解码；失败存原始字节 + `decode_error`
- [ ] `normalize.py`：归一、`null` ≠ `0`、结构差异标注（empty）
- [ ] `fetch` 退役 exit 3，失败隔离（单只失败不影响其余）
- [ ] 双通道一致性夹具（同基金代码集合相等）
- [ ] 限频命中 → exit 4 且已成功结果保留
- [ ] 抓取产物只落 `snapshots/`（gitignore），仓库无真实数据
- [ ] 新增门禁变异验证 ≥3 道
- [ ] 双解释器 pytest 全绿 + `ci_smoke` 全绿 + 两条 `--check` 绿
- [ ] plan/00、05、06、README 状态回写
- [ ] `plan/HANDOFF-M3.md` 落盘并 commit

---

## 六、关键命令速查

```bash
# 测试（双解释器）
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 py -3.8  -X utf8 -m pytest -q
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 py -3.12 -X utf8 -m pytest -q

# 冒烟矩阵（自带 PYTHONPATH，头部含两条 --check）
py -3.12 -X utf8 tools/ci_smoke.py

# 冻结产物校验
py -3.12 -X utf8 tools/freeze_config.py --check
py -3.12 -X utf8 tools/gen_fixtures.py --check

# 真实命令（M1 末态）
py -3.12 -X utf8 -m funddiff --data-dir data selftest
py -3.12 -X utf8 -m funddiff --data-dir data --store local_data/watchlist.json watch add 990001 --name 样例基金甲
py -3.12 -X utf8 -m funddiff --data-dir data --store local_data/watchlist.json window --as-of 2026-10-20 --json

# 改配置/改生成器后的重冻结
py -3.12 -X utf8 tools/freeze_config.py
py -3.12 -X utf8 tools/gen_fixtures.py

# fixtures 输出到临时目录（不污染仓库）
py -3.12 -X utf8 tools/gen_fixtures.py --out <临时目录>

# 安装（干净环境）
py -3.12 -m venv .venv && ./.venv/Scripts/python.exe -m pip install -e ".[dev]"
```

> `local_data/`、`snapshots/`、`out/` 已被 `.gitignore` 隔离；演示与测试一律显式传 `--store` / `--out-dir`。
