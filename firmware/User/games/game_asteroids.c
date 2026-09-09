#include "game_asteroids.h"

#include "game_key.h"
#include "bluetooth_control.h"
#include "vector_draw.h"
#include "vector_font.h"

#include "./SYSTEM/sys/sys.h"

#include <math.h>
#include <stdint.h>
#include <stdio.h>

#define FIELD_LEFT              (-0.93f)
#define FIELD_RIGHT              0.93f
#define FIELD_TOP               (-0.61f)
#define FIELD_BOTTOM             0.62f

#define UPDATE_MS               16U
#define MAX_CATCH_UP_STEPS       3U
#define MAX_ASTEROIDS            9U
#define MAX_BULLETS              7U
#define PI                       3.14159265f

typedef struct
{
    float x;
    float y;
    float vx;
    float vy;
    float radius;
    float angle;
    float spin;
    uint8_t seed;
    uint8_t active;
} Asteroid;

typedef struct
{
    float x;
    float y;
    float vx;
    float vy;
    uint8_t life;
    uint8_t active;
} AsteroidBullet;

static Asteroid g_asteroids[MAX_ASTEROIDS];
static AsteroidBullet g_bullets[MAX_BULLETS];

static float g_ship_x;
static float g_ship_y;
static float g_ship_vx;
static float g_ship_vy;
static float g_ship_angle;
static uint16_t g_score;
static uint8_t g_lives;
static uint8_t g_bombs;
static uint8_t g_wave;
static uint8_t g_game_over;
static uint8_t g_restart_armed;
static uint8_t g_invulnerable_ticks;
static uint32_t g_last_update;
static uint32_t g_last_fire;
static uint32_t g_rng;

static uint32_t random_next(void)
{
    g_rng = g_rng * 1664525UL + 1013904223UL;
    return g_rng;
}

static float random_unit(void)
{
    return (float)(random_next() % 1001U) * 0.001f;
}

static void wrap_position(float *x, float *y)
{
    if (*x < FIELD_LEFT)
    {
        *x = FIELD_RIGHT;
    }
    else if (*x > FIELD_RIGHT)
    {
        *x = FIELD_LEFT;
    }

    if (*y < FIELD_TOP)
    {
        *y = FIELD_BOTTOM;
    }
    else if (*y > FIELD_BOTTOM)
    {
        *y = FIELD_TOP;
    }
}

static uint8_t asteroids_remaining(void)
{
    uint8_t i;
    uint8_t count = 0U;

    for (i = 0U; i < MAX_ASTEROIDS; i++)
    {
        if (g_asteroids[i].active != 0U)
        {
            count++;
        }
    }
    return count;
}

static void create_asteroid(
    float x,
    float y,
    float radius,
    float vx,
    float vy
)
{
    uint8_t i;

    for (i = 0U; i < MAX_ASTEROIDS; i++)
    {
        if (g_asteroids[i].active == 0U)
        {
            g_asteroids[i].x = x;
            g_asteroids[i].y = y;
            g_asteroids[i].vx = vx;
            g_asteroids[i].vy = vy;
            g_asteroids[i].radius = radius;
            g_asteroids[i].angle = random_unit() * PI * 2.0f;
            g_asteroids[i].spin =
                ((random_next() & 1U) != 0U) ? 0.018f : -0.018f;
            g_asteroids[i].seed = (uint8_t)(random_next() & 0xFFU);
            g_asteroids[i].active = 1U;
            return;
        }
    }
}

static void start_wave(void)
{
    uint8_t i;
    uint8_t count = (uint8_t)(3U + g_wave);

    if (count > 6U)
    {
        count = 6U;
    }

    for (i = 0U; i < count; i++)
    {
        float x = (random_next() & 1U) ? FIELD_LEFT + 0.10f : FIELD_RIGHT - 0.10f;
        float y = FIELD_TOP + 0.12f + random_unit() * 0.75f;
        float vx = (0.005f + random_unit() * 0.008f) * ((x < 0.0f) ? 1.0f : -1.0f);
        float vy = -0.006f + random_unit() * 0.012f;

        create_asteroid(x, y, 0.135f, vx, vy);
    }
}

