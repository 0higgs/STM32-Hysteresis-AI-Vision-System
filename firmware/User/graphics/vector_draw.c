#include "vector_draw.h"

#include "./SYSTEM/sys/sys.h"
#include "./SYSTEM/delay/delay.h"
#include "./BSP/DAC/dac.h"

/*
 * dac.c still contains the old DMA API and therefore references these symbols.
 * The modular vector engine does not start DMA; one dummy element is enough.
 */
uint16_t g_xy_buf_x[1];
uint16_t g_xy_buf_y[1];

extern DAC_HandleTypeDef g_xy_dac_handle;

#define DAC_CENTER              2048.0f
#define SCREEN_SCALE            1450.0f
#define DRAW_POINT_DELAY_US     3U
#define BLANK_SETTLE_US         5U

#define Z_GPIO_PORT             GPIOA
#define Z_GPIO_PIN              GPIO_PIN_7

/* Verified on the current CS-5400 interface: low = draw, high = blank. */
#define Z_DRAW_HIGH             0

static float g_cursor_x = 0.0f;
static float g_cursor_y = 0.0f;

static inline void z_draw(void)
{
#if Z_DRAW_HIGH
    Z_GPIO_PORT->BSRR = Z_GPIO_PIN;
#else
    Z_GPIO_PORT->BSRR = ((uint32_t)Z_GPIO_PIN << 16U);
#endif
}

static inline void z_blank(void)
{
#if Z_DRAW_HIGH
    Z_GPIO_PORT->BSRR = ((uint32_t)Z_GPIO_PIN << 16U);
#else
    Z_GPIO_PORT->BSRR = Z_GPIO_PIN;
#endif
}

static uint16_t dac_limit(float value)
{
    if (value < 50.0f)
    {
        value = 50.0f;
    }

    if (value > 4045.0f)
    {
        value = 4045.0f;
    }

    return (uint16_t)(value + 0.5f);
}

static inline void xy_output(float x, float y)
{
    uint16_t dac_x;
    uint16_t dac_y;

    dac_x = dac_limit(DAC_CENTER + x * SCREEN_SCALE);
    dac_y = dac_limit(DAC_CENTER - y * SCREEN_SCALE);

    HAL_DAC_SetValue(
        &g_xy_dac_handle,
        DAC_CHANNEL_2,
        DAC_ALIGN_12B_R,
        dac_x
    );

    HAL_DAC_SetValue(
        &g_xy_dac_handle,
        DAC_CHANNEL_1,
        DAC_ALIGN_12B_R,
        dac_y
    );
}

void vector_draw_init(void)
{
    GPIO_InitTypeDef gpio = {0};
    DAC_ChannelConfTypeDef config = {0};

    __HAL_RCC_GPIOA_CLK_ENABLE();

    gpio.Pin = Z_GPIO_PIN;
    gpio.Mode = GPIO_MODE_OUTPUT_PP;
    gpio.Pull = GPIO_NOPULL;
    gpio.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
    HAL_GPIO_Init(Z_GPIO_PORT, &gpio);

    z_blank();

    /*
     * Reuse the existing BSP DAC initialization, then switch both channels
     * from TIM7/DMA triggering to direct CPU writes.
     */
    xy_dac_init();

    config.DAC_Trigger = DAC_TRIGGER_NONE;
    config.DAC_OutputBuffer = DAC_OUTPUTBUFFER_ENABLE;

    HAL_DAC_ConfigChannel(
        &g_xy_dac_handle,
        &config,
        DAC_CHANNEL_1
    );

    HAL_DAC_ConfigChannel(
        &g_xy_dac_handle,
        &config,
        DAC_CHANNEL_2
    );

    HAL_DAC_Start(
        &g_xy_dac_handle,
        DAC_CHANNEL_1
    );

    HAL_DAC_Start(
        &g_xy_dac_handle,
        DAC_CHANNEL_2
    );

    xy_output(0.0f, 0.0f);
}

void vector_blank(void)
{
    z_blank();
}

void vector_move_to(float x, float y)
{
    z_blank();
    xy_output(x, y);
    delay_us(BLANK_SETTLE_US);

    g_cursor_x = x;
    g_cursor_y = y;
}

void vector_line_to(float x, float y, uint16_t points)
{
    uint16_t i;
    float start_x;
    float start_y;

    if (points < 2U)
    {
        points = 2U;
    }

    start_x = g_cursor_x;
    start_y = g_cursor_y;

    z_draw();

    for (i = 1U; i <= points; i++)
    {
        float t = (float)i / (float)points;
        float px = start_x + (x - start_x) * t;
        float py = start_y + (y - start_y) * t;

        xy_output(px, py);
        delay_us(DRAW_POINT_DELAY_US);
    }

    g_cursor_x = x;
    g_cursor_y = y;
}

void vector_draw_rect(float cx, float cy, float width, float height)
{
    float left = cx - width * 0.5f;
    float right = cx + width * 0.5f;
    float top = cy - height * 0.5f;
    float bottom = cy + height * 0.5f;

    vector_move_to(left, top);
    vector_line_to(right, top, 6U);
    vector_line_to(right, bottom, 12U);
    vector_line_to(left, bottom, 6U);
    vector_line_to(left, top, 12U);
    vector_blank();
}

void vector_draw_border(float left, float top, float right, float bottom)
{
    vector_move_to(left, top);
    vector_line_to(right, top, 42U);
    vector_line_to(right, bottom, 30U);
    vector_line_to(left, bottom, 42U);
    vector_line_to(left, top, 30U);
    vector_blank();
}
