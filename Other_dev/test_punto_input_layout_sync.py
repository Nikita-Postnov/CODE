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

    def GetForegroundWindow(self):
        return self.foreground

    def GetWindowThreadProcessId(self, hwnd, _pid):
        assert hwnd == 101, f"Should not touch unrelated hwnd={hwnd}"
        return self.thread

    def GetKeyboardLayout(self, tid):
        assert tid == self.thread
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
