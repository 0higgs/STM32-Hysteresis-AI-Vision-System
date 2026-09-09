#include "vector_font.h"
#include "hanzi_ui_data.h"
#include <stddef.h>

extern void vector_move_to(float x, float y);
extern void vector_line_to(float x, float y, uint16_t points);
extern void vector_blank(void);

#define SEG_A   (1U << 0)
#define SEG_B   (1U << 1)
#define SEG_C   (1U << 2)
#define SEG_D   (1U << 3)
#define SEG_E   (1U << 4)
#define SEG_F   (1U << 5)
#define SEG_G1  (1U << 6)
#define SEG_G2  (1U << 7)
#define SEG_H   (1U << 8)
#define SEG_I   (1U << 9)
#define SEG_J   (1U << 10)
#define SEG_K   (1U << 11)
#define SEG_L   (1U << 12)
#define SEG_M   (1U << 13)

#define FONT_W       0.62f
#define FONT_ADVANCE 0.78f
#define HANZI_ADVANCE 1.08f

#define HZV_HEADER_SIZE       36U
#define HZV_INDEX_ENTRY_SIZE  12U

typedef struct
{
    float x1, y1, x2, y2;
} Segment;

/* y=0 ??,y=1 ????????????????? */
static const Segment g_segments[14] =
{
    {0.00f,0.00f,1.00f,0.00f}, /* A  */
    {1.00f,0.00f,1.00f,0.50f}, /* B  */
    {1.00f,0.50f,1.00f,1.00f}, /* C  */
    {0.00f,1.00f,1.00f,1.00f}, /* D  */
    {0.00f,0.50f,0.00f,1.00f}, /* E  */
    {0.00f,0.00f,0.00f,0.50f}, /* F  */
    {0.00f,0.50f,0.50f,0.50f}, /* G1 */
    {0.50f,0.50f,1.00f,0.50f}, /* G2 */
    {0.00f,0.00f,0.50f,0.50f}, /* H  */
    {0.50f,0.50f,1.00f,0.00f}, /* I  */
    {0.50f,0.50f,0.00f,1.00f}, /* J  */
    {0.50f,0.50f,1.00f,1.00f}, /* K  */
    {0.50f,0.00f,0.50f,0.50f}, /* L  */
    {0.50f,0.50f,0.50f,1.00f}  /* M  */
};

static uint16_t hzv_read_u16(const uint8_t *data)
{
    return (uint16_t)data[0] |
           (uint16_t)((uint16_t)data[1] << 8U);
}

static uint32_t hzv_read_u32(const uint8_t *data)
{
    return (uint32_t)data[0] |
           ((uint32_t)data[1] << 8U) |
           ((uint32_t)data[2] << 16U) |
           ((uint32_t)data[3] << 24U);
}

static uint8_t hzv_font_valid(void)
{
    if (g_hanzi_ui_data_size < HZV_HEADER_SIZE)
    {
        return 0U;
    }

    return
        ((g_hanzi_ui_data[0] == (uint8_t)'H') &&
         (g_hanzi_ui_data[1] == (uint8_t)'Z') &&
         (g_hanzi_ui_data[2] == (uint8_t)'V') &&
         (g_hanzi_ui_data[3] == (uint8_t)'1') &&
         (hzv_read_u16(&g_hanzi_ui_data[4]) == 1U) &&
         (hzv_read_u16(&g_hanzi_ui_data[6]) == HZV_HEADER_SIZE) &&
         (hzv_read_u16(&g_hanzi_ui_data[26]) ==
          HZV_INDEX_ENTRY_SIZE)) ? 1U : 0U;
}

