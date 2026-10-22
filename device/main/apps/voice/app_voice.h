// main/apps/voice/app_voice.h —— 语音遥控应用入口(独立固件版,无 launcher)。
#pragma once

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// 按键事件(原 launcher app_registry 的枚举,本应用自带,便于独立编译)。
// LONG_UP 保留兼容:主输入路径用 PRESS/RELEASE/CLICK(LONG 后松开 BSP 报 RELEASE)。
typedef enum {
    BTN_EVT_PRESS = 0,
    BTN_EVT_RELEASE,
    BTN_EVT_CLICK,
    BTN_EVT_LONG,
    BTN_EVT_LONG_UP,
} app_btn_event_t;

// 初始化基础组件(nvs_settings/time_sync/事件队列/状态机)。开屏前调用。
void voice_app_init(void);

// 启动语音应用:建 UI(持锁)→ 起 worker → 开 UDP 通道 → 初始化音频管线。
// 幂等保护:任务已存在时不重复创建。
void voice_app_start(void);

// 停止语音应用(当前单页常驻固件不调用,保留给未来切应用)。
void voice_app_stop(void);

// 按键入口:input_task 将 BSP 事件映射后调用;内部转 app_event 入队。
// mv = 回调时刻的 bsp_button_read_mv()(ADC 真假按判别,见 app_state.c)。
void voice_app_on_key(uint8_t btn, app_btn_event_t event, uint16_t mv);

#ifdef __cplusplus
}
#endif