static void reset_ship(void)
{
    g_ship_x = 0.0f;
    g_ship_y = 0.0f;
    g_ship_vx = 0.010f;
    g_ship_vy = 0.0f;
    g_ship_angle = -PI * 0.5f;
    g_invulnerable_ticks = 90U;
}

static void fire_bullet(void)
{
    uint8_t i;

    for (i = 0U; i < MAX_BULLETS; i++)
    {
        if (g_bullets[i].active == 0U)
        {
            float dx = cosf(g_ship_angle);
            float dy = sinf(g_ship_angle);

            g_bullets[i].x = g_ship_x + dx * 0.075f;
            g_bullets[i].y = g_ship_y + dy * 0.075f;
            g_bullets[i].vx = g_ship_vx + dx * 0.040f;
            g_bullets[i].vy = g_ship_vy + dy * 0.040f;
            g_bullets[i].life = 42U;
            g_bullets[i].active = 1U;
            return;
        }
    }
}

static void split_asteroid(uint8_t index)
{
    Asteroid original = g_asteroids[index];

    g_asteroids[index].active = 0U;
    if (original.radius > 0.085f)
    {
        float child = original.radius * 0.62f;
        create_asteroid(
            original.x,
            original.y,
            child,
            original.vx - original.vy * 0.65f,
            original.vy + original.vx * 0.65f
        );
        create_asteroid(
            original.x,
            original.y,
            child,
            original.vx + original.vy * 0.65f,
            original.vy - original.vx * 0.65f
        );
    }
}

static void lose_life(void)
{
    if (g_invulnerable_ticks != 0U)
    {
        return;
    }

    if (g_lives > 0U)
    {
        g_lives--;
    }

    if (g_lives == 0U)
    {
        g_game_over = 1U;
        g_restart_armed = 0U;
    }
    else
    {
        reset_ship();
    }
}

static void update_ship(void)
{
    uint8_t thrust = bluetooth_up_down();

    if (bluetooth_left_down() != 0U)
    {
        g_ship_angle -= 0.075f;
    }
    if (bluetooth_right_down() != 0U)
    {
        g_ship_angle += 0.075f;
    }

    if (thrust != 0U)
    {
        g_ship_vx += cosf(g_ship_angle) * 0.0018f;
        g_ship_vy += sinf(g_ship_angle) * 0.0018f;
    }

    if (bluetooth_down_down() != 0U)
    {
        g_ship_vx *= 0.94f;
        g_ship_vy *= 0.94f;
    }

    g_ship_vx *= 0.994f;
    g_ship_vy *= 0.994f;

    if (g_ship_vx > 0.035f) g_ship_vx = 0.035f;
    if (g_ship_vx < -0.035f) g_ship_vx = -0.035f;
    if (g_ship_vy > 0.035f) g_ship_vy = 0.035f;
    if (g_ship_vy < -0.035f) g_ship_vy = -0.035f;

    g_ship_x += g_ship_vx;
    g_ship_y += g_ship_vy;
    wrap_position(&g_ship_x, &g_ship_y);
}

static void use_bomb(void)
{
    uint8_t i;

    if (g_bombs == 0U)
    {
        return;
    }

    g_bombs--;
    for (i = 0U; i < MAX_ASTEROIDS; i++)
    {
        if (g_asteroids[i].active != 0U)
        {
            g_asteroids[i].active = 0U;
            g_score = (uint16_t)(g_score + 3U);
        }
    }
    g_invulnerable_ticks = 60U;
}