static const uint8_t *hzv_find_glyph(
    uint32_t codepoint,
    uint16_t *data_length,
    uint8_t *stroke_count
)
{
    uint32_t low;
    uint32_t high;
    uint32_t index_offset;

    if ((hzv_font_valid() == 0U) ||
        (data_length == NULL) ||
        (stroke_count == NULL))
    {
        return NULL;
    }

    low = 0U;
    high = hzv_read_u32(&g_hanzi_ui_data[8]);
    index_offset = hzv_read_u32(&g_hanzi_ui_data[12]);

    while (low < high)
    {
        uint32_t middle = low + (high - low) / 2U;
        uint32_t entry_offset =
            index_offset + middle * HZV_INDEX_ENTRY_SIZE;
        const uint8_t *entry;
        uint32_t entry_codepoint;
        uint32_t glyph_offset;

        if (entry_offset + HZV_INDEX_ENTRY_SIZE >
            g_hanzi_ui_data_size)
        {
            return NULL;
        }

        entry = &g_hanzi_ui_data[entry_offset];
        entry_codepoint = hzv_read_u32(&entry[0]);

        if (entry_codepoint < codepoint)
        {
            low = middle + 1U;
        }
        else if (entry_codepoint > codepoint)
        {
            high = middle;
        }
        else
        {
            glyph_offset = hzv_read_u32(&entry[4]);
            *data_length = hzv_read_u16(&entry[8]);
            *stroke_count = entry[10];

            if ((glyph_offset + *data_length >
                 g_hanzi_ui_data_size) ||
                (*stroke_count == 0U))
            {
                return NULL;
            }

            return &g_hanzi_ui_data[glyph_offset];
        }
    }

    return NULL;
}

static uint32_t utf8_next(const char **text)
{
    const uint8_t *bytes = (const uint8_t *)*text;
    uint32_t codepoint;

    if (bytes[0] < 0x80U)
    {
        *text += 1;
        return bytes[0];
    }

    if (((bytes[0] & 0xE0U) == 0xC0U) &&
        ((bytes[1] & 0xC0U) == 0x80U))
    {
        codepoint =
            ((uint32_t)(bytes[0] & 0x1FU) << 6U) |
            (uint32_t)(bytes[1] & 0x3FU);
        *text += 2;
        return codepoint;
    }

    if (((bytes[0] & 0xF0U) == 0xE0U) &&
        ((bytes[1] & 0xC0U) == 0x80U) &&
        ((bytes[2] & 0xC0U) == 0x80U))
    {
        codepoint =
            ((uint32_t)(bytes[0] & 0x0FU) << 12U) |
            ((uint32_t)(bytes[1] & 0x3FU) << 6U) |
            (uint32_t)(bytes[2] & 0x3FU);
        *text += 3;
        return codepoint;
    }

    if (((bytes[0] & 0xF8U) == 0xF0U) &&
        ((bytes[1] & 0xC0U) == 0x80U) &&
        ((bytes[2] & 0xC0U) == 0x80U) &&
        ((bytes[3] & 0xC0U) == 0x80U))
    {
        codepoint =
            ((uint32_t)(bytes[0] & 0x07U) << 18U) |
            ((uint32_t)(bytes[1] & 0x3FU) << 12U) |
            ((uint32_t)(bytes[2] & 0x3FU) << 6U) |
            (uint32_t)(bytes[3] & 0x3FU);
        *text += 4;
        return codepoint;
    }

    *text += 1;
    return (uint32_t)'?';
}

static uint8_t draw_hanzi(
    uint32_t codepoint,
    float x,
    float y,
    float size
)
{
    uint16_t data_length;
    uint8_t stroke_count;
    const uint8_t *glyph =
        hzv_find_glyph(codepoint, &data_length, &stroke_count);
    uint16_t cursor = 0U;
    uint8_t stroke;

    if (glyph == NULL)
    {
        return 0U;
    }

    for (stroke = 0U; stroke < stroke_count; stroke++)
    {
        uint8_t point_count;
        uint8_t point;
        uint8_t previous_x;
        uint8_t previous_y;

        if (cursor >= data_length)
        {
            return 0U;
        }

        point_count = glyph[cursor++];
        if ((point_count < 2U) ||
            ((uint32_t)cursor + (uint32_t)point_count * 2U >
             data_length))
        {
            return 0U;
        }

        previous_x = glyph[cursor];
        previous_y = glyph[cursor + 1U];
        vector_move_to(
            x + (float)previous_x * size / 255.0f,
            y + (float)previous_y * size / 255.0f
        );
        cursor += 2U;

        for (point = 1U; point < point_count; point++)
        {
            uint8_t next_x = glyph[cursor];
            uint8_t next_y = glyph[cursor + 1U];
            uint8_t delta_x = (next_x > previous_x)
                ? (uint8_t)(next_x - previous_x)
                : (uint8_t)(previous_x - next_x);
            uint8_t delta_y = (next_y > previous_y)
                ? (uint8_t)(next_y - previous_y)
                : (uint8_t)(previous_y - next_y);
            uint8_t max_delta =
                (delta_x > delta_y) ? delta_x : delta_y;
            uint16_t samples = (uint16_t)(3U + max_delta / 28U);

            vector_line_to(
                x + (float)next_x * size / 255.0f,
                y + (float)next_y * size / 255.0f,
                samples
            );

            previous_x = next_x;
            previous_y = next_y;
            cursor += 2U;
        }

        vector_blank();
    }

    return (cursor == data_length) ? 1U : 0U;
}

