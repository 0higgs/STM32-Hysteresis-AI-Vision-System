#include "game_pong.h"

#include "game_key.h"
#include "bluetooth_control.h"
#include "vector_draw.h"
#include "vector_font.h"

#include "./SYSTEM/sys/sys.h"

#include <math.h>
#include <stdio.h>
#include <stdint.h>

#define PADDLE_X_LEFT          (-0.84f)
#define PADDLE_X_RIGHT         ( 0.84f)
#define PADDLE_HEIGHT          0.34f
#define PADDLE_HALF_HEIGHT     (PADDLE_HEIGHT * 0.5f)
#define PADDLE_WIDTH           0.035f

#define BALL_SIZE              0.055f

#define PLAYER_SPEED           0.030f
#define AI_SPEED               0.020f

#define BALL_START_VY          0.013f
#define BALL_SPEED             0.024f
#define BALL_MAX_VY            0.020f

#define PLAYER_CONTACT_EFFECT  0.010f
#define PLAYER_MOTION_EFFECT   0.75f
#define AI_CONTACT_EFFECT      0.008f
#define AI_MOTION_EFFECT       0.20f

#define UPDATE_MS              16U
#define MAX_CATCH_UP_STEPS      4U
#define WIN_SCORE              5U
#define SERVE_PAUSE_MS         700U

typedef struct
{
    float x;
    float y;
    float vx;
    float vy;
} PongBall;

static PongBall g_ball;

static float g_player_y;
static float g_ai_y;
static float g_player_vy;
static float g_ai_vy;

static uint8_t g_player_score;
static uint8_t g_ai_score;
static uint8_t g_game_over;
static uint8_t g_restart_armed;
static PongMode g_pong_mode = PONG_MODE_SINGLE_PLAYER;

static uint32_t g_last_update;
static uint32_t g_serve_until;

static int8_t g_next_serve_direction;
static uint8_t g_serve_alternate;

static void set_serve(int direction)
{
    float vy;

    g_ball.x = 0.0f;
    g_ball.y = 0.0f;

    g_serve_alternate = (uint8_t)!g_serve_alternate;

    vy =
        (g_serve_alternate != 0U) ?
        BALL_START_VY :
        -BALL_START_VY;

    g_ball.vy = vy;
    g_ball.vx = sqrtf(BALL_SPEED * BALL_SPEED - vy * vy);

    if (direction < 0)
    {
        g_ball.vx = -g_ball.vx;
    }
}

static void reset_after_score(void)
{
    set_serve(g_next_serve_direction);
    g_next_serve_direction = (int8_t)-g_next_serve_direction;
    g_serve_until = HAL_GetTick() + SERVE_PAUSE_MS;
}

static void score_point(uint8_t player_scored)
{
    if (player_scored != 0U)
    {
        if (g_player_score < 99U)
        {
            g_player_score++;
        }

    }
    else
    {
        if (g_ai_score < 99U)
        {
            g_ai_score++;
        }

    }

    if ((g_player_score >= WIN_SCORE) ||
        (g_ai_score >= WIN_SCORE))
    {
        g_game_over = 1U;
        g_restart_armed = 0U;
        return;
    }

    reset_after_score();
}

static void update_player(void)
{
    float old_y = g_player_y;

    /*
     * Board buttons only:
     * A / KEY0 = up
     * B / WKUP = down
     */
    if ((game_key_a_down() != 0U) ||
        (bluetooth_up_down() != 0U))
    {
        g_player_y -= PLAYER_SPEED;
    }

    if ((game_key_b_down() != 0U) ||
        (bluetooth_down_down() != 0U))
    {
        g_player_y += PLAYER_SPEED;
    }

    if (g_player_y - PADDLE_HALF_HEIGHT < VECTOR_SCREEN_Y_MIN)
    {
        g_player_y = VECTOR_SCREEN_Y_MIN + PADDLE_HALF_HEIGHT;
    }

    if (g_player_y + PADDLE_HALF_HEIGHT > VECTOR_SCREEN_Y_MAX)
    {
        g_player_y = VECTOR_SCREEN_Y_MAX - PADDLE_HALF_HEIGHT;
    }

    g_player_vy = g_player_y - old_y;
}

static void update_right_paddle(void)
{
    float old_y = g_ai_y;

    if (g_pong_mode == PONG_MODE_TWO_PLAYER)
    {
        if (bluetooth_player2_up_down() != 0U)
        {
            g_ai_y -= PLAYER_SPEED;
        }

        if (bluetooth_player2_down_down() != 0U)
        {
            g_ai_y += PLAYER_SPEED;
        }
    }
    else
    {
        if (g_ball.y > g_ai_y + 0.025f)
        {
            g_ai_y += AI_SPEED;
        }
        else if (g_ball.y < g_ai_y - 0.025f)
        {
            g_ai_y -= AI_SPEED;
        }
    }

    if (g_ai_y - PADDLE_HALF_HEIGHT < VECTOR_SCREEN_Y_MIN)
    {
        g_ai_y = VECTOR_SCREEN_Y_MIN + PADDLE_HALF_HEIGHT;
    }

    if (g_ai_y + PADDLE_HALF_HEIGHT > VECTOR_SCREEN_Y_MAX)
    {
        g_ai_y = VECTOR_SCREEN_Y_MAX - PADDLE_HALF_HEIGHT;
    }

    g_ai_vy = g_ai_y - old_y;
}

