// tests/test_app_state.c —— 语音遥控状态机宿主测试:三键语义 + 表情提示时效。
// 编译: cc -std=c11 -Wall -Wextra -Werror -Imain tests/test_app_state.c main/apps/voice/app_state.c
#include "apps/voice/app_state.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

#define NOW 1000u

static app_event_t key_ev(app_event_type_t t, uint8_t btn, uint16_t mv) {
    app_event_t ev = {0};
    ev.type = t;
    ev.u.key.btn = btn;
    ev.u.key.mv = mv;
    return ev;
}

static void test_init(void) {
    app_state_t s;
    app_ui_snapshot_t snap;
    app_state_init(&s);
    app_state_snapshot(&s, NOW, &snap);
    assert(s.state == APP_ST_READY);
    assert(!snap.link_up && !snap.pc_ready);
    assert(!snap.emo_hint_active);
    assert(snap.emo_hint == APP_EMO_HINT_NONE);
}

// 就绪 → 按住 UP 开录;松开收束。动作序列是状态机与外设的契约。
static void test_ptt_roundtrip(void) {
    app_state_t s;
    app_action_t acts[APP_ACT_MAX];
    uint8_t n;
    app_event_t ev;

    app_state_init(&s);
    ev.type = APP_EV_LINK_UP;
    app_state_reduce(&s, &ev, NOW, acts, &n);
    ev.type = APP_EV_PC_STATUS;
    ev.u.pc_status.audio_ready = true;
    ev.u.pc_status.hotkey_ready = true;
    app_state_reduce(&s, &ev, NOW + 100, acts, &n);
    assert(s.pc_ready);

    // 假按(射频腐蚀的松开电平)必须被 ADC 门禁拒绝
    ev = key_ev(APP_EV_KEY_PRESS, APP_BTN_UP, 2890);
    app_state_reduce(&s, &ev, NOW + 200, acts, &n);
    assert(s.state == APP_ST_READY && n == 0);

    // 真按:开录 = voice.start + stream.start
    ev = key_ev(APP_EV_KEY_PRESS, APP_BTN_UP, 100);
    app_state_reduce(&s, &ev, NOW + 300, acts, &n);
    assert(s.state == APP_ST_LISTENING && n == 2);
    assert(acts[0].type == APP_ACT_SEND_VOICE_START);
    assert(acts[1].type == APP_ACT_STREAM_START);

    // 松开:收束 = stream.stop + voice.end
    ev = key_ev(APP_EV_KEY_RELEASE, APP_BTN_UP, 0);
    app_state_reduce(&s, &ev, NOW + 1000, acts, &n);
    assert(s.state == APP_ST_READY && n == 2);
    assert(acts[0].type == APP_ACT_STREAM_STOP);
    assert(acts[1].type == APP_ACT_SEND_VOICE_END);
}

static void test_gate(void) {
    app_state_t s;
    app_action_t acts[APP_ACT_MAX];
    uint8_t n;
    app_event_t ev = key_ev(APP_EV_KEY_CLICK, APP_BTN_OK, 0);

    // 未连接时单击 OK:必须无动作(回车落进别的窗口 = 事故)
    app_state_init(&s);
    app_state_reduce(&s, &ev, NOW, acts, &n);
    assert(n == 0);
}

static void test_ok_enter_hint(void) {
    app_state_t s;
    app_action_t acts[APP_ACT_MAX];
    uint8_t n;
    app_ui_snapshot_t snap;
    app_event_t ev;

    app_state_init(&s);
    ev.type = APP_EV_LINK_UP;
    app_state_reduce(&s, &ev, NOW, acts, &n);
    ev.type = APP_EV_PC_STATUS;
    ev.u.pc_status.audio_ready = ev.u.pc_status.hotkey_ready = true;
    app_state_reduce(&s, &ev, NOW + 100, acts, &n);

    ev = key_ev(APP_EV_KEY_CLICK, APP_BTN_OK, 0);
    app_state_reduce(&s, &ev, NOW + 200, acts, &n);
    assert(n == 1 && acts[0].type == APP_ACT_SEND_KEY_ACTION);
    assert(acts[0].u.key_action.action == APP_KEY_ENTER);

    app_state_snapshot(&s, NOW + 300, &snap);
    assert(snap.emo_hint_active && snap.emo_hint == APP_EMO_HINT_SENT_OK);
    app_state_snapshot(&s, NOW + 2800, &snap);           // 2500ms 时效已过
    assert(!snap.emo_hint_active);
}

