#include "game_snake.h"

#include "game_key.h"
#include "bluetooth_control.h"
#include "vector_draw.h"
#include "vector_font.h"

#include "./SYSTEM/sys/sys.h"

#include <stdlib.h>
#include <stdint.h>
#include <stdio.h>

#define SNAKE_MAX_LENGTH     64U
#define SNAKE_MOVE_MS        125U

#define FIELD_LEFT           (-0.90f)
#define FIELD_RIGHT          ( 0.90f)
#define FIELD_TOP            (-0.60f)
#define FIELD_BOTTOM         ( 0.60f)

#define GRID_STEP            0.05f
#define GRID_X0              (-0.85f)
#define GRID_Y0              (-0.55f)
#define GRID_COLS            35
#define GRID_ROWS            23

typedef struct
{
    int8_t col;
    int8_t row;
} SnakeCell;

static SnakeCell g_snake[SNAKE_MAX_LENGTH];
static SnakeCell g_food;

static uint8_t g_length;
static uint16_t g_score;
static uint8_t g_direction;
static uint8_t g_game_over;
static uint8_t g_restart_armed;
static uint32_t g_last_move;

static uint8_t cell_equal(SnakeCell a, SnakeCell b)
{
    return ((a.col == b.col) && (a.row == b.row)) ? 1U : 0U;
}

static float cell_x(int8_t col)
{
    return GRID_X0 + (float)col * GRID_STEP;
}

static float cell_y(int8_t row)
{
    return GRID_Y0 + (float)row * GRID_STEP;
}

static uint8_t cell_on_snake(SnakeCell cell)
{
    uint8_t i;

    for (i = 0U; i < g_length; i++)
    {
        if (cell_equal(cell, g_snake[i]) != 0U)
        {
            return 1U;
        }
    }

    return 0U;
}

static void spawn_food(void)
{
    uint16_t attempts;

    for (attempts = 0U; attempts < 200U; attempts++)
    {
        SnakeCell candidate;

        candidate.col = (int8_t)(rand() % GRID_COLS);
        candidate.row = (int8_t)(rand() % GRID_ROWS);

        if (cell_on_snake(candidate) == 0U)
        {
            g_food = candidate;
            return;
        }
    }

    g_food.col = 28;
    g_food.row = 11;
}

static void turn_left(void)
{
    g_direction = (uint8_t)((g_direction + 3U) & 0x03U);
}

static void turn_right(void)
{
    g_direction = (uint8_t)((g_direction + 1U) & 0x03U);
}

static void set_direction(uint8_t direction)
{
    /* A snake may turn 90 degrees, but never reverse into itself. */
    if (((g_direction + 2U) & 0x03U) != direction)
    {
        g_direction = direction;
    }
}

static void move_once(void)
{
    SnakeCell old_tail;
    SnakeCell new_head;
    uint8_t i;
    uint8_t ate_food = 0U;

    old_tail = g_snake[g_length - 1U];
    new_head = g_snake[0];

    switch (g_direction)
    {
        case 0U:
            new_head.row--;
            break;

        case 1U:
            new_head.col++;
            break;

        case 2U:
            new_head.row++;
            break;

        case 3U:
        default:
            new_head.col--;
            break;
    }

    if ((new_head.col < 0) ||
        (new_head.col >= GRID_COLS) ||
        (new_head.row < 0) ||
        (new_head.row >= GRID_ROWS))
    {
        g_game_over = 1U;
        return;
    }

    /*
     * Check against current body. The tail cell is allowed only when it will
     * move away this frame and no food is being eaten there.
     */
    for (i = 0U; i < g_length - 1U; i++)
    {
        if (cell_equal(new_head, g_snake[i]) != 0U)
        {
            g_game_over = 1U;
            return;
        }
    }

    for (i = g_length - 1U; i > 0U; i--)
    {
        g_snake[i] = g_snake[i - 1U];
    }

    g_snake[0] = new_head;

    if (cell_equal(new_head, g_food) != 0U)
    {
        ate_food = 1U;
    }

    if (ate_food != 0U)
    {
        if (g_length < SNAKE_MAX_LENGTH)
        {
            g_snake[g_length] = old_tail;
            g_length++;
        }

        g_score++;
        spawn_food();
    }
}

