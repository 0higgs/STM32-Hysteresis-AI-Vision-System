#include "menu_key.h"
#include "bluetooth_control.h"
#include "./SYSTEM/sys/sys.h"

#define MENU_UP_PORT       GPIOC
#define MENU_UP_PIN        GPIO_PIN_6

#define MENU_DOWN_PORT     GPIOC
#define MENU_DOWN_PIN      GPIO_PIN_7

#define MENU_ENTER_PORT    GPIOD
#define MENU_ENTER_PIN     GPIO_PIN_13

#define DEBOUNCE_MS        18U

typedef struct
{
    GPIO_TypeDef *port;
    uint16_t pin;
    uint8_t raw;
    uint8_t stable;
    uint8_t pressed_event;
    uint32_t changed_at;
} MenuKeyState;

static MenuKeyState g_up;
static MenuKeyState g_down;
static MenuKeyState g_enter;

static uint8_t read_pressed(GPIO_TypeDef *port, uint16_t pin)
{
    return (HAL_GPIO_ReadPin(port, pin) == GPIO_PIN_RESET) ? 1U : 0U;
}

static void key_setup(MenuKeyState *key, GPIO_TypeDef *port, uint16_t pin)
{
    uint8_t now = read_pressed(port, pin);

    key->port = port;
    key->pin = pin;
    key->raw = now;
    key->stable = now;
    key->pressed_event = 0U;
    key->changed_at = HAL_GetTick();
}

static void key_update(MenuKeyState *key, uint32_t now)
{
    uint8_t raw = read_pressed(key->port, key->pin);

    if (raw != key->raw)
    {
        key->raw = raw;
        key->changed_at = now;
    }

    if ((key->stable != key->raw) &&
        ((uint32_t)(now - key->changed_at) >= DEBOUNCE_MS))
    {
        key->stable = key->raw;

        if (key->stable != 0U)
        {
            key->pressed_event = 1U;
        }
    }
}

static uint8_t take_event(MenuKeyState *key)
{
    uint8_t event = key->pressed_event;
    key->pressed_event = 0U;
    return event;
}

void menu_key_init(void)
{
    GPIO_InitTypeDef gpio = {0};

    __HAL_RCC_GPIOC_CLK_ENABLE();
    __HAL_RCC_GPIOD_CLK_ENABLE();

    gpio.Mode = GPIO_MODE_INPUT;
    gpio.Pull = GPIO_PULLUP;
    gpio.Speed = GPIO_SPEED_FREQ_LOW;

    gpio.Pin = MENU_UP_PIN | MENU_DOWN_PIN;
    HAL_GPIO_Init(GPIOC, &gpio);

    gpio.Pin = MENU_ENTER_PIN;
    HAL_GPIO_Init(GPIOD, &gpio);

    menu_key_reset();
}

void menu_key_reset(void)
{
    key_setup(&g_up, MENU_UP_PORT, MENU_UP_PIN);
    key_setup(&g_down, MENU_DOWN_PORT, MENU_DOWN_PIN);
    key_setup(&g_enter, MENU_ENTER_PORT, MENU_ENTER_PIN);
}

void menu_key_update(void)
{
    uint32_t now = HAL_GetTick();

    key_update(&g_up, now);
    key_update(&g_down, now);
    key_update(&g_enter, now);
}

uint8_t menu_key_up_pressed(void)
{
    uint8_t physical = take_event(&g_up);
    uint8_t bluetooth = bluetooth_menu_up_pressed();
    return ((physical != 0U) || (bluetooth != 0U)) ? 1U : 0U;
}

uint8_t menu_key_down_pressed(void)
{
    uint8_t physical = take_event(&g_down);
    uint8_t bluetooth = bluetooth_menu_down_pressed();
    return ((physical != 0U) || (bluetooth != 0U)) ? 1U : 0U;
}

uint8_t menu_key_enter_pressed(void)
{
    uint8_t physical = take_event(&g_enter);
    uint8_t bluetooth = bluetooth_menu_enter_pressed();
    return ((physical != 0U) || (bluetooth != 0U)) ? 1U : 0U;
}