static void test_down_alt_tab_hint(void) {
    app_state_t s;
    app_action_t acts[APP_ACT_MAX];
    uint8_t n;
    app_ui_snapshot_t snap;
    app_event_t ev;

    app_state_init(&s);
    ev.type = APP_EV_LINK_UP;
    app_state_reduce(&s, &ev, NOW, acts, &n);
    ev.type = APP_EV_PC_STATUS;
    ev.u.pc_status.audio_ready = ev.u.pc_status.hotkey_ready = true;
    app_state_reduce(&s, &ev, NOW + 100, acts, &n);

    ev = key_ev(APP_EV_KEY_CLICK, APP_BTN_DOWN, 0);
    app_state_reduce(&s, &ev, NOW + 200, acts, &n);
    assert(n == 1 && acts[0].type == APP_ACT_SEND_KEY_ACTION);
    assert(acts[0].u.key_action.action == APP_KEY_ALT_TAB);
    app_state_snapshot(&s, NOW + 300, &snap);
    assert(snap.emo_hint_active && snap.emo_hint == APP_EMO_HINT_SWITCHED);
}

static void test_audio_error_panic_hint(void) {
    app_state_t s;
    app_action_t acts[APP_ACT_MAX];
    uint8_t n;
    app_ui_snapshot_t snap;
    app_event_t ev;

    app_state_init(&s);
    ev.type = APP_EV_LINK_UP;
    app_state_reduce(&s, &ev, NOW, acts, &n);
    ev.type = APP_EV_PC_STATUS;
    ev.u.pc_status.audio_ready = ev.u.pc_status.hotkey_ready = true;
    app_state_reduce(&s, &ev, NOW + 100, acts, &n);
    ev = key_ev(APP_EV_KEY_PRESS, APP_BTN_UP, 100);
    app_state_reduce(&s, &ev, NOW + 200, acts, &n);
    assert(s.state == APP_ST_LISTENING);

    ev.type = APP_EV_AUDIO_ERROR;
    app_state_reduce(&s, &ev, NOW + 400, acts, &n);
    assert(s.state == APP_ST_READY && n == 2);
    assert(acts[0].type == APP_ACT_STREAM_CANCEL);       // 断链式收束:不排空
    assert(acts[1].type == APP_ACT_SEND_VOICE_END);
    app_state_snapshot(&s, NOW + 500, &snap);
    assert(snap.emo_hint_active && snap.emo_hint == APP_EMO_HINT_ERROR);
}

static void test_ptt_max_pause_hint(void) {
    app_state_t s;
    app_action_t acts[APP_ACT_MAX];
    uint8_t n;
    app_ui_snapshot_t snap;
    app_event_t ev;

    app_state_init(&s);
    ev.type = APP_EV_LINK_UP;
    app_state_reduce(&s, &ev, NOW, acts, &n);
    ev.type = APP_EV_PC_STATUS;
    ev.u.pc_status.audio_ready = ev.u.pc_status.hotkey_ready = true;
    app_state_reduce(&s, &ev, NOW + 100, acts, &n);
    ev = key_ev(APP_EV_KEY_PRESS, APP_BTN_UP, 100);
    app_state_reduce(&s, &ev, NOW + 200, acts, &n);

    // TICK 推进到 10 分钟上限:自动暂停 + WAIT 提示
    ev.type = APP_EV_TICK;
    app_state_reduce(&s, &ev, NOW + 200 + APP_PTT_MAX_TALK_MS + APP_TICK_MS, acts, &n);
    assert(s.state == APP_ST_READY);
    app_state_snapshot(&s, NOW + 400 + APP_PTT_MAX_TALK_MS, &snap);
    assert(snap.emo_hint_active && snap.emo_hint == APP_EMO_HINT_PAUSED);
}

static void test_pc_heartbeat_expiry(void) {
    app_state_t s;
    app_action_t acts[APP_ACT_MAX];
    uint8_t n;
    app_event_t ev;

    app_state_init(&s);
    ev.type = APP_EV_LINK_UP;
    app_state_reduce(&s, &ev, NOW, acts, &n);
    ev.type = APP_EV_PC_STATUS;
    ev.u.pc_status.audio_ready = ev.u.pc_status.hotkey_ready = true;
    app_state_reduce(&s, &ev, NOW + 100, acts, &n);
    ev = key_ev(APP_EV_KEY_PRESS, APP_BTN_UP, 100);
    app_state_reduce(&s, &ev, NOW + 200, acts, &n);
    assert(s.state == APP_ST_LISTENING);

    // 心跳超时(3500ms 无 pc.status):结束录音 + 撤就绪
    ev.type = APP_EV_TICK;
    app_state_reduce(&s, &ev, NOW + 200 + 4000, acts, &n);
    assert(s.state == APP_ST_READY && !s.pc_ready);
}

int main(void) {
    test_init();
    test_ptt_roundtrip();
    test_gate();
    test_ok_enter_hint();
    test_down_alt_tab_hint();
    test_audio_error_panic_hint();
    test_ptt_max_pause_hint();
    test_pc_heartbeat_expiry();
    printf("test_app_state: PASS\n");
    return 0;
}
