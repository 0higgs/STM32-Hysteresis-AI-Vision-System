#include "game_key.h"
#include "bluetooth_control.h"

#include "./SYSTEM/sys/sys.h"
#include "./BSP/KEY/key.h"

#define DEBOUNCE_MS       12U
#define EXIT_HOLD_MS      900U
#define ROTATE_PORT       GPIOD
#define ROTATE_PIN        GPIO_PIN_13

typedef struct
{
    uint8_t raw;
    uint8_t stable;
    uint8_t pressed_event;
    uint32_t changed_at;
} GameButtonState;

static GameButtonState g_a;
static GameButtonState g_b;
static GameButtonState g_rotate;

static uint32_t g_both_since = 0U;
static uint8_t g_exit_event = 0U;
static uint8_t g_exit_latched = 0U;

static uint8_t read_a(void)
{
    return (KEY0 == 1) ? 1U : 0U;
}

static uint8_t read_b(void)
{
    return (WKUP == 1) ? 1U : 0U;
}

static uint8_t read_rotate(void)
{
    return (HAL_GPIO_ReadPin(ROTATE_PORT, ROTATE_PIN) == GPIO_PIN_RESET)
        ? 1U : 0U;
}

static void button_setup(GameButtonState *button, uint8_t raw)
{
    button->raw = raw;
    button->stable = raw;
    button->pressed_event = 0U;
    button->changed_at = HAL_GetTick();
}

static void button_update(GameButtonState *button, uint8_t raw, uint32_t now)
{
    if (raw != button->raw)
    {
        button->raw = raw;
        button->changed_at = now;
    }

    if ((button->stable != button->raw) &&
        ((uint32_t)(now - button->changed_at) >= DEBOUNCE_MS))
    {
        button->stable = button->raw;

        if (button->stable != 0U)
        {
            button->pressed_event = 1U;
        }
    }
}

static uint8_t take_event(GameButtonState *button)
{
    uint8_t event = button->pressed_event;
    button->pressed_event = 0U;
    return event;
}

void game_key_init(void)
{
    GPIO_InitTypeDef gpio = {0};

    __HAL_RCC_GPIOD_CLK_ENABLE();

    gpio.Pin = ROTATE_PIN;
    gpio.Mode = GPIO_MODE_INPUT;
    gpio.Pull = GPIO_PULLUP;
    gpio.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(ROTATE_PORT, &gpio);

    game_key_reset();
}

void game_key_reset(void)
{
    button_setup(&g_a, read_a());
    button_setup(&g_b, read_b());
    button_setup(&g_rotate, read_rotate());

    g_both_since = 0U;
    g_exit_event = 0U;
    g_exit_latched = 0U;
}

void game_key_update(void)
{
    uint32_t now = HAL_GetTick();

    button_update(&g_a, read_a(), now);
    button_update(&g_b, read_b(), now);

    if ((g_a.stable != 0U) && (g_b.stable != 0U))
    {
        if (g_both_since == 0U)
        {
            g_both_since = now;
        }

        if ((g_exit_latched == 0U) &&
            ((uint32_t)(now - g_both_since) >= EXIT_HOLD_MS))
        {
            g_exit_event = 1U;
            g_exit_latched = 1U;
        }
    }
    else
    {
        g_both_since = 0U;
        g_exit_latched = 0U;
    }
}

void game_key_rotate_update(void)
{
    button_update(&g_rotate, read_rotate(), HAL_GetTick());
}

uint8_t game_key_a_down(void)
{
    return ((g_a.stable != 0U) || (bluetooth_a_down() != 0U)) ? 1U : 0U;
}

uint8_t game_key_b_down(void)
{
    return ((g_b.stable != 0U) || (bluetooth_b_down() != 0U)) ? 1U : 0U;
}

uint8_t game_key_rotate_down(void)
{
    return ((g_rotate.stable != 0U) || (bluetooth_rotate_down() != 0U)) ? 1U : 0U;
}

uint8_t game_key_a_pressed(void)
{
    uint8_t physical = take_event(&g_a);
    uint8_t bluetooth = bluetooth_a_pressed();
    return ((physical != 0U) || (bluetooth != 0U)) ? 1U : 0U;
}

uint8_t game_key_b_pressed(void)
{
    uint8_t physical = take_event(&g_b);
    uint8_t bluetooth = bluetooth_b_pressed();
    return ((physical != 0U) || (bluetooth != 0U)) ? 1U : 0U;
}

uint8_t game_key_rotate_pressed(void)
{
    uint8_t physical = take_event(&g_rotate);
    uint8_t bluetooth = bluetooth_rotate_pressed();
    return ((physical != 0U) || (bluetooth != 0U)) ? 1U : 0U;
}

uint8_t game_key_exit_requested(void)
{
    uint8_t event = g_exit_event;
    uint8_t bluetooth = bluetooth_exit_requested();
    g_exit_event = 0U;
    return ((event != 0U) || (bluetooth != 0U)) ? 1U : 0U;
}
