import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

PACKAGE = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(PACKAGE))
import desktop_sessions as sessions
import handoff


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="desktop-handoff-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / "中文 project $(unchanged)"
        self.project.mkdir()
        self.metadata = self.root / "desktop/account/folder"
        self.metadata.mkdir(parents=True)
        self.config = self.root / "config"
        self.logs = self.config / "projects/encoded-project"
        self.logs.mkdir(parents=True)
        self.sid = str(uuid.uuid4())
        self.transcript = self.logs / f"{self.sid}.jsonl"
        self.transcript.write_text("")
        self.metadata_file = self.metadata / f"local_{self.sid}.json"
        self.metadata_file.write_text(json.dumps({
            "cliSessionId": self.sid, "cwd": str(self.project), "title": "Continue my project",
            "remoteMcpServersConfig": {"credential": "must-not-be-copied"},
        }))

    def catalog(self):
        return sessions.catalog(self.root / "desktop", self.config)

    def write_messages(self, entries):
        self.transcript.write_text("\n".join(json.dumps(item) for item in entries))

    def entry(self, role, content):
        return {"sessionId": self.sid, "message": {"role": role, "content": content}}

    def test_discovers_only_existing_local_project_and_allowlisted_metadata(self):
        found = self.catalog()
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].session_id, self.sid)
        self.assertEqual(found[0].transcript, self.transcript)
        self.assertNotIn("must-not-be-copied", json.dumps(found[0].as_dict()))
        self.metadata_file.write_text(json.dumps({"cliSessionId": self.sid, "cwd": "ssh://host/project"}))
        self.assertEqual(self.catalog(), [])

    def test_corrupt_missing_and_duplicate_metadata_are_handled(self):
        (self.metadata / "local_broken.json").write_text("broken")
        (self.metadata / "local_missing.json").write_text(json.dumps({"cliSessionId": str(uuid.uuid4()), "cwd": "/does-not-exist"}))
        (self.metadata / "local_duplicate.json").write_text(self.metadata_file.read_text())
        self.assertEqual(len(self.catalog()), 1)

    def test_excerpt_retains_text_and_excludes_tool_results_images_and_thinking(self):
        self.write_messages([
            self.entry("user", "Need to fix orbit computation"),
            self.entry("assistant", [
                {"type": "thinking", "thinking": "hidden-reasoning"},
                {"type": "text", "text": "I changed the parser."},
                {"type": "tool_use", "input": {"secret": "tool-secret"}},
                {"type": "image", "source": {"data": "image-payload"}},
            ]),
            self.entry("user", [{"type": "tool_result", "content": "tool-result-secret"}]),
            {"sessionId": str(uuid.uuid4()), "message": {"role": "user", "content": "wrong-session"}},
        ])
        result = sessions.history_excerpt(self.catalog()[0])
        self.assertIn("Need to fix orbit", result)
        self.assertIn("changed the parser", result)
        for excluded in ("hidden-reasoning", "tool-secret", "image-payload", "tool-result-secret", "wrong-session"):
            self.assertNotIn(excluded, result)

    def test_excerpt_is_bounded_and_favors_recent_messages(self):
        self.write_messages([self.entry("user", "old message"), self.entry("assistant", "long " * 100),
                             self.entry("user", "latest task")])
        result = sessions.history_excerpt(self.catalog()[0], max_messages=2, max_message_chars=30)
        self.assertNotIn("old message", result)
        self.assertIn("latest task", result)
        self.assertIn("后文省略", result)

    def test_bookmark_keeps_original_transcript_notes_and_account_metadata_intact(self):
        self.write_messages([self.entry("user", "My current task")])
        original = self.transcript.read_bytes()
        metadata = self.metadata_file.read_bytes()
        folder, _ = handoff.prepare(self.project)
        (folder / "NOTES.md").write_text("Keep my decisions")
        folder, prompt = handoff.bookmark_session(self.catalog()[0])
        self.assertEqual(self.transcript.read_bytes(), original)
        self.assertEqual(self.metadata_file.read_bytes(), metadata)
        self.assertEqual((folder / "NOTES.md").read_text(), "Keep my decisions")
        self.assertIn("CONVERSATION.md", prompt)
        self.assertNotIn("must-not-be-copied", (folder / "session.json").read_text())
        handoff.prepare(self.project)
        self.assertIn("CONVERSATION.md", (folder / "接续工作提示词.txt").read_text())

    def test_open_uses_exact_official_arguments_and_original_project(self):
        session = self.catalog()[0]
        with patch.object(sessions.shutil, "which", return_value="/fake/claude"), \
             patch.object(sessions.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "Opened", "")) as run:
            self.assertEqual(sessions.open_session(session), "Opened")
        self.assertEqual(run.call_args.args[0], ["/fake/claude", "--desktop", "--resume", self.sid])
        self.assertEqual(run.call_args.kwargs["cwd"], self.project)
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_invalid_id_or_failed_resume_is_never_reported_successful(self):
        with self.assertRaises(ValueError):
            sessions.session_uuid("; bad command")
        with patch.object(sessions.shutil, "which", return_value="/fake/claude"), \
             patch.object(sessions.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "session still running")):
            with self.assertRaisesRegex(ValueError, "still running"):
                sessions.open_session(self.catalog()[0])

    def test_cancel_login_stage_keeps_bookmark_and_does_not_resume(self):
        session = self.catalog()[0]
        with patch.object(handoff, "select_session", return_value=session), \
             patch.object(handoff, "copy_text"), \
             patch.object(handoff, "dialog", side_effect=["账号 B", "稍后接续"]), \
             patch.object(handoff, "capture_git", return_value={"available": False, "reason": "test fixture"}), \
             patch.object(handoff.subprocess, "run"), \
             patch.object(sessions, "open_session") as open_session, \
             patch("builtins.print"):
            handoff.desktop_workflow(switch=True)
        open_session.assert_not_called()
        self.assertTrue((self.project / handoff.FOLDER / "session.json").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
