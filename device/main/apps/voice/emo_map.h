// main/apps/voice/emo_map.h —— 语音遥控状态 → EmoBall 表情映射(纯逻辑,可宿主测试)。
// 方法论来自 EmotionBall 调研(2026-10-19):系统侧只输出"意图"(emo_id),
// 表现由 widget 承担;映射函数无副作用,规则集中在一张优先级表里(见 emo_map.c)。
#pragma once

#include "app_types.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    EMO_SLEEP = 0,     // 闭眼休眠(息屏/面板断电)
    EMO_IDLE,          // 呼吸+眨眼(链路与电脑都就绪,随时可说)
    EMO_WAIT,          // 半睁等待(未连上电脑/电脑未就绪/录音暂停)
    EMO_CURIOUS,       // 左右张望(配网热点/连网中)
    EMO_LISTEN,        // 随录音能量律动(按住上键说话)
    EMO_HAPPY,         // 弹跳笑(回车已发出)
    EMO_SATISFIED,     // 眯眼微笑(窗口已切换)
    EMO_SURPRISED,     // 瞪大眼睛(保留:链路突变)
    EMO_PANIC,         // 抖动慌张(麦克风异常/配网失败)
    EMO_COUNT,
} emo_id_t;

typedef struct {
    bool screen_on;
    uint8_t wifi_prov;     // app_wifi_prov_t
    bool link_up;
    bool pc_ready;
    uint8_t stage;         // app_stage_t
    bool emo_hint_active;
    uint8_t emo_hint;      // app_emo_hint_t
} emo_input_t;

emo_id_t emo_map_resolve(const emo_input_t *in);
const char *emo_map_name(emo_id_t emo);   // 日志用

#ifdef __cplusplus
}
#endif