static void update_bullets(void)
{
    uint8_t i;

    for (i = 0U; i < MAX_BULLETS; i++)
    {
        uint8_t a;

        if (g_bullets[i].active == 0U)
        {
            continue;
        }

        g_bullets[i].x += g_bullets[i].vx;
        g_bullets[i].y += g_bullets[i].vy;
        wrap_position(&g_bullets[i].x, &g_bullets[i].y);

        if (g_bullets[i].life > 0U)
        {
            g_bullets[i].life--;
        }
        if (g_bullets[i].life == 0U)
        {
            g_bullets[i].active = 0U;
            continue;
        }

        for (a = 0U; a < MAX_ASTEROIDS; a++)
        {
            float dx;
            float dy;
            float radius;

            if (g_asteroids[a].active == 0U)
            {
                continue;
            }

            dx = g_bullets[i].x - g_asteroids[a].x;
            dy = g_bullets[i].y - g_asteroids[a].y;
            radius = g_asteroids[a].radius;
            if (dx * dx + dy * dy < radius * radius)
            {
                g_bullets[i].active = 0U;
                split_asteroid(a);
                g_score = (uint16_t)(g_score + 10U);
                break;
            }
        }
    }
}

static void update_asteroids(void)
{
    uint8_t i;

    for (i = 0U; i < MAX_ASTEROIDS; i++)
    {
        float dx;
        float dy;
        float hit_radius;

        if (g_asteroids[i].active == 0U)
        {
            continue;
        }

        g_asteroids[i].x += g_asteroids[i].vx;
        g_asteroids[i].y += g_asteroids[i].vy;
        g_asteroids[i].angle += g_asteroids[i].spin;
        wrap_position(&g_asteroids[i].x, &g_asteroids[i].y);

        dx = g_asteroids[i].x - g_ship_x;
        dy = g_asteroids[i].y - g_ship_y;
        hit_radius = g_asteroids[i].radius + 0.045f;

        if ((g_invulnerable_ticks == 0U) &&
            (dx * dx + dy * dy < hit_radius * hit_radius))
        {
            split_asteroid(i);
            lose_life();
        }
    }

    if (g_invulnerable_ticks > 0U)
    {
        g_invulnerable_ticks--;
    }

    if (asteroids_remaining() == 0U)
    {
        g_wave++;
        start_wave();
    }
}

void asteroids_init(void)
{
    uint8_t i;
    uint32_t now = HAL_GetTick();

    for (i = 0U; i < MAX_ASTEROIDS; i++)
    {
        g_asteroids[i].active = 0U;
    }
    for (i = 0U; i < MAX_BULLETS; i++)
    {
        g_bullets[i].active = 0U;
    }

    g_rng = now ^ 0xA57E201DU;
    g_score = 0U;
    g_lives = 3U;
    g_bombs = 3U;
    g_wave = 1U;
    g_game_over = 0U;
    g_restart_armed = 0U;
    reset_ship();
    start_wave();
    g_last_update = now;
    g_last_fire = now - 180U;
}

void asteroids_update(void)
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
            (void)bluetooth_action2_pressed();

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
            asteroids_init();
        }
        return;
    }

    fire_event =
        ((bluetooth_action1_pressed() != 0U) ||
         (bluetooth_action1_down() != 0U)) ? 1U : 0U;

    if ((fire_event != 0U) &&
        ((uint32_t)(now - g_last_fire) >= 140U))
    {
        g_last_fire = now;
        fire_bullet();
    }

    if (bluetooth_action2_pressed() != 0U)
    {
        g_ship_x = -0.70f + random_unit() * 1.40f;
        g_ship_y = -0.45f + random_unit() * 0.90f;
        g_invulnerable_ticks = 45U;
    }

    if (bluetooth_rotate_pressed() != 0U)
    {
        g_invulnerable_ticks = 75U;
    }

    if (bluetooth_hard_drop_pressed() != 0U)
    {
        use_bomb();
    }

    while (((uint32_t)(now - g_last_update) >= UPDATE_MS) &&
           (steps < MAX_CATCH_UP_STEPS))
    {
        g_last_update += UPDATE_MS;
        update_ship();
        update_bullets();
        update_asteroids();
        steps++;
    }

    if ((uint32_t)(now - g_last_update) >= UPDATE_MS * MAX_CATCH_UP_STEPS)
    {
        g_last_update = now;
    }
}

