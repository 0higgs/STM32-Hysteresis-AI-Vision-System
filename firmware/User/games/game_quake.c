#include "game_quake.h"

#include "game_key.h"
#include "bluetooth_control.h"
#include "vector_draw.h"
#include "vector_font.h"

#include "./SYSTEM/sys/sys.h"

#include <stdint.h>
#include <stdio.h>

#define UPDATE_MS               20U
#define MAX_CATCH_UP_STEPS       3U
#define MAX_TARGETS              5U
#define MAX_SPARKS               4U

typedef struct
{
    float x;
    float y;
    float z;
    float spin;
    uint8_t active;
} QuakeTarget;

typedef struct
{
    float x;
    float y;
    uint8_t ticks;
} QuakeSpark;

typedef struct
{
    float x;
    float y;
} Point2;

static QuakeTarget g_targets[MAX_TARGETS];
static QuakeSpark g_sparks[MAX_SPARKS];

static float g_camera_x;
static float g_camera_y;
static uint16_t g_score;
static uint8_t g_lives;
static uint8_t g_rockets;
static uint8_t g_game_over;
static uint8_t g_restart_armed;
static uint8_t g_hit_ticks;
static uint8_t g_shield_ticks;
static uint8_t g_rapid_weapon;
static uint32_t g_last_update;
static uint32_t g_last_spawn;
static uint32_t g_last_fire;
static uint32_t g_rng;

static uint32_t random_next(void)
{
    g_rng = g_rng * 1103515245UL + 12345UL;
    return g_rng;
}

static float random_range(float minimum, float maximum)
{
    float fraction = (float)(random_next() % 1001U) * 0.001f;
    return minimum + (maximum - minimum) * fraction;
}

static uint8_t targets_active(void)
{
    uint8_t i;
    uint8_t count = 0U;

    for (i = 0U; i < MAX_TARGETS; i++)
    {
        if (g_targets[i].active != 0U)
        {
            count++;
        }
    }
    return count;
}

static void add_spark(float x, float y)
{
    uint8_t i;

    for (i = 0U; i < MAX_SPARKS; i++)
    {
        if (g_sparks[i].ticks == 0U)
        {
            g_sparks[i].x = x;
            g_sparks[i].y = y;
            g_sparks[i].ticks = 10U;
            return;
        }
    }
}

static void spawn_target(void)
{
    uint8_t i;

    for (i = 0U; i < MAX_TARGETS; i++)
    {
        if (g_targets[i].active == 0U)
        {
            g_targets[i].x = random_range(-2.2f, 2.2f);
            g_targets[i].y = random_range(-1.35f, 1.35f);
            g_targets[i].z = random_range(6.0f, 8.0f);
            g_targets[i].spin = random_range(-0.018f, 0.018f);
            g_targets[i].active = 1U;
            return;
        }
    }
}

static Point2 project_point(float x, float y, float z)
{
    Point2 point;
    float safe_z = (z < 0.30f) ? 0.30f : z;
    float scale = 0.62f / safe_z;

    point.x = (x - g_camera_x) * scale;
    point.y = (y - g_camera_y) * scale;
    return point;
}

static void lose_life(void)
{
    if (g_shield_ticks != 0U)
    {
        return;
    }

    if (g_lives > 0U)
    {
        g_lives--;
    }
    g_shield_ticks = 45U;

    if (g_lives == 0U)
    {
        g_game_over = 1U;
        g_restart_armed = 0U;
    }
}

static void fire_weapon(void)
{
    uint8_t i;
    int best_index = -1;
    float best_error = 1000.0f;

    for (i = 0U; i < MAX_TARGETS; i++)
    {
        Point2 center;
        float error;

        if (g_targets[i].active == 0U)
        {
            continue;
        }

        center = project_point(
            g_targets[i].x,
            g_targets[i].y,
            g_targets[i].z
        );
        error = center.x * center.x + center.y * center.y;

        if ((error < 0.018f) && (error < best_error))
        {
            best_error = error;
            best_index = (int)i;
        }
    }

    if (best_index >= 0)
    {
        Point2 center = project_point(
            g_targets[best_index].x,
            g_targets[best_index].y,
            g_targets[best_index].z
        );
        add_spark(center.x, center.y);
        g_targets[best_index].active = 0U;
        g_score = (uint16_t)(g_score + 20U);
        g_hit_ticks = 7U;
    }
}

static void fire_rocket(void)
{
    uint8_t i;

    if (g_rockets == 0U)
    {
        return;
    }

    g_rockets--;
    for (i = 0U; i < MAX_TARGETS; i++)
    {
        if ((g_targets[i].active != 0U) &&
            (g_targets[i].z < 4.2f))
        {
            Point2 center = project_point(
                g_targets[i].x,
                g_targets[i].y,
                g_targets[i].z
            );
            add_spark(center.x, center.y);
            g_targets[i].active = 0U;
            g_score = (uint16_t)(g_score + 8U);
        }
    }
    g_hit_ticks = 12U;
}

