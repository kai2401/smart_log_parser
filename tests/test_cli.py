import unittest
import os
import sys
import tempfile
import shutil
import io
from contextlib import redirect_stdout
from unittest.mock import patch
import warnings

warnings.filterwarnings("ignore", category=ResourceWarning)

# Point DB_PATH to a temporary location before importing anything that might use it
import config  # noqa: E402
import database.db as db  # noqa: E402


class TestCLI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create a temporary directory for synthetic logs
        cls.temp_dir = tempfile.mkdtemp()
        cls.test_db_path = os.path.join(cls.temp_dir, "test_tool_logs.db")
        config.DB_PATH = cls.test_db_path

        # Import cli after setting DB_PATH
        import cli

        cls.cli = cli

    @classmethod
    def tearDownClass(cls):
        # Clean up temporary directory and database
        if os.path.exists(cls.temp_dir):
            shutil.rmtree(cls.temp_dir)

    def setUp(self):
        # Initialize an empty db for each test or rely on the commands to do it
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)
        db.init_db()

    def test_01_generate_and_ingest(self):
        """Test generation and ingestion of logs."""
        output_dir = os.path.join(self.temp_dir, "samples")

        # 1. Generate logs
        test_args = ["cli.py", "generate", "--output", output_dir]
        with patch.object(sys, "argv", test_args):
            f = io.StringIO()
            with redirect_stdout(f):
                self.cli.main()
            out = f.getvalue()
            self.assertIn("Generated", out)
            self.assertTrue(os.path.exists(output_dir))

        # Get list of generated files
        files = [
            os.path.join(output_dir, f)
            for f in os.listdir(output_dir)
            if os.path.isfile(os.path.join(output_dir, f))
        ]
        self.assertTrue(len(files) > 0, "No files generated")

        # 2. Ingest logs
        test_args = ["cli.py", "ingest"] + files
        with patch.object(sys, "argv", test_args):
            f = io.StringIO()
            with redirect_stdout(f):
                self.cli.main()
            out = f.getvalue()
            self.assertIn("Total stored", out)

        # Verify DB has entries
        stats = db.get_summary_stats()
        self.assertGreater(stats["total"], 0, "No records ingested into DB")

    def test_02_stats_and_query(self):
        """Test stats and query commands."""
        # First ingest some minimal data directly to DB for predictable querying
        db.insert_entries(
            [
                db.LogEntry(
                    id="test-1",
                    timestamp="2026-01-01T10:00:00",
                    tool_id="TEST-01",
                    log_type="test",
                    severity="ERROR",
                    raw_message="Test error",
                    drain_cluster_id=0,
                    metadata="{}",
                    source_format="test",
                    source_filename="test.log",
                    ai_summary="",
                    ai_classification="",
                    ai_root_cause_hint="",
                )
            ]
        )

        # Test stats
        test_args = ["cli.py", "stats"]
        with patch.object(sys, "argv", test_args):
            f = io.StringIO()
            with redirect_stdout(f):
                self.cli.main()
            out = f.getvalue()
            self.assertIn("Statistics: All Files", out)
            self.assertIn("Total Records", out)
            self.assertIn("TEST-01", out)

        # Test query
        test_args = ["cli.py", "query", "--tool", "TEST-01", "--severity", "ERROR"]
        with patch.object(sys, "argv", test_args):
            f = io.StringIO()
            with redirect_stdout(f):
                self.cli.main()
            out = f.getvalue()
            self.assertIn("Query Results", out)
            self.assertIn("TEST-01", out)
            self.assertIn("Test error", out)

    def test_03_export(self):
        """Test export command."""
        db.insert_entries(
            [
                db.LogEntry(
                    id="test-2",
                    timestamp="2026-01-01T10:00:00",
                    tool_id="TEST-02",
                    log_type="test",
                    severity="INFO",
                    raw_message="Test info",
                    drain_cluster_id=0,
                    metadata="{}",
                    source_format="test",
                    source_filename="test.log",
                    ai_summary="",
                    ai_classification="",
                    ai_root_cause_hint="",
                )
            ]
        )

        export_file = os.path.join(self.temp_dir, "export.json")
        test_args = ["cli.py", "export", export_file]
        with patch.object(sys, "argv", test_args):
            f = io.StringIO()
            with redirect_stdout(f):
                self.cli.main()
            out = f.getvalue()
            self.assertIn("Exported", out)

        self.assertTrue(os.path.exists(export_file))
        with open(export_file, "r") as f:
            content = f.read()
            self.assertIn("TEST-02", content)

    def test_04_clear(self):
        """Test clear command."""
        db.insert_entries(
            [
                db.LogEntry(
                    id="test-3",
                    timestamp="2026-01-01T10:00:00",
                    tool_id="TEST-03",
                    log_type="test",
                    severity="INFO",
                    raw_message="Test clear",
                    drain_cluster_id=0,
                    metadata="{}",
                    source_format="test",
                    source_filename="test.log",
                    ai_summary="",
                    ai_classification="",
                    ai_root_cause_hint="",
                )
            ]
        )

        self.assertGreater(db.get_summary_stats()["total"], 0)

        # Use -y to bypass confirmation
        test_args = ["cli.py", "clear", "-y"]
        with patch.object(sys, "argv", test_args):
            f = io.StringIO()
            with redirect_stdout(f):
                self.cli.main()
            out = f.getvalue()
            self.assertIn("All data cleared", out)

        self.assertEqual(db.get_summary_stats()["total"], 0)


if __name__ == "__main__":
    unittest.main(warnings="ignore")
