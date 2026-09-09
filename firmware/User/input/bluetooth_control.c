#include "bluetooth_control.h"

#include "./SYSTEM/sys/sys.h"
#include "./BSP/LED/led.h"

#define BLUETOOTH_TAP_MS              140U
#define BLUETOOTH_MAX_BYTES_PER_TICK  16U

static UART_HandleTypeDef g_bluetooth_uart;

static uint8_t g_menu_up_event;
static uint8_t g_menu_down_event;
static uint8_t g_menu_enter_event;
static uint8_t g_a_down;
static uint8_t g_b_down;
static uint8_t g_rotate_down;
static uint8_t g_a_event;
static uint8_t g_b_event;
static uint8_t g_rotate_event;
static uint8_t g_exit_event;
static uint8_t g_a_timed;
static uint8_t g_b_timed;
static uint32_t g_a_release_at;
static uint32_t g_b_release_at;

static uint8_t g_up_down;
static uint8_t g_down_down;
static uint8_t g_left_down;
static uint8_t g_right_down;
static uint8_t g_action1_down;
static uint8_t g_action2_down;
static uint8_t g_up_event;
static uint8_t g_down_event;
static uint8_t g_left_event;
static uint8_t g_right_event;
static uint8_t g_action1_event;
static uint8_t g_action2_event;
static uint8_t g_hard_drop_event;
static uint8_t g_pause_event;
static uint8_t g_start_event;

static uint8_t g_player2_up_down;
static uint8_t g_player2_down_down;
static uint8_t g_player2_up_event;
static uint8_t g_player2_down_event;

static uint8_t g_packet_state;
static uint8_t g_packet_code;
static uint32_t g_rx_led_off_at;
static uint32_t g_valid_led_off_at;

static uint8_t take_event(uint8_t *event)
{
    uint8_t value = *event;
    *event = 0U;
    return value;
}

static uint8_t time_reached(uint32_t now, uint32_t deadline)
{
    return ((int32_t)(now - deadline) >= 0) ? 1U : 0U;
}

static uint8_t is_legacy_command(uint8_t command)
{
    switch (command)
    {
        case 'U':
        case 'D':
        case 'E':
        case 'A':
        case 'a':
        case 'B':
        case 'b':
        case 'L':
        case 'R':
        case 'T':
        case 'X':
        case 'S':
        case '?':
        case '0':
        case '1':
        case '2':
        case '3':
        case '4':
        case '5':
        case '6':
        case '7':
        case '8':
        case '9':
        case 'q':
        case 'w':
        case 'e':
        case 'r':
        case 't':
        case 'y':
        case 'x':
        case 's':
        case 'I':
        case 'i':
        case 'K':
        case 'k':
        case 'z':
            return 1U;

        default:
            return 0U;
    }
}

static uint8_t is_extended_command(uint8_t code, uint8_t value)
{
    if ((value != '0') && (value != '1'))
    {
        return 0U;
    }

    switch (code)
    {
        case 'U':
        case 'D':
        case 'L':
        case 'R':
        case 'A':
        case 'B':
        case 'T':
        case 'H':
        case 'P':
        case 'E':
        case 'X':
        case 'S':
            return 1U;

        default:
            return 0U;
    }
}

static void signal_rx_activity(uint32_t now)
{
    LED0(0);
    g_rx_led_off_at = now + 200U;
}

static void signal_valid_command(uint32_t now)
{
    LED1(0);
    g_valid_led_off_at = now + 200U;
}

static void bluetooth_send(const char *text)
{
    const char *end = text;

    while (*end != '\0')
    {
        end++;
    }

    (void)HAL_UART_Transmit(
        &g_bluetooth_uart,
        (uint8_t *)text,
        (uint16_t)(end - text),
        30U
    );
}

static void press_a(uint8_t timed)
{
    if (g_a_down == 0U)
    {
        g_a_event = 1U;
    }

    g_a_down = 1U;
    g_a_timed = timed;

    if (timed != 0U)
    {
        g_a_release_at = HAL_GetTick() + BLUETOOTH_TAP_MS;
    }
}

static void press_b(uint8_t timed)
{
    if (g_b_down == 0U)
    {
        g_b_event = 1U;
    }

    g_b_down = 1U;
    g_b_timed = timed;

    if (timed != 0U)
    {
        g_b_release_at = HAL_GetTick() + BLUETOOTH_TAP_MS;
    }
}

static void set_extended_button(uint8_t *down, uint8_t *event,
                                uint8_t pressed)
{
    if ((pressed != 0U) && (*down == 0U))
    {
        *event = 1U;
    }

    *down = pressed;
}

