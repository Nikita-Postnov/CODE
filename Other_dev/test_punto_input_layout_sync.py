"""Punto: corrected text must synchronize the active Windows input language.

Run on Linux or Windows: mocks Win32, never changes the host keyboard layout.
"""
import unittest
from unittest.mock import Mock, patch

import punto_like_work_safe as punto


class FakeWindows:
    def __init__(self, current=0x04090409, foreground=101):
        self.foreground = foreground
        self.current = current
        self.thread = 55
        self.loaded = []
        self.posts = []
        self.on_post = None
        self.focus_thread = 66
        self.layout_threads = []

    def GetForegroundWindow(self):
        return self.foreground

    def GetWindowThreadProcessId(self, hwnd, _pid):
        assert hwnd in (101, 222), f"Should not touch unrelated hwnd={hwnd}"
        return self.focus_thread if hwnd == 222 else self.thread

    def GetKeyboardLayout(self, tid):
        assert tid in (self.thread, self.focus_thread)
        self.layout_threads.append(tid)
        return self.current

    def LoadKeyboardLayoutW(self, name, flags):
        self.loaded.append((name,flags))
        return 0x04190419 if name == punto.LAYOUT_RU else 0x04090409

    def PostMessageW(self, hwnd, msg, wp, lp):
        self.posts.append((hwnd,msg,wp,lp))
        if self.on_post:
            self.on_post()
        return 1


