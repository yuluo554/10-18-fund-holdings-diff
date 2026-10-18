# HANDOFF-M3 续接快照

> 用法：新对话以 `/goal 读取 "<项目绝对路径>\plan\HANDOFF-M3.md" 继续完成任务` 启动。
> 库内一律相对路径；绝对路径只出现在用户侧启动命令里。

**上一棒**：M2 抓取与归一（2026-10-18 完成）
**本棒目标**：M3 Q/Q diff（五态状态机 + provider/computed 双口径 + 冲突清单 + 双季溯源 + 确定性排序）
**当前状态**：仓库可用，`watch` / `window` / `fetch` / `selftest` 真实可用；配置与 fixtures 已冻结并有双层守门；diff / managers / scale / report / run 仍为显式 exit 3。

---

## 一、当前进度 + 证据（M2）

### 已完成

| 项 | 证据位置 | 怎么验的 |
|---|---|---|
| `net/http.py` 限频 + 指数退避 + stop_on | `src/funddiff/net/http.py` | 同域串行 + `min_interval_seconds`；瞬时失败（timeout/network_error/http_5xx）指数退避、总等待封顶 `max_total_wait_seconds`；429/403/验证码/登录墙命中 → 封锁该域名后续请求；**参数全部来自配置 `rate_limit`（K10），测试 `test_rate_limit_params_all_from_config` 断言改配置必改行为** |
| `net/eastmoney.py` 双通道 | `src/funddiff/net/eastmoney.py` | JSON 通道（`FundMNInverstPosition`，字段 GPDM/GPJC/JZBL/PCTNVCHGTYPE/PCTNVCHG/INDEXNAME）优先；`jjcc` 页面通道（GBK + `var apidata={content:"…"}` 正则）回落，回落必留痕 `source.fallback_reason`；endpoint 全部来自配置 `sources` |
| GBK 严格解码 | `fetch_position_page` | 失败保存原始字节 + `error_kind=decode_error`；无 `errors="ignore"`（变异验证可红） |
| `normalize.py` 归一 | `src/funddiff/normalize.py` | 去 `%`/全角空格/千分位、保留符号；名称只做空白清洗；`ratio`/`change_pct` 字符串十进制、缺失 `null` ≠ `0`（K3）；`industry` 缺失 → null；ETF 联接 → `status=empty + structural_note` |
| `fetch` 子命令退役 stub | `src/funddiff/cli.py::cmd_fetch` | `--fund`/`--period`/`--json`；失败隔离（单只失败不影响其余）；失败落 `snapshots/q<period>/failures.json`；限频命中 exit 4 且已成功结果保留；产物只落 `snapshots/`（gitignore，永不入仓） |
| 双通道一致性夹具 | `tests/test_fetch.py::test_channels_agree_on_same_code_set` | 同一数据两通道解析出的代码集合 + ratio 相等 |
| M2 测试 | `tests/test_fetch.py`（25 项） | 全部假传输注入，零真实外网 |

### 本轮实跑过的命令与结论

```
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 py -3.8  -X utf8 -m pytest   # 152 passed
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 py -3.12 -X utf8 -m pytest   # 152 passed
py -3.12 -X utf8 tools/ci_smoke.py              # PASS（24 项，fetch 空清单用例替代旧 stub）
py -3.12 -X utf8 tools/freeze_config.py --check  # PASS
py -3.12 -X utf8 tools/gen_fixtures.py --check   # PASS
PYTHONPATH=src py -3.12 -X utf8 -m funddiff --data-dir data selftest  # 10 项全 PASS
```

### M2 新增门禁的变异验证（5 处全红 → 还原后 152 全绿）

| 变异 | 打红它的测试 |
|---|---|
| `http.py` 429 不封锁域名 | `test_http_429_blocks_domain_and_subsequent_requests` + `test_fetch_blocked_returns_4_and_keeps_successful_results` |
| `eastmoney.py` 回落不写 `fallback_reason` | `test_page_fallback_leaves_trace`（KeyError） |
| `eastmoney.py` GBK 改 `errors="ignore"` | `test_gbk_strict_decode_failure_keeps_raw_bytes` |
| `normalize.py` ratio 缺失当 `"0"` | `test_missing_is_null_not_zero` |
| `http.py` 同域限频失效 | `test_fetcher_returns_body_and_respects_min_interval` |

### M2 设计要点（M3 要接住的事实）

- `fetch` 产物形状 = `data/fixtures/q<period>/holdings/*.json` 同形（`funddiff/holdings@1`），
  M3 的 diff 引擎**输入即此形状**，可与合成快照直接对齐（990006=parse_error、990007=timeout 是失败路径样本，`rows=[]` 且 `status=failed`，diff 引擎必须处理"上一季失败/本季失败"的组合）。
- `fetch` 输出顶层 schema `funddiff/fetch@1`；`holdings` payload 额外带 `period_end`、`sample: null`（合成快照里是 `"synthetic"`）。
- `normalize.failure_record` 的 `source.error_kind` 只在无 fallback_reason（未发生回落）时写入；回落路径失败时 `source.fallback_reason` 承载 JSON 通道的失败类别。
- `window.py` 新增 `period_end_of(config, period)` / `parse_period(period)` / `today_iso()`；`paths.py` 新增 `snapshots_dir(config=…)`。

