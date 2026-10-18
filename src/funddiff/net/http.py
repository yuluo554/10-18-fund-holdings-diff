"""HTTP 抓取：超时、重定向、限频、指数退避（M2）。

纪律：
- 参数全部来自配置 rate_limit（K10 同源纪律），代码里不写第二份口径；
- 同域名串行 + 固定最小间隔；瞬时失败指数退避，总等待封顶 max_total_wait；
- 命中 stop_on（429 / 403 / 验证码 / 登录墙）→ 封锁该域名后续请求，
  FetchError(kind=<命中类别>)，由调用方落台账并映射退出码 4；
- 本层只搬运字节，解码是调用方（eastmoney）的事，绝不 errors="ignore"。

网络库 import 只允许出现在 funddiff/net/ 包内（K6，AST 门禁现成）。
"""

import time
import urllib.error
import urllib.parse
import urllib.request

# 瞬时失败：允许退避重试。其余 kind（http_error 等）直接上抛。
RETRYABLE_KINDS = ("timeout", "network_error", "http_5xx")

# stop_on 里登记的"上游拒绝服务"类别：命中即封锁域名，不做退避重试。
HARD_BLOCK_KINDS = ("http_429", "http_403", "captcha", "login_redirect")

_CAPTCHA_MARKERS = ("验证码", "captcha", "Captcha", "CAPTCHA")
_LOGIN_MARKERS = ("login", "Login", "passport", "登录")


class FetchError(Exception):
    """抓取失败。kind 标注类别；raw 保留原始字节（调用方落证据用）。"""

    def __init__(self, message, kind="fetch_error", status=None, raw=None, url=None):
        Exception.__init__(self, message)
        self.kind = kind
        self.status = status
        self.raw = raw
        self.url = url


def _urllib_transport(url, headers, timeout):
    """默认传输：urllib，自动跟随重定向。返回 (status, body_bytes, final_url)。"""
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.getcode(), response.read(), response.geturl()
    except urllib.error.HTTPError as exc:
        body = exc.read() if hasattr(exc, "read") else b""
        raise FetchError(
            "HTTP %s：%s" % (exc.code, url),
            kind="http_error", status=exc.code, raw=body, url=url)
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise FetchError("网络错误：%s（%s）" % (url, exc),
                         kind="network_error", url=url)


