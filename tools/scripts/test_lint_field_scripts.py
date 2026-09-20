#!/usr/bin/env python3
# ABOUTME: Tests for lint_field_scripts.py, the field script checker.
# ABOUTME: Run with `python3 -m unittest tools/scripts/test_lint_field_scripts.py`.

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import fieldscript as fs  # noqa: E402
import lint_field_scripts as lint  # noqa: E402

HEADER = '#include "macros/scrcmd.inc"\n\n'


def parse(body):
    """Parse a script written inline, as a real file on disk."""
    with tempfile.NamedTemporaryFile("w", suffix=".s", delete=False) as handle:
        handle.write(HEADER + body)
        path = handle.name
    return fs.parse_script(path)


def findings_for(check, body, **kwargs):
    script = parse(body)
    report = lint.Report()
    check(script, report, **kwargs) if kwargs else check(script, report)
    return [message for _, _, message in report.findings]


class TestLabels(unittest.TestCase):
    def test_entry_naming_missing_label_is_flagged(self):
        found = findings_for(lint.check_labels, """
    ScriptEntry Map_Present
    ScriptEntry Map_Absent
    ScriptEntryEnd

Map_Present:
    End
""")
        self.assertTrue(any("Map_Absent" in f for f in found), found)

    def test_branch_to_undefined_label_is_flagged(self):
        found = findings_for(lint.check_labels, """
    ScriptEntry Map_Talk
    ScriptEntryEnd

Map_Talk:
    GoTo Map_Nowhere
""")
        self.assertTrue(any("Map_Nowhere" in f for f in found), found)

    def test_applymovement_to_non_movement_block_is_flagged(self):
        found = findings_for(lint.check_labels, """
    ScriptEntry Map_Scene
    ScriptEntryEnd

Map_Scene:
    ApplyMovement LOCALID_PLAYER, Map_NotAMovement
    End

Map_NotAMovement:
    End
""")
        self.assertTrue(any("does not end in EndMovement" in f for f in found), found)

    def test_unaligned_movement_block_after_code_is_flagged(self):
        found = findings_for(lint.check_labels, """
    ScriptEntry Map_Scene
    ScriptEntryEnd

Map_Scene:
    ApplyMovement LOCALID_PLAYER, Map_Movement_Walk
    End

Map_Movement_Walk:
    WalkNormalNorth
    EndMovement
""")
        self.assertTrue(any(".balign" in f for f in found), found)

    def test_consecutive_movement_blocks_need_only_one_align(self):
        # Movement actions are 4 bytes each, so the second block is already
        # aligned and must not be reported.
        found = findings_for(lint.check_labels, """
    ScriptEntry Map_Scene
    ScriptEntryEnd

Map_Scene:
    ApplyMovement LOCALID_PLAYER, Map_Movement_One
    ApplyMovement LOCALID_RIVAL, Map_Movement_Two
    End

    .balign 4, 0
Map_Movement_One:
    WalkNormalNorth
    EndMovement

Map_Movement_Two:
    WalkNormalSouth
    EndMovement
""")
        self.assertEqual([], [f for f in found if ".balign" in f])

    def test_clean_script_produces_nothing(self):
        self.assertEqual([], findings_for(lint.check_labels, """
    ScriptEntry Map_Talk
    ScriptEntryEnd

Map_Talk:
    NPCMessage Map_Text_Hello
    End
"""))


