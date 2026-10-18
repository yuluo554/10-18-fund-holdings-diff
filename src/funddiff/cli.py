"""命令行入口与退出码契约（K5）。

退出码：
  0 成功 / 谓词成立
  1 门禁不通过（selftest 失败、合规命中、基准不符）
  2 用法或输入错误
  3 该阶段尚未就绪（骨架期的显式契约，随模块落地逐条退役）
  4 上游/网络不可用（限频、验证码、登录墙、超时）
  5 内部一致性错误
"""

import argparse
import sys

from . import __version__, eid, paths, selftest, serialize, store, window
from .config import ConfigError, load_config

EXIT_OK = 0
EXIT_GATE_FAILED = 1
EXIT_USAGE = 2
EXIT_NOT_READY = 3
EXIT_UPSTREAM = 4
EXIT_INTERNAL = 5

STUB_STAGES = {
    "managers": "M4",
    "scale": "M4",
    "report": "M5",
    "run": "M5",
}


def _ensure_utf8_stdio():
    """控制台编码不足以输出中文时切到 UTF-8；cp936 保持不动。"""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        encoding = (getattr(stream, "encoding", None) or "").lower()
        if not encoding:
            continue
        try:
            "中文".encode(encoding)
        except (UnicodeEncodeError, LookupError):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError):
                pass


def _emit(text, stream=None):
    target = stream if stream is not None else sys.stdout
    target.write(text + "\n")


def _common_options(parser):
    parser.add_argument("--store", default=argparse.SUPPRESS,
                        help="自选清单路径（默认 ./local_data/watchlist.json）")
    parser.add_argument("--data-dir", default=argparse.SUPPRESS,
                        help="数据目录（含 config/ 与 fixtures/）")
    return parser


def build_parser():
    parser = argparse.ArgumentParser(
        prog="funddiff",
        description="基金季报持仓变动监控：自选清单 + Q/Q 持仓 diff + 经理变更 + 规模变动 + 本地季报",
    )
    parser.add_argument("--version", action="version", version="funddiff " + __version__)
    parser.add_argument("--store", default=None, help="自选清单路径")
    parser.add_argument("--data-dir", default=None, help="数据目录（含 config/ 与 fixtures/）")
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    watch = subparsers.add_parser("watch", help="管理自选基金清单（纯本地）")
    _common_options(watch)
    watch_sub = watch.add_subparsers(dest="action", metavar="<action>")

    add = _common_options(watch_sub.add_parser("add", help="添加或更新一只基金（幂等）"))
    add.add_argument("code", help="6 位基金代码")
    add.add_argument("--name", default=None, help="基金名称（可选）")
    add.add_argument("--note", default=None, help="备注（纯本地）")

    listing = _common_options(watch_sub.add_parser("list", help="列出清单"))
    listing.add_argument("--json", action="store_true", help="输出机读 JSON")

    remove = _common_options(watch_sub.add_parser("remove", help="从清单删除一只基金"))
    remove.add_argument("code", help="6 位基金代码")

    window_cmd = _common_options(subparsers.add_parser("window", help="报告窗口与披露状态"))
    window_cmd.add_argument("--as-of", default=None, help="判断基准日 YYYY-MM-DD（不读系统时钟）")
    window_cmd.add_argument("--json", action="store_true", help="输出机读 JSON")

    fetch = _common_options(subparsers.add_parser("fetch", help="抓取并归一持仓（M2）"))
    fetch.add_argument("--fund", default=None, help="基金代码；缺省为整份清单")
    fetch.add_argument("--period", default=None, help="报告期 YYYYQn")
    fetch.add_argument("--as-of", default=None, help="判断基准日 YYYY-MM-DD")
    fetch.add_argument("--json", action="store_true", help="输出机读 JSON")

    diff_cmd = _common_options(subparsers.add_parser("diff", help="Q/Q 持仓变动（M3）"))
    diff_cmd.add_argument("--mode", choices=["provider", "computed"], default=None,
                          help="diff 口径；缺省取配置冻结值")
    diff_cmd.add_argument("--period", default=None, help="报告期 YYYYQn")
    diff_cmd.add_argument("--fund", default=None, help="基金代码；缺省为整份清单")
    diff_cmd.add_argument("--json", action="store_true", help="输出机读 JSON")

    managers = _common_options(subparsers.add_parser("managers", help="基金经理变更（M4）"))
    managers.add_argument("--fund", default=None, help="基金代码")
    managers.add_argument("--period", default=None, help="报告期 YYYYQn")

    scale = _common_options(subparsers.add_parser("scale", help="规模变动（M4）"))
    scale.add_argument("--fund", default=None, help="基金代码")
    scale.add_argument("--period", default=None, help="报告期 YYYYQn")

    report = _common_options(subparsers.add_parser("report", help="生成季报（M5）"))
    report.add_argument("--period", default=None, help="报告期 YYYYQn")
    report.add_argument("--out-dir", default=None, help="产物目录")
    report.add_argument("--check-compliance", action="store_true", help="只做合规检查")
    report.add_argument("--prev-report", default=None, help="上期报告目录，用于对比")

    run = _common_options(subparsers.add_parser("run", help="一条命令跑全流程（M5）"))
    run.add_argument("--as-of", default=None, help="判断基准日 YYYY-MM-DD")
    run.add_argument("--out-dir", default=None, help="产物目录")

    selftest_cmd = _common_options(subparsers.add_parser("selftest", help="自检（可证伪）"))
    selftest_cmd.add_argument("--json", action="store_true", help="输出机读 JSON")

    return parser


