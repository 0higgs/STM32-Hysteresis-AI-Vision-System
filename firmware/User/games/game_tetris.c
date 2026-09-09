#include "game_tetris.h"

#include "game_key.h"
#include "bluetooth_control.h"
#include "vector_draw.h"
#include "vector_font.h"

#include "./SYSTEM/sys/sys.h"

#include <stdint.h>
#include <stdio.h>

#define BOARD_COLS          12
#define BOARD_ROWS          18

#define FIELD_LEFT          (-0.98f)
#define FIELD_RIGHT         (-0.02f)
#define FIELD_TOP           (-0.72f)
#define FIELD_BOTTOM        ( 0.72f)
#define CELL_SIZE           ( 0.08f)
#define BLOCK_SIZE          ( 0.072f)

#define MOVE_REPEAT_DELAY   230U
#define MOVE_REPEAT_MS       85U
#define FAST_RENDER_BLOCKS    56U

typedef struct
{
    uint8_t type;
    uint8_t rotation;
    int8_t x;
    int8_t y;
} TetrisPiece;

/*
 * Each tetromino is stored as four 4x4 bit masks. Bit (row * 4 + col)
 * represents one occupied block. Order: I, O, T, S, Z, J, L.
 */
static const uint16_t g_shapes[7][4] =
{
    {0x00F0U, 0x4444U, 0x00F0U, 0x4444U},
    {0x0066U, 0x0066U, 0x0066U, 0x0066U},
    {0x0072U, 0x0262U, 0x0270U, 0x0232U},
    {0x0036U, 0x0462U, 0x0036U, 0x0462U},
    {0x0063U, 0x0264U, 0x0063U, 0x0264U},
    {0x0071U, 0x0226U, 0x0470U, 0x0322U},
    {0x0074U, 0x0622U, 0x0170U, 0x0223U}
};

static uint8_t g_board[BOARD_ROWS][BOARD_COLS];
static TetrisPiece g_piece;
static uint8_t g_next_type;

static uint8_t g_bag[7];
static uint8_t g_bag_index;
static uint32_t g_random;

static uint32_t g_score;
static uint16_t g_lines;
static uint8_t g_level;
static uint8_t g_game_over;
static uint8_t g_restart_armed;

static uint32_t g_last_fall;
static uint32_t g_a_since;
static uint32_t g_b_since;
static uint32_t g_a_repeat;
static uint32_t g_b_repeat;
static uint8_t g_render_phase;

static uint32_t random_next(void)
{
    g_random = g_random * 1664525UL + 1013904223UL;
    return g_random;
}

static void refill_bag(void)
{
    int8_t i;

    for (i = 0; i < 7; i++)
    {
        g_bag[(uint8_t)i] = (uint8_t)i;
    }

    for (i = 6; i > 0; i--)
    {
        uint8_t j = (uint8_t)(random_next() % (uint32_t)(i + 1));
        uint8_t temp = g_bag[(uint8_t)i];
        g_bag[(uint8_t)i] = g_bag[j];
        g_bag[j] = temp;
    }

    g_bag_index = 0U;
}

static uint8_t take_piece_type(void)
{
    if (g_bag_index >= 7U)
    {
        refill_bag();
    }

    return g_bag[g_bag_index++];
}

static uint8_t shape_has_block(uint8_t type, uint8_t rotation,
                               uint8_t row, uint8_t col)
{
    uint16_t bit = (uint16_t)(1U << ((uint16_t)row * 4U + col));
    return ((g_shapes[type][rotation] & bit) != 0U) ? 1U : 0U;
}

static uint8_t piece_fits(int8_t x, int8_t y, uint8_t rotation)
{
    uint8_t row;
    uint8_t col;

    for (row = 0U; row < 4U; row++)
    {
        for (col = 0U; col < 4U; col++)
        {
            int8_t board_x;
            int8_t board_y;

            if (shape_has_block(g_piece.type, rotation, row, col) == 0U)
            {
                continue;
            }

            board_x = (int8_t)(x + (int8_t)col);
            board_y = (int8_t)(y + (int8_t)row);

            if ((board_x < 0) || (board_x >= BOARD_COLS) ||
                (board_y >= BOARD_ROWS))
            {
                return 0U;
            }

            if ((board_y >= 0) &&
                (g_board[(uint8_t)board_y][(uint8_t)board_x] != 0U))
            {
                return 0U;
            }
        }
    }

    return 1U;
}

