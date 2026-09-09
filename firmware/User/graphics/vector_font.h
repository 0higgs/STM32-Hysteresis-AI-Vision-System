#ifndef __VECTOR_FONT_H
#define __VECTOR_FONT_H
#include <stdint.h>
#include "ui_text_zh.h"

void vector_font_draw_char(char ch, float x, float y, float size);
void vector_font_draw_text(const char *text, float x, float y, float size);
float vector_font_text_width(const char *text, float size);
void vector_font_draw_text_center(const char *text, float center_x, float y, float size);

#endif