static void release_extended_buttons(void)
{
    g_up_down = 0U;
    g_down_down = 0U;
    g_left_down = 0U;
    g_right_down = 0U;
    g_action1_down = 0U;
    g_action2_down = 0U;
}

static void release_player2_buttons(void)
{
    g_player2_up_down = 0U;
    g_player2_down_down = 0U;
}

static void handle_packet(uint8_t code, uint8_t value)
{
    uint8_t pressed = (value == '1') ? 1U : 0U;

    switch (code)
    {
        case 'U':
            set_extended_button(&g_up_down, &g_up_event, pressed);
            break;

        case 'D':
            set_extended_button(&g_down_down, &g_down_event, pressed);
            break;

        case 'L':
            set_extended_button(&g_left_down, &g_left_event, pressed);
            break;

        case 'R':
            set_extended_button(&g_right_down, &g_right_event, pressed);
            break;

        case 'A':
            set_extended_button(
                &g_action1_down,
                &g_action1_event,
                pressed
            );
            break;

        case 'B':
            set_extended_button(
                &g_action2_down,
                &g_action2_event,
                pressed
            );
            break;

        case 'T':
            if (pressed != 0U)
            {
                g_rotate_event = 1U;
                g_rotate_down = 1U;
            }
            break;

        case 'H':
            if (pressed != 0U)
            {
                g_hard_drop_event = 1U;
            }
            break;

        case 'P':
            if (pressed != 0U)
            {
                g_pause_event = 1U;
            }
            break;

        case 'E':
            if (pressed != 0U)
            {
                g_start_event = 1U;
            }
            break;

        case 'X':
            if (pressed != 0U)
            {
                g_exit_event = 1U;
            }
            break;

        case 'S':
            if (pressed != 0U)
            {
                g_a_down = 0U;
                g_b_down = 0U;
                g_a_timed = 0U;
                g_b_timed = 0U;
                release_extended_buttons();
                release_player2_buttons();
            }
            break;

        default:
            break;
    }
}

static void handle_command(uint8_t command)
{
    switch (command)
    {
        case 'U':
            g_menu_up_event = 1U;
            break;

        case 'D':
            g_menu_down_event = 1U;
            break;

        case 'E':
            g_menu_enter_event = 1U;
            break;

        case 'A':
            press_a(0U);
            break;

        case 'a':
            g_a_down = 0U;
            g_a_timed = 0U;
            break;

        case 'B':
            press_b(0U);
            break;

        case 'b':
            g_b_down = 0U;
            g_b_timed = 0U;
            break;

        case 'L':
            press_a(1U);
            break;

        case 'R':
            press_b(1U);
            break;

        case 'T':
            g_rotate_event = 1U;
            g_rotate_down = 1U;
            break;

        case 'X':
            g_exit_event = 1U;
            break;

        case 'S':
            g_a_down = 0U;
            g_b_down = 0U;
            g_rotate_down = 0U;
            g_a_timed = 0U;
            g_b_timed = 0U;
            release_extended_buttons();
            release_player2_buttons();
            break;

        case '?':
            bluetooth_send(
                "\r\nU/D/E menu, A/a A hold/release, "
                "B/b B hold/release, L/R tap, T rotate, "
                "X menu, S stop. Extended: !U1/!U0 etc, "
                "!T1 rotate, !H1 drop, !P1 pause. "
                "PONG P2: I/i up, K/k down, z stop. "
                "Compact phone protocol enabled.\r\n"
            );
            break;

        /* Compact one-byte phone protocol: press/release pairs. */
        case '1':
            set_extended_button(&g_up_down, &g_up_event, 1U);
            break;

        case 'q':
            set_extended_button(&g_up_down, &g_up_event, 0U);
            break;

        case '2':
            set_extended_button(&g_down_down, &g_down_event, 1U);
            break;

        case 'w':
            set_extended_button(&g_down_down, &g_down_event, 0U);
            break;

        case '3':
            set_extended_button(&g_left_down, &g_left_event, 1U);
            break;

        case 'e':
            set_extended_button(&g_left_down, &g_left_event, 0U);
            break;

        case '4':
            set_extended_button(&g_right_down, &g_right_event, 1U);
            break;

        case 'r':
            set_extended_button(&g_right_down, &g_right_event, 0U);
            break;

        case '5':
            set_extended_button(
                &g_action1_down,
                &g_action1_event,
                1U
            );
            break;

        case 't':
            set_extended_button(
                &g_action1_down,
                &g_action1_event,
                0U
            );
            break;

        case '6':
            set_extended_button(
                &g_action2_down,
                &g_action2_event,
                1U
            );
            break;

        case 'y':
            set_extended_button(
                &g_action2_down,
                &g_action2_event,
                0U
            );
            break;

        /* Compact one-byte tap commands. */
        case '7':
            g_rotate_event = 1U;
            g_rotate_down = 1U;
            break;

        case '8':
            g_hard_drop_event = 1U;
            break;

        case '9':
            g_pause_event = 1U;
            break;

        case '0':
            g_start_event = 1U;
            break;

        case 'x':
            g_exit_event = 1U;
            break;

        case 's':
            g_a_down = 0U;
            g_b_down = 0U;
            g_rotate_down = 0U;
            g_a_timed = 0U;
            g_b_timed = 0U;
            release_extended_buttons();
            break;

        /* PONG player 2 uses a separate compact command set. */
        case 'I':
            set_extended_button(
                &g_player2_up_down,
                &g_player2_up_event,
                1U
            );
            break;

        case 'i':
            set_extended_button(
                &g_player2_up_down,
                &g_player2_up_event,
                0U
            );
            break;

        case 'K':
            set_extended_button(
                &g_player2_down_down,
                &g_player2_down_event,
                1U
            );
            break;

        case 'k':
            set_extended_button(
                &g_player2_down_down,
                &g_player2_down_event,
                0U
            );
            break;

        case 'z':
            release_player2_buttons();
            break;

        case '\r':
        case '\n':
        case ' ':
        case '\t':
        default:
            break;
    }
}

