"""M2 门禁：抓取与归一（net/http、net/eastmoney、normalize、fetch CLI）。

设计原则与 M1 一致：每道门禁都要能"被弄坏后变红"（变异验证）；
网络层全部用假传输注入，绝不真连外网（与 test_no_network 共同构成零网络纪律）。
"""

import json
from pathlib import Path

import pytest

from funddiff import cli, normalize
from funddiff.net import eastmoney
from funddiff.net.http import FetchError, Fetcher

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

DATA_CONFIG_RATE_LIMIT = {
    "min_interval_seconds": "0",
    "timeout_seconds": "15",
    "max_retries": 2,
    "backoff_initial_seconds": "0.01",
    "backoff_factor": "2.0",
    "backoff_max_seconds": "0.05",
    "max_total_wait_seconds": "1.0",
    "stop_on": ["http_429", "http_403", "captcha", "login_redirect"],
}


def make_config(**overrides):
    rate_limit = dict(DATA_CONFIG_RATE_LIMIT)
    rate_limit.update(overrides.pop("rate_limit", {}))
    return {
        "sources": {
            "eastmoney_position_json": {
                "endpoint": "https://fundmobapi.example/FundMNInverstPosition"},
            "eastmoney_position_page": {
                "endpoint": "https://fundf10.example/FundArchivesDatas.aspx",
                "encoding": "gbk"},
        },
        "rate_limit": rate_limit,
    }


