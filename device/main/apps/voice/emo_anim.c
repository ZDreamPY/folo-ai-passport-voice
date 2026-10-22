// main/apps/voice/emo_anim.c —— mood-mates 帧资产播放器实现。
//
// 数据面:assets 分区整体 mmap(零拷贝读 flash 缓存),RLE 流按
//   [run u8(1..255), 调色板索引 u8] 解码进 32KB 静态 RGB565 帧缓冲,
//   解满 w*h 像素即一帧,读指针自然推进;剪辑播完回绕到帧 0(无缝循环)。
// 控制面:lv_timer 按 1000/fps 推帧;切换表情 = 重置读指针 + 换调色板 + 首帧即出。
// 失败面:分区缺失 / 头校验不过 → ready=false,emo_ball 回退程序动画。
#include "emo_anim.h"
#include <string.h>

#include "esp_partition.h"

#define ANIM_MAX_DIM      128
#define ANIM_FB_PIXELS    (ANIM_MAX_DIM * ANIM_MAX_DIM)
#define ANIM_HEADER_BYTES 12
#define ANIM_ENTRY_BYTES  32

typedef struct {
    bool ready;
    const esp_partition_t *part;
    esp_partition_mmap_handle_t mmh;
    const uint8_t *base;              // assets.bin 起点(mmap)
    uint32_t map_size;
    emo_anim_clip_t clips[EMO_COUNT]; // slot → clip;pal_off/data_off 有效的才有资产

    lv_obj_t *img;
    lv_timer_t *timer;
    const emo_anim_clip_t *cur;
    const uint8_t *frame_p;           // RLE 读指针(mmap 内绝对位置)
    uint16_t frame_idx;
    uint16_t pal[256];
    uint16_t fb[ANIM_FB_PIXELS];      // 当前帧解码缓冲(小端 RGB565)
    lv_image_dsc_t dsc;
    uint8_t level;
} anim_state_t;

static anim_state_t S;

// ---------------- 资产发现与校验 ----------------
static inline uint32_t rd32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
static inline uint16_t rd16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }

bool emo_anim_ready(void) { return S.ready; }

bool emo_anim_init(void) {
    if (S.ready) return true;
    memset(&S, 0, sizeof(S));

    S.part = esp_partition_find_first(ESP_PARTITION_TYPE_DATA,
                                      ESP_PARTITION_SUBTYPE_DATA_SPIFFS, "assets");
    if (!S.part) return false;
    if (S.part->size < ANIM_HEADER_BYTES + ANIM_ENTRY_BYTES * EMO_COUNT) return false;

    const void *mm_ptr = NULL;
    esp_err_t err = esp_partition_mmap(S.part, 0, S.part->size,
                                       ESP_PARTITION_MMAP_DATA, &mm_ptr, &S.mmh);
    if (err != ESP_OK || !mm_ptr) return false;
    S.base = (const uint8_t *)mm_ptr;
    S.map_size = S.part->size;

    const uint8_t *h = S.base;
    if (h[0] != 'M' || h[1] != 'A' || h[2] != 'P' || h[3] != '1') return false;
    if (rd16(h + 4) != 1) return false;
    uint16_t count = rd16(h + 6);
    if (count == 0 || count > EMO_COUNT) return false;

    int found = 0;
    for (uint16_t i = 0; i < count; i++) {
        const uint8_t *e = h + ANIM_HEADER_BYTES + (uint32_t)i * ANIM_ENTRY_BYTES;
        uint8_t slot = e[0];
        if (slot >= EMO_COUNT) continue;
        emo_anim_clip_t *c = &S.clips[slot];
        c->slot = slot;
        c->fps = e[1];
        c->frame_count = rd16(e + 2);
        c->w = e[4];
        c->h = e[5];
        c->pal_n = e[6];
        c->pal_off = rd32(e + 8);
        c->data_off = rd32(e + 12);
        uint32_t data_len = rd32(e + 16);
        c->clip_ms = rd32(e + 20);
        // 边界校验:全部数据必须落在分区内
        if (c->fps == 0 || c->frame_count == 0 || c->w == 0 || c->h == 0 ||
            c->w > ANIM_MAX_DIM || c->h > ANIM_MAX_DIM || c->pal_n == 0 ||
            (uint32_t)c->pal_off + (uint32_t)c->pal_n * 2 > S.map_size ||
            (uint64_t)c->data_off + data_len > S.map_size) {
            memset(c, 0, sizeof(*c));
            continue;
        }
        found++;
    }
    if (found == 0) return false;
    S.ready = true;
    return true;
}