void bluetooth_control_init(uint32_t baudrate)
{
    GPIO_InitTypeDef gpio = {0};

    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_USART2_CLK_ENABLE();

    gpio.Pin = GPIO_PIN_2 | GPIO_PIN_3;
    gpio.Mode = GPIO_MODE_AF_PP;
    gpio.Pull = GPIO_PULLUP;
    gpio.Speed = GPIO_SPEED_FREQ_HIGH;
    gpio.Alternate = GPIO_AF7_USART2;
    HAL_GPIO_Init(GPIOA, &gpio);

    g_bluetooth_uart.Instance = USART2;
    g_bluetooth_uart.Init.BaudRate = baudrate;
    g_bluetooth_uart.Init.WordLength = UART_WORDLENGTH_8B;
    g_bluetooth_uart.Init.StopBits = UART_STOPBITS_1;
    g_bluetooth_uart.Init.Parity = UART_PARITY_NONE;
    g_bluetooth_uart.Init.Mode = UART_MODE_TX_RX;
    g_bluetooth_uart.Init.HwFlowCtl = UART_HWCONTROL_NONE;
    g_bluetooth_uart.Init.OverSampling = UART_OVERSAMPLING_16;
    (void)HAL_UART_Init(&g_bluetooth_uart);

    bluetooth_control_reset_inputs();
    bluetooth_send(
        "\r\nJDY-34 / HC-05D controller ready. Send ? for help.\r\n"
    );
}

void bluetooth_control_update(void)
{
    uint8_t count = 0U;
    uint32_t now = HAL_GetTick();

    if ((g_rx_led_off_at != 0U) &&
        (time_reached(now, g_rx_led_off_at) != 0U))
    {
        LED0(1);
        g_rx_led_off_at = 0U;
    }

    if ((g_valid_led_off_at != 0U) &&
        (time_reached(now, g_valid_led_off_at) != 0U))
    {
        LED1(1);
        g_valid_led_off_at = 0U;
    }

    if ((g_a_timed != 0U) && (time_reached(now, g_a_release_at) != 0U))
    {
        g_a_down = 0U;
        g_a_timed = 0U;
    }

    if ((g_b_timed != 0U) && (time_reached(now, g_b_release_at) != 0U))
    {
        g_b_down = 0U;
        g_b_timed = 0U;
    }

    /* Rotate is a one-update pulse; the pressed event remains latched. */
    g_rotate_down = 0U;

    while ((__HAL_UART_GET_FLAG(&g_bluetooth_uart, UART_FLAG_RXNE) != RESET) &&
           (count < BLUETOOTH_MAX_BYTES_PER_TICK))
    {
        uint8_t command = (uint8_t)(g_bluetooth_uart.Instance->DR & 0xFFU);
        signal_rx_activity(now);

        if (g_packet_state == 0U)
        {
            if (command == '!')
            {
                g_packet_state = 1U;
            }
            else
            {
                if (is_legacy_command(command) != 0U)
                {
                    signal_valid_command(now);
                }
                handle_command(command);
            }
        }
        else if (g_packet_state == 1U)
        {
            g_packet_code = command;
            g_packet_state = 2U;
        }
        else
        {
            if (is_extended_command(g_packet_code, command) != 0U)
            {
                signal_valid_command(now);
            }
            handle_packet(g_packet_code, command);
            g_packet_state = 0U;
        }

        count++;
    }

    if (__HAL_UART_GET_FLAG(&g_bluetooth_uart, UART_FLAG_ORE) != RESET)
    {
        volatile uint32_t status = g_bluetooth_uart.Instance->SR;
        volatile uint32_t data = g_bluetooth_uart.Instance->DR;
        (void)status;
        (void)data;
    }
}

