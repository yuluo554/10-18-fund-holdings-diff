"""东财抓取（M2 实现）。占位模块，用于固定依赖方向与命名。

骨架期一律抛 NotReady（CLI 映射为退出码 3）。
"""

from ..errors import NotReady

STAGE = "M2"


def fetch_position_json(config, fund_code, report_period):
    raise NotReady("FundMNInverstPosition JSON 通道", STAGE)


def fetch_position_page(config, fund_code, report_period):
    raise NotReady("jjcc 页面通道（GBK + 内嵌 JS 正则）", STAGE)


def fetch_scale(config, fund_code, report_period):
    raise NotReady("gmbd 规模变动", STAGE)


def fetch_managers(config, fund_code):
    raise NotReady("jjjl 经理变更", STAGE)


def fetch_fund_codes(config, cache_path=None):
    raise NotReady("fundcode_search.js 按需缓存", STAGE)