class PuntoLayoutSyncTests(unittest.TestCase):
    def setUp(self):
        self.fake=FakeWindows()
        self.send=Mock(return_value=True)
        self.sleep=Mock()
        self.patches=[
            patch.object(punto,'user32',self.fake),
            patch.object(punto,'_sendmsg_ok',self.send),
            patch.object(punto.time,'sleep',self.sleep),
            patch.object(punto,'_hkl_cache',{}),
        ]
        for p in self.patches:p.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])

    def test_auto_correction_changes_focused_child_input_language(self):
        """After the corrected word, the next keystroke must use its layout."""
        self.fake.GetGUIThreadInfo = Mock(return_value=True)
        with (patch.object(punto, "_get_focused_control_hwnd", return_value=222),
              patch.object(punto, "_settings", Mock(auto_layout_correction=True)),
              patch.object(punto, "_layout_words", frozenset({"привет"})),
              patch.object(punto, "_candidate_layout_correction", return_value="привет"),
              patch.object(punto, "_replace_range_in_edit_safely", return_value=True)):
            def change(hwnd, msg, wparam, lparam, timeout_ms):
                self.assertEqual(hwnd, 222, "Language request must reach focused Edit")
                self.fake.current = lparam
                return True
            self.send.side_effect = change
            self.assertTrue(punto._try_auto_layout_in_edit(222, "ghbdtn ", 6, 7))
        self.assertEqual(self.fake.current & 0xFFFF, 0x0419)
        self.assertEqual(self.fake.layout_threads[-1], self.fake.focus_thread)
        self.assertEqual(self.fake.posts, [])

    def test_focused_child_receives_request_before_foreground(self):
        self.fake.GetGUIThreadInfo = Mock(return_value=True)
        with patch.object(punto, "_get_focused_control_hwnd", return_value=222):
            self.send.side_effect = lambda hwnd, msg, wp, lp, timeout_ms: (
                setattr(self.fake, "current", lp) or True
            ) if hwnd == 222 else self.fail("Unexpected parent request")
            self.assertTrue(punto._switch_input_language_for_foreground(punto.LAYOUT_RU, 101))
        self.assertEqual(self.send.call_args.args[0], 222)
        self.assertEqual(self.fake.layout_threads[-1], self.fake.focus_thread)

    def test_parent_fallback_when_focused_control_ignores_language_request(self):
        self.fake.GetGUIThreadInfo = Mock(return_value=True)
        def receive(hwnd, msg, wparam, lparam, timeout_ms):
            if hwnd == 101:
                self.fake.current = lparam
            return True
        self.send.side_effect = receive
        with patch.object(punto, "_get_focused_control_hwnd", return_value=222):
            self.assertTrue(punto._switch_input_language_for_foreground(punto.LAYOUT_RU, 101))
        self.assertEqual([c.args[0] for c in self.send.call_args_list], [222, 222, 101])
        self.assertEqual(self.fake.posts, [])

    def test_focus_switch_during_delivery_aborts_even_if_foreground_is_same(self):
        self.fake.GetGUIThreadInfo = Mock(return_value=True)
        focus = [222]
        def receive(hwnd, msg, wparam, lparam, timeout_ms):
            focus[0] = 333
            return True
        self.send.side_effect = receive
        with patch.object(punto, "_get_focused_control_hwnd", side_effect=lambda: focus[0]):
            self.assertFalse(punto._switch_input_language_for_foreground(punto.LAYOUT_RU, 101))
        self.send.assert_called_once()
        self.assertEqual(self.fake.posts, [])
        self.sleep.assert_not_called()

    def test_unavailable_focus_uses_foreground_compatibility(self):
        self.fake.GetGUIThreadInfo = Mock(return_value=True)
        def receive(hwnd, msg, wparam, lparam, timeout_ms):
            self.assertEqual(hwnd, 101)
            self.fake.current = lparam
            return True
        self.send.side_effect = receive
        with patch.object(punto, "_get_focused_control_hwnd", return_value=0):
            self.assertTrue(punto._switch_input_language_for_foreground(punto.LAYOUT_RU, 101))
        self.send.assert_called_once()
        self.assertEqual(self.fake.posts, [])

    def test_english_auto_layout_target_uses_english_input(self):
        self.fake.current = 0x04190419
        self.fake.GetGUIThreadInfo = Mock(return_value=True)
        with patch.object(punto, "_get_focused_control_hwnd", return_value=222):
            def receive(hwnd, msg, wp, lp, timeout_ms):
                self.fake.current = lp
                return True
            self.send.side_effect = receive
            self.assertTrue(punto._switch_layout_toward_text("hello", 101))
        self.assertEqual(self.fake.current & 0xFFFF, 0x0409)

    def _enable_two_windows_layouts(self, layouts=(0x04090409, 0x04190419)):
        def list_layouts(count, data):
            if count == 0:
                return len(layouts)
            for i, layout in enumerate(layouts):
                data[i] = layout
            return len(layouts)
        self.fake.GetKeyboardLayoutList = list_layouts

    def test_win_space_fallback_switches_ru_when_messages_are_ignored(self):
        """The system shortcut is used only after two WinAPI message paths fail."""
        self._enable_two_windows_layouts()
        self.send.return_value = False
        injected = []
        def send_inputs(keys):
            injected.append(keys)
            self.fake.current = 0x04190419
        with (patch.object(punto, "_IS_WINDOWS", True),
              patch.object(punto, "_is_any_vk_pressed", return_value=False),
              patch.object(punto, "_key_input", side_effect=lambda vk, up: (vk, up)),
              patch.object(punto, "_send_input", side_effect=send_inputs)):
            self.assertTrue(punto._switch_input_language_for_foreground(punto.LAYOUT_RU, 101))
        self.assertEqual(injected, [[
            (punto.VK_LWIN, False), (punto.VK_SPACE, False),
            (punto.VK_SPACE, True), (punto.VK_LWIN, True),
        ]])
        self.assertEqual(self.fake.current & 0xFFFF, 0x0419)
        self.assertEqual(len(self.fake.posts), 1)

    def test_win_space_fallback_can_return_to_english(self):
        self._enable_two_windows_layouts()
        self.fake.current = 0x04190419
        self.send.return_value = False
        with (patch.object(punto, "_IS_WINDOWS", True),
              patch.object(punto, "_is_any_vk_pressed", return_value=False),
              patch.object(punto, "_key_input", side_effect=lambda vk, up: (vk, up)),
              patch.object(punto, "_send_input", side_effect=lambda _: setattr(
                  self.fake, "current", 0x04090409,
              )) as injected):
            self.assertTrue(punto._switch_input_language_for_foreground(punto.LAYOUT_EN, 101))
        injected.assert_called_once()
        self.assertEqual(self.fake.current & 0xFFFF, 0x0409)

    def test_shortcut_fallback_rejects_three_or_unknown_layouts(self):
        self.send.return_value = False
        for layouts in (
            (0x04090409, 0x04190419, 0x04070407),
            (0x04090409, 0x04070407),
        ):
            self._enable_two_windows_layouts(layouts)
            with (patch.object(punto, "_IS_WINDOWS", True),
                  patch.object(punto, "_is_any_vk_pressed", return_value=False),
                  patch.object(punto, "_send_input") as injected,
                  self.assertLogs(level='WARNING')):
                self.assertFalse(punto._switch_input_language_for_foreground(punto.LAYOUT_RU, 101))
            injected.assert_not_called()

    def test_shortcut_fallback_skips_held_modifier_keys(self):
        self._enable_two_windows_layouts()
        self.send.return_value = False
        with (patch.object(punto, "_IS_WINDOWS", True),
              patch.object(punto, "_is_any_vk_pressed", return_value=True),
              patch.object(punto, "_send_input") as injected,
              self.assertLogs(level='WARNING')):
            self.assertFalse(punto._switch_input_language_for_foreground(punto.LAYOUT_RU, 101))
        injected.assert_not_called()

    def test_shortcut_fallback_skips_when_keyboard_input_has_advanced(self):
        self._enable_two_windows_layouts()
        with patch.object(punto, "_keyboard_input_revision", 100):
            def user_typed_during_message(hwnd, msg, wp, lp, timeout_ms):
                punto._keyboard_input_revision += 1
                return False
            self.send.side_effect = user_typed_during_message
            with (patch.object(punto, "_IS_WINDOWS", True),
                  patch.object(punto, "_is_any_vk_pressed", return_value=False),
                  patch.object(punto, "_send_input") as injected,
                  self.assertLogs(level='WARNING')):
                self.assertFalse(punto._switch_input_language_for_foreground(punto.LAYOUT_RU, 101))
            injected.assert_not_called()

    def test_shortcut_fallback_releases_win_after_partial_send_failure(self):
        self._enable_two_windows_layouts()
        self.send.return_value = False
        commands = []
        def send_inputs(keys):
            commands.append(keys)
            if len(commands) == 1:
                raise RuntimeError("Partial SendInput")
        with (patch.object(punto, "_IS_WINDOWS", True),
              patch.object(punto, "_is_any_vk_pressed", return_value=False),
              patch.object(punto, "_key_input", side_effect=lambda vk, up: (vk, up)),
              patch.object(punto, "_send_input", side_effect=send_inputs),
              self.assertLogs(level='WARNING')):
            self.assertFalse(punto._switch_input_language_for_foreground(punto.LAYOUT_RU, 101))
        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[-1], [(punto.VK_LWIN, True)])

    def test_current_language_is_already_correct(self):
        self.fake.current=0x00000419
        self.assertTrue(punto._switch_input_language_for_foreground(punto.LAYOUT_RU,101))
        self.send.assert_not_called()
        self.assertEqual(self.fake.loaded,[])
        self.assertEqual(self.fake.posts,[])

    def test_synchronous_window_message_is_verified(self):
        def deliver(hwnd,msg,wparam,lparam,timeout_ms):
            self.assertEqual((hwnd,msg,wparam), (101,punto.WM_INPUTLANGCHANGEREQUEST,0))
            self.assertEqual(timeout_ms,120)
            self.fake.current=lparam
            return True
        self.send.side_effect=deliver
        self.assertTrue(punto._switch_input_language_for_foreground(punto.LAYOUT_RU,101))
        self.send.assert_called_once()
        self.assertEqual(self.fake.loaded,[(punto.LAYOUT_RU,0)])
        self.assertEqual(self.fake.posts,[])

    def test_window_ignoring_first_message_retries_until_verified(self):
        calls=0
        def deliver(hwnd,msg,wparam,lparam,timeout_ms):
            nonlocal calls
            calls+=1
            if calls==2:self.fake.current=lparam
            return True
        self.send.side_effect=deliver
        self.assertTrue(punto._switch_input_language_for_foreground(punto.LAYOUT_RU,101))
        self.assertEqual(calls,2)
        self.sleep.assert_called_once_with(0.025)
        self.assertEqual(self.fake.posts,[])

    def test_async_message_fallback_is_verified(self):
        self.send.return_value=False
        self.fake.on_post=lambda:setattr(self.fake,'current',0x04190419)
        self.assertTrue(punto._switch_input_language_for_foreground(punto.LAYOUT_RU,101))
        self.assertEqual(self.send.call_count,2)
        self.assertEqual(len(self.fake.posts),1)
        self.assertEqual(self.fake.posts[0][0:2],(101,punto.WM_INPUTLANGCHANGEREQUEST))

    def test_unsupported_window_is_reported_not_silent(self):
        self.send.return_value=False
        with self.assertLogs(level='WARNING') as logs:
            ok=punto._switch_input_language_for_foreground(punto.LAYOUT_RU,101)
        self.assertFalse(ok)
        self.assertIn('unable to confirm',logs.output[0])
        self.assertEqual(self.send.call_count,2)
        self.assertEqual(len(self.fake.posts),1)

    def test_does_not_switch_new_foreground_window(self):
        self.assertFalse(punto._switch_input_language_for_foreground(punto.LAYOUT_RU,200))
        self.send.assert_not_called()
        self.assertEqual(self.fake.loaded,[])
        self.assertEqual(self.fake.posts,[])

    def test_focus_change_during_delivery_aborts_without_retry(self):
        def deliver(hwnd,msg,wparam,lparam,timeout_ms):
            self.fake.foreground=202
            return True
        self.send.side_effect=deliver
        self.assertFalse(punto._switch_input_language_for_foreground(punto.LAYOUT_RU,101))
        self.send.assert_called_once()
        self.assertEqual(self.fake.posts,[])
        self.sleep.assert_not_called()

    def test_no_target_or_language_never_changes_layout(self):
        self.fake.foreground=0
        self.assertFalse(punto._switch_input_language_for_foreground(punto.LAYOUT_RU))
        self.assertFalse(punto._switch_input_language_for_foreground('INVALID'))
        self.send.assert_not_called()

    def test_manual_before_caret_passes_original_window_and_resulting_language(self):
        with (patch.object(punto,'_transform_run_before_caret',return_value='привет'),
              patch.object(punto,'_get_focused_control_hwnd',return_value=0),
              patch.object(punto,'_is_password_edit',return_value=False),
              patch.object(punto,'_learn_manual_word'),
              patch.object(punto,'_switch_layout_toward_text') as switch):
            punto.convert_before_caret_text(Mock())
            switch.assert_called_once_with('привет',101)

    def test_selected_conversion_passes_original_foreground(self):
        with (patch.object(punto,'_get_focused_control_hwnd',return_value=222),
              patch.object(punto,'_edit_get_sel',return_value=(0,6)),
              patch.object(punto,'_try_get_selected_text_from_edit',return_value='ghbdtn'),
              patch.object(punto,'_try_replace_selection_in_edit',return_value=True),
              patch.object(punto,'_learn_manual_word'),
              patch.object(punto,'_switch_layout_toward_text') as switch):
            punto.convert_selected_text(Mock(max_selected_length=100))
            switch.assert_called_once_with('привет',101)

    def test_auto_correction_syncs_layout_after_verified_text_replacement(self):
        with (patch.object(punto,'_settings',Mock(auto_layout_correction=True)),
              patch.object(punto,'_layout_words',frozenset({'привет'})),
              patch.object(punto,'_candidate_layout_correction',return_value='привет'),
              patch.object(punto,'_replace_range_in_edit_safely',return_value=True),
              patch.object(punto,'_switch_layout_toward_text') as switch):
            self.assertTrue(punto._try_auto_layout_in_edit(222,'ghbdtn',6,6))
            switch.assert_called_once_with('привет',101)

    def test_no_switch_when_auto_replacement_fails(self):
        with (patch.object(punto,'_settings',Mock(auto_layout_correction=True)),
              patch.object(punto,'_layout_words',frozenset({'привет'})),
              patch.object(punto,'_candidate_layout_correction',return_value='привет'),
              patch.object(punto,'_replace_range_in_edit_safely',return_value=False),
              patch.object(punto,'_get_class_name',return_value='Edit'),
              patch.object(punto,'_switch_layout_toward_text') as switch):
            self.assertFalse(punto._try_auto_layout_in_edit(222,'ghbdtn',6,6))
            switch.assert_not_called()

    def test_failed_conversion_does_not_switch(self):
        with (patch.object(punto,'_transform_run_before_caret',return_value=None),
              patch.object(punto,'_switch_layout_toward_text') as switch):
            punto.convert_before_caret_text(Mock())
            switch.assert_not_called()

    def test_russian_and_english_dominant_text_target(self):
        with patch.object(punto,'_switch_input_language_for_foreground',return_value=True) as switch:
            self.assertTrue(punto._switch_layout_toward_text('привет',101))
            switch.assert_called_with(punto.LAYOUT_RU,101)
            self.assertTrue(punto._switch_layout_toward_text('hello',101))
            switch.assert_called_with(punto.LAYOUT_EN,101)
            count=switch.call_count
            self.assertFalse(punto._switch_layout_toward_text('123',101))
            self.assertEqual(switch.call_count,count)


if __name__ == '__main__':
    unittest.main()