void bluetooth_control_reset_inputs(void)
{
    g_menu_up_event = 0U;
    g_menu_down_event = 0U;
    g_menu_enter_event = 0U;
    g_a_down = 0U;
    g_b_down = 0U;
    g_rotate_down = 0U;
    g_a_event = 0U;
    g_b_event = 0U;
    g_rotate_event = 0U;
    g_exit_event = 0U;
    g_a_timed = 0U;
    g_b_timed = 0U;
    g_up_event = 0U;
    g_down_event = 0U;
    g_left_event = 0U;
    g_right_event = 0U;
    g_action1_event = 0U;
    g_action2_event = 0U;
    g_hard_drop_event = 0U;
    g_pause_event = 0U;
    g_start_event = 0U;
    g_player2_up_event = 0U;
    g_player2_down_event = 0U;
    g_packet_state = 0U;
    g_packet_code = 0U;
    g_rx_led_off_at = 0U;
    g_valid_led_off_at = 0U;
    LED0(1);
    LED1(1);
    release_extended_buttons();
    release_player2_buttons();
}

uint8_t bluetooth_menu_up_pressed(void)
{
    uint8_t legacy = take_event(&g_menu_up_event);
    uint8_t extended = take_event(&g_up_event);
    uint8_t player2 = take_event(&g_player2_up_event);
    return ((legacy != 0U) ||
            (extended != 0U) ||
            (player2 != 0U)) ? 1U : 0U;
}

uint8_t bluetooth_menu_down_pressed(void)
{
    uint8_t legacy = take_event(&g_menu_down_event);
    uint8_t extended = take_event(&g_down_event);
    uint8_t player2 = take_event(&g_player2_down_event);
    return ((legacy != 0U) ||
            (extended != 0U) ||
            (player2 != 0U)) ? 1U : 0U;
}

uint8_t bluetooth_menu_enter_pressed(void)
{
    uint8_t legacy = take_event(&g_menu_enter_event);
    uint8_t extended = take_event(&g_start_event);
    return ((legacy != 0U) || (extended != 0U)) ? 1U : 0U;
}

uint8_t bluetooth_a_down(void)      { return g_a_down; }
uint8_t bluetooth_b_down(void)      { return g_b_down; }
uint8_t bluetooth_rotate_down(void) { return g_rotate_down; }

uint8_t bluetooth_a_pressed(void)      { return take_event(&g_a_event); }
uint8_t bluetooth_b_pressed(void)      { return take_event(&g_b_event); }
uint8_t bluetooth_rotate_pressed(void) { return take_event(&g_rotate_event); }
uint8_t bluetooth_exit_requested(void) { return take_event(&g_exit_event); }

uint8_t bluetooth_up_down(void)      { return g_up_down; }
uint8_t bluetooth_down_down(void)    { return g_down_down; }
uint8_t bluetooth_left_down(void)    { return g_left_down; }
uint8_t bluetooth_right_down(void)   { return g_right_down; }
uint8_t bluetooth_action1_down(void) { return g_action1_down; }
uint8_t bluetooth_action2_down(void) { return g_action2_down; }

uint8_t bluetooth_up_pressed(void)      { return take_event(&g_up_event); }
uint8_t bluetooth_down_pressed(void)    { return take_event(&g_down_event); }
uint8_t bluetooth_left_pressed(void)    { return take_event(&g_left_event); }
uint8_t bluetooth_right_pressed(void)   { return take_event(&g_right_event); }
uint8_t bluetooth_action1_pressed(void) { return take_event(&g_action1_event); }
uint8_t bluetooth_action2_pressed(void) { return take_event(&g_action2_event); }
uint8_t bluetooth_hard_drop_pressed(void)
{
    return take_event(&g_hard_drop_event);
}
uint8_t bluetooth_pause_pressed(void) { return take_event(&g_pause_event); }
uint8_t bluetooth_start_pressed(void) { return take_event(&g_start_event); }

uint8_t bluetooth_player2_up_down(void)
{
    return g_player2_up_down;
}

uint8_t bluetooth_player2_down_down(void)
{
    return g_player2_down_down;
}

uint8_t bluetooth_player2_up_pressed(void)
{
    return take_event(&g_player2_up_event);
}

uint8_t bluetooth_player2_down_pressed(void)
{
    return take_event(&g_player2_down_event);
}