class FakeTransport(object):
    """可编程假传输：按序返回 (status, body, final_url) 或抛 FetchError。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def __call__(self, url, headers, timeout):
        self.calls.append(url)
        item = self.script.pop(0)
        if isinstance(item, FetchError):
            raise item
        return item


def fake_fetcher(script, config=None, sleeper=None):
    transport = FakeTransport(script)
    fetcher = Fetcher(config or make_config(), transport=transport,
                      sleeper=sleeper or (lambda seconds: None))
    return fetcher, transport


def json_body(rows):
    return json.dumps({"Datas": rows}).encode("utf-8")


def page_body_gbk(html):
    template = ('<html><script>var apidata={content:"%s",arryear:[2019]};'
                '</script></html>')
    return (template % html.replace('"', '\\"')).encode("gbk")


# ---------- normalize ----------

def test_strip_percent_keeps_sign_and_strips_mark():
    assert normalize.strip_percent("8.54%") == "8.54"
    assert normalize.strip_change_pct("-0.50%") == "-0.50"
    assert normalize.strip_change_pct("+0.5") == "+0.5"
    assert normalize.strip_change_pct("--") is None


def test_missing_is_null_not_zero():
    assert normalize.strip_percent(None) is None
    assert normalize.strip_change_pct("") is None
    row = normalize.normalize_row("600001", "某股票", None)
    assert row["ratio"] is None and row["change_pct"] is None
    assert row["industry"] is None


def test_clean_name_only_whitespace():
    assert normalize.clean_name("\u3000样例\u3000股票 ") == "样例 股票"
    assert normalize.clean_name(None) is None


def test_change_type_whitelist():
    row = normalize.normalize_row("600001", "某股票", "1.0", change_type="乱写")
    assert row["change_type"] is None
    row = normalize.normalize_row("600001", "某股票", "1.0", change_type="增持")
    assert row["change_type"] == "增持"


def test_etf_feeder_detected():
    assert normalize.is_etf_feeder("某 ETF 联接 A")
    assert normalize.is_etf_feeder("某基金", fund_type="ETF联接")
    assert not normalize.is_etf_feeder("普通股票基金")


# ---------- net/http ----------

def test_fetcher_returns_body_and_respects_min_interval():
    sleeps = []
    fetcher, _ = fake_fetcher(
        [(200, b"ok", "https://a.example/x"), (200, b"ok", "https://a.example/y")],
        config=make_config(rate_limit={"min_interval_seconds": "5"}),
        sleeper=sleeps.append)
    status, body, final = fetcher.get("https://a.example/x")
    assert status == 200 and body == b"ok"
    # 第二次请求触发限频等待
    fetcher.get("https://a.example/y")
    assert any(s > 0 for s in sleeps), "同域第二次请求必须等待 min_interval"


def test_retryable_failure_backs_off_then_succeeds():
    sleeps = []
    script = [FetchError("超时", kind="timeout"),
              (200, b"ok", "https://a.example/x")]
    fetcher, transport = fake_fetcher(script, sleeper=sleeps.append)
    status, body, _ = fetcher.get("https://a.example/x")
    assert body == b"ok"
    assert len(transport.calls) == 2
    assert len(sleeps) == 1  # 退避了一次


def test_backoff_gives_up_after_max_retries():
    script = [FetchError("超时", kind="timeout")] * 3
    fetcher, transport = fake_fetcher(script)
    with pytest.raises(FetchError) as excinfo:
        fetcher.get("https://a.example/x")
    assert excinfo.value.kind == "timeout"
    assert len(transport.calls) == 3  # max_retries=2 → 共 3 次


def test_http_429_blocks_domain_and_subsequent_requests():
    script = [FetchError("HTTP 429", kind="http_error", status=429)]
    fetcher, _ = fake_fetcher(script)
    with pytest.raises(FetchError) as excinfo:
        fetcher.get("https://a.example/x")
    assert excinfo.value.kind == "http_429"
    assert fetcher.is_blocked("https://a.example/y")
    with pytest.raises(FetchError) as second:
        fetcher.get("https://a.example/y")
    assert second.value.kind == "blocked"


def test_captcha_in_body_blocks_domain():
    body = "请输入验证码 captcha".encode("utf-8")
    fetcher, _ = fake_fetcher([(200, body, "https://a.example/x")])
    with pytest.raises(FetchError) as excinfo:
        fetcher.get("https://a.example/x")
    assert excinfo.value.kind == "captcha"
    assert fetcher.is_blocked("https://a.example/y")


def test_login_redirect_blocks_domain():
    fetcher, _ = fake_fetcher([(302, b"", "https://a.example/login?next=/x")])
    with pytest.raises(FetchError) as excinfo:
        fetcher.get("https://a.example/x")
    assert excinfo.value.kind == "login_redirect"


def test_total_wait_cap_aborts_retry_loop():
    script = [FetchError("超时", kind="timeout")] * 10
    sleeps = []
    fetcher, _ = fake_fetcher(
        script,
        config=make_config(rate_limit={
            "backoff_initial_seconds": "0.4", "backoff_max_seconds": "0.4",
            "max_total_wait_seconds": "0.5"}),
        sleeper=sleeps.append)
    with pytest.raises(FetchError) as excinfo:
        fetcher.get("https://a.example/x")
    assert "max_total_wait" in str(excinfo.value)


def test_rate_limit_params_all_from_config():
    """K10：改配置必改行为，代码里不允许第二份口径。"""
    config = make_config(rate_limit={"max_retries": 0})
    fetcher, transport = fake_fetcher(
        [FetchError("超时", kind="timeout")], config=config)
    with pytest.raises(FetchError):
        fetcher.get("https://a.example/x")
    assert len(transport.calls) == 1


# ---------- net/eastmoney ----------

def test_json_channel_primary():
    rows = [{"GPDM": "600001", "GPJC": "样例股票600001", "JZBL": "8.54%",
             "PCTNVCHGTYPE": "1", "PCTNVCHG": "0.50", "INDEXNAME": "医药生物"}]
    fetcher, transport = fake_fetcher([(200, json_body(rows), "u")])
    payload = eastmoney.fetch_holdings(make_config(), "990001", "2026Q3",
                                       fetcher=fetcher, fund_name="样例基金甲",
                                       period_end="2026-09-30")
    assert payload["source"]["channel"] == "json"
    assert "fallback_reason" not in payload["source"]
    assert "FundMNInverstPosition" in transport.calls[0]
    assert payload["rows"][0]["ratio"] == "8.54"
    assert payload["rows"][0]["change_type"] == "增持"
    assert payload["rows"][0]["change_pct"] == "0.50"
    assert payload["schema"] == "funddiff/holdings@1"
    assert payload["fund_code"] == "990001"
    assert payload["status"] == "ok"


def test_page_fallback_leaves_trace():
    """JSON 通道字段不齐 → jjcc 页面回落，必须留痕 fallback_reason。"""
    html = ("<tr><td>1</td><td>600001</td><td>样例股票600001</td>"
            "<td>8.54%</td><td>增持</td><td>0.50%</td><td>医药生物</td></tr>")
    script = [
        FetchError("字段不齐", kind="http_error", status=500),
        (200, page_body_gbk(html), "u"),
    ]
    fetcher, transport = fake_fetcher(script)
    payload = eastmoney.fetch_holdings(make_config(), "990001", "2026Q3",
                                       fetcher=fetcher)
    assert payload["source"]["channel"] == "page"
    assert payload["source"]["fallback_reason"] == "http_error"
    assert payload["rows"][0]["stock_code"] == "600001"
    assert payload["rows"][0]["industry"] == "医药生物"
    assert "jjcc" in transport.calls[1]


def test_gbk_strict_decode_failure_keeps_raw_bytes():
    """GBK 严格解码失败：保存原始字节 + decode_error，禁止 errors=ignore。"""
    script = [FetchError("坏", kind="http_error", status=500),
              (200, b"\xff\xfe\x81", "u")]
    fetcher, _ = fake_fetcher(script)
    with pytest.raises(eastmoney.FetchFailure) as excinfo:
        eastmoney.fetch_holdings(make_config(), "990001", "2026Q3", fetcher=fetcher)
    assert excinfo.value.error_kind == "decode_error"
    assert excinfo.value.raw == b"\xff\xfe\x81"


def test_both_channels_fail_raises_with_fallback_reason():
    script = [FetchError("超时", kind="timeout"),
              FetchError("超时", kind="timeout")]
    fetcher, _ = fake_fetcher(script,
                              config=make_config(rate_limit={"max_retries": 0}))
    with pytest.raises(eastmoney.FetchFailure) as excinfo:
        eastmoney.fetch_holdings(make_config(), "990001", "2026Q3", fetcher=fetcher)
    assert excinfo.value.error_kind == "timeout"
    assert excinfo.value.fallback_reason == "timeout"


def test_empty_json_result_is_ok_with_zero_rows():
    fetcher, _ = fake_fetcher([(200, json_body([]), "u")])
    payload = eastmoney.fetch_holdings(make_config(), "990001", "2026Q3",
                                       fetcher=fetcher)
    assert payload["status"] == "ok"
    assert payload["rows"] == []
    assert payload["source"]["channel"] == "json"


def test_channels_agree_on_same_code_set():
    """双通道一致性夹具：同一响应数据，两通道解析出的代码集合必须相等。"""
    html = ("<tr><td>1</td><td>600001</td><td>样例股票600001</td>"
            "<td>8.54%</td><td>增持</td><td>0.50%</td><td>医药生物</td></tr>"
            "<tr><td>2</td><td>600002</td><td>样例股票600002</td>"
            "<td>3.76%</td><td>减持</td><td>-0.50%</td><td>医药生物</td></tr>")
    json_rows = [
        {"GPDM": "600001", "GPJC": "样例股票600001", "JZBL": "8.54%",
         "PCTNVCHGTYPE": "1", "PCTNVCHG": "0.50", "INDEXNAME": "医药生物"},
        {"GPDM": "600002", "GPJC": "样例股票600002", "JZBL": "3.76%",
         "PCTNVCHGTYPE": "2", "PCTNVCHG": "-0.50", "INDEXNAME": "医药生物"},
    ]
    fetcher, _ = fake_fetcher([(200, json_body(json_rows), "u")])
    json_payload = eastmoney.fetch_holdings(make_config(), "990001", "2026Q3",
                                            fetcher=fetcher)
    fetcher, _ = fake_fetcher([FetchError("坏", kind="http_error", status=500),
                               (200, page_body_gbk(html), "u")])
    page_payload = eastmoney.fetch_holdings(make_config(), "990001", "2026Q3",
                                            fetcher=fetcher)
    json_codes = {row["stock_code"] for row in json_payload["rows"]}
    page_codes = {row["stock_code"] for row in page_payload["rows"]}
    assert json_codes == page_codes == {"600001", "600002"}
    json_ratios = {row["stock_code"]: row["ratio"] for row in json_payload["rows"]}
    page_ratios = {row["stock_code"]: row["ratio"] for row in page_payload["rows"]}
    assert json_ratios == page_ratios


# ---------- fetch CLI（失败隔离 / exit 4 / snapshots 隔离） ----------

class GateTransport(object):
    """按 URL 前缀分域的假传输：json 域与 page 域可分别编程。"""

    def __init__(self, plan):
        self.plan = plan  # callable(url) -> script item
        self.calls = []

    def __call__(self, url, headers, timeout):
        self.calls.append(url)
        item = self.plan(url)
        if isinstance(item, FetchError):
            raise item
        return item


def patch_endpoints(monkeypatch, json_endpoint, page_endpoint):
    config = make_config()
    config["sources"]["eastmoney_position_json"]["endpoint"] = json_endpoint
    config["sources"]["eastmoney_position_page"]["endpoint"] = page_endpoint
    monkeypatch.setattr("funddiff.net.eastmoney._json_endpoint",
                        lambda cfg: json_endpoint)
    monkeypatch.setattr("funddiff.net.eastmoney._page_endpoint",
                        lambda cfg, code: page_endpoint)
    return config


def run_fetch(monkeypatch, tmp_path, store_file, transport, config=None,
              extra_args=()):
    if config is None:
        config = make_config()
    monkeypatch.setattr("funddiff.net.http._urllib_transport",
                        lambda url, headers, timeout:
                        transport(url, headers, timeout))
    monkeypatch.setattr("funddiff.cli.paths.snapshots_dir",
                        lambda data_dir=None, config=None, cwd=None:
                         tmp_path / "snapshots")
    monkeypatch.chdir(tmp_path)
    code = cli.main(["--store", str(store_file), "--data-dir", str(DATA_DIR),
                     "fetch", "--period", "2026Q3", "--json"] + list(extra_args))
    return code


@pytest.fixture
def watch_file(tmp_path):
    store_file = tmp_path / "watchlist.json"
    cli.main(["--store", str(store_file), "--data-dir", str(DATA_DIR),
              "watch", "add", "990001", "--name", "样例甲"])
    cli.main(["--store", str(store_file), "--data-dir", str(DATA_DIR),
              "watch", "add", "990002", "--name", "样例乙"])
    return store_file


def test_fetch_failure_isolation(monkeypatch, tmp_path, watch_file, capsys):
    """单只失败不影响其余：990001 成功、990002 失败，产物各归各。"""
    rows = [{"GPDM": "600001", "GPJC": "样例股票600001", "JZBL": "8.54%",
             "PCTNVCHGTYPE": "1", "PCTNVCHG": "0.50", "INDEXNAME": "医药生物"}]
    plan = GateTransport(lambda url: (200, json_body(rows), "u")
                         if "990001" in url else FetchError("超时", kind="timeout"))
    patch_endpoints(monkeypatch,
                    "https://api.example/FundMNInverstPosition",
                    "https://f10.example/FundArchivesDatas.aspx")
    capsys.readouterr()
    code = run_fetch(monkeypatch, tmp_path, watch_file, plan)
    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out)
    statuses = {item["fund_code"]: item["status"] for item in payload["funds"]}
    assert statuses == {"990001": "ok", "990002": "failed"}
    snapshots = tmp_path / "snapshots" / "q2026q3" / "holdings"
    assert (snapshots / "990001.json").exists()
    assert (snapshots / "990002.json").exists()
    failures = json.loads(
        (tmp_path / "snapshots" / "q2026q3" / "failures.json").read_text(
            encoding="utf-8"))
    assert [item["fund_code"] for item in failures] == ["990002"]
    assert failures[0]["error_kind"] == "timeout"


def test_fetch_blocked_returns_4_and_keeps_successful_results(
        monkeypatch, tmp_path, watch_file, capsys):
    """限频命中 → exit 4，已成功的结果保留。"""
    rows = [{"GPDM": "600001", "GPJC": "样例股票600001", "JZBL": "8.54%",
             "PCTNVCHGTYPE": "1", "PCTNVCHG": "0.50", "INDEXNAME": "医药生物"}]
    calls = {"n": 0}

    def plan(url):
        calls["n"] += 1
        if calls["n"] == 1:
            return (200, json_body(rows), "u")
        return FetchError("HTTP 429", kind="http_error", status=429)

    patch_endpoints(monkeypatch,
                    "https://api.example/FundMNInverstPosition",
                    "https://f10.example/FundArchivesDatas.aspx")
    capsys.readouterr()
    code = run_fetch(monkeypatch, tmp_path, watch_file, GateTransport(plan))
    captured = capsys.readouterr()
    assert code == cli.EXIT_UPSTREAM
    payload = json.loads(captured.out)
    statuses = {item["fund_code"]: item["status"] for item in payload["funds"]}
    assert statuses["990001"] == "ok"
    assert statuses["990002"] == "failed"
    assert payload["blocked_hosts"]
    assert (tmp_path / "snapshots" / "q2026q3" / "holdings" / "990001.json").exists()


def test_fetch_empty_watchlist_exits_1(monkeypatch, tmp_path, capsys):
    store_file = tmp_path / "empty.json"
    code = cli.main(["--store", str(store_file), "--data-dir", str(DATA_DIR),
                     "fetch"])
    assert code == cli.EXIT_GATE_FAILED


def test_fetch_invalid_period_exits_2(monkeypatch, tmp_path, watch_file):
    code = cli.main(["--store", str(watch_file), "--data-dir", str(DATA_DIR),
                     "fetch", "--period", "bad"])
    assert code == cli.EXIT_USAGE


def test_fetch_not_in_watchlist_exits_1(monkeypatch, tmp_path, watch_file):
    code = cli.main(["--store", str(watch_file), "--data-dir", str(DATA_DIR),
                     "fetch", "--fund", "999999"])
    assert code == cli.EXIT_GATE_FAILED


def test_fetch_writes_only_into_snapshots(monkeypatch, tmp_path, watch_file, capsys):
    """抓取产物只落 snapshots/（gitignore），仓库工作目录不得出现真实数据文件。"""
    rows = [{"GPDM": "600001", "GPJC": "样例股票600001", "JZBL": "8.54%",
             "PCTNVCHGTYPE": "1", "PCTNVCHG": "0.50", "INDEXNAME": "医药生物"}]
    plan = GateTransport(lambda url: (200, json_body(rows), "u"))
    patch_endpoints(monkeypatch,
                    "https://api.example/FundMNInverstPosition",
                    "https://f10.example/FundArchivesDatas.aspx")
    capsys.readouterr()
    code = run_fetch(monkeypatch, tmp_path, watch_file, plan)
    assert code == 0
    assert (tmp_path / "snapshots" / "q2026q3" / "holdings").is_dir()
    # 工作目录（tmp_path）下除 snapshots 与 watchlist 外没有新增数据文件
    entries = sorted(p.name for p in tmp_path.iterdir())
    assert entries == ["snapshots", "watchlist.json"]
