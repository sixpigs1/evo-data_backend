import unittest
from types import SimpleNamespace

from app.collection.oss_paths import collection_run_id_from_raw_oss_path, collection_run_raw_oss_path


class CollectionOssPathsTest(unittest.TestCase):
    def test_collection_run_raw_path_groups_raw_before_collection_runs(self):
        run = SimpleNamespace(
            id="run-1",
            org_id="org-1",
            user_id="user-1",
            dataset_name="cloud dataset",
        )

        oss_path = collection_run_raw_oss_path(run, "dev")

        self.assertEqual(
            oss_path,
            "dev/orgs/org-1/users/user-1/raw/collection-runs/run-1/cloud-dataset/",
        )
        self.assertEqual(
            collection_run_id_from_raw_oss_path(oss_path, "dev", "user-1"),
            "run-1",
        )

    def test_old_collection_run_raw_path_is_not_authorized(self):
        oss_path = "dev/orgs/org-1/users/user-1/collection-runs/run-1/raw/cloud-dataset/"

        self.assertIsNone(collection_run_id_from_raw_oss_path(oss_path, "dev", "user-1"))


if __name__ == "__main__":
    unittest.main()