// ---------------- 帧解码 ----------------
static void decode_next(void) {
    const emo_anim_clip_t *c = S.cur;
    if (!c || !S.img) return;

    const uint8_t *p = S.frame_p;
    const uint16_t *pal = S.pal;
    uint16_t *out = S.fb;
    size_t left = (size_t)c->w * c->h;
    while (left) {
        uint32_t run = *p++;
        uint16_t color = pal[*p++];
        if (run > left) run = (uint32_t)left;   // 损坏数据防御:不越界
        left -= run;
        while (run--) *out++ = color;
    }

    S.frame_idx++;
    if (S.frame_idx >= c->frame_count) {        // 循环回绕
        S.frame_idx = 0;
        p = S.base + c->data_off;
    }
    S.frame_p = p;
    lv_obj_invalidate(S.img);
}

static void anim_timer_cb(lv_timer_t *t) {
    (void)t;
    decode_next();
}

// ---------------- 对外接口 ----------------
static inline int32_t scale_for(emo_id_t emo) {
    if (emo == EMO_LISTEN) return 256 + (int32_t)S.level * 38 / 100;   // 最大 ~115%
    return 256;
}

static void on_img_delete(lv_event_t *e);

lv_obj_t *emo_anim_create_widget(lv_obj_t *parent, int32_t size) {
    if (!S.ready) return NULL;
    S.img = lv_image_create(parent);
    lv_obj_remove_flag(S.img, LV_OBJ_FLAG_CLICKABLE);
    lv_image_set_antialias(S.img, true);
    lv_image_set_pivot(S.img, size / 2, size / 2);
    lv_obj_set_size(S.img, size, size);
    lv_obj_align(S.img, LV_ALIGN_CENTER, 0, 0);
    S.timer = lv_timer_create(anim_timer_cb, 66, NULL);
    lv_timer_pause(S.timer);
    lv_obj_add_event_cb(S.img, on_img_delete, LV_EVENT_DELETE, NULL);
    return S.img;
}

// 控件随父删除:停 timer 并清引用,等待下一次 create_widget 重建
static void on_img_delete(lv_event_t *e) {
    (void)e;
    if (S.timer) { lv_timer_delete(S.timer); S.timer = NULL; }
    S.img = NULL;
    S.cur = NULL;
}

bool emo_anim_play(emo_id_t emo) {
    if (!S.ready || !S.img || emo >= EMO_COUNT) return false;
    const emo_anim_clip_t *c = &S.clips[emo];
    if (c->frame_count == 0) return false;
    if (S.cur == c) return true;                 // 同剪辑幂等

    S.cur = c;
    memcpy(S.pal, S.base + c->pal_off, (size_t)c->pal_n * 2);   // u16 LE 直接落 SRAM
    memset(&S.dsc, 0, sizeof(S.dsc));
    S.dsc.header.magic = LV_IMAGE_HEADER_MAGIC;
    S.dsc.header.cf = LV_COLOR_FORMAT_RGB565;
    S.dsc.header.w = c->w;
    S.dsc.header.h = c->h;
    S.dsc.header.stride = c->w * 2;              // 紧排,无对齐缝隙
    S.dsc.data = (const uint8_t *)S.fb;
    S.dsc.data_size = (uint32_t)c->w * c->h * 2;

    S.frame_idx = 0;
    S.frame_p = S.base + c->data_off;
    lv_image_set_src(S.img, &S.dsc);
    lv_image_set_scale(S.img, scale_for(emo));
    lv_timer_set_period(S.timer, 1000 / c->fps);
    lv_timer_resume(S.timer);
    decode_next();                               // 首帧立即上屏
    return true;
}

void emo_anim_set_level(uint8_t level) {
    S.level = level;
    if (S.img && S.cur && S.cur->slot == EMO_LISTEN) {
        lv_image_set_scale(S.img, scale_for(EMO_LISTEN));
    }
}
