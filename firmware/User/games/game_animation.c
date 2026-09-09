#include "game_animation.h"

#include "cat_wave_animation_data.h"
#include "vector_draw.h"

#include "./SYSTEM/sys/sys.h"

#include <stdint.h>

#define ANIMATION_FRAME_MS  33U
#define COORDINATE_SCALE    0.01f

static uint8_t g_frame_index;
static uint32_t g_last_frame_tick;

void animation_init(void)
{
    g_frame_index = 0U;
    g_last_frame_tick = HAL_GetTick();
}

void animation_update(void)
{
    uint32_t now = HAL_GetTick();

    if ((uint32_t)(now - g_last_frame_tick) >= ANIMATION_FRAME_MS)
    {
        g_last_frame_tick += ANIMATION_FRAME_MS;
        g_frame_index++;
        if (g_frame_index >= CAT_WAVE_FRAME_COUNT)
        {
            g_frame_index = 0U;
        }
    }
}

void animation_render(void)
{
    const CatWaveFrame *frame = &g_cat_wave_frames[g_frame_index];
    uint16_t end = (uint16_t)(frame->start + frame->count);
    uint16_t i;

    for (i = frame->start; i < end; i++)
    {
        const CatWavePoint *point = &g_cat_wave_points[i];
        float x = (float)point->x * COORDINATE_SCALE;
        float y = (float)point->y * COORDINATE_SCALE;

        if (point->move != 0U)
        {
            vector_move_to(x, y);
        }
        else
        {
            vector_line_to(x, y, 3U);
        }
    }

    vector_blank();
}
