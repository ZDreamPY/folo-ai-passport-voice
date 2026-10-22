// tests/test_emo_map.c —— EmoBall 状态→表情映射宿主测试(与 emo_map.c 注释一一对应)。
// 编译: cc -std=c11 -Wall -Wextra -Werror -Imain tests/test_emo_map.c main/apps/voice/emo_map.c
#include "apps/voice/emo_map.h"
#include <assert.h>
#include <stdio.h>

static emo_input_t base(void) {
    emo_input_t in = {0};
    in.screen_on = true;
    in.wifi_prov = APP_WIFI_CONNECTED;
    in.link_up = false;
    in.pc_ready = false;
    in.stage = APP_ST_READY;
    in.emo_hint_active = false;
    in.emo_hint = APP_EMO_HINT_NONE;
    return in;
}

static void test_screen_off_sleeps(void) {
    emo_input_t in = base();
    in.screen_on = false;
    in.emo_hint_active = true;
    in.emo_hint = APP_EMO_HINT_SENT_OK;
    in.stage = APP_ST_LISTENING;
    assert(emo_map_resolve(&in) == EMO_SLEEP);   // 息屏压倒一切(含提示/录音)
}

static void test_hints_win_over_state(void) {
    static const struct {
        uint8_t hint;
        emo_id_t want;
    } cases[] = {
        { APP_EMO_HINT_SENT_OK,  EMO_HAPPY },
        { APP_EMO_HINT_SWITCHED, EMO_SATISFIED },
        { APP_EMO_HINT_ERROR,    EMO_PANIC },
        { APP_EMO_HINT_PAUSED,   EMO_WAIT },
    };
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        emo_input_t in = base();
        in.emo_hint_active = true;
        in.emo_hint = cases[i].hint;
        assert(emo_map_resolve(&in) == cases[i].want);
    }
    // 提示过期:回常态
    emo_input_t in = base();
    in.emo_hint_active = false;
    in.emo_hint = APP_EMO_HINT_SENT_OK;
    assert(emo_map_resolve(&in) == EMO_WAIT);    // 无链路 → WAIT
}

static void test_listening_overrides(void) {
    emo_input_t in = base();
    in.stage = APP_ST_LISTENING;
    assert(emo_map_resolve(&in) == EMO_LISTEN);  // 录音压过配网/链路常态
}

static void test_wifi_states(void) {
    emo_input_t in = base();
    in.wifi_prov = APP_WIFI_AP_MODE;
    assert(emo_map_resolve(&in) == EMO_CURIOUS);
    in.wifi_prov = APP_WIFI_CONNECTING;
    assert(emo_map_resolve(&in) == EMO_CURIOUS);
    in.wifi_prov = APP_WIFI_FAILED;
    assert(emo_map_resolve(&in) == EMO_PANIC);
}

static void test_link_readiness(void) {
    emo_input_t in = base();
    assert(emo_map_resolve(&in) == EMO_WAIT);    // 什么都没连上
    in.link_up = true;
    assert(emo_map_resolve(&in) == EMO_WAIT);    // 链路通但电脑未就绪
    in.pc_ready = true;
    assert(emo_map_resolve(&in) == EMO_IDLE);    // 双就绪 → 待机呼吸
}

static void test_null_and_names(void) {
    assert(emo_map_resolve(NULL) == EMO_WAIT);
    for (int e = 0; e < EMO_COUNT; e++) {
        assert(emo_map_name((emo_id_t)e) != NULL);   // 全部可命名(日志安全)
    }
}

int main(void) {
    test_screen_off_sleeps();
    test_hints_win_over_state();
    test_listening_overrides();
    test_wifi_states();
    test_link_readiness();
    test_null_and_names();
    printf("test_emo_map: PASS\n");
    return 0;
}