static void spawn_piece(void)
{
    g_piece.type = g_next_type;
    g_piece.rotation = 0U;
    g_piece.x = (BOARD_COLS - 4) / 2;
    g_piece.y = -1;
    g_next_type = take_piece_type();

    if (piece_fits(g_piece.x, g_piece.y, g_piece.rotation) == 0U)
    {
        g_game_over = 1U;
    }
}

static uint8_t clear_complete_lines(void)
{
    int8_t row;
    uint8_t cleared = 0U;

    for (row = BOARD_ROWS - 1; row >= 0; row--)
    {
        uint8_t col;
        uint8_t full = 1U;

        for (col = 0U; col < BOARD_COLS; col++)
        {
            if (g_board[(uint8_t)row][col] == 0U)
            {
                full = 0U;
                break;
            }
        }

        if (full != 0U)
        {
            int8_t copy_row;

            for (copy_row = row; copy_row > 0; copy_row--)
            {
                for (col = 0U; col < BOARD_COLS; col++)
                {
                    g_board[(uint8_t)copy_row][col] =
                        g_board[(uint8_t)(copy_row - 1)][col];
                }
            }

            for (col = 0U; col < BOARD_COLS; col++)
            {
                g_board[0][col] = 0U;
            }

            cleared++;
            row++;
        }
    }

    return cleared;
}

static void lock_piece(void)
{
    uint8_t row;
    uint8_t col;
    uint8_t cleared;

    for (row = 0U; row < 4U; row++)
    {
        for (col = 0U; col < 4U; col++)
        {
            int8_t board_x;
            int8_t board_y;

            if (shape_has_block(g_piece.type, g_piece.rotation,
                                row, col) == 0U)
            {
                continue;
            }

            board_x = (int8_t)(g_piece.x + (int8_t)col);
            board_y = (int8_t)(g_piece.y + (int8_t)row);

            if (board_y < 0)
            {
                g_game_over = 1U;
                return;
            }

            g_board[(uint8_t)board_y][(uint8_t)board_x] =
                (uint8_t)(g_piece.type + 1U);
        }
    }

    cleared = clear_complete_lines();
    if (cleared != 0U)
    {
        static const uint16_t line_points[5] =
        {
            0U, 100U, 300U, 500U, 800U
        };

        g_score += (uint32_t)line_points[cleared] * (uint32_t)g_level;
        g_lines = (uint16_t)(g_lines + cleared);
        g_level = (uint8_t)(1U + g_lines / 10U);

        if (g_level > 12U)
        {
            g_level = 12U;
        }
    }

    spawn_piece();
}

static uint32_t fall_interval(void)
{
    uint32_t interval = 650U;
    uint32_t reduction = (uint32_t)(g_level - 1U) * 45U;

    if (reduction >= 500U)
    {
        return 150U;
    }

    return interval - reduction;
}

static void try_move(int8_t dx)
{
    int8_t next_x = (int8_t)(g_piece.x + dx);

    if (piece_fits(next_x, g_piece.y, g_piece.rotation) != 0U)
    {
        g_piece.x = next_x;
    }
}

static void try_rotate(int8_t direction)
{
    uint8_t delta = (direction >= 0) ? 1U : 3U;
    uint8_t next_rotation =
        (uint8_t)((g_piece.rotation + delta) & 3U);
    static const int8_t kicks[5] = {0, -1, 1, -2, 2};
    uint8_t i;

    for (i = 0U; i < 5U; i++)
    {
        int8_t next_x = (int8_t)(g_piece.x + kicks[i]);

        if (piece_fits(next_x, g_piece.y, next_rotation) != 0U)
        {
            g_piece.x = next_x;
            g_piece.rotation = next_rotation;
            return;
        }
    }
}

