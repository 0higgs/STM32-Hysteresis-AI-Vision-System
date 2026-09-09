#include "game_doom.h"

#include "game_key.h"
#include "bluetooth_control.h"
#include "vector_draw.h"
#include "vector_font.h"

#include "./SYSTEM/sys/sys.h"

#include <math.h>
#include <stdint.h>
#include <stdio.h>

#define MAP_WIDTH                8
#define MAP_HEIGHT               8
#define RAY_COUNT               17U
#define ENEMY_COUNT              4U
#define UPDATE_MS               24U
#define MAX_CATCH_UP_STEPS       3U
#define PI                       3.14159265f
#define FOV                      1.10f

typedef struct
{
    float x;
    float y;
    uint8_t active;
} DoomEnemy;

static const uint8_t g_map[MAP_HEIGHT][MAP_WIDTH] =
{
    {1,1,1,1,1,1,1,1},
    {1,0,0,0,0,0,0,1},
    {1,0,1,1,1,0,0,1},
    {1,0,0,0,1,0,0,1},
    {1,1,0,0,1,0,0,1},
    {1,0,0,0,0,0,0,1},
    {1,0,1,0,0,1,0,1},
    {1,1,1,1,1,1,1,1}
};

static DoomEnemy g_enemies[ENEMY_COUNT];
static float g_player_x;
static float g_player_y;
static float g_player_angle;
static uint16_t g_score;
static uint8_t g_lives;
static uint8_t g_level;
static uint8_t g_game_over;
static uint8_t g_restart_armed;
static uint8_t g_invulnerable_ticks;
static uint8_t g_muzzle_ticks;
static uint32_t g_last_update;
static uint32_t g_last_fire;

static uint8_t map_is_wall(float x, float y)
{
    int ix = (int)x;
    int iy = (int)y;

    if ((ix < 0) || (ix >= MAP_WIDTH) ||
        (iy < 0) || (iy >= MAP_HEIGHT))
    {
        return 1U;
    }
    return g_map[iy][ix];
}

static void reset_player(void)
{
    g_player_x = 1.50f;
    g_player_y = 1.50f;
    g_player_angle = 0.0f;
    g_invulnerable_ticks = 70U;
}

static void spawn_enemies(void)
{
    static const float positions[ENEMY_COUNT][2] =
    {
        {5.55f, 1.55f},
        {6.45f, 3.55f},
        {2.55f, 5.45f},
        {5.35f, 5.45f}
    };
    uint8_t i;

    for (i = 0U; i < ENEMY_COUNT; i++)
    {
        g_enemies[i].x = positions[i][0];
        g_enemies[i].y = positions[i][1];
        g_enemies[i].active = 1U;
    }
}

static uint8_t enemies_remaining(void)
{
    uint8_t i;
    uint8_t count = 0U;

    for (i = 0U; i < ENEMY_COUNT; i++)
    {
        if (g_enemies[i].active != 0U)
        {
            count++;
        }
    }
    return count;
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
        reset_player();
    }
}

static void move_player(float amount)
{
    float next_x = g_player_x + cosf(g_player_angle) * amount;
    float next_y = g_player_y + sinf(g_player_angle) * amount;

    if (map_is_wall(next_x, g_player_y) == 0U)
    {
        g_player_x = next_x;
    }
    if (map_is_wall(g_player_x, next_y) == 0U)
    {
        g_player_y = next_y;
    }
}

static void strafe_player(float amount)
{
    float next_x = g_player_x + cosf(g_player_angle + PI * 0.5f) * amount;
    float next_y = g_player_y + sinf(g_player_angle + PI * 0.5f) * amount;

    if (map_is_wall(next_x, g_player_y) == 0U)
    {
        g_player_x = next_x;
    }
    if (map_is_wall(g_player_x, next_y) == 0U)
    {
        g_player_y = next_y;
    }
}

static void update_player(void)
{
    float move_speed =
        (bluetooth_action2_down() != 0U) ? 0.085f : 0.055f;

    if (bluetooth_left_down() != 0U)
    {
        g_player_angle -= 0.075f;
    }
    if (bluetooth_right_down() != 0U)
    {
        g_player_angle += 0.075f;
    }

    if (bluetooth_up_down() != 0U)
    {
        move_player(move_speed);
    }
    if (bluetooth_down_down() != 0U)
    {
        move_player(-move_speed * 0.82f);
    }

    if (g_player_angle > PI) g_player_angle -= PI * 2.0f;
    if (g_player_angle < -PI) g_player_angle += PI * 2.0f;
}

