#include "bt_protocol.h"

#include <stdio.h>
#include <string.h>

#define BT_LINE_MAX 128U

static UART_HandleTypeDef g_bt_uart;
static char g_line[BT_LINE_MAX];
static uint16_t g_line_length;
static HystParams g_pending;
static uint8_t g_apply_ready;

static void send_text(const char *text)
{
    (void)HAL_UART_Transmit(&g_bt_uart, (uint8_t *)text,
                            (uint16_t)strlen(text), 500U);
}

static uint8_t valid(const HystParams *p)
{
    return (p->h_max > p->h_c && p->h_max <= 1000.0f &&
            p->h_c > 0.0f && p->b_s > 0.0f && p->b_s <= 10.0f &&
            p->b_r > 0.0f && p->b_r < p->b_s &&
            p->loop_hz >= 20.0f && p->loop_hz <= 500.0f &&
            p->x_gain >= 0.1f && p->x_gain <= 2.0f &&
            p->y_gain >= 0.1f && p->y_gain <= 2.0f &&
            p->x_offset >= -0.8f && p->x_offset <= 0.8f &&
            p->y_offset >= -0.8f && p->y_offset <= 0.8f &&
            p->xy_coupling >= -0.5f && p->xy_coupling <= 0.5f &&
            p->asymmetry >= -0.3f && p->asymmetry <= 0.3f &&
            p->dac_amplitude >= 200U && p->dac_amplitude <= 1900U) ? 1U : 0U;
}

static void preset(const char *name)
{
    g_pending = *Hyst_DefaultParams();
    if (strcmp(name, "SOFT") == 0) { g_pending.h_c = 10.0f; g_pending.b_r = 0.54f; }
    else if (strcmp(name, "HARD") == 0) { g_pending.h_c = 60.0f; g_pending.h_max = 300.0f; g_pending.b_r = 0.96f; }
    else if (strcmp(name, "UNSAT") == 0) { g_pending.h_c = 25.0f; g_pending.h_max = 55.0f; g_pending.b_r = 0.72f; }
    else { send_text("ERR PRESET\r\n"); return; }
    g_apply_ready = 1U;
    send_text("OK PRESET\r\n");
}

static void handle_line(char *line)
{
    char key[24];
    char name[24];
    float value;
    HystParams candidate = g_pending;

    if (strcmp(line, "PING") == 0) { send_text("PONG\r\n"); return; }
    if (strcmp(line, "CAPS") == 0) { send_text("CAPS SETALL HYST-V2\r\n"); return; }
    if (strcmp(line, "GET STATUS") == 0) { BT_ProtocolReportApplied(&g_pending); return; }
    if (strcmp(line, "APPLY") == 0) { g_apply_ready = 1U; send_text("OK APPLY\r\n"); return; }
    if (sscanf(line, "PRESET %23s", name) == 1) { preset(name); return; }
    if (strncmp(line, "SETALL ", 7U) == 0)
    {
        unsigned int amplitude;
        int count = sscanf(
            line + 7,
            "%f %f %f %f %f %f %f %f %f %f %f %u",
            &candidate.h_max, &candidate.h_c, &candidate.b_r, &candidate.b_s,
            &candidate.loop_hz, &candidate.x_gain, &candidate.y_gain,
            &candidate.x_offset, &candidate.y_offset, &candidate.xy_coupling,
            &candidate.asymmetry, &amplitude);
        if (count != 12) { send_text("ERR SETALL FORMAT\r\n"); return; }
        candidate.dac_amplitude = (uint16_t)amplitude;
        if (valid(&candidate) == 0U) { send_text("ERR SETALL RANGE\r\n"); return; }
        g_pending = candidate;
        g_apply_ready = 1U;
        send_text("OK SETALL\r\n");
        return;
    }
    if (sscanf(line, "SET %23s %f", key, &value) != 2) { send_text("ERR COMMAND\r\n"); return; }

    if (strcmp(key, "HMAX") == 0) candidate.h_max = value;
    else if (strcmp(key, "HC") == 0) candidate.h_c = value;
    else if (strcmp(key, "BR") == 0) candidate.b_r = value;
    else if (strcmp(key, "BS") == 0) candidate.b_s = value;
    else if (strcmp(key, "LOOP_HZ") == 0) candidate.loop_hz = value;
    else if (strcmp(key, "X_GAIN") == 0) candidate.x_gain = value;
    else if (strcmp(key, "Y_GAIN") == 0) candidate.y_gain = value;
    else if (strcmp(key, "X_OFFSET") == 0) candidate.x_offset = value;
    else if (strcmp(key, "Y_OFFSET") == 0) candidate.y_offset = value;
    else if (strcmp(key, "XY_COUPLING") == 0) candidate.xy_coupling = value;
    else if (strcmp(key, "ASYMMETRY") == 0) candidate.asymmetry = value;
    else if (strcmp(key, "AMPLITUDE") == 0) candidate.dac_amplitude = (uint16_t)value;
    else { send_text("ERR PARAM\r\n"); return; }

    if (valid(&candidate) == 0U) { send_text("ERR RANGE\r\n"); return; }
    g_pending = candidate;
    send_text("OK\r\n");
}