def _fail(message, code):
    _emit(message, sys.stderr)
    return code


def _resolve(args):
    """解析 data_dir 与 store 路径；抛 ConfigError/DataDirError。"""
    data_dir = paths.resolve_data_dir(explicit=getattr(args, "data_dir", None))
    config = load_config(data_dir)
    store_file = paths.store_path(
        explicit=getattr(args, "store", None),
        default_relative=config["paths"]["store_default"],
    )
    return data_dir, config, store_file


def cmd_watch(args):
    action = getattr(args, "action", None)
    if action is None:
        return _fail("用法：funddiff watch <add|list|remove> [选项]", EXIT_USAGE)

    _, config, store_file = _resolve(args)
    watchlist = store.Watchlist(store_file)

    if action == "add":
        state, entry = watchlist.add(args.code, name=args.name, note=args.note)
        if state == "created":
            _emit("已添加：%s%s" % (entry["code"], " " + entry["name"] if entry["name"] else ""))
        elif state == "updated":
            _emit("已更新：%s%s" % (entry["code"], " " + entry["name"] if entry["name"] else ""))
        else:
            _emit("已存在，未改动：%s" % entry["code"])
        return EXIT_OK

    if action == "list":
        entries = watchlist.list_all()
        if getattr(args, "json", False):
            _emit(_json_text({"schema": store.SCHEMA, "funds": entries}))
        else:
            if not entries:
                _emit("清单为空。用 `funddiff watch add <code>` 添加。")
            for entry in entries:
                name = entry.get("name") or "(名称未缓存)"
                _emit("%s  %s" % (entry["code"], name))
        return EXIT_OK

    if action == "remove":
        if watchlist.remove(args.code):
            _emit("已删除：%s" % args.code)
            return EXIT_OK
        return _fail("未在清单中：%s" % args.code, EXIT_GATE_FAILED)

    return _fail("未知操作：%s" % action, EXIT_USAGE)


