import pytest
from httpx import ASGITransport, AsyncClient

from deepfolder.main import create_app


@pytest.mark.asyncio
async def test_health_returns_ok() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
