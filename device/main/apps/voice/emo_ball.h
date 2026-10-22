// main/apps/voice/emo_ball.h —— EmoBall 表情小球 LVGL widget(LVGL 9.5)。
// EmotionBall 方法论移植:上层只给 emo_id(意图),小球负责所有表现;
// 纯 LVGL 对象零图片:圆体 squash&stretch(lv_anim)、眨眼(lv_timer)、抖动。
// 须持 bsp_lvgl_lock 调用;所有动画/timer 在对象删除事件里自动回收。
#pragma once

#include "lvgl.h"
#include "emo_map.h"

#ifdef __cplusplus
extern "C" {
#endif

// 在 parent 上创建小球(容器实际尺寸 = size)。容器透明,body 居中。
lv_obj_t *emo_ball_create(lv_obj_t *parent, int32_t x, int32_t y, int32_t size);

// 切换表情(同表情重复调用只刷新能量,不重启动画)。
void emo_ball_set(lv_obj_t *ball, emo_id_t emo);

// 录音能量 0..100(LISTEN 态直接驱动体径,无需动画)。
void emo_ball_set_level(lv_obj_t *ball, uint8_t level);

// 删除小球(lv_obj_delete 包装,DELETE 事件统一回收 timer/动画/上下文)。
void emo_ball_delete(lv_obj_t *ball);

#ifdef __cplusplus
}
#endif
