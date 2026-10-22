// main/apps/voice/emo_map.c —— 表情映射实现(纯 C,零 ESP-IDF 依赖)。
// 优先级从高到低:息屏 > 瞬时提示 > 录音中 > 配网状态 > 链路就绪。
// 每条规则一行注释,行为与 tests/test_emo_map.c 一一对应。
#include "emo_map.h"

emo_id_t emo_map_resolve(const emo_input_t *in) {
    if (!in) return EMO_WAIT;
    // 1. 屏幕灭:小球也睡(唯一入口,面板断电时 UI 不会渲染,保底防御)
    if (!in->screen_on) return EMO_SLEEP;
    // 2. 瞬时提示最优先:动作结果必须被看见,即使状态机已经切走
    if (in->emo_hint_active) {
        switch (in->emo_hint) {
        case APP_EMO_HINT_SENT_OK:  return EMO_HAPPY;
        case APP_EMO_HINT_SWITCHED: return EMO_SATISFIED;
        case APP_EMO_HINT_ERROR:    return EMO_PANIC;
        case APP_EMO_HINT_PAUSED:   return EMO_WAIT;
        default: break;   // NONE/未知:落回常态
        }
    }
    // 3. 录音中优先于一切常态(配网页下不会录音,无冲突)
    if (in->stage == APP_ST_LISTENING) return EMO_LISTEN;
    // 4. 配网状态:热点/连网中 → 好奇张望;重试耗尽 → 慌张
    if (in->wifi_prov == APP_WIFI_AP_MODE ||
        in->wifi_prov == APP_WIFI_CONNECTING) return EMO_CURIOUS;
    if (in->wifi_prov == APP_WIFI_FAILED) return EMO_PANIC;
    // 5. 链路与电脑都就绪 → 待机呼吸;其余(未连/电脑未就绪) → 等待
    if (in->link_up && in->pc_ready) return EMO_IDLE;
    return EMO_WAIT;
}

const char *emo_map_name(emo_id_t emo) {
    switch (emo) {
    case EMO_SLEEP:     return "sleep";
    case EMO_IDLE:      return "idle";
    case EMO_WAIT:      return "wait";
    case EMO_CURIOUS:   return "curious";
    case EMO_LISTEN:    return "listen";
    case EMO_HAPPY:     return "happy";
    case EMO_SATISFIED: return "satisfied";
    case EMO_SURPRISED: return "surprised";
    case EMO_PANIC:     return "panic";
    default:            return "?";
    }
}
