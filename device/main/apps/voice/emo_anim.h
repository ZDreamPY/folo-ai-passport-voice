// main/apps/voice/emo_anim.h —— mood-mates 帧资产播放器(内部接口,emo_ball 代理调用)。
// 资产 = assets 分区内的 assets.bin:9 个表情 × 量化 RLE 帧流(120x120 RGB565 索引帧),
// 由 tools/anim_export/pack.js 从 mood-mates(云宝 Nimbo)预渲染导出,循环剪辑无缝。
// 须持 bsp_lvgl_lock 调用;单实例假设(应用只有一个表情小球)。
#pragma once

#include "emo_map.h"
#include "lvgl.h"
#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    uint8_t slot;          // emo_id_t
    uint8_t fps;
    uint16_t frame_count;
    uint8_t w, h;
    uint8_t pal_n;
    uint32_t clip_ms;
    uint32_t pal_off;      // assets.bin 内偏移
    uint32_t data_off;
} emo_anim_clip_t;

// 找 assets 分区 + mmap + 校验头;失败返回 false(emo_ball 自动回退程序动画)。
bool emo_anim_init(void);
bool emo_anim_ready(void);

// 在 parent(size×size 容器)上创建 120x120 图像控件,居中。
lv_obj_t *emo_anim_create_widget(lv_obj_t *parent, int32_t size);

// 切换到指定表情剪辑(首帧立即解码,定时器按 fps 推进;同剪辑幂等)。
bool emo_anim_play(emo_id_t emo);

// 录音能量 0..100(LISTEN 剪辑轻微缩放律动)。
void emo_anim_set_level(uint8_t level);

#ifdef __cplusplus
}
#endif
