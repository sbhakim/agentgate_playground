import pytest

from app.scenarios import preset_policy
from app.sessions import Session


@pytest.fixture
def make_session():
    def _make(preset="sensitive", **policy_overrides):
        policy = preset_policy(preset).model_copy(update=policy_overrides)
        return Session(id="test", run_id=1, policy=policy, status="running")
    return _make