static void update_enemies(void)
{
    uint8_t i;
    float speed = 0.006f + (float)g_level * 0.0008f;

    if (speed > 0.012f)
    {
        speed = 0.012f;
    }

    for (i = 0U; i < ENEMY_COUNT; i++)
    {
        float dx;
        float dy;
        float distance_sq;
        float distance;
        float next_x;
        float next_y;

        if (g_enemies[i].active == 0U)
        {
            continue;
        }

        dx = g_player_x - g_enemies[i].x;
        dy = g_player_y - g_enemies[i].y;
        distance_sq = dx * dx + dy * dy;

        if (distance_sq < 0.15f)
        {
            lose_life();
            g_enemies[i].active = 0U;
            continue;
        }

        if (distance_sq > 0.25f)
        {
            distance = sqrtf(distance_sq);
            next_x = g_enemies[i].x + dx / distance * speed;
            next_y = g_enemies[i].y + dy / distance * speed;

            if (map_is_wall(next_x, g_enemies[i].y) == 0U)
            {
                g_enemies[i].x = next_x;
            }
            if (map_is_wall(g_enemies[i].x, next_y) == 0U)
            {
                g_enemies[i].y = next_y;
            }
        }
    }

    if (g_invulnerable_ticks > 0U)
    {
        g_invulnerable_ticks--;
    }
    if (g_muzzle_ticks > 0U)
    {
        g_muzzle_ticks--;
    }

    if (enemies_remaining() == 0U)
    {
        g_level++;
        spawn_enemies();
        reset_player();
    }
}

static void fire_weapon(void)
{
    uint8_t i;
    int best_index = -1;
    float best_forward = 1000.0f;
    float view_cos = cosf(g_player_angle);
    float view_sin = sinf(g_player_angle);

    for (i = 0U; i < ENEMY_COUNT; i++)
    {
        float dx;
        float dy;
        float forward;
        float side;

        if (g_enemies[i].active == 0U)
        {
            continue;
        }

        dx = g_enemies[i].x - g_player_x;
        dy = g_enemies[i].y - g_player_y;
        forward = dx * view_cos + dy * view_sin;
        side = -dx * view_sin + dy * view_cos;

        if ((forward > 0.20f) &&
            (fabsf(side / forward) < 0.11f) &&
            (forward < best_forward))
        {
            best_forward = forward;
            best_index = (int)i;
        }
    }

    if (best_index >= 0)
    {
        g_enemies[best_index].active = 0U;
        g_score = (uint16_t)(g_score + 25U);
    }
    g_muzzle_ticks = 5U;
}

void doom_init(void)
{
    uint32_t now = HAL_GetTick();

    g_score = 0U;
    g_lives = 4U;
    g_level = 1U;
    g_game_over = 0U;
    g_restart_armed = 0U;
    g_muzzle_ticks = 0U;
    reset_player();
    spawn_enemies();
    g_last_update = now;
    g_last_fire = now - 200U;
}

