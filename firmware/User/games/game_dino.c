#include "game_dino.h"

#include "bluetooth_control.h"
#include "vector_draw.h"
#include "vector_font.h"

#include "./SYSTEM/sys/sys.h"

#include <stdint.h>
#include <stdio.h>

#define UPDATE_MS               16U
#define MAX_CATCH_UP_STEPS       3U

#define GROUND_Y                 0.48f
#define DINO_X                  (-0.62f)
#define DINO_WIDTH               0.18f
#define DINO_HEIGHT              0.27f
#define DINO_GROUND_CENTER_Y     (GROUND_Y - DINO_HEIGHT * 0.5f)

#define JUMP_SPEED              (-0.060f)
#define GRAVITY                  0.0030f

#define START_SPEED              0.0140f
#define MAX_SPEED                0.0340f
#define SPEED_RAMP               0.000006f

#define MAX_OBSTACLES            4U

typedef struct
{
    float x;
    float width;
    float height;
    uint8_t active;
    uint8_t double_cactus;
} DinoObstacle;

static DinoObstacle g_obstacles[MAX_OBSTACLES];

static float g_dino_y;
static float g_dino_vy;
static float g_speed;
static float g_spawn_distance;
static float g_next_spawn_distance;
static float g_ground_offset;
static float g_score_fraction;
static uint32_t g_score;
static uint32_t g_last_update;
static uint32_t g_rng;
static uint8_t g_game_over;
static uint8_t g_restart_armed;
static uint8_t g_run_frame;

static uint32_t random_next(void)
{
    g_rng = g_rng * 1664525UL + 1013904223UL;
    return g_rng;
}

static float random_unit(void)
{
    return (float)(random_next() % 1001U) * 0.001f;
}

static uint8_t on_ground(void)
{
    return (g_dino_y >= DINO_GROUND_CENTER_Y - 0.001f) ? 1U : 0U;
}

static void spawn_obstacle(void)
{
    uint8_t i;

    for (i = 0U; i < MAX_OBSTACLES; i++)
    {
        if (g_obstacles[i].active == 0U)
        {
            float kind = random_unit();

            g_obstacles[i].x = 1.08f;
            g_obstacles[i].active = 1U;
            g_obstacles[i].double_cactus =
                ((kind > 0.66f) && (g_speed > 0.019f)) ? 1U : 0U;

            if (kind < 0.34f)
            {
                g_obstacles[i].width = 0.09f;
                g_obstacles[i].height = 0.22f;
            }
            else if (kind < 0.72f)
            {
                g_obstacles[i].width = 0.12f;
                g_obstacles[i].height = 0.30f;
            }
            else
            {
                g_obstacles[i].width = 0.17f;
                g_obstacles[i].height = 0.24f;
            }
            return;
        }
    }
}

static uint8_t obstacle_hits_dino(const DinoObstacle *obstacle)
{
    /*
     * Keep the collision box inside the visible body.  The nose, tail and
     * animated feet must not make a visually clean jump count as a crash.
     */
    float dino_left = DINO_X - DINO_WIDTH * 0.34f;
    float dino_right = DINO_X + DINO_WIDTH * 0.34f;
    float dino_top = g_dino_y - DINO_HEIGHT * 0.38f;
    float dino_bottom = g_dino_y + DINO_HEIGHT * 0.40f;
    float obstacle_left = obstacle->x - obstacle->width * 0.5f;
    float obstacle_right = obstacle->x + obstacle->width * 0.5f;
    float obstacle_top = GROUND_Y - obstacle->height;

    return
        ((dino_right >= obstacle_left) &&
         (dino_left <= obstacle_right) &&
         (dino_bottom >= obstacle_top) &&
         (dino_top <= GROUND_Y)) ? 1U : 0U;
}

