#ifndef __HYST_MODEL_H
#define __HYST_MODEL_H

#include <stdint.h>

#define HYST_WAVE_SAMPLES 512U

typedef struct
{
    float h_max;
    float h_c;
    float b_r;
    float b_s;
    float loop_hz;
    float x_gain;
    float y_gain;
    float x_offset;
    float y_offset;
    float xy_coupling;
    float asymmetry;
    uint16_t dac_amplitude;
} HystParams;

extern uint16_t g_hyst_buf_x[HYST_WAVE_SAMPLES];
extern uint16_t g_hyst_buf_y[HYST_WAVE_SAMPLES];

void Hyst_Generate(const HystParams *params);
void Hyst_GenerateDefault(void);
const HystParams *Hyst_DefaultParams(void);
void Hyst_CommitGenerated(void);

#endif
