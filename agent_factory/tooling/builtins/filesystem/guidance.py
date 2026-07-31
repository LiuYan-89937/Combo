"""Shared guidance for selecting the filesystem write strategy."""

WRITE_STRATEGY_GUIDANCE = (
    "写入前必须先选择一种策略。若当前已经拥有单个文件的完整最终正文，且能够在一次工具调用中可靠提供全部内容，"
    "使用 action=write_once；该操作会整体替换目标文件，不适用于局部修改。若正文还会按章节、模块或代码单元继续生成，"
    "无法确认一次参数能够完整传输，或需要在生成过程中保留进度，使用 action=start，随后按顺序以完整语义块调用 "
    "action=append，全部完成后仅调用一次 action=commit；放弃时调用 action=abort。策略依据是正文是否完整以及一次调用的"
    "传输可靠性，不是文件在磁盘上的字节数；append 不应拆成随机 token 或零散行。已有文件的局部修改、多文件变更、"
    "移动、复制和删除使用 edit。禁止省略 action，不能只传 path 和 content。"
)

