"""실시간 알림: 저장 성공마다 번호가 오르고, 기다리던 연결이 새 번호를 받는다."""
import asyncio

from app.operations_routes import Changes


def test_stream_sends_baseline_then_each_bump_and_cleans_up():
    async def scenario():
        changes = Changes()
        stream = changes.stream(keepalive=0.05)
        first = await anext(stream)
        assert first == f"data: {changes.boot}:0\n\n"
        changes.bump()
        assert await anext(stream) == f"data: {changes.boot}:1\n\n"
        assert (await anext(stream)).startswith(":")   # 조용하면 keepalive
        await stream.aclose()
        assert changes.waiting == set()
    asyncio.run(scenario())


def test_successful_writes_bump_but_reads_and_failures_do_not(client, app):
    before = app.state.changes.count
    client.get("/api/state")                      # 읽기
    client.post("/api/ledger", json={})           # 실패(노션 미설정 503)
    assert app.state.changes.count == before
