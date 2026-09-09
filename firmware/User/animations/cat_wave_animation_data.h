#ifndef __CAT_WAVE_ANIMATION_DATA_H
#define __CAT_WAVE_ANIMATION_DATA_H

#include <stdint.h>

typedef struct
{
    int8_t x;
    int8_t y;
    uint8_t move;
} CatWavePoint;

typedef struct
{
    uint16_t start;
    uint16_t count;
} CatWaveFrame;

#define CAT_WAVE_FRAME_COUNT 60U

extern const CatWavePoint g_cat_wave_points[];
extern const CatWaveFrame g_cat_wave_frames[CAT_WAVE_FRAME_COUNT];

#endif