static void hard_drop(void)
{
    uint16_t rows = 0U;

    while (piece_fits(g_piece.x, (int8_t)(g_piece.y + 1),
                      g_piece.rotation) != 0U)
    {
        g_piece.y++;
        rows++;
    }

    g_score += (uint32_t)rows * 2U;
    lock_piece();
    g_last_fall = HAL_GetTick();
}

static uint8_t repeat_move_event(uint8_t down, uint8_t pressed,
                                 uint32_t now, uint32_t *since,
                                 uint32_t *last_repeat)
{
    if (pressed != 0U)
    {
        *since = now;
        *last_repeat = now;
        return 1U;
    }

    if (down == 0U)
    {
        *since = 0U;
        *last_repeat = 0U;
        return 0U;
    }

    if ((*since != 0U) &&
        ((uint32_t)(now - *since) >= MOVE_REPEAT_DELAY) &&
        ((uint32_t)(now - *last_repeat) >= MOVE_REPEAT_MS))
    {
        *last_repeat = now;
        return 1U;
    }

    return 0U;
}

void tetris_init(void)
{
    uint8_t row;
    uint8_t col;

    for (row = 0U; row < BOARD_ROWS; row++)
    {
        for (col = 0U; col < BOARD_COLS; col++)
        {
            g_board[row][col] = 0U;
        }
    }

    g_random = HAL_GetTick() ^ 0x5A17C3E1UL;
    g_bag_index = 7U;
    g_score = 0U;
    g_lines = 0U;
    g_level = 1U;
    g_game_over = 0U;
    g_restart_armed = 0U;

    g_a_since = 0U;
    g_b_since = 0U;
    g_a_repeat = 0U;
    g_b_repeat = 0U;
    g_render_phase = 0U;

    g_next_type = take_piece_type();
    spawn_piece();
    g_last_fall = HAL_GetTick();
}

void tetris_update(void)
{
    uint32_t now = HAL_GetTick();
    uint8_t left_pressed = bluetooth_left_pressed();
    uint8_t right_pressed = bluetooth_right_pressed();
    uint8_t up_pressed = bluetooth_up_pressed();
    uint8_t down_pressed = bluetooth_down_pressed();
    uint8_t action1 = bluetooth_action1_pressed();
    uint8_t action2 = bluetooth_action2_pressed();
    uint8_t hard_drop_pressed = bluetooth_hard_drop_pressed();
    uint8_t start = bluetooth_start_pressed();
    uint8_t a_pressed = game_key_a_pressed();
    uint8_t b_pressed = game_key_b_pressed();
    uint8_t rotate_pressed = game_key_rotate_pressed();
    uint8_t left_down =
        ((game_key_a_down() != 0U) ||
         (bluetooth_left_down() != 0U)) ? 1U : 0U;
    uint8_t right_down =
        ((game_key_b_down() != 0U) ||
         (bluetooth_right_down() != 0U)) ? 1U : 0U;

    a_pressed =
        ((a_pressed != 0U) || (left_pressed != 0U)) ? 1U : 0U;
    b_pressed =
        ((b_pressed != 0U) || (right_pressed != 0U)) ? 1U : 0U;

    if (g_game_over != 0U)
    {
        if (g_restart_armed == 0U)
        {
            /*
             * The three events were consumed above. Wait for every Tetris
             * control to be released before accepting a new restart press.
             */
            if ((game_key_a_down() == 0U) &&
                (game_key_b_down() == 0U) &&
                (game_key_rotate_down() == 0U))
            {
                g_restart_armed = 1U;
            }

            return;
        }

        if ((a_pressed != 0U) || (b_pressed != 0U) ||
            (rotate_pressed != 0U) ||
            (up_pressed != 0U) || (down_pressed != 0U) ||
            (action1 != 0U) || (action2 != 0U) ||
            (hard_drop_pressed != 0U) || (start != 0U))
        {
            tetris_init();
        }

        return;
    }

    if (repeat_move_event(left_down, a_pressed, now,
                          &g_a_since, &g_a_repeat) != 0U)
    {
        try_move(-1);
    }

    if (repeat_move_event(right_down, b_pressed, now,
                          &g_b_since, &g_b_repeat) != 0U)
    {
        try_move(1);
    }

    if ((rotate_pressed != 0U) || (up_pressed != 0U))
    {
        try_rotate(1);
    }

    if (action2 != 0U)
    {
        try_rotate(-1);
    }

    if ((action1 != 0U) || (hard_drop_pressed != 0U))
    {
        hard_drop();
        return;
    }

    if ((uint32_t)(now - g_last_fall) >=
        ((bluetooth_down_down() != 0U) ? 45U : fall_interval()))
    {
        g_last_fall = now;

        if (piece_fits(g_piece.x, (int8_t)(g_piece.y + 1),
                       g_piece.rotation) != 0U)
        {
            g_piece.y++;

            if (bluetooth_down_down() != 0U)
            {
                g_score++;
            }
        }
        else
        {
            lock_piece();
        }
    }
}

