#include "hyst_model.h"

#include <math.h>

#define PI_F 3.14159265358979323846f
#define DAC_MIDPOINT 2048
#define TURN_BLEND_RADIANS (12.0f * PI_F / 180.0f)

uint16_t g_hyst_buf_x[HYST_WAVE_SAMPLES];
uint16_t g_hyst_buf_y[HYST_WAVE_SAMPLES];
static uint16_t g_hyst_next_x[HYST_WAVE_SAMPLES];
static uint16_t g_hyst_next_y[HYST_WAVE_SAMPLES];
static float g_raw_x[HYST_WAVE_SAMPLES + 1U];
static float g_raw_y[HYST_WAVE_SAMPLES + 1U];
static float g_raw_length[HYST_WAVE_SAMPLES + 1U];

static float clamp_float(float value, float low, float high)
{
    if (value < low) return low;
    if (value > high) return high;
    return value;
}

static uint16_t normalized_to_dac(float value, uint16_t amplitude)
{
    int32_t code;

    value = clamp_float(value, -1.0f, 1.0f);
    code = DAC_MIDPOINT + (int32_t)(value * (float)amplitude);
    if (code < 0) code = 0;
    if (code > 4095) code = 4095;
    return (uint16_t)code;
}

static float smoothstep(float value)
{
    value = clamp_float(value, 0.0f, 1.0f);
    return value * value * (3.0f - 2.0f * value);
}

void Hyst_Generate(const HystParams *params)
{
    uint32_t index;
    uint32_t segment;
    float ratio;
    float shape;
    float total_length;

    if ((params == 0) || (params->h_max <= 0.0f) ||
        (params->h_c <= 0.0f) || (params->b_s <= 0.0f))
    {
        return;
    }

    ratio = clamp_float(params->b_r / params->b_s, 0.001f, 0.999f);
    shape = params->h_c / atanhf(ratio);
    if (shape < 0.000001f) shape = 0.000001f;

    for (index = 0U; index < HYST_WAVE_SAMPLES; index++)
    {
        float phase = 2.0f * PI_F * (float)index /
                      (float)HYST_WAVE_SAMPLES;
        float h = params->h_max * sinf(phase);
        float b_up = params->b_s * tanhf((h + params->h_c) / shape);
        float b_down = params->b_s * tanhf((h - params->h_c) / shape);
        float b;

        if ((phase >= (0.5f * PI_F - TURN_BLEND_RADIANS)) &&
            (phase <= (0.5f * PI_F + TURN_BLEND_RADIANS)))
        {
            float blend = smoothstep(
                (phase - (0.5f * PI_F - TURN_BLEND_RADIANS)) /
                (2.0f * TURN_BLEND_RADIANS)
            );
            b = b_up + (b_down - b_up) * blend;
        }
        else if ((phase >= (1.5f * PI_F - TURN_BLEND_RADIANS)) &&
                 (phase <= (1.5f * PI_F + TURN_BLEND_RADIANS)))
        {
            float blend = smoothstep(
                (phase - (1.5f * PI_F - TURN_BLEND_RADIANS)) /
                (2.0f * TURN_BLEND_RADIANS)
            );
            b = b_down + (b_up - b_down) * blend;
        }
        else if (cosf(phase) >= 0.0f) b = b_up;
        else b = b_down;

        if (cosf(phase) >= 0.0f) b *= (1.0f + params->asymmetry);
        else b *= (1.0f - params->asymmetry);

        g_raw_x[index] = params->x_gain * (h / params->h_max) +
                         params->x_offset;
        g_raw_y[index] = params->y_gain * (b / params->b_s) +
                         params->y_offset +
                         params->xy_coupling * (h / params->h_max);
    }

    /* Close the curve explicitly, then build cumulative X-Y arc length.
     * Equal-phase sampling leaves too few points on steep branches.  Arc-
     * length resampling assigns points according to visible travel distance,
     * keeping steep loops continuous on an analogue oscilloscope. */
    g_raw_x[HYST_WAVE_SAMPLES] = g_raw_x[0];
    g_raw_y[HYST_WAVE_SAMPLES] = g_raw_y[0];
    g_raw_length[0] = 0.0f;
    for (index = 1U; index <= HYST_WAVE_SAMPLES; index++)
    {
        float dx = g_raw_x[index] - g_raw_x[index - 1U];
        float dy = g_raw_y[index] - g_raw_y[index - 1U];
        g_raw_length[index] = g_raw_length[index - 1U] +
                              sqrtf(dx * dx + dy * dy);
    }

    total_length = g_raw_length[HYST_WAVE_SAMPLES];
    if (total_length < 0.000001f)
    {
        return;
    }

    segment = 1U;
    for (index = 0U; index < HYST_WAVE_SAMPLES; index++)
    {
        float target = total_length * (float)index /
                       (float)HYST_WAVE_SAMPLES;
        float span;
        float blend;
        float x;
        float y;

        while ((segment < HYST_WAVE_SAMPLES) &&
               (g_raw_length[segment] < target))
        {
            segment++;
        }

        span = g_raw_length[segment] - g_raw_length[segment - 1U];
        blend = (span > 0.000001f) ?
                ((target - g_raw_length[segment - 1U]) / span) : 0.0f;
        x = g_raw_x[segment - 1U] +
            (g_raw_x[segment] - g_raw_x[segment - 1U]) * blend;
        y = g_raw_y[segment - 1U] +
            (g_raw_y[segment] - g_raw_y[segment - 1U]) * blend;

        g_hyst_next_x[index] = normalized_to_dac(x, params->dac_amplitude);
        g_hyst_next_y[index] = normalized_to_dac(y, params->dac_amplitude);
    }
}

void Hyst_CommitGenerated(void)
{
    uint32_t index;
    for (index = 0U; index < HYST_WAVE_SAMPLES; index++)
    {
        g_hyst_buf_x[index] = g_hyst_next_x[index];
        g_hyst_buf_y[index] = g_hyst_next_y[index];
    }
}

void Hyst_GenerateDefault(void)
{
    Hyst_Generate(Hyst_DefaultParams());
}

const HystParams *Hyst_DefaultParams(void)
{
    static const HystParams defaults =
    {
        100.0f, /* Hmax */
        25.0f,  /* Hc   */
        0.65f,  /* Br   */
        1.20f,  /* Bs   */
        195.3125f,
        1.0f, 1.0f,
        0.0f, 0.0f,
        0.0f, 0.0f,
        1500U   /* about 0.44 V to 2.86 V at VDDA=3.3 V */
    };
    return &defaults;
}