static void draw_ship(void)
{
    float front_x = g_ship_x + cosf(g_ship_angle) * 0.075f;
    float front_y = g_ship_y + sinf(g_ship_angle) * 0.075f;
    float left_x = g_ship_x + cosf(g_ship_angle + 2.45f) * 0.060f;
    float left_y = g_ship_y + sinf(g_ship_angle + 2.45f) * 0.060f;
    float right_x = g_ship_x + cosf(g_ship_angle - 2.45f) * 0.060f;
    float right_y = g_ship_y + sinf(g_ship_angle - 2.45f) * 0.060f;

    vector_move_to(front_x, front_y);
    vector_line_to(left_x, left_y, 3U);
    vector_line_to(
        g_ship_x - cosf(g_ship_angle) * 0.025f,
        g_ship_y - sinf(g_ship_angle) * 0.025f,
        2U
    );
    vector_line_to(right_x, right_y, 2U);
    vector_line_to(front_x, front_y, 3U);
}

static void draw_asteroid(const Asteroid *asteroid)
{
    uint8_t vertex;
    float first_x = 0.0f;
    float first_y = 0.0f;

    for (vertex = 0U; vertex < 7U; vertex++)
    {
        float angle =
            asteroid->angle +
            (float)vertex * (PI * 2.0f / 7.0f);
        float irregular =
            (((asteroid->seed >> (vertex % 6U)) & 1U) != 0U) ?
            1.0f :
            0.76f;
        float x = asteroid->x + cosf(angle) * asteroid->radius * irregular;
        float y = asteroid->y + sinf(angle) * asteroid->radius * irregular;

        if (vertex == 0U)
        {
            first_x = x;
            first_y = y;
            vector_move_to(x, y);
        }
        else
        {
            vector_line_to(x, y, 3U);
        }
    }
    vector_line_to(first_x, first_y, 3U);
}

void asteroids_render(void)
{
    uint8_t i;
    char score_text[16];
    char life_text[12];
    char bomb_text[12];

    vector_draw_border(FIELD_LEFT, FIELD_TOP, FIELD_RIGHT, FIELD_BOTTOM);

    for (i = 0U; i < MAX_ASTEROIDS; i++)
    {
        if (g_asteroids[i].active != 0U)
        {
            draw_asteroid(&g_asteroids[i]);
        }
    }

    for (i = 0U; i < MAX_BULLETS; i++)
    {
        if (g_bullets[i].active != 0U)
        {
            vector_move_to(g_bullets[i].x - 0.008f, g_bullets[i].y);
            vector_line_to(g_bullets[i].x + 0.008f, g_bullets[i].y, 2U);
        }
    }

    draw_ship();
    if (g_invulnerable_ticks != 0U)
    {
        vector_draw_rect(g_ship_x, g_ship_y, 0.18f, 0.16f);
    }

    snprintf(score_text, sizeof(score_text), UI_TEXT_SCORE "%04u", (unsigned int)g_score);
    snprintf(life_text, sizeof(life_text), UI_TEXT_LIFE "%u", (unsigned int)g_lives);
    snprintf(bomb_text, sizeof(bomb_text), UI_TEXT_BOMB "%u", (unsigned int)g_bombs);
    vector_font_draw_text(score_text, -0.88f, -0.73f, 0.09f);
    vector_font_draw_text(life_text, 0.24f, -0.73f, 0.09f);
    vector_font_draw_text(bomb_text, 0.60f, -0.73f, 0.09f);

    if (g_game_over != 0U)
    {
        vector_font_draw_text_center(UI_TEXT_GAME_OVER, 0.0f, -0.07f, 0.20f);
        vector_font_draw_text_center(UI_TEXT_PRESS_TO_START, 0.0f, 0.20f, 0.12f);
    }

    vector_blank();
}
