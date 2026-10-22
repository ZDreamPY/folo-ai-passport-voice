#!/usr/bin/env python3
"""热重载(apply_config)与设置面板配置校验(validate_config)的纯逻辑单测。"""

import argparse
import os
import sys
import unittest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))
import hotkey_forwarder as h  # noqa: E402
import settings_server as s  # noqa: E402


def make_args(**kw):
    base = dict(key="right-shift", mode="tap", no_audio=True,
                output_substr="CABLE Input", device_ip="192.168.31.172",
                port=33333)
    base.update(kw)
    return argparse.Namespace(**base)


class ApplyConfigTest(unittest.TestCase):
    def setUp(self):
        self.fwd = h.Forwarder(make_args(key_actions={"enter": "enter",
                                                      "alt_tab": "alt+tab"}))

    def test_voice_hotkey_swap(self):
        self.fwd.apply_config({"hotkey_key": "f9", "hotkey_mode": "hold"})
        self.assertEqual(self.fwd.args.key, "f9")
        self.assertEqual(self.fwd.args.mode, "hold")

    def test_voice_hotkey_invalid_keeps_old(self):
        self.fwd.apply_config({"hotkey_key": "不存在的键!!"})
        self.assertEqual(self.fwd.args.key, "right-shift")

    def test_action_keys_swap(self):
        self.fwd.apply_config({"key_actions": {"enter": "ctrl+alt+space",
                                               "alt_tab": "f9"}})
        self.assertEqual(self.fwd.enter_spec, "ctrl+alt+space")
        self.assertEqual(self.fwd.alt_tab_spec, "f9")

    def test_action_key_invalid_keeps_old(self):
        self.fwd.apply_config({"key_actions": {"enter": "bad key ++"}})
        self.assertEqual(self.fwd.enter_spec, "enter")

    def test_device_ip_change_sets_reload_link(self):
        self.fwd.apply_config({"device_ip": "192.168.1.66"})
        self.assertEqual(self.fwd.args.device_ip, "192.168.1.66")
        self.assertTrue(self.fwd.reload_link)

    def test_port_change_sets_reload_link(self):
        self.fwd.apply_config({"udp_port": "34444"})
        self.assertEqual(self.fwd.args.port, 34444)
        self.assertTrue(self.fwd.reload_link)

    def test_bad_port_ignored(self):
        self.fwd.apply_config({"udp_port": "abc"})
        self.assertEqual(self.fwd.args.port, 33333)
        self.assertFalse(self.fwd.reload_link)

    def test_empty_config_noop(self):
        self.fwd.apply_config({})
        self.assertEqual(self.fwd.args.key, "right-shift")
        self.assertFalse(self.fwd.reload_link)

    def test_hysteresis_change_rebuilds_chord(self):
        self.fwd.apply_config({"alt_tab_hysteresis_ms": 900})
        self.assertEqual(self.fwd.hysteresis_ms, 900)
        self.assertAlmostEqual(self.fwd.alt_chord.hysteresis, 0.9)

    def test_hysteresis_out_of_range_clamped(self):
        self.fwd.apply_config({"alt_tab_hysteresis_ms": 99999})
        self.assertEqual(self.fwd.hysteresis_ms, 3000)
        self.fwd.apply_config({"alt_tab_hysteresis_ms": "abc"})
        self.assertEqual(self.fwd.hysteresis_ms, 3000)   # 非法 → 保持原值

    def test_audio_swap_deferred_when_active(self):
        # no_audio=True → sink 为 None,音频分支应整体跳过不崩溃
        self.fwd.apply_config({"output_substr": "Speakers"})


class ValidateConfigTest(unittest.TestCase):
    OLD = {"hotkey_key": "ctrl+win", "hotkey_mode": "tap",
           "key_actions": {"enter": "enter", "alt_tab": "alt+tab"},
           "output_substr": "CABLE Input", "udp_port": 33333,
           "device_ip": "192.168.31.172"}

    def test_valid_passthrough(self):
        clean, errors = s.validate_config(dict(self.OLD), {})
        self.assertEqual(errors, [])
        self.assertEqual(clean["hotkey_key"], "ctrl+win")
        self.assertEqual(clean["udp_port"], 33333)
        self.assertEqual(clean["alt_tab_hysteresis_ms"], 1000)  # 缺省补默认

    def test_hysteresis_validated(self):
        clean, errors = s.validate_config(
            dict(self.OLD, alt_tab_hysteresis_ms=800), self.OLD)
        self.assertEqual(errors, [])
        self.assertEqual(clean["alt_tab_hysteresis_ms"], 800)
        clean2, errors2 = s.validate_config(
            dict(self.OLD, alt_tab_hysteresis_ms="99999"), self.OLD)
        self.assertTrue(errors2)
        self.assertEqual(clean2["alt_tab_hysteresis_ms"], 1000)

    def test_bad_hotkey_falls_back(self):
        new = dict(self.OLD, hotkey_key="win+不存在的键")
        clean, errors = s.validate_config(new, self.OLD)
        self.assertTrue(errors)
        self.assertEqual(clean["hotkey_key"], "ctrl+win")

    def test_port_range(self):
        clean, errors = s.validate_config(dict(self.OLD, udp_port="99999"), self.OLD)
        self.assertTrue(errors)
        self.assertEqual(clean["udp_port"], 33333)
        clean2, errors2 = s.validate_config(dict(self.OLD, udp_port=" 34444 "),
                                            self.OLD)
        self.assertEqual(errors2, [])
        self.assertEqual(clean2["udp_port"], 34444)

    def test_device_ip(self):
        clean, errors = s.validate_config(
            dict(self.OLD, device_ip="300.1.1.1"), self.OLD)
        self.assertTrue(errors)
        self.assertEqual(clean["device_ip"], "192.168.31.172")
        clean2, errors2 = s.validate_config(dict(self.OLD, device_ip=""), self.OLD)
        self.assertEqual(errors2, [])
        self.assertEqual(clean2["device_ip"], "")

    def test_unknown_keys_dropped(self):
        clean, errors = s.validate_config(dict(self.OLD, evil={"x": 1}), self.OLD)
        self.assertEqual(errors, [])
        self.assertNotIn("evil", clean)

    def test_mode_normalized(self):
        clean, errors = s.validate_config(dict(self.OLD, hotkey_mode="auto"), self.OLD)
        self.assertEqual(errors, [])
        self.assertEqual(clean["hotkey_mode"], "tap")

    def test_partial_update_keeps_rest(self):
        clean, errors = s.validate_config({"hotkey_key": "f6"}, self.OLD)
        self.assertEqual(errors, [])
        self.assertEqual(clean["hotkey_key"], "f6")
        self.assertEqual(clean["device_ip"], "192.168.31.172")
        self.assertEqual(clean["key_actions"]["enter"], "enter")


if __name__ == "__main__":
    unittest.main()
