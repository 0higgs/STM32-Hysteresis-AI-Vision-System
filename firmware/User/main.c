/**
 ****************************************************************************************************
 * @file        main.c
 * @brief       STM32F407 programmable hysteresis-loop generator
 *
 * Output wiring required by the project plan:
 *   PA5 / DAC_OUT2 -> oscilloscope X
 *   PA4 / DAC_OUT1 -> oscilloscope Y
 *   GND             -> oscilloscope signal ground
 *
 * Active JDY-34 Bluetooth control link:
 *   PA2 / USART2_TX -> JDY-34 RXD
 *   PA3 / USART2_RX <- JDY-34 TXD
 ****************************************************************************************************
 */

#include "./SYSTEM/sys/sys.h"
#include "./SYSTEM/delay/delay.h"
#include "./SYSTEM/usart/usart.h"
#include "./BSP/DAC/dac.h"
#include "hyst_model.h"
#include "bt_protocol.h"

#include <stdio.h>

static void fatal_error(void)
{
    __disable_irq();
    while (1)
    {
    }
}

int main(void)
{
    HAL_Init();
    if (sys_stm32_clock_init(336, 8, 2, 7) != 0U)
    {
        fatal_error();
    }
    delay_init(168);
    usart_init(115200);

    Hyst_GenerateDefault();
    Hyst_CommitGenerated();
    if (xy_dac_init() != HAL_OK)
    {
        fatal_error();
    }

    /* APB1 timer clock = 84 MHz. TIM7 update = 84 MHz / (839 + 1) = 100 kHz.
     * With 512 points, the displayed loop repeats at 195.3125 Hz.
     */
    if (xy_dac_start(HYST_WAVE_SAMPLES, 839U, 0U) != HAL_OK)
    {
        fatal_error();
    }
    if (BT_ProtocolInit(9600U) != HAL_OK) fatal_error();

    printf(
        "\r\nSTM32F407 PROGRAMMABLE HYSTERESIS LOOP HYST-V1\r\n"
        "X: PA5 / DAC2, Y: PA4 / DAC1\r\n"
        "512 samples, 100 kS/s, 195.3125 Hz loop\r\n"
        "JDY-34 active: TXD->PA3, RXD<-PA2, 9600 8N1\r\n"
    );

    while (1)
    {
        HystParams next;
        BT_ProtocolPoll();
        if (BT_ProtocolTakeApply(&next) != 0U)
        {
            uint32_t timer_clock = 84000000U;
            uint32_t sample_rate = (uint32_t)(next.loop_hz * HYST_WAVE_SAMPLES + 0.5f);
            uint32_t divider = (timer_clock + sample_rate / 2U) / sample_rate;
            if (divider < 2U) divider = 2U;
            if (divider > 65536U) divider = 65536U;
            Hyst_Generate(&next);
            /* Keep TIM7 and both circular DMA streams running.  Copying 2 KB
             * may affect at most one scan, but can never blank the display. */
            Hyst_CommitGenerated();
            if (xy_dac_set_timer((uint16_t)(divider - 1U), 0U) == HAL_OK)
                BT_ProtocolReportApplied(&next);
            else
                BT_ProtocolReportError("OUTPUT");
        }
    }
}
