// main/apps/voice/emo_ball.c —— EmoBall 表情小球实现(LVGL 9.5)。
//
// 视觉优先级:assets 分区存在且校验通过 → emo_anim 帧播放器(mood-mates 云宝,
// tools/anim_export 预渲染);否则回退到本文件的程序动画(实心大眼 + 弧线嘴)。
// 程序动画原则:所有常态动画(呼吸/漂移/眨眼)在 apply_emo 里直接启动,
// 不经一次性动画回调接力;幅度按"120px 球上肉眼明显"标定。
// 清理:LV_EVENT_DELETE 里删 blink timer + 各对象动画 + ctx。
#include "emo_ball.h"
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "emo_anim.h"

// ---------------- 配色(深色页面,情绪即颜色) ----------------
#define EMO_INK   0x0E1620            // 五官色 = 页面底色,像"镂空"
#define EMO_GLINT 0xF7FBFF            // 眼内高光
typedef struct { uint32_t body; } emo_palette_t;
static const emo_palette_t PALETTE[EMO_COUNT] = {
    [EMO_SLEEP]     = { .body = 0x39434E },
    [EMO_IDLE]      = { .body = 0xFFB35C },   // 蜜橙
    [EMO_WAIT]      = { .body = 0x8CA0B4 },   // 灰蓝
    [EMO_CURIOUS]   = { .body = 0xB49CFF },   // 薰衣草
    [EMO_LISTEN]    = { .body = 0xFF7E6B },   // 珊瑚
    [EMO_HAPPY]     = { .body = 0xFFD35C },   // 明黄
    [EMO_SATISFIED] = { .body = 0x63C7FF },   // 天蓝
    [EMO_SURPRISED] = { .body = 0xFF9CB0 },   // 粉
    [EMO_PANIC]     = { .body = 0xFF5C5C },   // 红
};

typedef struct {
    lv_obj_t *anim_img;           // 帧资产路径:mood-mates 图像控件(NULL=程序动画路径)
    lv_obj_t *body;
    lv_obj_t *eye_l, *eye_r;      // 实心眼(圆角竖椭圆)
    lv_obj_t *glint_l, *glint_r;  // 眼内高光
    lv_obj_t *mouth;              // lv_arc 弧线嘴(微笑/皱眉)
    lv_obj_t *o_mouth;            // 圆嘴/短横线(录音 O、平嘴、闭眼嘴)
    lv_timer_t *blink;
    bool blink_quick;
    int32_t base;
    emo_id_t emo;
    uint8_t level;
} emo_ctx_t;

// ---------------- 几何(相对 base) ----------------
static inline int32_t ew(int32_t s) { return s * 13 / 100; }   // 眼宽
static inline int32_t eh(int32_t s) { return s * 20 / 100; }   // 眼高
static inline int32_t ex(int32_t s) { return s * 21 / 100; }   // 眼距中线
static inline int32_t ey(int32_t s) { return -s * 7 / 100; }   // 眼高中线