static void draw_segment(float x1, float y1, float x2, float y2,
                         uint8_t cells, uint8_t vertical,
                         uint8_t fast)
{
    uint16_t points_per_cell;
    uint16_t points;

    if (vertical != 0U)
    {
        points_per_cell = (fast != 0U) ? 4U : 8U;
    }
    else
    {
        points_per_cell = (fast != 0U) ? 2U : 4U;
    }

    points = (uint16_t)cells * points_per_cell;
    if (points < 2U)
    {
        points = 2U;
    }

    vector_move_to(x1, y1);
    vector_line_to(x2, y2, points);
    vector_blank();
}

static void draw_outline_rect(float cx, float cy, float width, float height,
                              uint8_t fast)
{
    float left = cx - width * 0.5f;
    float right = cx + width * 0.5f;
    float top = cy - height * 0.5f;
    float bottom = cy + height * 0.5f;
    uint16_t horizontal_points = (fast != 0U) ? 3U : 5U;
    uint16_t vertical_points = (fast != 0U) ? 5U : 8U;

    vector_move_to(left, top);
    vector_line_to(right, top, horizontal_points);
    vector_line_to(right, bottom, vertical_points);
    vector_line_to(left, bottom, horizontal_points);
    vector_line_to(left, top, vertical_points);
    vector_blank();
}

static void draw_field_border(uint8_t fast)
{
    uint16_t horizontal_points = (fast != 0U) ? 21U : 42U;
    uint16_t vertical_points = (fast != 0U) ? 15U : 30U;

    vector_move_to(FIELD_LEFT, FIELD_TOP);
    vector_line_to(FIELD_RIGHT, FIELD_TOP, horizontal_points);
    vector_line_to(FIELD_RIGHT, FIELD_BOTTOM, vertical_points);
    vector_line_to(FIELD_LEFT, FIELD_BOTTOM, horizontal_points);
    vector_line_to(FIELD_LEFT, FIELD_TOP, vertical_points);
    vector_blank();
}

static uint16_t board_block_count(void)
{
    uint8_t row;
    uint8_t col;
    uint16_t count = 0U;

    for (row = 0U; row < BOARD_ROWS; row++)
    {
        for (col = 0U; col < BOARD_COLS; col++)
        {
            if (g_board[row][col] != 0U)
            {
                count++;
            }
        }
    }

    return count;
}

/*
 * Draw the settled pile as a grid of shared edges.  A normal per-cell
 * rectangle draws every common edge twice and performs four blanked moves
 * per block.  These scans merge collinear edges while keeping every cell
 * boundary visible once.
 */
