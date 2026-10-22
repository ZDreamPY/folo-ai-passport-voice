// WeType remote: UP records, OK sends Enter, DOWN switches window (Alt+Tab).
#include "app_state.h"
#include <stdio.h>
#include <string.h>

#define PC_STATUS_TIMEOUT_MS 3500u
static void emit(app_action_t *out, uint8_t *n, app_action_type_t type) {
    if (*n < APP_ACT_MAX) out[(*n)++] = (app_action_t){ .type = type };
}
// 表情提示统一入口:动作成功/失败时的瞬时反馈,emo_map 优先消费。
static void hint(app_state_t *s, uint64_t now, app_emo_hint_t h, uint32_t ms) {
    s->emo_hint = (uint8_t)h;
    s->emo_hint_until_ms = now + ms;
}
static void end_voice(app_state_t *s, uint64_t now, bool cancel, app_action_t *out, uint8_t *n) {
    if (s->state != APP_ST_LISTENING) return;
    emit(out, n, cancel ? APP_ACT_STREAM_CANCEL : APP_ACT_STREAM_STOP);
    emit(out, n, APP_ACT_SEND_VOICE_END);
    s->state = APP_ST_READY;
    s->state_since_ms = now;
    s->stream_started = false;
    s->net_busy = false;
}
void app_state_init(app_state_t *s) {
    memset(s, 0, sizeof(*s));
    s->state = APP_ST_READY;
    s->screen_on = s->panel_on = true;
}
void app_state_snapshot(const app_state_t *s, uint64_t now, app_ui_snapshot_t *snap) {
    memset(snap, 0, sizeof(*snap));
    snap->state = s->state;
    snap->link_up = s->link_up;
    snap->pc_ready = s->pc_ready;
    snap->screen_on = s->screen_on;
    snap->panel_on = s->panel_on;
    snap->net_busy = s->net_busy;
    snap->elapsed_ms = (uint32_t)(now - s->state_since_ms);
    snprintf(snap->link_name, sizeof(snap->link_name), "WiFi");
    if (now < s->toast_until_ms) snprintf(snap->toast, sizeof(snap->toast), "%s", s->toast);
    snap->emo_hint_active = now < s->emo_hint_until_ms;
    snap->emo_hint = snap->emo_hint_active ? s->emo_hint : (uint8_t)APP_EMO_HINT_NONE;
}
void app_state_reduce(app_state_t *s, const app_event_t *ev, uint64_t now, app_action_t *out, uint8_t *n) {
    *n = 0;
    switch (ev->type) {
    case APP_EV_LINK_UP: s->link_up = true; break;
    case APP_EV_LINK_DOWN:
        s->link_up = s->pc_ready = false;
        s->pc_status_ms = 0;
        end_voice(s, now, true, out, n);
        break;
    case APP_EV_PC_STATUS:
        s->pc_status_ms = now;
        s->pc_ready = ev->u.pc_status.audio_ready && ev->u.pc_status.hotkey_ready;
        if (!s->pc_ready) end_voice(s, now, true, out, n);
        break;
    case APP_EV_KEY_CLICK:
        // 点按模式(tap-to-talk):上键单击开录、再击收束,与微信输入法
        // "点按开始/再点按上屏"节奏一致;CLICK 由 BSP 在抬起时判定,天然滤抖。
        // Vibe Coding 遥控器键位:中键单击=回车发送;下键单击=Alt+Tab 切窗口。
        if (ev->u.key.btn == APP_BTN_UP) {
            if (s->state == APP_ST_READY && s->link_up && s->pc_ready) {
                s->state = APP_ST_LISTENING;
                s->state_since_ms = now;
                s->stream_started = true;
                s->toast_until_ms = 0;
                emit(out, n, APP_ACT_SEND_VOICE_START);
                emit(out, n, APP_ACT_STREAM_START);
            } else if (s->state == APP_ST_LISTENING) {
                end_voice(s, now, false, out, n);
            }
            break;
        }
        // 单击只在 READY 态生效。录音中/电脑心跳过期一律忽略,防止把回车
        // 发进别的窗口。松开 ADC 读数不是键 ID,不做 mv 门禁(与 demo 一致)。
        if (s->state == APP_ST_READY && s->link_up && s->pc_ready) {
            if (ev->u.key.btn == APP_BTN_OK) {
                out[(*n)++] = (app_action_t){.type = APP_ACT_SEND_KEY_ACTION,
                    .u.key_action.action = APP_KEY_ENTER};
                snprintf(s->toast, sizeof(s->toast), "已发送回车");
                s->toast_until_ms = now + 1500;
                hint(s, now, APP_EMO_HINT_SENT_OK, 2500);
            } else if (ev->u.key.btn == APP_BTN_DOWN) {
                out[(*n)++] = (app_action_t){.type = APP_ACT_SEND_KEY_ACTION,
                    .u.key_action.action = APP_KEY_ALT_TAB};
                snprintf(s->toast, sizeof(s->toast), "已切换窗口");
                s->toast_until_ms = now + 1500;
                hint(s, now, APP_EMO_HINT_SWITCHED, 2500);
            }
        }
        break;
    case APP_EV_AUDIO_ERROR:
        end_voice(s, now, true, out, n);
        snprintf(s->toast, sizeof(s->toast), "麦克风异常，请重试");
        s->toast_until_ms = now + 4000;
        hint(s, now, APP_EMO_HINT_ERROR, 4000);
        break;
    case APP_EV_AUDIO_DROP_START: s->net_busy = s->state == APP_ST_LISTENING; break;
    case APP_EV_AUDIO_DROP_END: s->net_busy = false; break;
    case APP_EV_TICK:
        if (s->pc_ready && now - s->pc_status_ms > PC_STATUS_TIMEOUT_MS) {
            s->pc_ready = false;
            end_voice(s, now, true, out, n);
        }
        if (s->state == APP_ST_LISTENING && now - s->state_since_ms >= APP_PTT_MAX_TALK_MS) {
            end_voice(s, now, false, out, n);
            snprintf(s->toast, sizeof(s->toast), "已暂停");
            s->toast_until_ms = now + 4000;
            hint(s, now, APP_EMO_HINT_PAUSED, 4000);
        }
        break;
    case APP_EV_TIME_SET:
        out[(*n)++] = (app_action_t){.type = APP_ACT_TIME_SET, .u.time_set.epoch = ev->u.time_set.epoch};
        break;
    default:
        // No clear, approval or transcript. Registry owns exit and sleep.
        break;
    }
}
