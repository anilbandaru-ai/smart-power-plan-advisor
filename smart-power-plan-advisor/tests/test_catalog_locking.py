import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from backend.catalog.locking import catalog_lock


class LockTests(unittest.TestCase):
    def test_cross_process_contention_and_release(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.lock"
            script = "from pathlib import Path; from backend.catalog.locking import catalog_lock; import sys\nwith catalog_lock(Path(sys.argv[1])): print('acquired')"
            with self.assertRaisesRegex(RuntimeError, "test exit"):
                with catalog_lock(path):
                    blocked = subprocess.run([sys.executable, "-c", script, str(path)], capture_output=True, text=True, timeout=15)
                    self.assertNotEqual(blocked.returncode, 0)
                    self.assertIn("Another catalog sync is running", blocked.stderr)
                    raise RuntimeError("test exit")
            released = subprocess.run([sys.executable, "-c", script, str(path)], capture_output=True, text=True, timeout=15)
            self.assertEqual(released.returncode, 0, released.stderr)
            self.assertIn("acquired", released.stdout)