static void draw_board_edges(uint8_t fast)
{
    uint8_t row;
    uint8_t col;

    /* Top edge of each occupied row run. */
    for (row = 0U; row < BOARD_ROWS; row++)
    {
        col = 0U;
        while (col < BOARD_COLS)
        {
            uint8_t start;

            while ((col < BOARD_COLS) && (g_board[row][col] == 0U))
            {
                col++;
            }
            start = col;
            while ((col < BOARD_COLS) && (g_board[row][col] != 0U))
            {
                col++;
            }

            if (col > start)
            {
                float y = FIELD_TOP + (float)row * CELL_SIZE;
                draw_segment(
                    FIELD_LEFT + (float)start * CELL_SIZE,
                    y,
                    FIELD_LEFT + (float)col * CELL_SIZE,
                    y,
                    (uint8_t)(col - start),
                    0U,
                    fast
                );
            }
        }
    }

    /* Bottom exposed edges, merged horizontally. */
    for (row = 0U; row < BOARD_ROWS; row++)
    {
        col = 0U;
        while (col < BOARD_COLS)
        {
            uint8_t start;

            while ((col < BOARD_COLS) &&
                   ((g_board[row][col] == 0U) ||
                    (((row + 1U) < BOARD_ROWS) &&
                     (g_board[row + 1U][col] != 0U))))
            {
                col++;
            }
            start = col;
            while ((col < BOARD_COLS) &&
                   (g_board[row][col] != 0U) &&
                   (((row + 1U) >= BOARD_ROWS) ||
                    (g_board[row + 1U][col] == 0U)))
            {
                col++;
            }

            if (col > start)
            {
                float y = FIELD_TOP + (float)(row + 1U) * CELL_SIZE;
                draw_segment(
                    FIELD_LEFT + (float)start * CELL_SIZE,
                    y,
                    FIELD_LEFT + (float)col * CELL_SIZE,
                    y,
                    (uint8_t)(col - start),
                    0U,
                    fast
                );
            }
        }
    }

    /* Left edge of each occupied column run. */
    for (col = 0U; col < BOARD_COLS; col++)
    {
        row = 0U;
        while (row < BOARD_ROWS)
        {
            uint8_t start;

            while ((row < BOARD_ROWS) && (g_board[row][col] == 0U))
            {
                row++;
            }
            start = row;
            while ((row < BOARD_ROWS) && (g_board[row][col] != 0U))
            {
                row++;
            }

            if (row > start)
            {
                float x = FIELD_LEFT + (float)col * CELL_SIZE;
                draw_segment(
                    x,
                    FIELD_TOP + (float)start * CELL_SIZE,
                    x,
                    FIELD_TOP + (float)row * CELL_SIZE,
                    (uint8_t)(row - start),
                    1U,
                    fast
                );
            }
        }
    }

    /* Right exposed edges, merged vertically. */
    for (col = 0U; col < BOARD_COLS; col++)
    {
        row = 0U;
        while (row < BOARD_ROWS)
        {
            uint8_t start;

            while ((row < BOARD_ROWS) &&
                   ((g_board[row][col] == 0U) ||
                    (((col + 1U) < BOARD_COLS) &&
                     (g_board[row][col + 1U] != 0U))))
            {
                row++;
            }
            start = row;
            while ((row < BOARD_ROWS) &&
                   (g_board[row][col] != 0U) &&
                   (((col + 1U) >= BOARD_COLS) ||
                    (g_board[row][col + 1U] == 0U)))
            {
                row++;
            }

            if (row > start)
            {
                float x = FIELD_LEFT + (float)(col + 1U) * CELL_SIZE;
                draw_segment(
                    x,
                    FIELD_TOP + (float)start * CELL_SIZE,
                    x,
                    FIELD_TOP + (float)row * CELL_SIZE,
                    (uint8_t)(row - start),
                    1U,
                    fast
                );
            }
        }
    }
}

/*
 * Shared grid edges alone cannot distinguish an enclosed empty cell from an
 * occupied cell on a monochrome vector display.  A short diagonal inside
 * every settled block provides an unambiguous occupancy mark at only two or
 * three DAC samples per block.
 */