static void update_obstacles(void)
{
    uint8_t i;

    for (i = 0U; i < MAX_OBSTACLES; i++)
    {
        if (g_obstacles[i].active == 0U)
        {
            continue;
        }

        g_obstacles[i].x -= g_speed;

        if (g_obstacles[i].x + g_obstacles[i].width < -1.05f)
        {
            g_obstacles[i].active = 0U;
            continue;
        }

        if (obstacle_hits_dino(&g_obstacles[i]) != 0U)
        {
            g_game_over = 1U;
            g_restart_armed = 0U;
        }
    }

    g_spawn_distance += g_speed;
    if (g_spawn_distance >= g_next_spawn_distance)
    {
        spawn_obstacle();
        g_spawn_distance = 0.0f;
        g_next_spawn_distance =
            1.05f + random_unit() * 0.55f + g_speed * 7.0f;
    }
}

static void update_step(void)
{
    uint8_t jump_pressed =
        ((bluetooth_action1_pressed() != 0U) ||
         (bluetooth_action2_pressed() != 0U)) ? 1U : 0U;

    if ((jump_pressed != 0U) && (on_ground() != 0U))
    {
        g_dino_vy = JUMP_SPEED;
    }

    g_dino_vy += GRAVITY;
    g_dino_y += g_dino_vy;

    if (g_dino_y >= DINO_GROUND_CENTER_Y)
    {
        g_dino_y = DINO_GROUND_CENTER_Y;
        g_dino_vy = 0.0f;
    }

    if (g_speed < MAX_SPEED)
    {
        g_speed += SPEED_RAMP;
        if (g_speed > MAX_SPEED)
        {
            g_speed = MAX_SPEED;
        }
    }

    g_ground_offset += g_speed;
    while (g_ground_offset >= 0.18f)
    {
        g_ground_offset -= 0.18f;
    }

    update_obstacles();

    g_score_fraction += g_speed * 3.0f;
    while (g_score_fraction >= 1.0f)
    {
        g_score++;
        g_score_fraction -= 1.0f;
    }

    if (on_ground() != 0U)
    {
        g_run_frame =
            (uint8_t)((HAL_GetTick() / ((g_speed > 0.024f) ? 70U : 95U)) & 1U);
    }
}

static void draw_dino(void)
{
    float x = DINO_X;
    float y = g_dino_y;
    float leg_a;
    float leg_b;

    vector_move_to(x - 0.085f, y + 0.045f);
    vector_line_to(x - 0.060f, y - 0.070f, 5U);
    vector_line_to(x - 0.015f, y - 0.105f, 4U);
    vector_line_to(x + 0.025f, y - 0.105f, 3U);
    vector_line_to(x + 0.025f, y - 0.150f, 3U);
    vector_line_to(x + 0.095f, y - 0.150f, 4U);
    vector_line_to(x + 0.095f, y - 0.090f, 4U);
    vector_line_to(x + 0.050f, y - 0.090f, 3U);
    vector_line_to(x + 0.050f, y + 0.040f, 5U);
    vector_line_to(x - 0.030f, y + 0.070f, 4U);
    vector_line_to(x - 0.085f, y + 0.045f, 4U);

    vector_move_to(x + 0.072f, y - 0.130f);
    vector_line_to(x + 0.078f, y - 0.130f, 2U);

    if (on_ground() == 0U)
    {
        leg_a = 0.035f;
        leg_b = 0.035f;
    }
    else if (g_run_frame == 0U)
    {
        leg_a = 0.075f;
        leg_b = 0.030f;
    }
    else
    {
        leg_a = 0.030f;
        leg_b = 0.075f;
    }

    vector_move_to(x - 0.030f, y + 0.055f);
    vector_line_to(x - 0.050f, y + leg_a, 3U);
    vector_line_to(x - 0.015f, y + leg_a, 2U);
    vector_move_to(x + 0.025f, y + 0.045f);
    vector_line_to(x + 0.040f, y + leg_b, 3U);
    vector_line_to(x + 0.072f, y + leg_b, 2U);
}

