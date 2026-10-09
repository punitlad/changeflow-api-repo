import json

import pytest

from changeflow.change_request import AlreadyOnboarded, append_team
from changeflow.pipeline import reviewable_environment_ids


def test_append_to_keyed_array():
    out = append_team(json.dumps({"teams": [{"team": "a"}]}), "b", "teams")
    assert json.loads(out) == {"teams": [{"team": "a"}, {"team": "b"}]}
    assert out.endswith("\n")


def test_append_to_root_array():
    out = append_team("[]", "a", "")
    assert json.loads(out) == [{"team": "a"}]


def test_duplicate_is_rejected():
    with pytest.raises(AlreadyOnboarded):
        append_team(json.dumps({"teams": [{"team": "a"}]}), "a", "teams")


def test_only_approvable_envs_selected():
    pending = [
        {"environment": {"id": 1, "name": "prod"}, "current_user_can_approve": True},
        {"environment": {"id": 2, "name": "staging"}, "current_user_can_approve": False},
        {"environment": {"id": 3, "name": "dev"}, "current_user_can_approve": True},
    ]
    assert reviewable_environment_ids(pending, None) == [1, 3]
    assert reviewable_environment_ids(pending, "prod") == [1]
