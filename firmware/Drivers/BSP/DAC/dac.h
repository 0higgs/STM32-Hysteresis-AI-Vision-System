/**
 ****************************************************************************************************
 * @file        dac.h
 * @brief       双通道 DAC + DMA + TIM7，用于示波器 X-Y 模式输出
 *
 * 基于正点原子 M100Z-M4 STM32F407 HAL 库标准例程
 * “实验19-3 DAC输出正弦波实验”修改。
 *
 * X轴：PA5 / DAC_OUT2 / DAC Channel2
 * Y轴：PA4 / DAC_OUT1 / DAC Channel1
 *
 * 两路 DAC 均由 TIM7 TRGO 触发：
 *   DAC1 -> DMA1 Stream5 Channel7
 *   DAC2 -> DMA1 Stream6 Channel7
 ****************************************************************************************************
 */

#ifndef __DAC_H
#define __DAC_H

#include "./SYSTEM/sys/sys.h"

 /* ---------------- DAC 外设 ---------------- */
#define XY_DAC                              DAC
#define XY_DAC_CLK_ENABLE()                 \
    do                                      \
    {                                       \
        __HAL_RCC_DAC_CLK_ENABLE();         \
    } while (0)

/* ---------------- TIM7 触发 ---------------- */
#define XY_DAC_TIM                          TIM7
#define XY_DAC_TIM_CLK_ENABLE()             \
    do                                      \
    {                                       \
        __HAL_RCC_TIM7_CLK_ENABLE();        \
    } while (0)

/* ---------------- GPIO ----------------
 * PA5 = DAC_OUT2 = X
 * PA4 = DAC_OUT1 = Y
 */
#define XY_DAC_GPIO_PORT                    GPIOA
#define XY_DAC_GPIO_PIN_X                   GPIO_PIN_5
#define XY_DAC_GPIO_PIN_Y                   GPIO_PIN_4
#define XY_DAC_GPIO_CLK_ENABLE()            \
    do                                      \
    {                                       \
        __HAL_RCC_GPIOA_CLK_ENABLE();       \
    } while (0)

 /* ---------------- DAC Channel 2 / X ---------------- */
#define XY_DAC_CH_X                         DAC_CHANNEL_2
#define XY_DAC_DMA_X_STREAM                 DMA1_Stream6
#define XY_DAC_DMA_X_CHANNEL                DMA_CHANNEL_7
#define XY_DAC_DMA_X_IRQn                   DMA1_Stream6_IRQn
#define XY_DAC_DMA_X_IRQHandler             DMA1_Stream6_IRQHandler

/* ---------------- DAC Channel 1 / Y ---------------- */
#define XY_DAC_CH_Y                         DAC_CHANNEL_1
#define XY_DAC_DMA_Y_STREAM                 DMA1_Stream5
#define XY_DAC_DMA_Y_CHANNEL                DMA_CHANNEL_7
#define XY_DAC_DMA_Y_IRQn                   DMA1_Stream5_IRQn
#define XY_DAC_DMA_Y_IRQHandler             DMA1_Stream5_IRQHandler

#define XY_DAC_DMA_CLK_ENABLE()             \
    do                                      \
    {                                       \
        __HAL_RCC_DMA1_CLK_ENABLE();        \
    } while (0)

/* API */
HAL_StatusTypeDef xy_dac_init(void);
HAL_StatusTypeDef xy_dac_start(uint16_t samples, uint16_t arr, uint16_t psc);
HAL_StatusTypeDef xy_dac_set_timer(uint16_t arr, uint16_t psc);
void xy_dac_stop(void);

#endif
