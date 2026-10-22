// main/apps/voice/app_ui.c —— 语音遥控 UI:顶部标题/电池,中央 EmoBall,
// 下方状态行 + 按键提示卡 + 底部 toast;AP_MODE 切配网页。
// 约束:文案只用 app_font_16/20 已生成的字符集(见 assets/fonts 生成命令),
// 未知汉字会渲染成占位方块 —— 改文案前先查 assets/README.md。
#include "app_ui.h"
#include "emo_map.h"
#include "emo_ball.h"
#include "audio_streamer.h"

#include "lvgl.h"
#include <stdio.h>
#include <string.h>

extern const lv_font_t app_font_16;
extern const lv_font_t app_font_20;

// ---------------- 配色(与 EmoBall 同一套深色系统) ----------------
#define UI_BG     0x0E1620
#define UI_CARD   0x182530
#define UI_INK    0xE8F1F2
#define UI_DIM    0x7B8A94
#define UI_ACCENT 0xFFA94D
#define UI_WARN   0xE05B5B

// ---------------- 布局常量(240x320,圆角 30) ----------------
#define BALL_SIZE   120
#define BALL_X      60
#define BALL_Y_MAIN 76
#define BALL_Y_PROV 44

typedef struct {
    lv_obj_t *scr;
    lv_obj_t *battery;
    lv_obj_t *ball;
    lv_obj_t *main_group;
    lv_obj_t *status;
    lv_obj_t *hint;
    lv_obj_t *toast_pill;
    lv_obj_t *toast_label;
    lv_obj_t *prov_group;
    lv_obj_t *prov_head;
    lv_obj_t *prov_ap;
    lv_obj_t *prov_url;
} ui_t;

static ui_t s_ui;

static lv_obj_t *label(lv_obj_t *parent, const lv_font_t *font, uint32_t color,
                       int32_t x, int32_t y, int32_t w, const char *text) {
    lv_obj_t *l = lv_label_create(parent);
    lv_label_set_text(l, text);
    lv_obj_set_style_text_font(l, font, 0);
    lv_obj_set_style_text_color(l, lv_color_hex(color), 0);
    lv_obj_set_style_text_align(l, LV_TEXT_ALIGN_CENTER, 0);
    if (w > 0) {
        lv_obj_set_width(l, w);
        lv_label_set_long_mode(l, LV_LABEL_LONG_WRAP);
    }
    lv_obj_set_pos(l, x, y);
    return l;
}

