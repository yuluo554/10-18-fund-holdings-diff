"""跨模块异常类型。

NotReady 表示"该能力尚未落地"——CLI 层统一映射为退出码 3（既定契约，非故障）。
用它替代 Python 内置的"未实现"异常：后者是"代码写漏了"的信号，会被桩哨兵扫描判为缺陷，
也无法携带"目标里程碑"这类可读信息。
"""


class NotReady(Exception):
    def __init__(self, capability, stage):
        Exception.__init__(self, "%s 将在 %s 实现" % (capability, stage))
        self.capability = capability
        self.stage = stage