HAL_StatusTypeDef BT_ProtocolInit(uint32_t baudrate)
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
    g_bt_uart.Instance = USART2;
    g_bt_uart.Init.BaudRate = baudrate;
    g_bt_uart.Init.WordLength = UART_WORDLENGTH_8B;
    g_bt_uart.Init.StopBits = UART_STOPBITS_1;
    g_bt_uart.Init.Parity = UART_PARITY_NONE;
    g_bt_uart.Init.Mode = UART_MODE_TX_RX;
    g_bt_uart.Init.HwFlowCtl = UART_HWCONTROL_NONE;
    g_bt_uart.Init.OverSampling = UART_OVERSAMPLING_16;
    g_pending = *Hyst_DefaultParams();
    if (HAL_UART_Init(&g_bt_uart) != HAL_OK) return HAL_ERROR;
    send_text("READY HYST-V1\r\n");
    return HAL_OK;
}

void BT_ProtocolPoll(void)
{
    uint8_t count = 0U;
    while ((__HAL_UART_GET_FLAG(&g_bt_uart, UART_FLAG_RXNE) != RESET) && count++ < 32U)
    {
        char c = (char)(g_bt_uart.Instance->DR & 0xFFU);
        if (c == '\n' || c == '\r')
        {
            if (g_line_length != 0U) { g_line[g_line_length] = '\0'; handle_line(g_line); g_line_length = 0U; }
        }
        else if (g_line_length < BT_LINE_MAX - 1U) g_line[g_line_length++] = c;
        else { g_line_length = 0U; send_text("ERR LINE\r\n"); }
    }
    if (__HAL_UART_GET_FLAG(&g_bt_uart, UART_FLAG_ORE) != RESET)
    { volatile uint32_t sr = g_bt_uart.Instance->SR; volatile uint32_t dr = g_bt_uart.Instance->DR; (void)sr; (void)dr; }
}

uint8_t BT_ProtocolTakeApply(HystParams *params)
{
    if (g_apply_ready == 0U) return 0U;
    *params = g_pending;
    g_apply_ready = 0U;
    return 1U;
}

void BT_ProtocolReportApplied(const HystParams *p)
{
    char text[220];
    sprintf(text, "STATUS HMAX=%.3f HC=%.3f BR=%.3f BS=%.3f LOOP_HZ=%.3f X_GAIN=%.3f Y_GAIN=%.3f X_OFFSET=%.3f Y_OFFSET=%.3f XY_COUPLING=%.3f ASYMMETRY=%.3f AMPLITUDE=%u\r\n",
            p->h_max,p->h_c,p->b_r,p->b_s,p->loop_hz,p->x_gain,p->y_gain,p->x_offset,p->y_offset,p->xy_coupling,p->asymmetry,p->dac_amplitude);
    send_text(text);
}

void BT_ProtocolReportError(const char *reason)
{
    send_text("ERR ");
    send_text(reason);
    send_text("\r\n");
}
