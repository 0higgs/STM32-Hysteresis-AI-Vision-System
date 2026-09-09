#include "game_breakout.h"

#include "game_key.h"
#include "bluetooth_control.h"
#include "vector_draw.h"
#include "vector_font.h"

#include "./SYSTEM/sys/sys.h"

#include <stdint.h>
#include <math.h>
#include <stdio.h>

#define FIELD_LEFT          (-0.92f)
#define FIELD_RIGHT         ( 0.92f)
#define FIELD_TOP           (-0.62f)
#define FIELD_BOTTOM        ( 0.62f)

#define PADDLE_Y             0.50f
#define PADDLE_WIDTH         0.34f
#define PADDLE_HEIGHT        0.045f
#define PADDLE_SPEED         0.035f

#define BALL_SIZE            0.045f
#define BALL_START_VX        0.012f
#define BALL_START_VY       (-0.014f)

#define UPDATE_MS            16U

#define BRICK_ROWS           3U
#define BRICK_COLS           6U
#define BRICK_WIDTH          0.225f
#define BRICK_HEIGHT         0.085f
#define BRICK_X_START       (-0.625f)
#define BRICK_X_STEP         0.250f
#define BRICK_Y_START       (-0.46f)
#define BRICK_Y_STEP         0.135f

typedef struct
{
    float x;
    float y;
    float vx;
    float vy;
} BreakoutBall;

static uint8_t g_bricks[BRICK_ROWS][BRICK_COLS];

static BreakoutBall g_ball;
static float g_paddle_x;

static uint16_t g_score;
static uint8_t g_lives;
static uint8_t g_game_over;
static uint8_t g_win;
static uint8_t g_restart_armed;

static uint32_t g_last_update;

static void reset_ball(void)
{
    g_ball.x = 0.0f;
    g_ball.y = 0.23f;
    g_ball.vx = BALL_START_VX;
    g_ball.vy = BALL_START_VY;
}

static uint8_t bricks_remaining(void)
{
    uint8_t r;
    uint8_t c;
    uint8_t count = 0U;

    for (r = 0U; r < BRICK_ROWS; r++)
    {
        for (c = 0U; c < BRICK_COLS; c++)
        {
            if (g_bricks[r][c] != 0U)
            {
                count++;
            }
        }
    }

    return count;
}

static void update_paddle(void)
{
    float speed = PADDLE_SPEED;

    /* Hold phone B for faster paddle travel. */
    if (bluetooth_action2_down() != 0U)
    {
        speed *= 1.55f;
    }

    if ((game_key_a_down() != 0U) ||
        (bluetooth_left_down() != 0U))
    {
        g_paddle_x -= speed;
    }

    if ((game_key_b_down() != 0U) ||
        (bluetooth_right_down() != 0U))
    {
        g_paddle_x += speed;
    }

    if (g_paddle_x - PADDLE_WIDTH * 0.5f < FIELD_LEFT)
    {
        g_paddle_x = FIELD_LEFT + PADDLE_WIDTH * 0.5f;
    }

    if (g_paddle_x + PADDLE_WIDTH * 0.5f > FIELD_RIGHT)
    {
        g_paddle_x = FIELD_RIGHT - PADDLE_WIDTH * 0.5f;
    }
}

static void check_brick_collision(void)
{
    uint8_t r;
    uint8_t c;
    float half_ball = BALL_SIZE * 0.5f;

    for (r = 0U; r < BRICK_ROWS; r++)
    {
        for (c = 0U; c < BRICK_COLS; c++)
        {
            float bx;
            float by;

            if (g_bricks[r][c] == 0U)
            {
                continue;
            }

            bx = BRICK_X_START + (float)c * BRICK_X_STEP;
            by = BRICK_Y_START + (float)r * BRICK_Y_STEP;

            if ((g_ball.x + half_ball >= bx - BRICK_WIDTH * 0.5f) &&
                (g_ball.x - half_ball <= bx + BRICK_WIDTH * 0.5f) &&
                (g_ball.y + half_ball >= by - BRICK_HEIGHT * 0.5f) &&
                (g_ball.y - half_ball <= by + BRICK_HEIGHT * 0.5f))
            {
                g_bricks[r][c] = 0U;
                g_score += 10U;
                g_ball.vy = -g_ball.vy;

                if (bricks_remaining() == 0U)
                {
                    g_win = 1U;
                    g_game_over = 1U;
                }

                return;
            }
        }
    }
}

