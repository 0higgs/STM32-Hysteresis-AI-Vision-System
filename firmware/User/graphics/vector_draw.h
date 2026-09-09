#ifndef __VECTOR_DRAW_H
#define __VECTOR_DRAW_H

#include <stdint.h>

/* Logical screen coordinates used by all games. */
#define VECTOR_SCREEN_X_MIN   (-1.00f)
#define VECTOR_SCREEN_X_MAX   ( 1.00f)
#define VECTOR_SCREEN_Y_MIN   (-0.75f)
#define VECTOR_SCREEN_Y_MAX   ( 0.75f)

/* PA5/DAC2 -> X, PA4/DAC1 -> Y, PA7 -> Z blanking. */
void vector_draw_init(void);

void vector_blank(void);
void vector_move_to(float x, float y);
void vector_line_to(float x, float y, uint16_t points);

void vector_draw_rect(float cx, float cy, float width, float height);
void vector_draw_border(float left, float top, float right, float bottom);

#endif