static void draw_board_markers(uint8_t fast)
{
    uint8_t row;
    uint8_t col;
    float half = (fast != 0U) ? 0.010f : 0.013f;
    uint16_t points = (fast != 0U) ? 2U : 3U;

    for (row = 0U; row < BOARD_ROWS; row++)
    {
        for (col = 0U; col < BOARD_COLS; col++)
        {
            float x;
            float y;

            if (g_board[row][col] == 0U)
            {
                continue;
            }

            x = FIELD_LEFT + ((float)col + 0.5f) * CELL_SIZE;
            y = FIELD_TOP + ((float)row + 0.5f) * CELL_SIZE;

            vector_move_to(x - half, y + half);
            vector_line_to(x + half, y - half, points);
            vector_blank();
        }
    }
}

static void draw_board_block(uint8_t row, uint8_t col, uint8_t fast)
{
    float x = FIELD_LEFT + ((float)col + 0.5f) * CELL_SIZE;
    float y = FIELD_TOP + ((float)row + 0.5f) * CELL_SIZE;
    draw_outline_rect(x, y, BLOCK_SIZE, BLOCK_SIZE, fast);
}

static void draw_current_piece(uint8_t fast)
{
    uint8_t row;
    uint8_t col;

    for (row = 0U; row < 4U; row++)
    {
        for (col = 0U; col < 4U; col++)
        {
            int8_t board_x;
            int8_t board_y;

            if (shape_has_block(g_piece.type, g_piece.rotation,
                                row, col) == 0U)
            {
                continue;
            }

            board_x = (int8_t)(g_piece.x + (int8_t)col);
            board_y = (int8_t)(g_piece.y + (int8_t)row);

            if ((board_y >= 0) && (board_y < BOARD_ROWS) &&
                (board_x >= 0) && (board_x < BOARD_COLS))
            {
                draw_board_block(
                    (uint8_t)board_y,
                    (uint8_t)board_x,
                    fast
                );
            }
        }
    }
}

static void draw_next_piece(uint8_t fast)
{
    uint8_t row;
    uint8_t col;
    const float preview_cell = 0.085f;
    const float start_x = 0.31f;
    const float start_y = 0.26f;

    for (row = 0U; row < 4U; row++)
    {
        for (col = 0U; col < 4U; col++)
        {
            if (shape_has_block(g_next_type, 0U, row, col) != 0U)
            {
                draw_outline_rect(
                    start_x + ((float)col + 0.5f) * preview_cell,
                    start_y + ((float)row + 0.5f) * preview_cell,
                    preview_cell * 0.88f,
                    preview_cell * 0.88f,
                    fast
                );
            }
        }
    }
}

void tetris_render(void)
{
    uint16_t blocks = board_block_count();
    uint8_t fast = (blocks >= FAST_RENDER_BLOCKS) ? 1U : 0U;
    char text[20];

    draw_field_border(fast);
    draw_board_edges(fast);
    draw_board_markers(fast);

    if (g_game_over == 0U)
    {
        draw_current_piece(fast);
    }

    if ((fast == 0U) || (g_render_phase == 0U))
    {
        vector_font_draw_text_center(UI_TEXT_TETRIS, 0.49f, -0.70f, 0.13f);

        snprintf(text, sizeof(text), UI_TEXT_SCORE "%05lu", (unsigned long)g_score);
        vector_font_draw_text(text, 0.03f, -0.38f, 0.10f);

        snprintf(text, sizeof(text), UI_TEXT_LINES "%03u", (unsigned int)g_lines);
        vector_font_draw_text(text, 0.03f, -0.20f, 0.10f);

        snprintf(text, sizeof(text), UI_TEXT_LEVEL "%02u", (unsigned int)g_level);
        vector_font_draw_text(text, 0.03f, -0.02f, 0.10f);
    }

    if ((fast == 0U) || (g_render_phase != 0U))
    {
        vector_font_draw_text(UI_TEXT_NEXT, 0.18f, 0.16f, 0.10f);
        draw_next_piece(fast);
    }

    if (g_game_over != 0U)
    {
        vector_font_draw_text_center(UI_TEXT_GAME_OVER, 0.43f, 0.54f, 0.13f);
    }

    g_render_phase ^= 1U;
    vector_blank();
}
