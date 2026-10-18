# funddiff — 基金季报持仓变动监控

维护自选基金清单 → 抓季报前十大持仓 → 与上季做 diff（新进 / 退出 / 加仓 / 减仓 / 不变）
→ 叠加基金经理变更与规模变动 → 生成"这一季我的基金换了什么"的本地报告。

**纯本地 Python CLI**：无服务器、无账号、无 GPU、无数据上传。报告是单文件 HTML（零外链）+ Markdown + 机器可读 JSON。

> **它不是实时估值工具，是季度事件回顾。**

---

## ⚠️ 先读这三条结构性限制（不是缺陷，是定位）

1. **季报一年只有 4 次新数据。** 公募基金季报按季度披露，Q3 报告期截止 9/30、披露截止 10 月底。
   工具在一年中绝大部分时间**没有新数据可处理**——它是季度复盘工具，不是常驻服务，也不是盘中工具。
   演示与验证靠**历史季度回放**与**随包的合成快照**，不依赖"实时新鲜度"。
2. **数据源有 ToS 边界。** 商业接口（东财）仅限个人本地低频使用：**不建公开镜像、不再分发原始数据、
   不把抓取结果提交进仓库**。仓库内所有样例均为**程序化合成的快照**（`sample: synthetic`）。
   遇到 429 / 403 / 验证码 / 登录墙即停止并落台账，**不做任何规避**。
3. **巨潮基金栏目收录滞后（实测）。** 2026-10-01 ~ 10-17 区间返回 0 条，而同期 Q2 窗口有 1023 条。
   因此巨潮**只作备用核对，不作主源**。主源顺序：证监会 eid 元数据判"发了没有" → 东财补"写了什么"。

**覆盖度**：首期以股票型 / 混合型为主；ETF 联接 / QDII / LOF 只标注结构差异，**不承诺字段完整**；
货币基金、债券基金的首十大口径不同，首期不承诺。**抽样覆盖，非穷举**。

---

## 当前状态

**M0–M4 已完成，M5（季报与合规门禁）待开工。** 真实可用的有 `watch` / `window` / `fetch` / `diff` / `managers` / `scale` / `selftest`
（M1 起含配置冻结门禁与两季合成快照；M2 起双通道持仓抓取与归一真实可用，M3 起五态 diff 真实可用，M4 起经理变更与规模变动真实可用，产物落 `snapshots/`，不入仓）；其余子命令按契约返回退出码 **3**（该阶段尚未就绪），**不是故障**。

| 里程碑 | 内容 | 状态 |
|---|---|---|
| M0 | 骨架、退出码契约、确定性写盘、清单、窗口三态 | ✅ |
| M1 | 冻结配置包（法规化披露期限）+ 合成两季快照 + 真值 + eid 接入 | ✅ |
| M2 | 双通道抓取（JSON 优先 / 页面回落）+ 归一 + 失败隔离 | ✅ |
| M3 | 五态 Q/Q diff + 双口径 + 冲突清单 + 双季溯源 | ✅ |
| M4 | 经理变更 + 规模变动 | ✅ |
| M5 | 季报三产物 + 合规硬门禁 | ⬜ |
| M6 | GitHub 发布 | ⬜ |

> CI：仓库尚无远端，**尚未跑过 CI**。当前所有验证均为"本地等价校验"，待首推验证。

---

## 安装

需要 **Python ≥ 3.8**（3.8 与 3.12 均实测）。运行时**零第三方依赖**。

```bash
git clone <repo-url> 10-18-fund-holdings-diff
cd 10-18-fund-holdings-diff
py -3.12 -m pip install -e ".[dev]"
```

Linux / macOS 把 `py -3.12` 换成 `python3` 即可。

**配置包不在 wheel 内**（它是可审计的数据资产，不是代码）。因此：

- 从源码目录（editable 安装）运行时，工具会自动找到 `./data/`；
- **非 editable 安装**（`pip install .`）后，必须用 `--data-dir` 或环境变量显式指向克隆下来的 `data/`：

```bash
funddiff --data-dir /path/to/10-18-fund-holdings-diff/data window --as-of 2026-10-18
export FUNDDIFF_DATA_DIR=/path/to/10-18-fund-holdings-diff/data
```

---

## 快速开始

```bash
# 1) 自检（可证伪；含配置包 / fixtures 的 MANIFEST 一致性检查）
py -3.12 -X utf8 -m funddiff selftest

# 2) 管理自选清单（纯本地，幂等）
py -3.12 -X utf8 -m funddiff watch add 990001 --name "样例基金甲"
py -3.12 -X utf8 -m funddiff watch add 990001 --name "样例基金甲"   # 重复添加不产生新条目
py -3.12 -X utf8 -m funddiff watch list
py -3.12 -X utf8 -m funddiff watch remove 990001

# 3) 报告窗口与披露状态（已披露 / 待披露 / 无数据 三态；--as-of 历史回放）
py -3.12 -X utf8 -m funddiff window --as-of 2026-10-18
py -3.12 -X utf8 -m funddiff window --as-of 2026-10-20 --json

# 4) Q/Q 持仓 diff（五态 + 双口径 + 冲突清单；M3）
py -3.12 -X utf8 -m funddiff diff --period 2026Q3                # 文本输出
py -3.12 -X utf8 -m funddiff diff --period 2026Q3 --mode provider --json
# 产物落 snapshots/q2026q3/diff.json（gitignore，不入仓）

# 5) 经理变更与规模变动（四类事件判定 + 单位读表头 + 缺失≠0；M4）
py -3.12 -X utf8 -m funddiff managers --period 2026Q3 --fund 990002      # 经理变更（in_period / prior_period / none / unparsed）
py -3.12 -X utf8 -m funddiff scale --period 2026Q3 --json                # 规模六字段（0 申赎与缺失 null 严格区分）
# 产物落 snapshots/q2026q3/managers.json 与 scale.json（gitignore，不入仓）

# 6) 冻结产物校验（CI 与本地同一份门禁）
py -3.12 -X utf8 tools/freeze_config.py --check
py -3.12 -X utf8 tools/gen_fixtures.py --check
```