static void draw_cactus(const DinoObstacle *obstacle)
{
    float x = obstacle->x;
    float top = GROUND_Y - obstacle->height;
    float half = obstacle->width * 0.25f;

    vector_move_to(x - half, GROUND_Y);
    vector_line_to(x - half, top, 6U);
    vector_line_to(x + half, top, 3U);
    vector_line_to(x + half, GROUND_Y, 6U);

    vector_move_to(x - half, top + obstacle->height * 0.42f);
    vector_line_to(x - half - 0.045f, top + obstacle->height * 0.35f, 3U);
    vector_line_to(x - half - 0.045f, top + obstacle->height * 0.20f, 3U);

    vector_move_to(x + half, top + obstacle->height * 0.58f);
    vector_line_to(x + half + 0.045f, top + obstacle->height * 0.50f, 3U);
    vector_line_to(x + half + 0.045f, top + obstacle->height * 0.34f, 3U);

    if (obstacle->double_cactus != 0U)
    {
        float x2 = x + obstacle->width * 0.46f;
        vector_move_to(x2, GROUND_Y);
        vector_line_to(x2, top + obstacle->height * 0.34f, 5U);
    }
}

void dino_init(void)
{
    uint8_t i;

    for (i = 0U; i < MAX_OBSTACLES; i++)
    {
        g_obstacles[i].active = 0U;
    }

    g_dino_y = DINO_GROUND_CENTER_Y;
    g_dino_vy = 0.0f;
    g_speed = START_SPEED;
    g_spawn_distance = 0.0f;
    g_next_spawn_distance = 1.55f;
    g_ground_offset = 0.0f;
    g_score_fraction = 0.0f;
    g_score = 0U;
    g_game_over = 0U;
    g_restart_armed = 0U;
    g_run_frame = 0U;
    g_last_update = HAL_GetTick();
    g_rng = g_last_update ^ 0xD10A2026UL;
}

void dino_update(void)
{
    uint32_t now;
    uint8_t steps = 0U;

    if (g_game_over != 0U)
    {
        if (g_restart_armed == 0U)
        {
            (void)bluetooth_action1_pressed();
            (void)bluetooth_action2_pressed();

            if ((bluetooth_action1_down() == 0U) &&
                (bluetooth_action2_down() == 0U))
            {
                g_restart_armed = 1U;
            }
            return;
        }

        if ((bluetooth_action1_pressed() != 0U) ||
            (bluetooth_action2_pressed() != 0U))
        {
            dino_init();
        }
        return;
    }

    now = HAL_GetTick();
    while (((uint32_t)(now - g_last_update) >= UPDATE_MS) &&
           (steps < MAX_CATCH_UP_STEPS) &&
           (g_game_over == 0U))
    {
        g_last_update += UPDATE_MS;
        update_step();
        steps++;
    }

    if ((uint32_t)(now - g_last_update) >= UPDATE_MS * MAX_CATCH_UP_STEPS)
    {
        g_last_update = now;
    }
}

void dino_render(void)
{
    char text[24];
    uint8_t i;
    int segment;
    uint16_t speed_value =
        (uint16_t)(((g_speed - START_SPEED) /
                    (MAX_SPEED - START_SPEED)) * 99.0f);

    vector_font_draw_text(UI_TEXT_DINO, -0.92f, -0.67f, 0.11f);
    (void)snprintf(text, sizeof(text), "%05lu", (unsigned long)g_score);
    vector_font_draw_text(text, 0.34f, -0.67f, 0.11f);
    (void)snprintf(text, sizeof(text), UI_TEXT_SPEED "%02u", speed_value);
    vector_font_draw_text(text, -0.10f, -0.67f, 0.08f);

    for (segment = -6; segment <= 6; segment++)
    {
        float x = (float)segment * 0.18f - g_ground_offset;
        vector_move_to(x, GROUND_Y);
        vector_line_to(x + 0.11f, GROUND_Y, 3U);
    }

    draw_dino();

    for (i = 0U; i < MAX_OBSTACLES; i++)
    {
        if (g_obstacles[i].active != 0U)
        {
            draw_cactus(&g_obstacles[i]);
        }
    }

    if (g_game_over != 0U)
    {
        vector_draw_rect(0.0f, -0.02f, 1.14f, 0.35f);
        vector_font_draw_text_center(UI_TEXT_GAME_OVER, 0.0f, -0.10f, 0.18f);
        vector_font_draw_text_center(UI_TEXT_PRESS_TO_START, 0.0f, 0.11f, 0.11f);
    }

    vector_blank();
}