def cmd_window(args):
    data_dir, config, store_file = _resolve(args)
    window_info, as_of_date = window.resolve_window(config, args.as_of)

    entries = store.Watchlist(store_file).list_all()
    disclosure = eid.load_disclosure(data_dir, period=window_info["report_period"])

    states = []
    for entry in entries:
        status = window.disclosure_status(
            disclosure["available"], disclosure["reports"], entry["code"],
            window_info["report_period"], as_of=as_of_date.isoformat(),
        )
        states.append(status)

    payload = {
        "schema": "funddiff/window@1",
        "window": window_info,
        "as_of": as_of_date.isoformat(),
        "disclosure_source": {
            "available": disclosure["available"],
            "reason": disclosure["reason"],
            "snapshot": disclosure.get("snapshot"),
        },
        "funds": [
            {"code": entry["code"], "name": entry.get("name"), "disclosure": status}
            for entry, status in zip(entries, states)
        ],
        "totals": window.summarize(states),
    }

    if getattr(args, "json", False):
        _emit(_json_text(payload))
        return EXIT_OK

    _emit("报告期：%s（%s ~ %s）" % (
        window_info["report_period"], window_info["period_start"], window_info["period_end"]))
    if window_info["disclosure_deadline"] is None:
        _emit("披露截止：无法计算（%s）" % _deadline_reason(window_info))
    else:
        _emit("披露截止：%s（季度结束后第 %d 个工作日）" % (
            window_info["disclosure_deadline"], window_info["deadline_count"]))
    _emit("判断基准日：%s" % as_of_date.isoformat())
    if not disclosure["available"]:
        _emit("披露元数据不可用（%s）：全部基金记为「无数据」" % disclosure["reason"], sys.stderr)
    if not entries:
        _emit("清单为空。")
    for item in payload["funds"]:
        _emit("%s  %s  %s" % (item["code"], item["disclosure"], item.get("name") or "(名称未缓存)"))
    totals = payload["totals"]
    _emit("合计：已披露 %d / 待披露 %d / 无数据 %d" % (
        totals["已披露"], totals["待披露"], totals["无数据"]))
    return EXIT_OK


def cmd_fetch(args):
    """抓取并归一持仓（M2）。

    退出码契约：成功 0；限频/验证码/登录墙等上游拒绝 4；
    全部失败但非封锁类 0（失败隔离：单只失败不影响其余，失败落台账）。
    产物落 snapshots/（gitignore，永不入仓）。
    """
    from . import eid, normalize, window
    from .net import eastmoney
    from .net.http import Fetcher

    data_dir, config, store_file = _resolve(args)
    window_info, _as_of = window.resolve_window(config, args.as_of)
    report_period = args.period or window_info["report_period"]
    try:
        window.parse_period(report_period)
    except window.WindowError as exc:
        return _fail(str(exc), EXIT_USAGE)

    entries = store.Watchlist(store_file).list_all()
    if args.fund:
        if not any(entry["code"] == args.fund for entry in entries):
            return _fail("未在清单中：%s（先 watch add）" % args.fund, EXIT_GATE_FAILED)
        entries = [entry for entry in entries if entry["code"] == args.fund]
    if not entries:
        return _fail("清单为空。用 `funddiff watch add <code>` 添加。", EXIT_GATE_FAILED)

    snapshots_dir = paths.snapshots_dir(data_dir, config=config)
    disclosure = eid.load_disclosure(data_dir, period=report_period)
    period_end = window.period_end_of(config, report_period)
    fetched_at = window.today_iso()

    fetcher = Fetcher(config)
    payloads = []
    for entry in entries:
        code = entry["code"]
        if fetcher.blocked_hosts():
            # 域名被封：剩余基金不再发请求，落 timeout/blocked 台账（失败隔离）。
            payloads.append(normalize.failure_record(
                code, report_period, "blocked", channel=None,
                fund_name=entry.get("name"), period_end=period_end))
            continue
        try:
            payload = eastmoney.fetch_holdings(
                config, code, report_period, fetcher=fetcher, fetched_at=fetched_at,
                fund_name=entry.get("name"),
                period_end=period_end)
        except eastmoney.FetchFailure as failure:
            payloads.append(normalize.failure_record(
                code, report_period, failure.error_kind,
                channel=failure.channel, endpoint=failure.endpoint,
                fallback_reason=failure.fallback_reason,
                fund_name=entry.get("name"), period_end=period_end,
                raw=failure.raw))
            continue
        # ETF 联接：结构性无股票持仓。
        if normalize.is_etf_feeder(payload.get("fund_name"), payload.get("fund_type")):
            payload = normalize.empty_holdings(
                code, report_period, fund_name=payload.get("fund_name"),
                fund_type=payload.get("fund_type"))
        payloads.append(payload)

    blocked = fetcher.blocked_hosts()
    summary = {
        "ok": sum(1 for item in payloads if item["status"] == "ok"),
        "empty": sum(1 for item in payloads if item["status"] == "empty"),
        "failed": sum(1 for item in payloads if item["status"] == "failed"),
    }
    result = {
        "schema": "funddiff/fetch@1",
        "report_period": report_period,
        "period_end": period_end,
        "fetched_at": fetched_at,
        "disclosure_available": disclosure["available"],
        "snapshots_dir": str(snapshots_dir),
        "funds": payloads,
        "totals": summary,
        "blocked_hosts": blocked,
    }
    # 产物落盘：snapshots/<period>/holdings/<code>.json + failures 台账。
    holdings_dir = snapshots_dir / ("q" + report_period.lower()) / "holdings"
    holdings_dir.mkdir(parents=True, exist_ok=True)
    failures = []
    for payload in payloads:
        if payload["status"] == "failed":
            failures.append(payload)
        (holdings_dir / (payload["fund_code"] + ".json")).write_text(
            serialize.dumps(payload), encoding="utf-8")
    if failures:
        (snapshots_dir / ("q" + report_period.lower()) / "failures.json").write_text(
            serialize.dumps(failures), encoding="utf-8")

    if getattr(args, "json", False):
        _emit(_json_text(result))
    else:
        _emit("报告期：%s  产物目录：%s" % (report_period, holdings_dir))
        for payload in payloads:
            label = {"ok": "成功", "empty": "空仓（结构性）", "failed": "失败"}[
                payload["status"]]
            suffix = ""
            if payload["status"] == "failed":
                suffix = "（%s）" % (payload["source"].get("fallback_reason") or
                                    payload["error_kind"])
            _emit("%s  %s  %d 行%s" % (
                payload["fund_code"], label, len(payload["rows"]), suffix))
        _emit("合计：成功 %d / 空 %d / 失败 %d" % (
            summary["ok"], summary["empty"], summary["failed"]))
        if blocked:
            _emit("上游封锁：%s（后续请求已停止，退出码 4）" % ", ".join(sorted(blocked)),
                  sys.stderr)

    if blocked:
        return EXIT_UPSTREAM
    return EXIT_OK