class Fetcher(object):
    """同域串行 + 固定最小间隔 + 指数退避的抓取器。

    transport 可注入（测试用假传输），签名：
        transport(url, headers, timeout) -> (status, body_bytes, final_url)
    失败以 FetchError 表达，kind ∈ timeout / network_error / http_5xx / http_error。
    """

    def __init__(self, config, transport=None, sleeper=None, clock=None):
        rate_limit = config["rate_limit"]
        self.min_interval = float(rate_limit["min_interval_seconds"])
        self.timeout = float(rate_limit["timeout_seconds"])
        self.max_retries = int(rate_limit["max_retries"])
        self.backoff_initial = float(rate_limit["backoff_initial_seconds"])
        self.backoff_factor = float(rate_limit["backoff_factor"])
        self.backoff_max = float(rate_limit["backoff_max_seconds"])
        self.max_total_wait = float(rate_limit["max_total_wait_seconds"])
        self.stop_on = tuple(rate_limit["stop_on"])
        self._transport = transport or _urllib_transport
        self._sleeper = sleeper or time.sleep
        self._clock = clock or time.monotonic
        self._blocked = {}          # host -> 命中的 stop_on 类别
        self._last_request_at = {}  # host -> 上次请求时刻（monotonic）

    def is_blocked(self, url):
        return urllib.parse.urlsplit(url).netloc in self._blocked

    def blocked_hosts(self):
        return dict(self._blocked)

    def get(self, url, headers=None):
        """抓取一个 URL，返回 (status, body_bytes, final_url)。

        退避重试只针对瞬时失败（超时 / 网络错误 / 5xx）；
        stop_on 类别立即封锁域名并抛 FetchError(kind=...)，不消耗重试。
        """
        host = urllib.parse.urlsplit(url).netloc
        if host in self._blocked:
            kind = self._blocked[host]
            raise FetchError(
                "域名 %s 已因 %s 被封锁，跳过后续请求" % (host, kind),
                kind="blocked", url=url)

        attempts = self.max_retries + 1
        wait_total = 0.0
        last_error = None
        for attempt in range(attempts):
            self._throttle(host)
            try:
                status, body, final_url = self._transport(url, headers, self.timeout)
            except FetchError as exc:
                last_error = exc
                matched = self._match_stop_on(exc)
                if matched:
                    self._blocked[host] = matched
                    raise FetchError(
                        "命中 stop_on（%s）：%s" % (matched, url),
                        kind=matched, status=exc.status, raw=exc.raw, url=url)
                if exc.kind not in RETRYABLE_KINDS or attempt == attempts - 1:
                    raise
            else:
                status_text = str(status)
                if status_text == "429" and "http_429" in self.stop_on:
                    self._blocked[host] = "http_429"
                    raise FetchError("HTTP 429（限频）：%s" % url,
                                     kind="http_429", status=429, raw=body, url=url)
                if status_text == "403" and "http_403" in self.stop_on:
                    self._blocked[host] = "http_403"
                    raise FetchError("HTTP 403（拒绝访问）：%s" % url,
                                     kind="http_403", status=403, raw=body, url=url)
                matched = self._sniff_stop_on(body, final_url)
                if matched:
                    self._blocked[host] = matched
                    raise FetchError("命中 stop_on（%s）：%s" % (matched, url),
                                     kind=matched, status=status, raw=body, url=url)
                if status_text.startswith("5"):
                    last_error = FetchError("HTTP %s（服务端错误）：%s" % (status, url),
                                            kind="http_5xx", status=status,
                                            raw=body, url=url)
                    if attempt == attempts - 1:
                        raise last_error
                else:
                    return status, body, final_url
            delay = self._backoff_delay(attempt)
            wait_total += delay
            if wait_total > self.max_total_wait:
                raise FetchError(
                    "退避总等待超过 max_total_wait（%.1fs）：%s"
                    % (self.max_total_wait, url),
                    kind=last_error.kind if last_error else "network_error",
                    status=getattr(last_error, "status", None), url=url)
            self._sleeper(delay)
        raise last_error  # pragma: no cover - 循环的每个分支都已 raise/return

    def _throttle(self, host):
        """同域串行 + 固定最小间隔（K10：间隔值来自配置）。"""
        now = self._clock()
        last = self._last_request_at.get(host)
        if last is not None:
            remaining = self.min_interval - (now - last)
            if remaining > 0:
                self._sleeper(remaining)
                now = self._clock()
        self._last_request_at[host] = now

    def _backoff_delay(self, attempt):
        delay = self.backoff_initial * (self.backoff_factor ** attempt)
        return min(delay, self.backoff_max)

    def _match_stop_on(self, exc):
        """把请求层异常映射到 stop_on 登记的类别。"""
        if exc.kind in self.stop_on:
            return exc.kind
        status_text = str(exc.status)
        if status_text == "429" and "http_429" in self.stop_on:
            return "http_429"
        if status_text == "403" and "http_403" in self.stop_on:
            return "http_403"
        return None

    def _sniff_stop_on(self, body, final_url):
        """响应嗅探：验证码页与登录墙（传输层不分类，只能在这里识别）。"""
        if body:
            text = body.decode("utf-8", "replace")
            if any(marker in text for marker in _CAPTCHA_MARKERS):
                if "captcha" in self.stop_on:
                    return "captcha"
        if final_url:
            for marker in _LOGIN_MARKERS:
                if marker in final_url and "login_redirect" in self.stop_on:
                    return "login_redirect"
        return None
