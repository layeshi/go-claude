import importlib.util
import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOL = Path(__file__).resolve().parents[1] / "src/handoff.py"
sys.path.insert(0, str(TOOL.parent))
spec = importlib.util.spec_from_file_location("handoff", TOOL)
handoff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handoff)


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="handoff-test-")
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "中文 project with spaces"
        self.project.mkdir()

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.project), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def initialize_repo(self):
        self.git("init")
        self.git("config", "user.name", "Test User")
        self.git("config", "user.email", "test@example.invalid")
        (self.project / "app.txt").write_text("initial\n")
        self.git("add", "app.txt")
        self.git("-c", "core.hooksPath=/dev/null", "commit", "-m", "fixture")

    def test_non_git_project_creates_notes_and_preserves_source_and_env(self):
        source = self.project / "app.py"
        source.write_text("print('hello')\n")
        secret = self.project / ".env"
        secret.write_text("SECRET_TEST_VALUE=do-not-copy-secret-content\n")
        folder, state = handoff.prepare(self.project)
        self.assertFalse(state["git"]["available"])
        self.assertEqual(source.read_text(), "print('hello')\n")
        self.assertEqual(secret.read_text(), "SECRET_TEST_VALUE=do-not-copy-secret-content\n")
        for path in folder.iterdir():
            self.assertNotIn("do-not-copy-secret-content", path.read_text())
        self.assertIn(str(self.project), (folder / "接续工作提示词.txt").read_text())
        self.assertEqual((folder / "state.json").stat().st_mode & 0o777, 0o600)

    @unittest.skipUnless(shutil.which("git"), "requires Git")
    def test_dirty_repo_snapshot_leaves_index_and_configuration_unchanged(self):
        self.initialize_repo()
        (self.project / "app.txt").write_text("staged change\n")
        self.git("add", "app.txt")
        (self.project / "app.txt").write_text("unstaged change\n")
        (self.project / "untracked file.txt").write_text("untracked\n")
        config = (self.project / ".git/config").read_bytes()
        index = (self.project / ".git/index").read_bytes()
        _, state = handoff.prepare(self.project)
        self.assertIn("MM app.txt", state["git"]["status"])
        self.assertIn("untracked file.txt", state["git"]["status"])
        self.assertNotIn(".claude-handoff", state["git"]["status"])
        self.assertEqual((self.project / ".git/config").read_bytes(), config)
        self.assertEqual((self.project / ".git/index").read_bytes(), index)
        self.assertEqual((self.project / "app.txt").read_text(), "unstaged change\n")

    def test_repeated_prepare_preserves_human_notes_and_creates_no_claude_settings(self):
        folder, _ = handoff.prepare(self.project)
        note = "# 已整理\n目标：修复计算；下一步：验证。\n"
        (folder / "NOTES.md").write_text(note)
        handoff.prepare(self.project)
        self.assertEqual((folder / "NOTES.md").read_text(), note)
        self.assertFalse((self.project / "CLAUDE.md").exists())
        self.assertFalse((self.project / ".claude").exists())
        self.assertFalse((self.project / ".gitignore").exists())

    def test_existing_unowned_folder_is_never_overwritten(self):
        folder = self.project / handoff.FOLDER
        folder.mkdir()
        (folder / "NOTES.md").write_text("original")
        with self.assertRaises(ValueError):
            handoff.prepare(self.project)
        self.assertEqual((folder / "NOTES.md").read_text(), "original")
        self.assertEqual([p.name for p in folder.iterdir()], ["NOTES.md"])

    def test_symlink_folder_and_generated_file_are_rejected(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        link = self.project / handoff.FOLDER
        link.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            handoff.prepare(self.project)
        self.assertEqual(list(outside.iterdir()), [])
        link.unlink()
        folder, _ = handoff.prepare(self.project)
        state = folder / "state.json"
        state.unlink()
        target = outside / "state.json"
        target.write_text("keep")
        state.symlink_to(target)
        with self.assertRaises(ValueError):
            handoff.prepare(self.project)
        self.assertEqual(target.read_text(), "keep")

    def test_missing_git_still_allows_manual_handoff(self):
        with patch.object(handoff.subprocess, "run", side_effect=FileNotFoundError):
            folder, state = handoff.prepare(self.project)
        self.assertFalse(state["git"]["available"])
        self.assertIn("未找到 Git", state["git"]["reason"])
        self.assertTrue((folder / "NOTES.md").exists())

    def test_git_timeout_is_reported_instead_of_fake_clean_state(self):
        with patch.object(handoff.subprocess, "run", side_effect=subprocess.TimeoutExpired("git", 20)):
            _, state = handoff.prepare(self.project)
        self.assertFalse(state["git"]["available"])
        self.assertIn("超时", state["git"]["reason"])

    def test_path_with_shell_characters_is_passed_as_data(self):
        project = Path(self.temp.name) / "project $(touch SHOULD_NOT_EXIST) `echo ignored`"
        project.mkdir()
        result = subprocess.run([sys.executable, str(TOOL), "resume", str(project)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(project), result.stdout)
        self.assertFalse((project / "SHOULD_NOT_EXIST").exists())
        state = json.loads((project / handoff.FOLDER / "state.json").read_text())
        self.assertEqual(Path(state["project"]), project.resolve())

    @unittest.skipUnless(shutil.which("git"), "requires Git")
    def test_worktree_path_and_branch_are_preserved(self):
        self.initialize_repo()
        worktree = Path(self.temp.name) / "actual worktree"
        self.git("worktree", "add", "-b", "handoff-test", str(worktree))
        _, state = handoff.prepare(worktree)
        self.assertEqual(Path(state["project"]), worktree.resolve())
        self.assertEqual(state["git"]["branch"], "handoff-test")
        self.assertEqual(Path(state["git"]["root"]).resolve(), worktree.resolve())

    def test_ui_saving_only_copies_prompt_and_keeps_note_as_template(self):
        with patch.object(handoff.sys, "platform", "darwin"), \
             patch.object(handoff, "dialog", side_effect=["保存进度：复制整理提示词", str(self.project)]), \
             patch.object(handoff, "copy_text") as clipboard, \
             patch("builtins.print"):
            handoff.ui()
        clipboard.assert_called_once()
        self.assertIn("更新交接笔记", clipboard.call_args.args[0])
        self.assertIn("尚未填写", (self.project / handoff.FOLDER / "NOTES.md").read_text())

    def test_cli_invalid_arguments_do_not_create_project_files(self):
        result = subprocess.run([sys.executable, str(TOOL), "prepare", str(self.project), "--copy"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.project / handoff.FOLDER).exists())

    @unittest.skipUnless(shutil.which("osacompile"), "requires macOS AppleScript compiler")
    def test_all_native_dialogs_compile(self):
        scripts = [node.args[0].value for node in ast.walk(ast.parse(TOOL.read_text()))
                   if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                   and node.func.id == "dialog" and isinstance(node.args[0], ast.Constant)]
        self.assertGreaterEqual(len(scripts), 5)
        for index, script in enumerate(scripts):
            result = subprocess.run(["osacompile", "-o", str(self.project / f"dialog-{index}.scpt"), "-"],
                                    input=script, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