static void update_ball(void)
{
    float half = BALL_SIZE * 0.5f;
    float paddle_top = PADDLE_Y - PADDLE_HEIGHT * 0.5f;

    g_ball.x += g_ball.vx;
    g_ball.y += g_ball.vy;

    if (g_ball.x - half <= FIELD_LEFT)
    {
        g_ball.x = FIELD_LEFT + half;
        g_ball.vx = fabsf(g_ball.vx);
    }

    if (g_ball.x + half >= FIELD_RIGHT)
    {
        g_ball.x = FIELD_RIGHT - half;
        g_ball.vx = -fabsf(g_ball.vx);
    }

    if (g_ball.y - half <= FIELD_TOP)
    {
        g_ball.y = FIELD_TOP + half;
        g_ball.vy = fabsf(g_ball.vy);
    }

    if ((g_ball.vy > 0.0f) &&
        (g_ball.y + half >= paddle_top) &&
        (g_ball.y - half <= PADDLE_Y + PADDLE_HEIGHT * 0.5f) &&
        (g_ball.x + half >= g_paddle_x - PADDLE_WIDTH * 0.5f) &&
        (g_ball.x - half <= g_paddle_x + PADDLE_WIDTH * 0.5f))
    {
        float relative =
            (g_ball.x - g_paddle_x) /
            (PADDLE_WIDTH * 0.5f);

        g_ball.y = paddle_top - half;
        g_ball.vy = -fabsf(g_ball.vy);
        g_ball.vx += relative * 0.006f;

        if (g_ball.vx > 0.025f)
        {
            g_ball.vx = 0.025f;
        }
        else if (g_ball.vx < -0.025f)
        {
            g_ball.vx = -0.025f;
        }
    }

    check_brick_collision();

    if (g_ball.y - half > FIELD_BOTTOM)
    {
        if (g_lives > 0U)
        {
            g_lives--;
        }

        if (g_lives == 0U)
        {
            g_game_over = 1U;
            g_win = 0U;
        }
        else
        {
            reset_ball();
        }
    }
}

void breakout_init(void)
{
    uint8_t r;
    uint8_t c;

    for (r = 0U; r < BRICK_ROWS; r++)
    {
        for (c = 0U; c < BRICK_COLS; c++)
        {
            g_bricks[r][c] = 1U;
        }
    }

    g_paddle_x = 0.0f;
    g_score = 0U;
    g_lives = 3U;
    g_game_over = 0U;
    g_win = 0U;
    g_restart_armed = 0U;

    reset_ball();
    g_last_update = HAL_GetTick();
}

void breakout_update(void)
{
    uint32_t now = HAL_GetTick();
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
             * Paddle movement uses held states, leaving press events queued.
             * Discard them and require a complete release before restart.
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
            (left != 0U) || (right != 0U) ||
            (action1 != 0U) || (action2 != 0U) ||
            (start != 0U))
        {
            breakout_init();
        }

        return;
    }

    /* Phone A is a quick paddle recenter action. */
    if (action1 != 0U)
    {
        g_paddle_x = 0.0f;
    }

    if ((uint32_t)(now - g_last_update) < UPDATE_MS)
    {
        return;
    }

    g_last_update = now;

    update_paddle();
    update_ball();
}

void breakout_render(void)
{
    uint8_t r;
    uint8_t c;
    char score_text[20];
    char life_text[12];

    vector_draw_border(
        FIELD_LEFT,
        FIELD_TOP,
        FIELD_RIGHT,
        FIELD_BOTTOM
    );

    for (r = 0U; r < BRICK_ROWS; r++)
    {
        for (c = 0U; c < BRICK_COLS; c++)
        {
            if (g_bricks[r][c] != 0U)
            {
                vector_draw_rect(
                    BRICK_X_START + (float)c * BRICK_X_STEP,
                    BRICK_Y_START + (float)r * BRICK_Y_STEP,
                    BRICK_WIDTH,
                    BRICK_HEIGHT
                );
            }
        }
    }

    vector_draw_rect(
        g_paddle_x,
        PADDLE_Y,
        PADDLE_WIDTH,
        PADDLE_HEIGHT
    );

    vector_draw_rect(
        g_ball.x,
        g_ball.y,
        BALL_SIZE,
        BALL_SIZE
    );

    snprintf(
        score_text,
        sizeof(score_text),
        UI_TEXT_SCORE " %03u",
        (unsigned int)g_score
    );

    snprintf(
        life_text,
        sizeof(life_text),
        UI_TEXT_LIFE " %u",
        (unsigned int)g_lives
    );

    vector_font_draw_text(
        score_text,
        -0.88f,
        -0.73f,
        0.095f
    );

    vector_font_draw_text(
        life_text,
        0.37f,
        -0.73f,
        0.095f
    );

    if (g_game_over != 0U)
    {
        vector_font_draw_text_center(
            g_win ? UI_TEXT_PLAYER_WINS : UI_TEXT_GAME_OVER,
            0.0f,
            0.02f,
            0.22f
        );

        vector_font_draw_text_center(
            UI_TEXT_PRESS_TO_START,
            0.0f,
            0.28f,
            0.12f
        );
    }

    vector_blank();
}