static void update_camera(void)
{
    if (bluetooth_left_down() != 0U)
    {
        g_camera_x -= 0.060f;
    }
    if (bluetooth_right_down() != 0U)
    {
        g_camera_x += 0.060f;
    }
    if (bluetooth_up_down() != 0U)
    {
        g_camera_y -= 0.055f;
    }
    if (bluetooth_down_down() != 0U)
    {
        g_camera_y += 0.055f;
    }

    if (g_camera_x < -1.15f) g_camera_x = -1.15f;
    if (g_camera_x > 1.15f) g_camera_x = 1.15f;
    if (g_camera_y < -0.75f) g_camera_y = -0.75f;
    if (g_camera_y > 0.75f) g_camera_y = 0.75f;
}

static void update_targets(void)
{
    uint8_t i;
    float speed = 0.035f + (float)(g_score / 120U) * 0.002f;

    if (speed > 0.060f)
    {
        speed = 0.060f;
    }

    for (i = 0U; i < MAX_TARGETS; i++)
    {
        float dx;
        float dy;

        if (g_targets[i].active == 0U)
        {
            continue;
        }

        g_targets[i].z -= speed;
        g_targets[i].x += g_targets[i].spin;
        if ((g_targets[i].x < -2.4f) || (g_targets[i].x > 2.4f))
        {
            g_targets[i].spin = -g_targets[i].spin;
        }

        if (g_targets[i].z <= 0.55f)
        {
            dx = g_targets[i].x - g_camera_x;
            dy = g_targets[i].y - g_camera_y;
            if ((dx * dx + dy * dy) < 0.90f)
            {
                lose_life();
            }
            g_targets[i].active = 0U;
        }
    }

    for (i = 0U; i < MAX_SPARKS; i++)
    {
        if (g_sparks[i].ticks > 0U)
        {
            g_sparks[i].ticks--;
        }
    }

    if (g_hit_ticks > 0U) g_hit_ticks--;
    if (g_shield_ticks > 0U) g_shield_ticks--;
}

void quake_init(void)
{
    uint8_t i;
    uint32_t now = HAL_GetTick();

    for (i = 0U; i < MAX_TARGETS; i++)
    {
        g_targets[i].active = 0U;
    }
    for (i = 0U; i < MAX_SPARKS; i++)
    {
        g_sparks[i].ticks = 0U;
    }

    g_rng = now ^ 0x1996A11DU;
    g_camera_x = 0.0f;
    g_camera_y = 0.0f;
    g_score = 0U;
    g_lives = 4U;
    g_rockets = 3U;
    g_game_over = 0U;
    g_restart_armed = 0U;
    g_hit_ticks = 0U;
    g_shield_ticks = 35U;
    g_rapid_weapon = 0U;
    g_last_update = now;
    g_last_spawn = now - 900U;
    g_last_fire = now - 180U;
}

void quake_update(void)
{
    uint32_t now = HAL_GetTick();
    uint8_t steps = 0U;
    uint8_t fire_event;

    if (g_game_over != 0U)
    {
        if (g_restart_armed == 0U)
        {
            (void)bluetooth_rotate_pressed();
            (void)bluetooth_hard_drop_pressed();
            (void)bluetooth_action1_pressed();

            if ((bluetooth_up_down() == 0U) &&
                (bluetooth_down_down() == 0U) &&
                (bluetooth_left_down() == 0U) &&
                (bluetooth_right_down() == 0U) &&
                (bluetooth_action1_down() == 0U) &&
                (bluetooth_action2_down() == 0U))
            {
                g_restart_armed = 1U;
            }
            return;
        }

        if ((bluetooth_up_pressed() != 0U) ||
            (bluetooth_down_pressed() != 0U) ||
            (bluetooth_left_pressed() != 0U) ||
            (bluetooth_right_pressed() != 0U) ||
            (bluetooth_rotate_pressed() != 0U) ||
            (bluetooth_hard_drop_pressed() != 0U) ||
            (bluetooth_action1_pressed() != 0U) ||
            (bluetooth_action2_pressed() != 0U) ||
            (bluetooth_start_pressed() != 0U))
        {
            quake_init();
        }
        return;
    }

    fire_event = bluetooth_action1_pressed();

    if ((g_rapid_weapon != 0U) &&
        (bluetooth_action1_down() != 0U))
    {
        fire_event = 1U;
    }

    if ((fire_event != 0U) &&
        ((uint32_t)(now - g_last_fire) >=
         ((g_rapid_weapon != 0U) ? 80U : 150U)))
    {
        g_last_fire = now;
        fire_weapon();
    }

    if (bluetooth_rotate_pressed() != 0U)
    {
        g_rapid_weapon = (uint8_t)!g_rapid_weapon;
    }

    if (bluetooth_hard_drop_pressed() != 0U)
    {
        fire_rocket();
    }

    if (bluetooth_action2_pressed() != 0U)
    {
        g_shield_ticks = 45U;
    }

    if ((uint32_t)(now - g_last_spawn) >=
        ((targets_active() < 2U) ? 650U : 1050U))
    {
        g_last_spawn = now;
        spawn_target();
    }

    while (((uint32_t)(now - g_last_update) >= UPDATE_MS) &&
           (steps < MAX_CATCH_UP_STEPS))
    {
        g_last_update += UPDATE_MS;
        update_camera();
        update_targets();
        steps++;

        if (g_game_over != 0U)
        {
            break;
        }
    }

    if ((uint32_t)(now - g_last_update) >= UPDATE_MS * MAX_CATCH_UP_STEPS)
    {
        g_last_update = now;
    }
}