esp_err_t app_ui_init(void) {
    s_ui.scr = lv_obj_create(NULL);
    lv_obj_set_style_bg_color(s_ui.scr, lv_color_hex(UI_BG), 0);
    lv_obj_set_style_bg_opa(s_ui.scr, LV_OPA_COVER, 0);

    // 顶栏:标题 + 电池(读不到就整块隐藏)
    label(s_ui.scr, &app_font_20, UI_INK, 16, 12, 120, "语音遥控");
    s_ui.battery = label(s_ui.scr, &app_font_16, UI_ACCENT, 150, 14, 74, "");
    lv_obj_set_style_text_align(s_ui.battery, LV_TEXT_ALIGN_RIGHT, 0);

    // 表情小球:常驻顶层,主/配网页共用(切页时仅挪位置)
    s_ui.ball = emo_ball_create(s_ui.scr, BALL_X, BALL_Y_MAIN, BALL_SIZE);

    // ---- 主页组 ----
    s_ui.main_group = lv_obj_create(s_ui.scr);
    lv_obj_remove_style_all(s_ui.main_group);
    lv_obj_set_size(s_ui.main_group, 240, 320);
    lv_obj_set_pos(s_ui.main_group, 0, 0);
    lv_obj_remove_flag(s_ui.main_group, LV_OBJ_FLAG_SCROLLABLE);

    s_ui.status = label(s_ui.main_group, &app_font_20, UI_INK, 0, 208, 240, "未连接");
    s_ui.hint = label(s_ui.main_group, &app_font_16, UI_DIM, 0, 246, 240,
                      "上键说话·再点结束\nOK发送 下切换窗口");

    s_ui.toast_pill = lv_obj_create(s_ui.main_group);
    lv_obj_set_size(s_ui.toast_pill, 200, 30);
    lv_obj_set_pos(s_ui.toast_pill, 20, 274);
    lv_obj_set_style_radius(s_ui.toast_pill, 15, 0);
    lv_obj_set_style_bg_color(s_ui.toast_pill, lv_color_hex(UI_CARD), 0);
    lv_obj_set_style_bg_opa(s_ui.toast_pill, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(s_ui.toast_pill, 0, 0);
    lv_obj_remove_flag(s_ui.toast_pill, LV_OBJ_FLAG_SCROLLABLE);
    s_ui.toast_label = label(s_ui.toast_pill, &app_font_16, UI_INK, 0, 0, 184, "");
    lv_obj_center(s_ui.toast_label);
    lv_obj_add_flag(s_ui.toast_pill, LV_OBJ_FLAG_HIDDEN);

    // ---- 配网组(AP_MODE 时替换主页组) ----
    s_ui.prov_group = lv_obj_create(s_ui.scr);
    lv_obj_remove_style_all(s_ui.prov_group);
    lv_obj_set_size(s_ui.prov_group, 240, 320);
    lv_obj_set_pos(s_ui.prov_group, 0, 0);
    lv_obj_remove_flag(s_ui.prov_group, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(s_ui.prov_group, LV_OBJ_FLAG_HIDDEN);

    s_ui.prov_head = label(s_ui.prov_group, &app_font_20, UI_ACCENT, 0, 176, 240,
                           "配网模式");
    s_ui.prov_ap = label(s_ui.prov_group, &app_font_16, UI_INK, 0, 214, 240,
                         "热点 AI-Passport-Setup");
    label(s_ui.prov_group, &app_font_16, UI_DIM, 0, 242, 240, "浏览器打开");
    s_ui.prov_url = label(s_ui.prov_group, &app_font_20, UI_INK, 0, 270, 240,
                          "192.168.4.1");

    lv_screen_load(s_ui.scr);
    return ESP_OK;
}

void app_ui_deinit(void) {
    if (s_ui.scr) {
        // 小球随 screen 一起删;DELETE 事件里已回收其 timer/动画/上下文
        lv_obj_delete(s_ui.scr);
    }
    memset(&s_ui, 0, sizeof(s_ui));
}

void app_ui_show(void) {
    if (s_ui.scr) lv_obj_remove_flag(s_ui.scr, LV_OBJ_FLAG_HIDDEN);
}

void app_ui_hide(void) {
    if (s_ui.scr) lv_obj_add_flag(s_ui.scr, LV_OBJ_FLAG_HIDDEN);
}

static void render_main(const app_ui_snapshot_t *snap) {
    // 状态行:录音时长 > 链路/就绪
    char buf[40];
    if (snap->state == APP_ST_LISTENING) {
        uint32_t sec = snap->elapsed_ms / 1000;
        snprintf(buf, sizeof(buf), "录音中 %02u:%02u",
                 (unsigned)(sec / 60), (unsigned)(sec % 60));
        lv_obj_set_style_text_color(s_ui.status, lv_color_hex(UI_ACCENT), 0);
    } else if (!snap->link_up) {
        snprintf(buf, sizeof(buf), "未连接");
        lv_obj_set_style_text_color(s_ui.status, lv_color_hex(UI_DIM), 0);
    } else if (!snap->pc_ready) {
        snprintf(buf, sizeof(buf), "等待电脑就绪");
        lv_obj_set_style_text_color(s_ui.status, lv_color_hex(UI_DIM), 0);
    } else {
        snprintf(buf, sizeof(buf), "已连接");
        lv_obj_set_style_text_color(s_ui.status, lv_color_hex(UI_INK), 0);
    }
    lv_label_set_text(s_ui.status, buf);

    // 提示卡:只在完全就绪时出现(录音中让位给状态行)
    bool ready = snap->state == APP_ST_READY && snap->link_up && snap->pc_ready;
    if (ready) lv_obj_remove_flag(s_ui.hint, LV_OBJ_FLAG_HIDDEN);
    else lv_obj_add_flag(s_ui.hint, LV_OBJ_FLAG_HIDDEN);

    // toast(状态机已带时效)
    if (snap->toast[0] != '\0') {
        lv_label_set_text(s_ui.toast_label, snap->toast);
        lv_obj_remove_flag(s_ui.toast_pill, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(s_ui.toast_pill, LV_OBJ_FLAG_HIDDEN);
    }
}

static void render_prov(const app_ui_snapshot_t *snap) {
    // 配网状态拼进标题行,省一行版面
    const char *st = snap->wifi_prov == APP_WIFI_FAILED ? "失败"
                     : (snap->wifi_prov == APP_WIFI_CONNECTED ? "已连接" : "正在连");
    char buf[48];
    snprintf(buf, sizeof(buf), "配网模式 %s", st);
    lv_label_set_text(s_ui.prov_head, buf);
    lv_obj_set_style_text_color(s_ui.prov_head,
        lv_color_hex(snap->wifi_prov == APP_WIFI_FAILED ? UI_WARN : UI_ACCENT), 0);
}

void app_ui_render(const app_ui_snapshot_t *snap) {
    if (!s_ui.scr || !snap) return;

    // 电池(采样失败隐藏)
    if (snap->battery_available) {
        char buf[8];
        snprintf(buf, sizeof(buf), "%u%%", (unsigned)snap->battery_soc);
        lv_label_set_text(s_ui.battery, buf);
        lv_obj_set_style_text_color(s_ui.battery,
            lv_color_hex(snap->battery_soc > 20 ? UI_ACCENT : UI_WARN), 0);
        lv_obj_remove_flag(s_ui.battery, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(s_ui.battery, LV_OBJ_FLAG_HIDDEN);
    }

    // 主页 / 配网页切换(小球挪到当前页的留白处)
    bool prov = snap->wifi_prov == APP_WIFI_AP_MODE || snap->wifi_prov == APP_WIFI_FAILED;
    if (prov) {
        lv_obj_add_flag(s_ui.main_group, LV_OBJ_FLAG_HIDDEN);
        lv_obj_remove_flag(s_ui.prov_group, LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_pos(s_ui.ball, BALL_X, BALL_Y_PROV);
        render_prov(snap);
    } else {
        lv_obj_remove_flag(s_ui.main_group, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(s_ui.prov_group, LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_pos(s_ui.ball, BALL_X, BALL_Y_MAIN);
        render_main(snap);
    }

    // 表情:状态机意图(emo_map)→ 小球表现;录音态喂能量
    emo_input_t in = {
        .screen_on = snap->screen_on,
        .wifi_prov = snap->wifi_prov,
        .link_up = snap->link_up,
        .pc_ready = snap->pc_ready,
        .stage = (uint8_t)snap->state,
        .emo_hint_active = snap->emo_hint_active,
        .emo_hint = snap->emo_hint,
    };
    emo_id_t emo = emo_map_resolve(&in);
    emo_ball_set(s_ui.ball, emo);
    if (emo == EMO_LISTEN) {
        uint32_t peak = audio_streamer_peak();
        uint32_t lvl = peak / 150;               // 粗标定:日常说话可见起伏,不顶格
        if (lvl > 100) lvl = 100;
        emo_ball_set_level(s_ui.ball, (uint8_t)lvl);
    }
}