// ---------------- 小工具 ----------------
static void pill(lv_obj_t *o, uint32_t color, int32_t w, int32_t h) {
    lv_obj_set_size(o, w, h);
    lv_obj_set_style_radius(o, (w < h ? w : h) / 2, 0);
    lv_obj_set_style_bg_color(o, lv_color_hex(color), 0);
    lv_obj_set_style_bg_opa(o, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(o, 0, 0);
    lv_obj_remove_flag(o, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_remove_flag(o, LV_OBJ_FLAG_CLICKABLE);
}

static void anim_width_cb(void *var, int32_t v) { lv_obj_set_width((lv_obj_t *)var, v); }
static void anim_height_cb(void *var, int32_t v) { lv_obj_set_height((lv_obj_t *)var, v); }
static void anim_tx_cb(void *var, int32_t v) { lv_obj_set_style_translate_x((lv_obj_t *)var, v, 0); }
static void anim_ty_cb(void *var, int32_t v) { lv_obj_set_style_translate_y((lv_obj_t *)var, v, 0); }

// 体呼吸:宽涨高缩,果冻式一鼓一收(直启,无回调接力)。
static void start_breath(emo_ctx_t *c, int32_t amp, uint32_t ms) {
    lv_anim_t a;
    lv_anim_init(&a);
    lv_anim_set_var(&a, c->body);
    lv_anim_set_exec_cb(&a, anim_width_cb);
    lv_anim_set_values(&a, c->base, c->base + amp);
    lv_anim_set_duration(&a, ms);
    lv_anim_set_reverse_duration(&a, ms);
    lv_anim_set_repeat_count(&a, LV_ANIM_REPEAT_INFINITE);
    lv_anim_set_path_cb(&a, lv_anim_path_ease_in_out);
    lv_anim_start(&a);
    lv_anim_set_exec_cb(&a, anim_height_cb);
    lv_anim_set_values(&a, c->base, c->base - amp);
    lv_anim_start(&a);
}

// 眼球平移:眼 + 高光一起动。
static void gaze(emo_ctx_t *c, int32_t amp, uint32_t ms, int32_t repeats) {
    lv_obj_t *objs[4] = { c->eye_l, c->eye_r, c->glint_l, c->glint_r };
    for (int i = 0; i < 4; i++) {
        lv_anim_t a;
        lv_anim_init(&a);
        lv_anim_set_var(&a, objs[i]);
        lv_anim_set_exec_cb(&a, anim_tx_cb);
        lv_anim_set_values(&a, -amp, amp);
        lv_anim_set_duration(&a, ms);
        lv_anim_set_reverse_duration(&a, ms);
        lv_anim_set_repeat_count(&a, repeats);
        lv_anim_set_path_cb(&a, lv_anim_path_ease_in_out);
        lv_anim_start(&a);
    }
}

// 眨眼:双眼高度压扁(90ms 闭 + 90ms 开)。
static void blink_once(emo_ctx_t *c) {
    int32_t w = ew(c->base);
    lv_obj_t *eyes[2] = { c->eye_l, c->eye_r };
    for (int i = 0; i < 2; i++) {
        lv_anim_t a;
        lv_anim_init(&a);
        lv_anim_set_var(&a, eyes[i]);
        lv_anim_set_exec_cb(&a, anim_height_cb);
        lv_anim_set_values(&a, w, 3);
        lv_anim_set_duration(&a, 90);
        lv_anim_set_reverse_duration(&a, 90);
        lv_anim_start(&a);
    }
    lv_obj_t *glints[2] = { c->glint_l, c->glint_r };
    for (int i = 0; i < 2; i++) {   // 高光同步藏/现,避免闭眼时白点悬空
        lv_anim_t a;
        lv_anim_init(&a);
        lv_anim_set_var(&a, glints[i]);
        lv_anim_set_exec_cb(&a, anim_height_cb);
        lv_anim_set_values(&a, lv_obj_get_height(glints[i]), 1);
        lv_anim_set_duration(&a, 90);
        lv_anim_set_reverse_duration(&a, 90);
        lv_anim_start(&a);
    }
}

static void blink_timer_cb(lv_timer_t *t) {
    emo_ctx_t *c = (emo_ctx_t *)lv_timer_get_user_data(t);
    blink_once(c);
    if (c->blink_quick) {              // 双眨的第二次
        c->blink_quick = false;
        lv_timer_set_period(t, 230);
        return;
    }
    if (lv_rand(0, 3) == 0) {          // 25% 概率连眨两次,更像活物
        c->blink_quick = true;
        lv_timer_set_period(t, 270);
    } else {
        lv_timer_set_period(t, (uint32_t)lv_rand(1700, 3400));
    }
}

static void set_blink(emo_ctx_t *c, bool on) {
    if (!c->blink) return;
    if (on) lv_timer_resume(c->blink);
    else lv_timer_pause(c->blink);
}

// ---------------- 嘴 ----------------

// 弧线嘴:d 外接圆直径;微笑 start=20..160(过 90°/下),皱眉 200..340(过 270°/上)。
static void mouth_arc(emo_ctx_t *c, int32_t d, int32_t start, int32_t end,
                      int32_t aw, int32_t cy_off) {
    lv_obj_t *a = c->mouth;
    lv_obj_remove_flag(a, LV_OBJ_FLAG_HIDDEN);
    lv_obj_set_size(a, d, d);
    lv_arc_set_bg_angles(a, start, end);
    lv_arc_set_angles(a, start, end);
    lv_obj_set_style_bg_opa(a, LV_OPA_TRANSP, LV_PART_MAIN);
    lv_obj_set_style_arc_width(a, aw, LV_PART_INDICATOR);
    lv_obj_set_style_arc_color(a, lv_color_hex(EMO_INK), LV_PART_INDICATOR);
    lv_obj_set_style_arc_opa(a, LV_OPA_COVER, LV_PART_INDICATOR);
    lv_obj_set_style_arc_rounded(a, true, LV_PART_INDICATOR);
    lv_obj_set_style_bg_opa(a, LV_OPA_TRANSP, LV_PART_KNOB);
    lv_obj_set_style_pad_all(a, 0, LV_PART_KNOB);
    lv_obj_align(a, LV_ALIGN_CENTER, 0, cy_off);
    lv_obj_add_flag(c->o_mouth, LV_OBJ_FLAG_HIDDEN);
}

// 圆嘴(录音 O / 惊讶)或短横线(平嘴:w>h)。
static void mouth_o(emo_ctx_t *c, int32_t w, int32_t h, int32_t cy_off) {
    lv_obj_remove_flag(c->o_mouth, LV_OBJ_FLAG_HIDDEN);
    pill(c->o_mouth, EMO_INK, w, h);
    lv_obj_align(c->o_mouth, LV_ALIGN_CENTER, 0, cy_off);
    lv_obj_add_flag(c->mouth, LV_OBJ_FLAG_HIDDEN);
}

static void mouth_hide(emo_ctx_t *c) {
    lv_obj_add_flag(c->mouth, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(c->o_mouth, LV_OBJ_FLAG_HIDDEN);
}

// ---------------- 眼(重建) ----------------
static void eyes_normal(emo_ctx_t *c, int32_t h_scale) {
    int32_t s = c->base, w = ew(s), h = eh(s) * h_scale / 100;
    int32_t g = s * 45 / 1000;
    if (g < 3) g = 3;
    pill(c->eye_l, EMO_INK, w, h);
    lv_obj_align(c->eye_l, LV_ALIGN_CENTER, -ex(s), ey(s));
    pill(c->eye_r, EMO_INK, w, h);
    lv_obj_align(c->eye_r, LV_ALIGN_CENTER, ex(s), ey(s));
    lv_obj_remove_flag(c->glint_l, LV_OBJ_FLAG_HIDDEN);
    lv_obj_remove_flag(c->glint_r, LV_OBJ_FLAG_HIDDEN);
    pill(c->glint_l, EMO_GLINT, g, g);
    lv_obj_align(c->glint_l, LV_ALIGN_CENTER, -ex(s) + w / 3, ey(s) - h / 4);
    pill(c->glint_r, EMO_GLINT, g, g);
    lv_obj_align(c->glint_r, LV_ALIGN_CENTER, ex(s) + w / 3, ey(s) - h / 4);
}

static void eyes_closed(emo_ctx_t *c) {   // 闭眼/笑眯眼:两条短横线
    int32_t s = c->base, w = ew(s) + s * 2 / 100;
    pill(c->eye_l, EMO_INK, w, 4);
    lv_obj_align(c->eye_l, LV_ALIGN_CENTER, -ex(s), ey(s) + s * 2 / 100);
    pill(c->eye_r, EMO_INK, w, 4);
    lv_obj_align(c->eye_r, LV_ALIGN_CENTER, ex(s), ey(s) + s * 2 / 100);
    lv_obj_add_flag(c->glint_l, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(c->glint_r, LV_OBJ_FLAG_HIDDEN);
}

// ---------------- 录音能量驱动(体缩放 + O 嘴张合) ----------------
static void apply_level(emo_ctx_t *c) {
    int32_t lvl = c->level;
    lv_obj_set_width(c->body, c->base + c->base * lvl * 14 / 100);
    lv_obj_set_height(c->body, c->base - c->base * lvl * 8 / 100);
    mouth_o(c, c->base * (10 + lvl * 18) / 100,
            c->base * (10 + lvl * 18) / 100, c->base * 17 / 100);
}

// ---------------- 每个表情的姿态 ----------------
static void apply_emo(emo_ctx_t *c) {
    // 帧资产路径:表情切换即换剪辑,程序动画完全绕开
    if (c->anim_img) {
        emo_anim_play(c->emo);
        return;
    }
    // 清场:旧动画/旧平移全部撤销,再按新表情摆姿势(动画全部直启)
    lv_anim_delete(c->body, NULL);
    lv_obj_t *eye_objs[4] = { c->eye_l, c->eye_r, c->glint_l, c->glint_r };
    for (int i = 0; i < 4; i++) {
        lv_anim_delete(eye_objs[i], NULL);
        lv_obj_set_style_translate_x(eye_objs[i], 0, 0);
        lv_obj_set_style_translate_y(eye_objs[i], 0, 0);
    }
    lv_obj_set_style_translate_x(c->body, 0, 0);
    lv_obj_set_style_translate_y(c->body, 0, 0);
    lv_obj_set_style_shadow_width(c->body, c->base * 8 / 100, 0);
    lv_obj_set_style_shadow_opa(c->body, LV_OPA_20, 0);
    lv_obj_set_style_shadow_offset_y(c->body, c->base * 4 / 100, 0);
    pill(c->body, PALETTE[c->emo].body, c->base, c->base);
    lv_obj_set_style_radius(c->body, LV_RADIUS_CIRCLE, 0);

    switch (c->emo) {
    case EMO_SLEEP:      // 闭眼灰:短呼吸,平嘴小横线
        eyes_closed(c);
        mouth_o(c, c->base * 12 / 100, 4, c->base * 18 / 100);
        start_breath(c, c->base / 45, 2800);
        set_blink(c, false);
        break;
    case EMO_IDLE: {     // 待机:明显呼吸 + 整体轻浮 + 眼珠慢漂 + 眨眼
        eyes_normal(c, 100);
        mouth_arc(c, c->base * 34 / 100, 20, 160, c->base * 5 / 100 + 2,
                  c->base * 15 / 100);
        start_breath(c, c->base / 9, 1150);
        lv_anim_t a;
        lv_anim_init(&a);
        lv_anim_set_var(&a, c->body);
        lv_anim_set_exec_cb(&a, anim_ty_cb);
        lv_anim_set_values(&a, -c->base / 45, c->base / 45);
        lv_anim_set_duration(&a, 2300);
        lv_anim_set_reverse_duration(&a, 2300);
        lv_anim_set_repeat_count(&a, LV_ANIM_REPEAT_INFINITE);
        lv_anim_set_path_cb(&a, lv_anim_path_ease_in_out);
        lv_anim_start(&a);
        gaze(c, c->base * 5 / 100, 2800, LV_ANIM_REPEAT_INFINITE);
        set_blink(c, true);
        break;
    }
    case EMO_WAIT:       // 等待:眼半睁,慢呼吸,平嘴
        eyes_normal(c, 60);
        mouth_o(c, c->base * 14 / 100, 4, c->base * 18 / 100);
        start_breath(c, c->base / 13, 1750);
        gaze(c, c->base * 3 / 100, 3600, LV_ANIM_REPEAT_INFINITE);
        set_blink(c, true);
        break;
    case EMO_CURIOUS: {  // 张望:眼珠大幅扫视 + 身体跟着微微探
        eyes_normal(c, 100);
        mouth_arc(c, c->base * 28 / 100, 20, 160, c->base * 5 / 100 + 2,
                  c->base * 16 / 100);
        gaze(c, c->base * 8 / 100, 480, 6);
        lv_anim_t a;
        lv_anim_init(&a);
        lv_anim_set_var(&a, c->body);
        lv_anim_set_exec_cb(&a, anim_tx_cb);
        lv_anim_set_values(&a, -c->base * 3 / 100, c->base * 3 / 100);
        lv_anim_set_duration(&a, 480);
        lv_anim_set_reverse_duration(&a, 480);
        lv_anim_set_repeat_count(&a, 6);
        lv_anim_set_path_cb(&a, lv_anim_path_ease_in_out);
        lv_anim_start(&a);
        start_breath(c, c->base / 11, 1400);
        set_blink(c, true);
        break;
    }
    case EMO_LISTEN:     // 律动:体+O嘴由 set_level 逐帧驱动;眼稍大专注
        eyes_normal(c, 110);
        apply_level(c);
        set_blink(c, true);
        break;
    case EMO_HAPPY: {    // 发送成功:果冻弹跳 3 下 + 笑眯眼 + 大笑弧
        eyes_closed(c);
        mouth_arc(c, c->base * 44 / 100, 15, 165, c->base * 6 / 100 + 2,
                  c->base * 12 / 100);
        lv_anim_t a;
        lv_anim_init(&a);
        lv_anim_set_var(&a, c->body);
        lv_anim_set_exec_cb(&a, anim_height_cb);
        lv_anim_set_values(&a, c->base * 82 / 100, c->base);
        lv_anim_set_duration(&a, 500);
        lv_anim_set_repeat_count(&a, 3);
        lv_anim_set_path_cb(&a, lv_anim_path_overshoot);
        lv_anim_start(&a);
        lv_anim_set_exec_cb(&a, anim_width_cb);
        lv_anim_set_values(&a, c->base * 116 / 100, c->base);
        lv_anim_start(&a);
        set_blink(c, false);
        break;
    }
    case EMO_SATISFIED:  // 切窗完成:右眼 wink + 微笑弧 + 轻呼吸
        eyes_normal(c, 100);
        pill(c->eye_r, EMO_INK, ew(c->base), 4);
        lv_obj_align(c->eye_r, LV_ALIGN_CENTER, ex(c->base),
                     ey(c->base) + c->base * 2 / 100);
        lv_obj_add_flag(c->glint_r, LV_OBJ_FLAG_HIDDEN);
        mouth_arc(c, c->base * 36 / 100, 20, 160, c->base * 5 / 100 + 2,
                  c->base * 14 / 100);
        start_breath(c, c->base / 22, 950);
        set_blink(c, false);
        break;
    case EMO_SURPRISED: {  // 瞪大 + 一次鼓起 + 圆嘴
        eyes_normal(c, 125);
        mouth_o(c, c->base * 15 / 100, c->base * 15 / 100, c->base * 17 / 100);
        lv_anim_t a;
        lv_anim_init(&a);
        lv_anim_set_var(&a, c->body);
        lv_anim_set_exec_cb(&a, anim_height_cb);
        lv_anim_set_values(&a, c->base * 106 / 100, c->base);
        lv_anim_set_duration(&a, 280);
        lv_anim_set_path_cb(&a, lv_anim_path_overshoot);
        lv_anim_start(&a);
        set_blink(c, false);
        break;
    }
    case EMO_PANIC: {    // 异常:皱眉弧 + 快速发抖
        eyes_normal(c, 90);
        mouth_arc(c, c->base * 30 / 100, 200, 340, c->base * 5 / 100 + 2,
                  c->base * 22 / 100);
        lv_anim_t a;
        lv_anim_init(&a);
        lv_anim_set_var(&a, c->body);
        lv_anim_set_exec_cb(&a, anim_tx_cb);
        lv_anim_set_values(&a, -c->base / 20, c->base / 20);
        lv_anim_set_duration(&a, 60);
        lv_anim_set_reverse_duration(&a, 60);
        lv_anim_set_repeat_count(&a, 14);
        lv_anim_set_path_cb(&a, lv_anim_path_linear);
        lv_anim_start(&a);
        set_blink(c, false);
        break;
    }
    default:
        eyes_normal(c, 100);
        mouth_hide(c);
        set_blink(c, true);
        break;
    }
}

// ---------------- 对外接口 ----------------
static void on_ball_delete(lv_event_t *e) {
    emo_ctx_t *c = (emo_ctx_t *)lv_event_get_user_data(e);
    if (!c) return;
    if (c->anim_img) { lv_free(c); return; }   // 帧资产路径:控件随父删除,timer 由 emo_anim 管
    if (c->blink) { lv_timer_delete(c->blink); c->blink = NULL; }
    lv_anim_delete(c->body, NULL);
    lv_obj_t *eye_objs[4] = { c->eye_l, c->eye_r, c->glint_l, c->glint_r };
    for (int i = 0; i < 4; i++) lv_anim_delete(eye_objs[i], NULL);
    lv_free(c);
}

lv_obj_t *emo_ball_create(lv_obj_t *parent, int32_t x, int32_t y, int32_t size) {
    emo_ctx_t *c = (emo_ctx_t *)lv_malloc(sizeof(emo_ctx_t));
    if (!c) return NULL;
    memset(c, 0, sizeof(*c));
    c->base = size;
    c->emo = EMO_IDLE;

    lv_obj_t *ball = lv_obj_create(parent);
    lv_obj_remove_style_all(ball);
    lv_obj_set_size(ball, size, size);
    lv_obj_set_pos(ball, x, y);
    lv_obj_remove_flag(ball, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_user_data(ball, c);
    lv_obj_add_event_cb(ball, on_ball_delete, LV_EVENT_DELETE, c);

    // 优先 mood-mates 帧资产(预渲染循环剪辑);失败则回退程序动画
    if (emo_anim_init()) {
        c->anim_img = emo_anim_create_widget(ball, size);
        if (c->anim_img) {
            emo_anim_play(EMO_IDLE);
            return ball;
        }
    }

    c->body = lv_obj_create(ball);
    pill(c->body, PALETTE[EMO_IDLE].body, size, size);
    lv_obj_align(c->body, LV_ALIGN_CENTER, 0, 0);
    lv_obj_set_style_shadow_color(c->body, lv_color_hex(0x000000), 0);

    c->eye_l = lv_obj_create(ball);
    c->eye_r = lv_obj_create(ball);
    c->glint_l = lv_obj_create(ball);
    c->glint_r = lv_obj_create(ball);
    c->mouth = lv_arc_create(ball);
    lv_obj_remove_flag(c->mouth, LV_OBJ_FLAG_CLICKABLE);
    c->o_mouth = lv_obj_create(ball);
    lv_obj_add_flag(c->o_mouth, LV_OBJ_FLAG_HIDDEN);

    c->blink = lv_timer_create(blink_timer_cb, 2400, c);
    lv_timer_pause(c->blink);

    apply_emo(c);   // 摆出 EMO_IDLE 初始姿态,呼吸/漂移动画即刻启动
    return ball;
}

void emo_ball_set(lv_obj_t *ball, emo_id_t emo) {
    emo_ctx_t *c = (emo_ctx_t *)lv_obj_get_user_data(ball);
    if (!c || emo >= EMO_COUNT) return;
    if (emo == c->emo) return;   // 同表情重复调用不重启动画
    c->emo = emo;
    apply_emo(c);
}

void emo_ball_set_level(lv_obj_t *ball, uint8_t level) {
    emo_ctx_t *c = (emo_ctx_t *)lv_obj_get_user_data(ball);
    if (!c) return;
    c->level = level;
    if (c->anim_img) {              // 帧资产路径:LISTEN 剪辑轻微缩放律动
        emo_anim_set_level(level);
        return;
    }
    if (c->emo != EMO_LISTEN) return;   // 只缓存;进 LISTEN 时 apply 会消费
    apply_level(c);
}

void emo_ball_delete(lv_obj_t *ball) {
    if (ball) lv_obj_delete(ball);
}