void snake_init(void)
{
    uint8_t i;

    g_length = 5U;
    g_score = 0U;
    g_direction = 1U; /* right */
    g_game_over = 0U;
    g_restart_armed = 0U;

    for (i = 0U; i < g_length; i++)
    {
        g_snake[i].col = (int8_t)(10 - i);
        g_snake[i].row = 11;
    }

    srand((unsigned int)(HAL_GetTick() ^ 0x5A17U));
    spawn_food();

    g_last_move = HAL_GetTick();
}

void snake_update(void)
{
    uint32_t now = HAL_GetTick();
    uint32_t move_interval = SNAKE_MOVE_MS;
    uint8_t up = bluetooth_up_pressed();
    uint8_t down = bluetooth_down_pressed();
    uint8_t left = bluetooth_left_pressed();
    uint8_t right = bluetooth_right_pressed();
    uint8_t action1 = bluetooth_action1_pressed();
    uint8_t action2 = bluetooth_action2_pressed();
    uint8_t start = bluetooth_start_pressed();

    if (g_game_over != 0U)
    {
        if (g_restart_armed == 0U)
        {
            /*
             * Clear any turn event left from the final movement and wait
             * until both controls are physically released.
             */
            (void)game_key_a_pressed();
            (void)game_key_b_pressed();

            if ((game_key_a_down() == 0U) &&
                (game_key_b_down() == 0U))
            {
                g_restart_armed = 1U;
            }

            return;
        }

        if ((game_key_a_pressed() != 0U) ||
            (game_key_b_pressed() != 0U) ||
            (up != 0U) || (down != 0U) ||
            (left != 0U) || (right != 0U) ||
            (action1 != 0U) || (action2 != 0U) ||
            (start != 0U))
        {
            snake_init();
        }

        return;
    }

    /*
     * Board buttons only:
     * A / KEY0 = turn left
     * B / WKUP = turn right
     */
    if (game_key_a_pressed() != 0U)
    {
        turn_left();
    }

    if (game_key_b_pressed() != 0U)
    {
        turn_right();
    }

    /* The phone D-pad selects an absolute direction. */
    if (up != 0U)
    {
        set_direction(0U);
    }
    else if (right != 0U)
    {
        set_direction(1U);
    }
    else if (down != 0U)
    {
        set_direction(2U);
    }
    else if (left != 0U)
    {
        set_direction(3U);
    }

    /* Hold phone B for a temporary speed boost. */
    if (bluetooth_action2_down() != 0U)
    {
        move_interval = SNAKE_MOVE_MS / 2U;
    }

    if ((uint32_t)(now - g_last_move) < move_interval)
    {
        return;
    }

    g_last_move = now;
    move_once();
}

void snake_render(void)
{
    uint8_t i;
    char score_text[20];

    vector_draw_border(
        FIELD_LEFT,
        FIELD_TOP,
        FIELD_RIGHT,
        FIELD_BOTTOM
    );

    /*
     * Draw one continuous polyline through all snake cell centers.
     * Z blanking is used before moving to the head.
     */
    vector_move_to(
        cell_x(g_snake[0].col),
        cell_y(g_snake[0].row)
    );

    for (i = 1U; i < g_length; i++)
    {
        vector_line_to(
            cell_x(g_snake[i].col),
            cell_y(g_snake[i].row),
            5U
        );
    }

    /* Small head marker. */
    vector_draw_rect(
        cell_x(g_snake[0].col),
        cell_y(g_snake[0].row),
        0.045f,
        0.045f
    );

    /* Food. */
    vector_draw_rect(
        cell_x(g_food.col),
        cell_y(g_food.row),
        0.065f,
        0.065f
    );

    snprintf(
        score_text,
        sizeof(score_text),
        UI_TEXT_SCORE " %03u",
        (unsigned int)g_score
    );

    vector_font_draw_text_center(
        score_text,
        0.0f,
        -0.73f,
        0.105f
    );

    if (g_game_over != 0U)
    {
        vector_font_draw_text_center(
            UI_TEXT_GAME_OVER,
            0.0f,
            -0.10f,
            0.22f
        );

        vector_font_draw_text_center(
            UI_TEXT_PRESS_TO_START,
            0.0f,
            0.22f,
            0.13f
        );
    }

    vector_blank();
}