static uint16_t font_mask(char ch)
{
    if (ch >= 'a' && ch <= 'z') ch = (char)(ch - 'a' + 'A');

    switch (ch)
    {
        case '0': return SEG_A|SEG_B|SEG_C|SEG_D|SEG_E|SEG_F;
        case '1': return SEG_B|SEG_C;
        case '2': return SEG_A|SEG_B|SEG_G1|SEG_G2|SEG_E|SEG_D;
        case '3': return SEG_A|SEG_B|SEG_C|SEG_D|SEG_G1|SEG_G2;
        case '4': return SEG_F|SEG_G1|SEG_G2|SEG_B|SEG_C;
        case '5': return SEG_A|SEG_F|SEG_G1|SEG_G2|SEG_C|SEG_D;
        case '6': return SEG_A|SEG_F|SEG_E|SEG_D|SEG_C|SEG_G1|SEG_G2;
        case '7': return SEG_A|SEG_B|SEG_C;
        case '8': return SEG_A|SEG_B|SEG_C|SEG_D|SEG_E|SEG_F|SEG_G1|SEG_G2;
        case '9': return SEG_A|SEG_B|SEG_C|SEG_D|SEG_F|SEG_G1|SEG_G2;

        case 'A': return SEG_A|SEG_B|SEG_C|SEG_E|SEG_F|SEG_G1|SEG_G2;
        case 'B': return SEG_A|SEG_B|SEG_C|SEG_D|SEG_G1|SEG_G2|SEG_L|SEG_M;
        case 'C': return SEG_A|SEG_D|SEG_E|SEG_F;
        case 'D': return SEG_A|SEG_B|SEG_C|SEG_D|SEG_L|SEG_M;
        case 'E': return SEG_A|SEG_D|SEG_E|SEG_F|SEG_G1|SEG_G2;
        case 'F': return SEG_A|SEG_E|SEG_F|SEG_G1|SEG_G2;
        case 'G': return SEG_A|SEG_C|SEG_D|SEG_E|SEG_F|SEG_G2;
        case 'H': return SEG_B|SEG_C|SEG_E|SEG_F|SEG_G1|SEG_G2;
        case 'I': return SEG_A|SEG_D|SEG_L|SEG_M;
        case 'J': return SEG_B|SEG_C|SEG_D|SEG_E;
        case 'K': return SEG_E|SEG_F|SEG_G1|SEG_I|SEG_K;
        case 'L': return SEG_D|SEG_E|SEG_F;
        case 'M': return SEG_B|SEG_C|SEG_E|SEG_F|SEG_H|SEG_I;
        case 'N': return SEG_B|SEG_C|SEG_E|SEG_F|SEG_H|SEG_K;
        case 'O': return SEG_A|SEG_B|SEG_C|SEG_D|SEG_E|SEG_F;
        case 'P': return SEG_A|SEG_B|SEG_E|SEG_F|SEG_G1|SEG_G2;
        case 'Q': return SEG_A|SEG_B|SEG_C|SEG_D|SEG_E|SEG_F|SEG_K;
        case 'R': return SEG_A|SEG_B|SEG_E|SEG_F|SEG_G1|SEG_G2|SEG_K;
        case 'S': return SEG_A|SEG_C|SEG_D|SEG_F|SEG_G1|SEG_G2;
        case 'T': return SEG_A|SEG_L|SEG_M;
        case 'U': return SEG_B|SEG_C|SEG_D|SEG_E|SEG_F;
        case 'V': return SEG_F | SEG_B | SEG_J | SEG_K;
        case 'W': return SEG_B|SEG_C|SEG_E|SEG_F|SEG_J|SEG_K;
        case 'X': return SEG_H|SEG_I|SEG_J|SEG_K;
        case 'Y': return SEG_H|SEG_I|SEG_M;
        case 'Z': return SEG_A|SEG_I|SEG_J|SEG_D;

        case '-': return SEG_G1|SEG_G2;
        case '_': return SEG_D;
        case '=': return SEG_G1|SEG_G2|SEG_D;
        default:  return 0;
    }
}