class TestLocks(unittest.TestCase):
    def test_lock_with_no_release_anywhere_is_flagged(self):
        found = findings_for(lint.check_locks, """
    ScriptEntry Map_Talk
    ScriptEntryEnd

Map_Talk:
    LockAll
    FacePlayer
    Message Map_Text_Hello
    WaitButton
    CloseMessage
    End
""")
        self.assertTrue(any("nothing reachable" in f for f in found), found)

    def test_lock_with_release_is_clean(self):
        self.assertEqual([], findings_for(lint.check_locks, """
    ScriptEntry Map_Talk
    ScriptEntryEnd

Map_Talk:
    LockAll
    Message Map_Text_Hello
    WaitButton
    CloseMessage
    ReleaseAll
    End
"""))

    def test_release_reached_by_fall_through_is_clean(self):
        # Execution runs on into the next label; the checker must model that.
        self.assertEqual([], findings_for(lint.check_locks, """
    ScriptEntry Map_Talk
    ScriptEntryEnd

Map_Talk:
    LockAll
    Message Map_Text_Hello

Map_TalkFinish:
    CloseMessage
    ReleaseAll
    End
"""))

    def test_warp_hand_off_is_clean(self):
        # Locking and then warping away is a normal, intentional pattern.
        self.assertEqual([], findings_for(lint.check_locks, """
    ScriptEntry Map_Stairs
    ScriptEntryEnd

Map_Stairs:
    LockAll
    FadeScreenOut
    WaitFadeScreen
    Warp MAP_HEADER_TWINLEAF_TOWN, 12, 30, DIR_NORTH
    End
"""))

    def test_npcmessage_locks_and_releases_internally(self):
        # The composite macro balances itself; deriving that from scrcmd.inc
        # is what keeps this from being a false positive.
        self.assertEqual([], findings_for(lint.check_locks, """
    ScriptEntry Map_Talk
    ScriptEntryEnd

Map_Talk:
    NPCMessage Map_Text_Hello
    End
"""))

    def test_strict_flags_one_branch_that_forgets_release(self):
        found = findings_for(lint.check_locks_strict, """
    ScriptEntry Map_Talk
    ScriptEntryEnd

Map_Talk:
    LockAll
    GoToIfSet FLAG_HAS_POKEDEX, Map_TalkAfter
    Message Map_Text_Before
    CloseMessage
    ReleaseAll
    End

Map_TalkAfter:
    Message Map_Text_After
    CloseMessage
    End
""")
        self.assertTrue(any("Map_TalkAfter" in f for f in found), found)


class TestEvents(unittest.TestCase):
    TABLE = """
    ScriptEntry Map_One
    ScriptEntry Map_Two
    ScriptEntryEnd

Map_One:
    End

Map_Two:
    End
"""

    def _check(self, events=None, init_body=None):
        script = parse(self.TABLE)
        init = parse(init_body) if init_body else None
        report = lint.Report()
        lint.check_events(script, events, init, report)
        return [message for _, _, message in report.findings]

    def test_index_past_end_of_table_is_flagged(self):
        events = {"object_events": [{"id": "LOCALID_NPC", "script": 7}]}
        found = self._check(events)
        self.assertTrue(any("only 2 entries" in f for f in found), found)

    def test_valid_index_is_clean(self):
        self.assertEqual([], self._check(
            {"object_events": [{"id": "LOCALID_NPC", "script": 2}]}))

    def test_no_script_sentinels_are_clean(self):
        self.assertEqual([], self._check({"object_events": [
            {"id": "LOCALID_A", "script": 0},
            {"id": "LOCALID_B", "script": 65535},
        ]}))

    def test_shared_script_range_is_clean(self):
        # 10001 routes to scripts_field_moves, not to this map's table.
        self.assertEqual([], self._check(
            {"object_events": [{"id": "LOCALID_TREE", "script": 10001}]}))

    def test_init_script_past_end_of_table_is_flagged(self):
        found = self._check(init_body="    InitScriptEntry_OnTransition 9\n"
                                      "    InitScriptEntryEnd\n\n"
                                      "    InitScriptEnd\n")
        self.assertTrue(any("only 2 entries" in f for f in found), found)

    def test_init_script_shared_range_is_clean(self):
        self.assertEqual([], self._check(
            init_body="    InitScriptEntry_OnTransition 10200\n"
                      "    InitScriptEntryEnd\n\n"
                      "    InitScriptEnd\n"))


class TestMessages(unittest.TestCase):
    BANK = {"Map_Text_Known": 0}

    def _check(self, body):
        script = parse(body)
        report = lint.Report()
        lint.check_messages(script, self.BANK, report)
        return [message for _, _, message in report.findings]

    def test_unknown_message_id_is_flagged(self):
        found = self._check("""
    ScriptEntry Map_Talk
    ScriptEntryEnd

Map_Talk:
    Message Map_Text_Missing
    End
""")
        self.assertTrue(any("Map_Text_Missing" in f for f in found), found)

    def test_known_message_id_is_clean(self):
        self.assertEqual([], self._check("""
    ScriptEntry Map_Talk
    ScriptEntryEnd

Map_Talk:
    Message Map_Text_Known
    End
"""))

    def test_message_from_variable_is_clean(self):
        self.assertEqual([], self._check("""
    ScriptEntry Map_Talk
    ScriptEntryEnd

Map_Talk:
    Message VAR_0x8004
    End
"""))


if __name__ == "__main__":
    unittest.main()
