"""冒烟测试共用：把“一次性返回结果”的假沙盒包成 sandbox_client.stream 的形状（只产出最后一行 exit）。"""


def streamed(run):
    async def stream(project_id, command, timeout=60, stdin=None, **kw):
        yield {"type": "exit", **await run(project_id, command, timeout)}
    return stream
