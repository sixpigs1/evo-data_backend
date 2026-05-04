import json
import unittest
from datetime import date
from types import SimpleNamespace

from app.collection.router import _assignment_response
from app.models import CollectionRunStatus


class FakeRunQuery:
    def __init__(self, runs):
        self.runs = runs

    def filter(self, *_args):
        return self

    def all(self):
        return list(self.runs)


class FakeDb:
    def __init__(self, runs):
        self.runs = runs

    def query(self, _model):
        return FakeRunQuery(self.runs)


def make_task():
    return SimpleNamespace(
        name="Pick task",
        task_prompt="pick the block",
        num_episodes=10,
        fps=20,
        episode_time_s=60,
        reset_time_s=10,
        use_cameras=True,
    )


def make_assignment():
    return SimpleNamespace(
        id="assignment-1",
        user_id="user-1",
        phone="13800138000",
        task_id="task-1",
        task=make_task(),
        target_date=date(2026, 5, 2),
        target_seconds=600,
        is_active=True,
    )


def make_run(status, duration_seconds, *, saved_episodes=0, metadata=None):
    metadata_json = json.dumps(metadata, separators=(",", ":")) if metadata is not None else None
    return SimpleNamespace(
        id=f"run-{status}-{duration_seconds}-{saved_episodes}",
        status=status,
        duration_seconds=duration_seconds,
        saved_episodes=saved_episodes,
        metadata_json=metadata_json,
    )


class CollectionProgressTest(unittest.TestCase):
    def test_assignment_progress_counts_failed_saved_partial_duration(self):
        runs = [
            make_run(CollectionRunStatus.finished, 100),
            make_run(CollectionRunStatus.active, 40),
            make_run(CollectionRunStatus.interrupted, 50),
            make_run(CollectionRunStatus.failed, 30, saved_episodes=3),
        ]

        response = _assignment_response(make_assignment(), FakeDb(runs))

        self.assertEqual(response.completed_seconds, 220)
        self.assertEqual(response.active_run_id, runs[1].id)

    def test_assignment_progress_excludes_failed_without_saved_local_data(self):
        runs = [
            make_run(CollectionRunStatus.finished, 10),
            make_run(CollectionRunStatus.failed, 80, saved_episodes=0),
            make_run(CollectionRunStatus.failed, 0, saved_episodes=3),
            make_run(
                CollectionRunStatus.failed,
                90,
                saved_episodes=3,
                metadata={"local_start_failed": True},
            ),
        ]

        response = _assignment_response(make_assignment(), FakeDb(runs))

        self.assertEqual(response.completed_seconds, 10)


if __name__ == "__main__":
    unittest.main()
