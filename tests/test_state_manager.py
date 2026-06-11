import pytest
import asyncio
from xapp.state import StateManager

@pytest.mark.asyncio
async def test_state_manager_multi_cell():
    manager = StateManager()
    
    state1 = manager.get_state("cell_1")
    state2 = manager.get_state("cell_2")
    
    assert state1.cell_id == "cell_1"
    assert state2.cell_id == "cell_2"
    assert state1 is not state2
    
    state1_again = manager.get_state("cell_1")
    assert state1 is state1_again
    
@pytest.mark.asyncio
async def test_state_manager_concurrency():
    manager = StateManager()
    
    async def get_state_async(cell_id):
        # simulate some async work
        await asyncio.sleep(0.01)
        return manager.get_state(cell_id)
        
    tasks = [get_state_async("cell_x") for _ in range(100)]
    results = await asyncio.gather(*tasks)
    
    # All 100 concurrent requests should yield the exact same LiveState instance
    first_state = results[0]
    for r in results:
        assert r is first_state
