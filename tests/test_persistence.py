import pytest
from unittest.mock import AsyncMock, MagicMock
from xapp.persistence.redis_client import RedisClient
from xapp.persistence.pg_audit import PGAuditTrail

@pytest.mark.asyncio
async def test_redis_client():
    client = RedisClient()
    client.client = AsyncMock()
    
    await client.add_history("cell_1", {"latency_ms": 10})
    client.client.xadd.assert_called_once()
    args, kwargs = client.client.xadd.call_args
    assert args[0] == "astra:cell_1:kpi_history"
    
@pytest.mark.asyncio
async def test_pg_audit():
    audit = PGAuditTrail()
    audit.SessionLocal = MagicMock()
    mock_db = MagicMock()
    audit.SessionLocal.return_value = mock_db
    
    audit.append_event("cell_1", "ADMISSION_CONTROL", {"threshold": 90.0})
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()
    mock_db.close.assert_called_once()