安装后也可以直接用控制台脚本（两条通路等价，CI 与冒烟各跑一遍）：

```bash
funddiff selftest
funddiff --version
```

---

## 命令表

| 命令 | 说明 | 退出码语义 |
|---|---|---|
| `funddiff watch add <code> [--name N] [--note T]` | 幂等添加/更新自选基金 | `0` 成功；`2` 代码非法 |
| `funddiff watch list [--json]` | 列出清单（按代码升序） | `0` |
| `funddiff watch remove <code>` | 删除；不存在时返回 `1`（谓词不成立） | `0` / `1` |
| `funddiff window [--as-of YYYY-MM-DD] [--json]` | 本期报告窗口 + 逐基金披露状态 | `0`；`2` 日期非法 |
| `funddiff fetch [--fund CODE] [--period YYYYQn] [--json]` | 抓取并归一持仓（失败隔离；产物落 `snapshots/`） | `0` 成功（含部分失败，失败落 `failures.json`）；`1` 清单为空/基金不在清单；`4` 上游封锁（限频/验证码/登录墙）；`2` 参数非法 |
| `funddiff diff [--mode provider\|computed] [--period YYYYQn] [--fund CODE] [--json]` | Q/Q 五态变动（与上季持仓对齐；产物落 `snapshots/q<period>/diff.json`） | `0` 成功；`1` 清单为空/基金不在清单/缺两季快照；`2` 口径或报告期非法 |
| `funddiff managers [--fund CODE] [--period YYYYQn] [--json]` | 基金经理变更四类判定（区间来自冻结配置；`unparsed` 附页面快照，与无变更分开；产物落 `snapshots/q<period>/managers.json`） | `0` 成功；`1` 清单为空/基金不在清单/缺事件快照；`2` 报告期非法 |
| `funddiff scale [--fund CODE] [--period YYYYQn] [--json]` | 规模六字段台账（单位读表头原样记录；`0` 真实零申赎与 `null` 缺失可区分；`no_prev_baseline` 时流量字段为 null 不补 0；产物落 `snapshots/q<period>/scale.json`） | `0` 成功；`1` 清单为空/基金不在清单/缺事件快照；`2` 报告期非法 |
| `funddiff report [--period YYYYQn] [--out-dir DIR]` | 生成季报三产物 | `3`（M5 实现）；`1` 合规命中 |
| `funddiff run [--as-of YYYY-MM-DD] [--out-dir DIR]` | 一条命令跑全流程 | `3`（M5 实现） |
| `funddiff selftest [--json]` | 自检（可证伪） | `0` 通过；`1` 有检查失败；`2` 数据目录不可用（自检未运行） |

全局参数：`--store PATH`（清单路径）、`--data-dir PATH`（数据目录）。

**退出码总表**：`0` 成功 / 谓词成立 · `1` 门禁不通过 · `2` 用法或输入错误 ·
`3` 该阶段尚未就绪（骨架期显式契约）· `4` 上游/网络不可用 · `5` 内部一致性错误。

---

## 目录

```
plan/        计划与留档（00 总览 / 01 题目 / 02 架构 / 03 模块详设 / 04 数据 / 05 里程碑 / 06 交付对标）
data/        README（依据与口径唯一权威处）+ config（冻结配置包）+ fixtures（合成快照）
src/funddiff/  CLI、窗口、清单、序列化、合规、网络层（双通道抓取 + 归一，M2）
tests/       单元 + CLI 契约 + README 门禁 + 零网络门禁
tools/       配置冻结、fixtures 生成、CI 冒烟
```

---

## 开发

```bash
py -3.8  -X utf8 -m pytest -q     # 最低支持版本
py -3.12 -X utf8 -m pytest -q
py -3.12 -X utf8 tools/ci_smoke.py
```

`data/config/app.json` 是**冻结配置**：季度窗口、diff 口径与阈值、限频退避、合规词表、
法规化披露期限（第十八条"十五个工作日" + 国务院节假日日历）都在这里，代码中不写第二份。
改动需重跑 `tools/freeze_config.py` 重生成 MANIFEST；`--check` 逐文件 SHA256 校验，不符 exit 1。
`data/fixtures/` 由 `tools/gen_fixtures.py`（splitmix64、固定 seed）生成，`--check` 做两层校验：
MANIFEST 与冻结文件一致 + 临时重生成逐字节一致。**两者都是生成物，禁止手改。**

---

## 数据来源与免责

- 持仓：`来源：基金季度报告`；规模与经理：`来源：基金定期报告公开披露`。
- 商业接口只作字段补充，**不写成官方来源**；官方（证监会 eid）只提供"报告是否已发布"的元数据。
- 季报数据版权属基金公司；数据与官方披露存在差异时，以基金公司公告及证监会披露为准。
- 本工具只做**已经披露的季报里发生了什么**的事实回顾：**不推荐、不排名、不预测收益、不给买卖信号、
  不做基金经理能力评价**。报告页脚固定为"非投资建议 · 来源：基金季度报告"，不可通过配置关闭。
- 自选清单**纯本地存储**，不上传、不同步、无账号体系；报告不含任何个人身份信息。

## 许可

MIT，见 [LICENSE](LICENSE)。