void doom_update(void)
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
            (bluetooth_start_pressed() != 0U))
        {
            doom_init();
        }
        return;
    }

    fire_event =
        ((bluetooth_action1_pressed() != 0U) ||
         (bluetooth_action1_down() != 0U)) ? 1U : 0U;

    if ((fire_event != 0U) &&
        ((uint32_t)(now - g_last_fire) >= 180U))
    {
        g_last_fire = now;
        fire_weapon();
    }

    if (bluetooth_rotate_pressed() != 0U)
    {
        strafe_player(-0.18f);
    }
    if (bluetooth_hard_drop_pressed() != 0U)
    {
        strafe_player(0.18f);
    }

    while (((uint32_t)(now - g_last_update) >= UPDATE_MS) &&
           (steps < MAX_CATCH_UP_STEPS))
    {
        g_last_update += UPDATE_MS;
        update_player();
        update_enemies();
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

static float cast_ray(float ray_angle)
{
    float distance = 0.05f;
    float dx = cosf(ray_angle) * 0.05f;
    float dy = sinf(ray_angle) * 0.05f;
    float x = g_player_x;
    float y = g_player_y;

    while (distance < 7.0f)
    {
        x += dx;
        y += dy;
        if (map_is_wall(x, y) != 0U)
        {
            float corrected = distance * cosf(ray_angle - g_player_angle);
            return (corrected < 0.08f) ? 0.08f : corrected;
        }
        distance += 0.05f;
    }
    return 7.0f;
}

static void draw_enemy_view(const DoomEnemy *enemy)
{
    float dx = enemy->x - g_player_x;
    float dy = enemy->y - g_player_y;
    float view_cos = cosf(g_player_angle);
    float view_sin = sinf(g_player_angle);
    float forward = dx * view_cos + dy * view_sin;
    float side = -dx * view_sin + dy * view_cos;
    float screen_x;
    float size;

    if (forward <= 0.20f)
    {
        return;
    }

    screen_x = side / forward * 0.82f;
    size = 0.18f / forward;
    if (size > 0.25f) size = 0.25f;
    if (size < 0.035f) size = 0.035f;

    if ((screen_x < -0.92f) || (screen_x > 0.92f))
    {
        return;
    }

    vector_draw_rect(screen_x, 0.05f, size, size * 1.65f);
    vector_move_to(screen_x - size * 0.45f, 0.05f);
    vector_line_to(screen_x + size * 0.45f, 0.05f, 3U);
    vector_move_to(screen_x, 0.05f + size * 0.82f);
    vector_line_to(screen_x - size * 0.42f, 0.05f + size * 1.18f, 3U);
    vector_move_to(screen_x, 0.05f + size * 0.82f);
    vector_line_to(screen_x + size * 0.42f, 0.05f + size * 1.18f, 3U);
}

void doom_render(void)
{
    uint8_t ray;
    uint8_t enemy;
    float previous_x = 0.0f;
    float previous_top = 0.0f;
    float previous_bottom = 0.0f;
    char score_text[16];
    char life_text[12];

    for (ray = 0U; ray < RAY_COUNT; ray++)
    {
        float fraction = (float)ray / (float)(RAY_COUNT - 1U);
        float ray_angle = g_player_angle + (fraction - 0.5f) * FOV;
        float distance = cast_ray(ray_angle);
        float x = -0.84f + fraction * 1.68f;
        float half_height = 0.42f / distance;
        float top;
        float bottom;

        if (half_height > 0.56f) half_height = 0.56f;
        if (half_height < 0.035f) half_height = 0.035f;
        top = -half_height;
        bottom = half_height;

        vector_move_to(x, top);
        vector_line_to(x, bottom, 5U);

        if (ray != 0U)
        {
            vector_move_to(previous_x, previous_top);
            vector_line_to(x, top, 3U);
            vector_move_to(previous_x, previous_bottom);
            vector_line_to(x, bottom, 3U);
        }

        previous_x = x;
        previous_top = top;
        previous_bottom = bottom;
    }

    for (enemy = 0U; enemy < ENEMY_COUNT; enemy++)
    {
        if (g_enemies[enemy].active != 0U)
        {
            draw_enemy_view(&g_enemies[enemy]);
        }
    }

    vector_move_to(-0.12f, 0.60f);
    vector_line_to(-0.055f, 0.42f, 4U);
    vector_line_to(0.055f, 0.42f, 3U);
    vector_line_to(0.12f, 0.60f, 4U);

    vector_move_to(-0.025f, 0.0f);
    vector_line_to(0.025f, 0.0f, 2U);
    vector_move_to(0.0f, -0.025f);
    vector_line_to(0.0f, 0.025f, 2U);

    if (g_muzzle_ticks != 0U)
    {
        vector_move_to(-0.08f, 0.38f);
        vector_line_to(0.0f, 0.25f, 3U);
        vector_line_to(0.08f, 0.38f, 3U);
    }

    snprintf(score_text, sizeof(score_text), UI_TEXT_SCORE "%04u", (unsigned int)g_score);
    snprintf(life_text, sizeof(life_text), UI_TEXT_LIFE "%u", (unsigned int)g_lives);
    vector_font_draw_text(score_text, -0.88f, -0.73f, 0.09f);
    vector_font_draw_text(life_text, 0.61f, -0.73f, 0.09f);

    if (g_game_over != 0U)
    {
        vector_font_draw_text_center(UI_TEXT_GAME_OVER, 0.0f, -0.08f, 0.20f);
        vector_font_draw_text_center(UI_TEXT_PRESS_TO_START, 0.0f, 0.20f, 0.12f);
    }

    vector_blank();
}
