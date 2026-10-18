"""证监会 eid 在线抓取（M2 实现）。占位模块。"""

from ..errors import NotReady

STAGE = "M2"


def fetch_public_metadata(config):
    raise NotReady("indexPublicData.json 元数据抓取", STAGE)