static void draw_local_line(float x,float y,float size,
                            float x1,float y1,float x2,float y2)
{
    float w = size * FONT_W;
    vector_move_to(x + x1*w, y + y1*size);
    vector_line_to(x + x2*w, y + y2*size, 8);
    vector_blank();
}

static void draw_dot(float x,float y,float size)
{
    draw_local_line(x,y,size,0.48f,0.92f,0.54f,0.92f);
}

static uint8_t draw_special(char ch,float x,float y,float size)
{
    switch (ch)
    {
		        case 'V':
            /*
             * V:
             *
             * |       |
             * |       |
             *  \     /
             *   \   /
             *    \ /
             *
             * y=0 ???
             * y=1 ???
             */

            /* ???? */
            draw_local_line(
                x, y, size,
                0.10f, 0.00f,
                0.10f, 0.48f
            );

            /* ???? */
            draw_local_line(
                x, y, size,
                0.90f, 0.00f,
                0.90f, 0.48f
            );

            /* ???? */
            draw_local_line(
                x, y, size,
                0.10f, 0.48f,
                0.50f, 1.00f
            );

            /* ???? */
            draw_local_line(
                x, y, size,
                0.90f, 0.48f,
                0.50f, 1.00f
            );

            return 1;
        case ' ': return 1;
        case '+':
            draw_local_line(x,y,size,0.15f,0.50f,0.85f,0.50f);
            draw_local_line(x,y,size,0.50f,0.20f,0.50f,0.80f);
            return 1;
        case '/':
            draw_local_line(x,y,size,0.05f,1.00f,0.95f,0.00f); return 1;
        case '\\':
            draw_local_line(x,y,size,0.05f,0.00f,0.95f,1.00f); return 1;
        case '|':
            draw_local_line(x,y,size,0.50f,0.00f,0.50f,1.00f); return 1;
        case '*':
            draw_local_line(x,y,size,0.10f,0.50f,0.90f,0.50f);
            draw_local_line(x,y,size,0.50f,0.15f,0.50f,0.85f);
            draw_local_line(x,y,size,0.15f,0.20f,0.85f,0.80f);
            draw_local_line(x,y,size,0.85f,0.20f,0.15f,0.80f);
            return 1;
        case '!':
            draw_local_line(x,y,size,0.50f,0.05f,0.50f,0.70f);
            draw_dot(x,y,size);
            return 1;
        case '?':
            draw_local_line(x,y,size,0.15f,0.15f,0.35f,0.02f);
            draw_local_line(x,y,size,0.35f,0.02f,0.75f,0.02f);
            draw_local_line(x,y,size,0.75f,0.02f,0.90f,0.20f);
            draw_local_line(x,y,size,0.90f,0.20f,0.50f,0.52f);
            draw_local_line(x,y,size,0.50f,0.52f,0.50f,0.68f);
            draw_dot(x,y,size);
            return 1;
        case '.': draw_dot(x,y,size); return 1;
        case ',':
            draw_dot(x,y,size);
            draw_local_line(x,y,size,0.50f,0.92f,0.35f,1.08f);
            return 1;
        case ':':
            draw_local_line(x,y,size,0.48f,0.30f,0.54f,0.30f);
            draw_local_line(x,y,size,0.48f,0.78f,0.54f,0.78f);
            return 1;
        case ';':
            draw_local_line(x,y,size,0.48f,0.30f,0.54f,0.30f);
            draw_local_line(x,y,size,0.48f,0.78f,0.54f,0.78f);
            draw_local_line(x,y,size,0.54f,0.78f,0.38f,0.96f);
            return 1;
        case '\'':
            draw_local_line(x,y,size,0.50f,0.00f,0.45f,0.20f); return 1;
        case '"':
            draw_local_line(x,y,size,0.32f,0.00f,0.28f,0.20f);
            draw_local_line(x,y,size,0.68f,0.00f,0.64f,0.20f);
            return 1;
        case '(':
            draw_local_line(x,y,size,0.65f,0.00f,0.35f,0.25f);
            draw_local_line(x,y,size,0.35f,0.25f,0.35f,0.75f);
            draw_local_line(x,y,size,0.35f,0.75f,0.65f,1.00f);
            return 1;
        case ')':
            draw_local_line(x,y,size,0.35f,0.00f,0.65f,0.25f);
            draw_local_line(x,y,size,0.65f,0.25f,0.65f,0.75f);
            draw_local_line(x,y,size,0.65f,0.75f,0.35f,1.00f);
            return 1;
        case '[':
            draw_local_line(x,y,size,0.65f,0.00f,0.30f,0.00f);
            draw_local_line(x,y,size,0.30f,0.00f,0.30f,1.00f);
            draw_local_line(x,y,size,0.30f,1.00f,0.65f,1.00f);
            return 1;
        case ']':
            draw_local_line(x,y,size,0.35f,0.00f,0.70f,0.00f);
            draw_local_line(x,y,size,0.70f,0.00f,0.70f,1.00f);
            draw_local_line(x,y,size,0.70f,1.00f,0.35f,1.00f);
            return 1;
        case '<':
            draw_local_line(x,y,size,0.80f,0.15f,0.20f,0.50f);
            draw_local_line(x,y,size,0.20f,0.50f,0.80f,0.85f);
            return 1;
        case '>':
            draw_local_line(x,y,size,0.20f,0.15f,0.80f,0.50f);
            draw_local_line(x,y,size,0.80f,0.50f,0.20f,0.85f);
            return 1;
        case '%':
            draw_local_line(x,y,size,0.08f,1.00f,0.92f,0.00f);
            draw_local_line(x,y,size,0.15f,0.10f,0.30f,0.10f);
            draw_local_line(x,y,size,0.70f,0.90f,0.85f,0.90f);
            return 1;
        default:
            return 0;
    }
}