def cmd_diff(args):
    """Q/Q 持仓 diff（M3）。

    退出码契约：成功 0；清单空/基金不在清单/快照缺失 1；
    口径非法或报告期非法 2。
    双口径：缺省取配置冻结 diff.mode；--mode 可覆盖但必须显式选择。
    """
    from . import diff as diff_mod
    from . import window

    data_dir, config, store_file = _resolve(args)
    mode = args.mode or config["diff"]["mode"]
    if mode not in ("provider", "computed"):
        return _fail("未知 diff 口径：%r（仅 provider / computed）" % mode, EXIT_USAGE)

    report_period = args.period
    if report_period is None:
        window_info, _as_of = window.resolve_window(config, getattr(args, "as_of", None))
        report_period = window_info["report_period"]

    entries = store.Watchlist(store_file).list_all()
    if args.fund:
        if not any(entry["code"] == args.fund for entry in entries):
            return _fail("未在清单中：%s（先 watch add）" % args.fund, EXIT_GATE_FAILED)
        codes = [args.fund]
    else:
        codes = [entry["code"] for entry in entries]

    try:
        result = diff_mod.build(data_dir, config, codes, report_period, mode)
    except diff_mod.DiffError as exc:
        return _fail(str(exc), EXIT_GATE_FAILED)
    except window.WindowError as exc:
        return _fail(str(exc), EXIT_USAGE)
    except ValueError as exc:
        return _fail(str(exc), EXIT_INTERNAL)

    out_dir = paths.snapshots_dir(data_dir, config=config) / (
        "q" + report_period.lower())
    out_file = out_dir / "diff.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(serialize.dumps(result), encoding="utf-8")

    if getattr(args, "json", False):
        _emit(_json_text(result))
    else:
        _emit("报告期：%s（对比 %s）  口径：%s  阈值：%s" % (
            result["report_period"], result["prev_period"], mode,
            result["threshold"]))
        for fund in result["funds"]:
            if fund["status"] == diff_mod.FUND_INSUFFICIENT:
                _emit("%s  %s  数据不足（任一季抓取失败），不与空仓混淆" % (
                    fund["fund_code"], fund["fund_name"] or ""))
                continue
            _emit("%s  %s  %d 条" % (fund["fund_code"], fund["fund_name"] or "",
                                     len(fund["entries"])))
            for entry in fund["entries"]:
                delta = entry["delta"] if entry["delta"] is not None else "—"
                _emit("  %s  %s  %s→%s（%s）%s" % (
                    entry["stock_code"], entry["status"],
                    entry["prev_ratio"], entry["cur_ratio"], delta,
                    ("  异常:%s" % ",".join(entry["anomalies"]))
                    if entry["anomalies"] else ""))
        if result["conflicts"]:
            _emit("双口径冲突 %d 条（详见产物 conflicts，不合并、不裁决）：" %
                  len(result["conflicts"]), sys.stderr)
            for item in result["conflicts"]:
                _emit("  %s %s：provider=%s(%s) vs computed=%s(%s)" % (
                    item["fund_code"], item["stock_code"],
                    item["provider_status"], item["provider_change_pct"],
                    item["computed_status"], item["computed_delta"]), sys.stderr)
        _emit("产物：%s" % out_file)
    return EXIT_OK