static void set_bounce_velocity(int8_t horizontal_direction,
                                float desired_vy)
{
    float vx;

    if (desired_vy > BALL_MAX_VY)
    {
        desired_vy = BALL_MAX_VY;
    }
    else if (desired_vy < -BALL_MAX_VY)
    {
        desired_vy = -BALL_MAX_VY;
    }

    /*
     * Recalculate X from a fixed total speed. This keeps the apparent ball
     * speed stable while still allowing contact point and paddle motion to
     * change the outgoing angle.
     */
    vx = sqrtf(BALL_SPEED * BALL_SPEED - desired_vy * desired_vy);

    g_ball.vx = (horizontal_direction >= 0) ? vx : -vx;
    g_ball.vy = desired_vy;
}

static void update_ball(void)
{
    float half = BALL_SIZE * 0.5f;
    float previous_x;
    float previous_y;
    float relative;

    if (g_serve_until != 0U)
    {
        if ((int32_t)(HAL_GetTick() - g_serve_until) < 0)
        {
            return;
        }

        g_serve_until = 0U;
    }

    previous_x = g_ball.x;
    previous_y = g_ball.y;

    g_ball.x += g_ball.vx;
    g_ball.y += g_ball.vy;

    if (g_ball.y - half <= VECTOR_SCREEN_Y_MIN)
    {
        g_ball.y = VECTOR_SCREEN_Y_MIN + half;
        g_ball.vy = fabsf(g_ball.vy);
    }

    if (g_ball.y + half >= VECTOR_SCREEN_Y_MAX)
    {
        g_ball.y = VECTOR_SCREEN_Y_MAX - half;
        g_ball.vy = -fabsf(g_ball.vy);
    }

    if (g_ball.vx < 0.0f)
    {
        float paddle_face = PADDLE_X_LEFT + PADDLE_WIDTH * 0.5f;
        float previous_front = previous_x - half;
        float current_front = g_ball.x - half;

        /*
         * Only collide when the leading edge crosses the paddle's inner
         * face during this physics step. This prevents catches from behind
         * the paddle after the ball has already passed it.
         */
        if ((previous_front >= paddle_face) &&
            (current_front <= paddle_face))
        {
            float travel = previous_front - current_front;
            float t = (travel > 0.0f)
                ? (previous_front - paddle_face) / travel
                : 0.0f;
            float impact_y = previous_y + (g_ball.y - previous_y) * t;

            if ((impact_y + half >=
                 g_player_y - PADDLE_HALF_HEIGHT) &&
                (impact_y - half <=
                 g_player_y + PADDLE_HALF_HEIGHT))
            {
                g_ball.x = paddle_face + half;

                relative =
                    (impact_y - g_player_y) /
                    PADDLE_HALF_HEIGHT;

                set_bounce_velocity(
                    1,
                    g_ball.vy +
                    relative * PLAYER_CONTACT_EFFECT +
                    g_player_vy * PLAYER_MOTION_EFFECT
                );
            }
        }
    }

    if (g_ball.vx > 0.0f)
    {
        float paddle_face = PADDLE_X_RIGHT - PADDLE_WIDTH * 0.5f;
        float previous_front = previous_x + half;
        float current_front = g_ball.x + half;

        if ((previous_front <= paddle_face) &&
            (current_front >= paddle_face))
        {
            float travel = current_front - previous_front;
            float t = (travel > 0.0f)
                ? (paddle_face - previous_front) / travel
                : 0.0f;
            float impact_y = previous_y + (g_ball.y - previous_y) * t;

            if ((impact_y + half >= g_ai_y - PADDLE_HALF_HEIGHT) &&
                (impact_y - half <= g_ai_y + PADDLE_HALF_HEIGHT))
            {
                g_ball.x = paddle_face - half;

                relative =
                    (impact_y - g_ai_y) /
                    PADDLE_HALF_HEIGHT;

                set_bounce_velocity(
                    -1,
                    g_ball.vy +
                    relative *
                    ((g_pong_mode == PONG_MODE_TWO_PLAYER) ?
                        PLAYER_CONTACT_EFFECT :
                        AI_CONTACT_EFFECT) +
                    g_ai_vy *
                    ((g_pong_mode == PONG_MODE_TWO_PLAYER) ?
                        PLAYER_MOTION_EFFECT :
                        AI_MOTION_EFFECT)
                );
            }
        }
    }

    if (g_ball.x < VECTOR_SCREEN_X_MIN - 0.12f)
    {
        score_point(0U);
        return;
    }

    if (g_ball.x > VECTOR_SCREEN_X_MAX + 0.12f)
    {
        score_point(1U);
    }
}