void vector_font_draw_char(char ch,float x,float y,float size)
{
    uint16_t mask;
    uint8_t i;

    if (draw_special(ch,x,y,size))
    {
        vector_blank();
        return;
    }

    mask = font_mask(ch);

    for (i=0;i<14;i++)
    {
        if ((mask & (1U<<i)) != 0U)
        {
            const Segment *s = &g_segments[i];
            draw_local_line(x,y,size,s->x1,s->y1,s->x2,s->y2);
        }
    }

    vector_blank();
}

float vector_font_text_width(const char *text,float size)
{
    float cursor = 0.0f;
    float width = 0.0f;

    if (text == NULL || *text == '\0') return 0.0f;

    while (*text != '\0')
    {
        uint32_t codepoint = utf8_next(&text);

        if (codepoint < 0x80U)
        {
            width = cursor + size * FONT_W;
            cursor += size * FONT_ADVANCE;
        }
        else
        {
            width = cursor + size;
            cursor += size * HANZI_ADVANCE;
        }
    }

    return width;
}

void vector_font_draw_text(const char *text,float x,float y,float size)
{
    float cursor_x = x;

    if (text == NULL) return;

    while (*text != '\0')
    {
        uint32_t codepoint = utf8_next(&text);

        if (codepoint < 0x80U)
        {
            vector_font_draw_char((char)codepoint,cursor_x,y,size);
            cursor_x += size*FONT_ADVANCE;
        }
        else
        {
            if (draw_hanzi(codepoint,cursor_x,y,size) == 0U)
            {
                vector_font_draw_char('?',cursor_x,y,size);
            }

            cursor_x += size*HANZI_ADVANCE;
        }
    }

    vector_blank();
}

void vector_font_draw_text_center(const char *text,float center_x,float y,float size)
{
    float width = vector_font_text_width(text,size);
    vector_font_draw_text(text,center_x-width*0.5f,y,size);
}
