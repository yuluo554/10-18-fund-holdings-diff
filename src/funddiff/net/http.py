"""HTTP 抓取：超时、重定向、限频、指数退避（M2 填充实现）。

M0 契约：
- 参数全部来自配置（rate_limit 段），代码里不写第二份口径；
- 命中 429/403/验证码/登录 → 停止该域名后续请求并抛 FetchError(kind="blocked")；
- 解码失败抛 FetchError(kind="decode_error") 并保留原始字节，不做 errors="ignore"。
"""


class FetchError(Exception):
    def __init__(self, message, kind="fetch_error", status=None, raw=None):
        Exception.__init__(self, message)
        self.kind = kind
        self.status = status
        self.raw = raw


class Fetcher(object):
    """M2 实现。当前仅保存配置，供调用方注入。"""

    def __init__(self, config, cache_dir=None):
        self.config = config
        self.cache_dir = cache_dir
        self._blocked_hosts = set()

    def get(self, url, headers=None):
        from ..errors import NotReady
        raise NotReady("HTTP 抓取（超时 / 限频 / 退避）", "M2")