---

## 二、下一棒待办（M3，按顺序）

1. **`diff.py` 五态状态机**：新进 / 退出 / 增持 / 减持 / 不变；以 stock_code 为主键做 Q/Q 对齐；
   `ratio`/`change_pct` 用 Decimal（K3：字符串十进制，禁二进制浮点）。
2. **双口径**：`diff.mode = provider | computed`（配置冻结值，`--mode` 可覆盖但必须显式）。
   provider 口径直接吃上游 `PCTNVCHGTYPE`；computed 口径由两季 ratio 自算；
   两口径结论不一致的条目进**冲突清单**（不静默合并、不猜谁对）。
3. **失败季处理**：任一季 `status=failed` → 该基金 diff 整体标 `insufficient_data`（或配置规定口径），不得与"空仓"混淆。
4. **`diff` 子命令退役 stub**：`--fund`/`--period`/`--mode`；产物 `funddiff/diff@1`；确定性排序（K2：同输入双跑字节一致）。
5. **fixtures 真值对齐**：`data/fixtures/truth/` 里已有五态真值；diff 引擎输出必须逐条对齐（M1 独立复算测试的反向校验）。
6. **收尾**：双解释器全量 pytest + `ci_smoke` + 两条 `--check`；回写 plan/00、05、06、README；写 `plan/HANDOFF-M4.md` → commit。

---

## 三、既定口径清单（K 编号；动了会打挂测试）

见 `plan/HANDOFF-M1.md §三`（K1–K12）与 `plan/HANDOFF-M2.md §三`（K13–K16），全部仍有效。M3 特别相关：

| 编号 | 约定 |
|---|---|
| K3 | 数值字符串十进制（Decimal），缺失 `null` ≠ `0` |
| K2 | 确定性：同输入双跑字节一致（`serialize.dumps` 排序键） |
| K5 | 退出码契约：0 成功/谓词成立，1 门禁不通过，2 用法错误，3 未就绪，4 上游不可用，5 内部一致性 |
| K10 | 参数同源纪律：URL/阈值/口径全来自冻结配置，代码零硬编码 |

---

## 四、本机环境坑（在 HANDOFF-M1/M2 §四基础上追加）

1. M1/M2 既有坑全部有效（`py` 而非 `python`、`-X utf8`、3.8 语法底线、`PYTHONPATH=src`、非 editable 必须 `--data-dir`）。
2. **测试里 patch 网络层**：`Fetcher` 的默认传输是模块级函数 `net.http._urllib_transport`（`__init__` 时取值），
   monkeypatch 要打**模块全局**（`monkeypatch.setattr("funddiff.net.http._urllib_transport", …)`），
   打在类属性上不生效。
3. **capsys 与 watch add**：`watch add` 会往 stdout 写"已添加"；测试里先 `capsys.readouterr()` 清缓冲再跑 `fetch --json` 解析 JSON。
4. **heredoc 里替换源码**：`python - <<'PYEOF'` 在 Git Bash 下可用，但多段替换容易静默不命中（模式不匹配不报错）；
   替换后必须 grep 验证命中数，别信 print("ok")。
5. **eastmoney `_APIDATA_RE`**：页面通道正则容忍 `content:"…"` 后跟其它键（`,arryear:[…]`），以 `[,}]` 收尾。

---

## 五、DoD 逐项 checklist（M3）

- [ ] `diff.py` 五态状态机，stock_code 主键 Q/Q 对齐
- [ ] provider / computed 双口径 + 冲突清单（不一致可见，不合并）
- [ ] 任一季失败 → `insufficient_data`（或配置口径），与空仓区分
- [ ] `diff` 子命令退役 exit 3，产物 `funddiff/diff@1`
- [ ] 输出与 `data/fixtures/truth/` 真值逐条对齐
- [ ] 确定性：同输入双跑字节一致（既有 `serialize` 门禁继续守）
- [ ] 新增门禁变异验证 ≥3 道
- [ ] 双解释器 pytest 全绿 + `ci_smoke` 全绿 + 两条 `--check` 绿
- [ ] plan/00、05、06、README 状态回写
- [ ] `plan/HANDOFF-M4.md` 落盘并 commit

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

# 真实命令（M2 末态）
PYTHONPATH=src py -3.12 -X utf8 -m funddiff --data-dir data selftest
PYTHONPATH=src py -3.12 -X utf8 -m funddiff --data-dir data --store local_data/watchlist.json watch add 990001 --name 样例基金甲
PYTHONPATH=src py -3.12 -X utf8 -m funddiff --data-dir data --store local_data/watchlist.json window --as-of 2026-10-20 --json
# fetch：产物落 ./snapshots/（gitignore），失败落 failures.json，封锁 exit 4
PYTHONPATH=src py -3.12 -X utf8 -m funddiff --data-dir data --store local_data/watchlist.json fetch --json

# 改配置/改生成器后的重冻结
py -3.12 -X utf8 tools/freeze_config.py
py -3.12 -X utf8 tools/gen_fixtures.py

# 安装（干净环境）
py -3.12 -m venv .venv && ./.venv/Scripts/python.exe -m pip install -e ".[dev]"
```

> `local_data/`、`snapshots/`、`out/` 已被 `.gitignore` 隔离；演示与测试一律显式传 `--store` / `--out-dir`。