static void draw_cube(const QuakeTarget *target)
{
    Point2 p[8];
    float half = 0.42f;
    float front_z = target->z - half;
    float back_z = target->z + half;
    uint8_t i;
    static const uint8_t edges[12][2] =
    {
        {0,1},{1,2},{2,3},{3,0},
        {4,5},{5,6},{6,7},{7,4},
        {0,4},{1,5},{2,6},{3,7}
    };

    if (front_z < 0.30f)
    {
        front_z = 0.30f;
    }

    p[0] = project_point(target->x - half, target->y - half, front_z);
    p[1] = project_point(target->x + half, target->y - half, front_z);
    p[2] = project_point(target->x + half, target->y + half, front_z);
    p[3] = project_point(target->x - half, target->y + half, front_z);
    p[4] = project_point(target->x - half, target->y - half, back_z);
    p[5] = project_point(target->x + half, target->y - half, back_z);
    p[6] = project_point(target->x + half, target->y + half, back_z);
    p[7] = project_point(target->x - half, target->y + half, back_z);

    for (i = 0U; i < 12U; i++)
    {
        vector_move_to(p[edges[i][0]].x, p[edges[i][0]].y);
        vector_line_to(p[edges[i][1]].x, p[edges[i][1]].y, 3U);
    }
}

static void draw_tunnel_frame(float z)
{
    Point2 top_left = project_point(-2.8f, -1.75f, z);
    Point2 top_right = project_point(2.8f, -1.75f, z);
    Point2 bottom_right = project_point(2.8f, 1.75f, z);
    Point2 bottom_left = project_point(-2.8f, 1.75f, z);

    vector_move_to(top_left.x, top_left.y);
    vector_line_to(top_right.x, top_right.y, 4U);
    vector_line_to(bottom_right.x, bottom_right.y, 4U);
    vector_line_to(bottom_left.x, bottom_left.y, 4U);
    vector_line_to(top_left.x, top_left.y, 4U);
}

void quake_render(void)
{
    uint8_t i;
    char score_text[16];
    char life_text[12];
    char rocket_text[12];

    draw_tunnel_frame(1.8f);
    draw_tunnel_frame(3.0f);
    draw_tunnel_frame(4.8f);
    draw_tunnel_frame(7.2f);

    for (i = 0U; i < MAX_TARGETS; i++)
    {
        if (g_targets[i].active != 0U)
        {
            draw_cube(&g_targets[i]);
        }
    }

    for (i = 0U; i < MAX_SPARKS; i++)
    {
        if (g_sparks[i].ticks != 0U)
        {
            float size = 0.025f + (float)g_sparks[i].ticks * 0.006f;
            vector_move_to(g_sparks[i].x - size, g_sparks[i].y);
            vector_line_to(g_sparks[i].x + size, g_sparks[i].y, 3U);
            vector_move_to(g_sparks[i].x, g_sparks[i].y - size);
            vector_line_to(g_sparks[i].x, g_sparks[i].y + size, 3U);
        }
    }

    vector_move_to(-0.040f, 0.0f);
    vector_line_to(0.040f, 0.0f, 2U);
    vector_move_to(0.0f, -0.040f);
    vector_line_to(0.0f, 0.040f, 2U);

    if (g_hit_ticks != 0U)
    {
        float size = 0.08f + (float)g_hit_ticks * 0.012f;
        vector_move_to(0.0f, -size);
        vector_line_to(size, 0.0f, 3U);
        vector_line_to(0.0f, size, 3U);
        vector_line_to(-size, 0.0f, 3U);
        vector_line_to(0.0f, -size, 3U);
    }

    if (g_shield_ticks != 0U)
    {
        vector_draw_rect(0.0f, 0.0f, 1.78f, 1.08f);
    }

    snprintf(score_text, sizeof(score_text), UI_TEXT_SCORE "%04u", (unsigned int)g_score);
    snprintf(life_text, sizeof(life_text), UI_TEXT_LIFE "%u", (unsigned int)g_lives);
    snprintf(rocket_text, sizeof(rocket_text), UI_TEXT_ROCKET "%u", (unsigned int)g_rockets);
    vector_font_draw_text(score_text, -0.88f, -0.73f, 0.09f);
    vector_font_draw_text(life_text, 0.22f, -0.73f, 0.09f);
    vector_font_draw_text(rocket_text, 0.58f, -0.73f, 0.09f);

    if (g_game_over != 0U)
    {
        vector_font_draw_text_center(UI_TEXT_GAME_OVER, 0.0f, -0.08f, 0.20f);
        vector_font_draw_text_center(UI_TEXT_PRESS_TO_START, 0.0f, 0.20f, 0.12f);
    }

    vector_blank();
}