def _deadline_reason(window_info):
    reason = window_info.get("unverified_reason") or ""
    if reason.startswith("calendar_missing:"):
        year = reason.split(":", 1)[1]
        return "缺少 %s 年国务院节假日安排，未作近似" % year
    return "截止日规则超出可计算范围"


def cmd_selftest(args):
    try:
        data_dir, config, store_file = _resolve(args)
    except (ConfigError, paths.DataDirError) as exc:
        # 数据目录不可用属"用法/输入错误"（退出码 2），不是"检查失败"（1）：
        # 保留 1 给"门禁跑了但结论不达标"，否则用户分不清"没跑起来"与"跑了没过"。
        report = selftest.run(data_dir=None, config=None, store_file=None)
        report["checks"].insert(0, {
            "name": "paths.resolve", "status": selftest.FAIL, "detail": str(exc)})
        report["failed"] = report["failed"] + 1
        report["ok"] = False
        if getattr(args, "json", False):
            _emit(_json_text(report))
        else:
            _emit("[FAIL] paths.resolve — %s" % exc, sys.stderr)
            _emit("自检未运行：数据目录不可用（退出码 2 表示输入问题）", sys.stderr)
        return EXIT_USAGE

    report = selftest.run(data_dir=data_dir, config=config, store_file=store_file)
    if getattr(args, "json", False):
        _emit(_json_text(report))
    else:
        for check in report["checks"]:
            _emit("[%s] %s — %s" % (check["status"], check["name"], check["detail"]))
        _emit("自检：%s（%d 项失败 / %d 项跳过 / 共 %d 项）" % (
            "通过" if report["ok"] else "未通过",
            report["failed"], report["skipped"], len(report["checks"])))
    return EXIT_OK if report["ok"] else EXIT_GATE_FAILED


def cmd_stub(args):
    stage = STUB_STAGES.get(args.command, "后续里程碑")
    return _fail(
        "`%s` 将在 %s 实现（当前为骨架期，退出码 3 是既定契约）。" % (args.command, stage),
        EXIT_NOT_READY,
    )


def _json_text(payload):
    return serialize.dumps(payload).rstrip("\n")


def main(argv=None):
    _ensure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return EXIT_OK

    handlers = {
        "watch": cmd_watch,
        "window": cmd_window,
        "fetch": cmd_fetch,
        "diff": cmd_diff,
        "selftest": cmd_selftest,
    }
    if args.command in STUB_STAGES:
        return cmd_stub(args)

    handler = handlers.get(args.command)
    if handler is None:
        return _fail("未知命令：%s" % args.command, EXIT_USAGE)

    try:
        return handler(args)
    except (ConfigError, paths.DataDirError, store.StoreError, window.WindowError) as exc:
        return _fail(str(exc), EXIT_USAGE)
    except ValueError as exc:
        return _fail(str(exc), EXIT_INTERNAL)
    except KeyboardInterrupt:
        return _fail("已中断。", EXIT_UPSTREAM)
