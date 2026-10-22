#!/usr/bin/env python3
"""Pure dispatch tests: validate key mappings without injecting into the desktop."""

import argparse
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))
import hotkey_forwarder as h  # noqa: E402


class ForwarderDispatchTest(unittest.TestCase):
    def setUp(self):
        args = argparse.Namespace(
            key="right-shift",
            mode="tap",
            no_audio=True,
            output_substr="CABLE Input",
        )
        self.forwarder = h.Forwarder(args)

    @staticmethod
    def event(name, **fields):
        return (json.dumps({"event": name, **fields}) + "\n").encode("utf-8")

    def test_up_ptt_hold_mode_holds_key_and_releases_on_end(self):
        args = argparse.Namespace(
            key="right-shift",
            mode="hold",
            no_audio=True,
            output_substr="CABLE Input",
        )
        fwd = h.Forwarder(args)
        sent = []
        with mock.patch.object(h, "_send_key", side_effect=lambda *a, **kw: sent.append((a, kw))), \
             mock.patch.object(h.time, "sleep"):
            fwd.on_event(self.event("voice.start"))
            fwd.on_event(self.event("voice.end"))

        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[0][0][:3], h.KEY_MAP["right-shift"])
        self.assertFalse(sent[0][1]["up"])   # Key down
        self.assertEqual(sent[1][0][:3], h.KEY_MAP["right-shift"])
        self.assertTrue(sent[1][1]["up"])    # Key up

    def test_up_ptt_clicks_right_shift_at_start_and_again_at_release(self):
        sent = []
        with mock.patch.object(h, "_send_key", side_effect=lambda *a, **kw: sent.append((a, kw))), \
             mock.patch.object(h.time, "sleep"):
            self.forwarder.on_event(self.event("voice.start"))
            self.forwarder.on_event(self.event("voice.end"))

        self.assertEqual(len(sent), 4)
        self.assertEqual(sent[0][0][:3], h.KEY_MAP["right-shift"])
        self.assertFalse(sent[0][1]["up"])
        self.assertEqual(sent[1][0][:3], h.KEY_MAP["right-shift"])
        self.assertTrue(sent[1][1]["up"])
        self.assertEqual(sent[2][0][:3], h.KEY_MAP["right-shift"])
        self.assertFalse(sent[2][1]["up"])
        self.assertEqual(sent[3][0][:3], h.KEY_MAP["right-shift"])
        self.assertTrue(sent[3][1]["up"])

    def test_down_enter_releases_stale_voice_then_injects_once(self):
        order = []
        self.forwarder.active = True
        with mock.patch.object(self.forwarder, "finish",
                               side_effect=lambda **_kw: order.append("release")), \
             mock.patch.object(self.forwarder.enter_injector, "click",
                               side_effect=lambda: order.append("enter")), \
             mock.patch.object(h.time, "monotonic", side_effect=[10.0, 10.1]), \
             mock.patch.object(h.time, "sleep"):
            self.forwarder.on_event(self.event("key.action", action="enter"))
            self.forwarder.on_event(self.event("key.action", action="enter"))

        self.assertEqual(order, ["release", "enter"])

    def test_down_enter_works_after_normal_voice_end(self):
        order = []
        with mock.patch.object(self.forwarder, "finish",
                               side_effect=lambda **_kw: order.append("reconcile")), \
             mock.patch.object(self.forwarder.enter_injector, "click",
                               side_effect=lambda: order.append("enter")), \
             mock.patch.object(h.time, "monotonic", return_value=20.0):
            self.forwarder.on_event(self.event("key.action", action="enter"))
        self.assertEqual(order, ["reconcile", "enter"])

    def test_alt_tab_first_press_holds_modifier_and_taps_trigger(self):
        sent = []
        with mock.patch.object(h, "_send_key", side_effect=lambda *a, **kw: sent.append((a, kw))), \
             mock.patch.object(h.threading, "Timer"), \
             mock.patch.object(h.time, "sleep"):
            self.forwarder.on_event(self.event("key.action", action="alt_tab"))
        # left-alt 按住不放,tab 点一下;迟滞窗开启
        self.assertEqual(sent[0][0][:3], h.KEY_MAP["left-alt"])
        self.assertFalse(sent[0][1]["up"])
        self.assertEqual(sent[1][0][:3], h.KEY_MAP["tab"])
        self.assertFalse(sent[1][1]["up"])
        self.assertEqual(sent[2][0][:3], h.KEY_MAP["tab"])
        self.assertTrue(sent[2][1]["up"])
        self.assertTrue(self.forwarder.alt_chord.active())

    def test_alt_tab_repeat_press_within_hysteresis_taps_trigger_only(self):
        sent = []
        with mock.patch.object(h, "_send_key", side_effect=lambda *a, **kw: sent.append((a, kw))), \
             mock.patch.object(h.threading, "Timer"), \
             mock.patch.object(h.time, "sleep"):
            self.forwarder.on_event(self.event("key.action", action="alt_tab"))
            self.forwarder.on_event(self.event("key.action", action="alt_tab"))
        downs = [s[0][:3] for s in sent if not s[1]["up"]]
        # alt 只按下一次;tab 点两次(多选窗口)
        self.assertEqual(downs.count(h.KEY_MAP["left-alt"]), 1)
        self.assertEqual(downs.count(h.KEY_MAP["tab"]), 2)

    def test_alt_tab_hysteresis_timeout_releases_modifier(self):
        sent = []
        with mock.patch.object(h, "_send_key", side_effect=lambda *a, **kw: sent.append((a, kw))), \
             mock.patch.object(h.threading, "Timer"), \
             mock.patch.object(h.time, "sleep"):
            self.forwarder.on_event(self.event("key.action", action="alt_tab"))
            self.forwarder.alt_chord._release()
        self.assertFalse(self.forwarder.alt_chord.active())
        self.assertEqual(sent[-1][0][:3], h.KEY_MAP["left-alt"])
        self.assertTrue(sent[-1][1]["up"])

    def test_alt_tab_chord_cancelled_on_disconnect(self):
        sent = []
        with mock.patch.object(h, "_send_key", side_effect=lambda *a, **kw: sent.append((a, kw))), \
             mock.patch.object(h.threading, "Timer"), \
             mock.patch.object(h.time, "sleep"):
            self.forwarder.on_event(self.event("key.action", action="alt_tab"))
            self.forwarder.on_disconnect()
        self.assertFalse(self.forwarder.alt_chord.active())
        ups = [s[0][:3] for s in sent if s[1]["up"]]
        self.assertIn(h.KEY_MAP["left-alt"], ups)

    def test_alt_tab_first_press_releases_stale_voice_then_chords(self):
        order = []
        self.forwarder.active = True
        sent = []
        with mock.patch.object(self.forwarder, "finish",
                               side_effect=lambda **_kw: order.append("release")), \
             mock.patch.object(h, "_send_key", side_effect=lambda *a, **kw: sent.append((a, kw))), \
             mock.patch.object(h.threading, "Timer"), \
             mock.patch.object(h.time, "sleep"):
            self.forwarder.on_event(self.event("key.action", action="alt_tab"))
            self.forwarder.on_event(self.event("key.action", action="alt_tab"))
        # 仅首点做语音对账;迟滞窗内连点不再对账、畅通无阻
        self.assertEqual(order, ["release"])
        tab_ups = [s for s in sent
                   if s[0][:3] == h.KEY_MAP["tab"] and s[1]["up"]]
        self.assertEqual(len(tab_ups), 2)

    def test_key_actions_config_overrides_specs(self):
        args = argparse.Namespace(
            key="right-shift", mode="tap", no_audio=True,
            output_substr="CABLE Input",
            key_actions={"enter": "f9", "alt_tab": "ctrl+tab"},
        )
        fwd = h.Forwarder(args)
        self.assertEqual(fwd.enter_injector.spec, "f9")
        self.assertEqual(fwd.alt_chord.spec, "ctrl+tab")

    def test_retired_clear_and_agent_actions_never_inject_keys(self):
        with mock.patch.object(self.forwarder.enter_injector, "click") as click:
            self.forwarder.on_event(self.event("key.action", action="clear"))
            self.forwarder.on_event(self.event("agent.action", decision="approve"))
        click.assert_not_called()

    def test_audio_route_controls_readiness_and_start(self):
        fwd = self.forwarder
        self.assertFalse(fwd.pc_status()["audioReady"])
        fwd.sink = mock.Mock(enabled=False)
        with mock.patch.object(fwd.injector, "start") as start:
            fwd.on_event(self.event("voice.start"))
            start.assert_not_called()
        fwd.sink.enabled = True
        self.assertTrue(fwd.pc_status()["audioReady"])

    def test_drain_precedes_release_and_late_audio_is_ignored(self):
        fwd = self.forwarder
        fwd.sink = mock.Mock(enabled=True)
        order = []
        with mock.patch.object(fwd.injector, "start"), mock.patch.object(fwd.injector, "stop", side_effect=lambda: order.append('release')):
            fwd.sink.drain.side_effect = lambda: order.append('drain')
            fwd.on_event(self.event("voice.start"))
            fwd.on_audio(bytes([255,128])+bytes(804))
            fwd.on_audio(bytes([0,128])+bytes(804))
            fwd.on_audio(bytes([0,128])+bytes(804))  # Duplicate
            fwd.on_audio(bytes([255,128])+bytes(804))  # Late
            fwd.on_event(self.event("voice.end"))
            fwd.on_audio(bytes([1,128])+bytes(804))
        self.assertEqual(fwd.audio_blocks,2)
        self.assertEqual(order,['drain','release'])

    def test_lost_end_or_audio_failure_releases_even_with_live_transport(self):
        fwd = self.forwarder
        with mock.patch.object(fwd.injector,"start"), mock.patch.object(fwd.injector,"stop") as stop:
            fwd.on_event(self.event("voice.start"))
            fwd.check_health(fwd.last_audio_at + 3)
            self.assertFalse(fwd.active)
            stop.assert_called_once()
            fwd.sink = mock.Mock(enabled=True)
            fwd.on_event(self.event("voice.start"))
            fwd.sink.enabled = False
            fwd.check_health()
            self.assertFalse(fwd.active)
            self.assertEqual(stop.call_count,2)

    def test_malformed_events_ignored(self):
        for payload in (b'null', b'[]', b'garbage', b'"voice.start"'):
            self.forwarder.on_event(payload)
        self.assertFalse(self.forwarder.active)

    def test_no_audio_mode_discards_device_audio(self):
        self.forwarder.on_audio(b"\x01\x80payload")

    def test_disconnect_without_active_session_does_not_inject_shift(self):
        sent = []
        with mock.patch.object(h, "_send_key", side_effect=lambda *a, **kw: sent.append((a, kw))), \
             mock.patch.object(h.time, "sleep"):
            self.forwarder.on_disconnect()
        self.assertEqual(sent, [])


class ResolveKeySpecTest(unittest.TestCase):
    def test_all_modifier_chord_ctrl_win_allowed(self):
        # 微信输入法语音热键:全修饰键和弦 ctrl+win
        keys = h.resolve_key_spec("ctrl+win")
        self.assertEqual([k[0] for k in keys], ["left-ctrl", "left-win"])

    def test_mixed_combo_with_modifier_tail_rejected(self):
        # 普通键在前面、后面还跟别的键 = 非法组合
        with self.assertRaises(ValueError):
            h.resolve_key_spec("h+ctrl")

    def test_normal_combo_still_works(self):
        keys = h.resolve_key_spec("alt+tab")
        self.assertEqual([k[0] for k in keys], ["left-alt", "tab"])


if __name__ == "__main__":
    unittest.main()