void pong_set_mode(PongMode mode)
{
    if (mode >= PONG_MODE_COUNT)
    {
        mode = PONG_MODE_SINGLE_PLAYER;
    }

    g_pong_mode = mode;
}

void pong_init(void)
{
    g_player_y = 0.0f;
    g_ai_y = 0.0f;
    g_player_vy = 0.0f;
    g_ai_vy = 0.0f;

    g_player_score = 0U;
    g_ai_score = 0U;
    g_game_over = 0U;
    g_restart_armed = 0U;

    /* First serve travels toward the player, then serve sides alternate. */
    g_next_serve_direction = -1;
    g_serve_alternate = 0U;

    set_serve(g_next_serve_direction);
    g_next_serve_direction = 1;

    g_serve_until = HAL_GetTick() + SERVE_PAUSE_MS;
    g_last_update = HAL_GetTick();
}

void pong_update(void)
{
    uint32_t now = HAL_GetTick();
    uint8_t steps = 0U;
    uint8_t action1 = bluetooth_action1_pressed();
    uint8_t start = bluetooth_start_pressed();

    (void)bluetooth_action2_pressed();

    if (g_game_over != 0U)
    {
        /*
         * Movement uses the held state, so a press event can remain queued
         * when the winning point is scored. Discard it and require both
         * buttons to be released before accepting a fresh restart press.
         */
        if (g_restart_armed == 0U)
        {
            (void)game_key_a_pressed();
            (void)game_key_b_pressed();
            (void)bluetooth_player2_up_pressed();
            (void)bluetooth_player2_down_pressed();

            if ((game_key_a_down() == 0U) &&
                (game_key_b_down() == 0U) &&
                (bluetooth_up_down() == 0U) &&
                (bluetooth_down_down() == 0U) &&
                (bluetooth_player2_up_down() == 0U) &&
                (bluetooth_player2_down_down() == 0U))
            {
                g_restart_armed = 1U;
            }

            return;
        }

        if ((game_key_a_pressed() != 0U) ||
            (game_key_b_pressed() != 0U) ||
            (action1 != 0U) ||
            (start != 0U))
        {
            pong_init();
        }

        return;
    }

    /* Phone A or START skips the short serve countdown. */
    if (((action1 != 0U) || (start != 0U)) &&
        (g_serve_until != 0U))
    {
        g_serve_until = 0U;
    }

    while (((uint32_t)(now - g_last_update) >= UPDATE_MS) &&
           (steps < MAX_CATCH_UP_STEPS))
    {
        g_last_update += UPDATE_MS;
        steps++;

        update_player();
        update_right_paddle();
        update_ball();

        if (g_game_over != 0U)
        {
            break;
        }
    }

    /*
     * Avoid an unbounded catch-up loop after a debugger halt or long stall.
     * Normal rendering delays are absorbed by the fixed 16 ms steps above.
     */
    if ((steps >= MAX_CATCH_UP_STEPS) &&
        ((uint32_t)(now - g_last_update) >= UPDATE_MS))
    {
        g_last_update = now;
    }
}

void pong_render(void)
{
    char score_text[12];

    vector_draw_border(
        VECTOR_SCREEN_X_MIN,
        VECTOR_SCREEN_Y_MIN,
        VECTOR_SCREEN_X_MAX,
        VECTOR_SCREEN_Y_MAX
    );

    snprintf(
        score_text,
        sizeof(score_text),
        "%u:%u",
        (unsigned int)g_player_score,
        (unsigned int)g_ai_score
    );

    vector_font_draw_text_center(
        score_text,
        0.0f,
        -0.69f,
        0.13f
    );

    vector_draw_rect(
        PADDLE_X_LEFT,
        g_player_y,
        PADDLE_WIDTH,
        PADDLE_HEIGHT
    );

    vector_draw_rect(
        g_ball.x,
        g_ball.y,
        BALL_SIZE,
        BALL_SIZE
    );

    vector_draw_rect(
        PADDLE_X_RIGHT,
        g_ai_y,
        PADDLE_WIDTH,
        PADDLE_HEIGHT
    );

    if (g_game_over != 0U)
    {
        vector_font_draw_text_center(
            UI_TEXT_GAME_OVER,
            0.0f,
            -0.20f,
            0.22f
        );

        if (g_player_score > g_ai_score)
        {
            vector_font_draw_text_center(
                (g_pong_mode == PONG_MODE_TWO_PLAYER) ?
                    UI_TEXT_LEFT_SIDE_WINS :
                    UI_TEXT_PLAYER_WINS,
                0.0f,
                0.10f,
                0.18f
            );
        }
        else
        {
            vector_font_draw_text_center(
                (g_pong_mode == PONG_MODE_TWO_PLAYER) ?
                    UI_TEXT_RIGHT_SIDE_WINS :
                    UI_TEXT_CPU_WINS,
                0.0f,
                0.10f,
                0.18f
            );
        }

        vector_font_draw_text_center(
            UI_TEXT_PRESS_TO_START,
            0.0f,
            0.38f,
            0.12f
        );
    }

    vector_blank();
}
