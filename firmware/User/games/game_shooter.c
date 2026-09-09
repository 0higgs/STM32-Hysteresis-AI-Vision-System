#include "game_shooter.h"

#include "game_key.h"
#include "bluetooth_control.h"
#include "vector_draw.h"
#include "vector_font.h"

#include "./SYSTEM/sys/sys.h"

#include <stdint.h>
#include <stdio.h>

#define FIELD_LEFT              (-0.92f)
#define FIELD_RIGHT              0.92f
#define FIELD_TOP               (-0.60f)
#define FIELD_BOTTOM             0.62f

#define UPDATE_MS               16U
#define MAX_CATCH_UP_STEPS       3U

#define PLAYER_START_Y           0.48f
#define PLAYER_SPEED             0.030f
#define PLAYER_HALF_WIDTH        0.065f
#define PLAYER_HALF_HEIGHT       0.060f

#define MAX_PLAYER_SHOTS         9U
#define MAX_ENEMIES              8U
#define MAX_ENEMY_SHOTS          7U
#define MAX_EXPLOSIONS           4U
#define STAR_COUNT               7U

#define NORMAL_FIRE_MS         220U
#define RAPID_FIRE_MS           90U
typedef struct
{
    float x;
    float y;
    uint8_t active;
} Shot;

typedef struct
{
    float x;
    float y;
    float vx;
    uint8_t active;
} Enemy;

typedef struct
{
    float x;
    float y;
    uint8_t ticks;
} Explosion;

typedef struct
{
    float x;
    float y;
    float speed;
} Star;

static Shot g_player_shots[MAX_PLAYER_SHOTS];
static Shot g_enemy_shots[MAX_ENEMY_SHOTS];
static Enemy g_enemies[MAX_ENEMIES];
static Explosion g_explosions[MAX_EXPLOSIONS];
static Star g_stars[STAR_COUNT];

static float g_player_x;
static float g_player_y;
static uint16_t g_score;
static uint8_t g_lives;
static uint8_t g_bombs;
static uint8_t g_game_over;
static uint8_t g_restart_armed;
static uint8_t g_invulnerable_ticks;
static uint8_t g_blast_ticks;

static uint32_t g_last_update;
static uint32_t g_last_fire;
static uint32_t g_last_enemy_fire;
static uint32_t g_last_spawn;
static uint32_t g_rng;
static ShooterDifficulty g_difficulty = SHOOTER_DIFFICULTY_EASY;

static float enemy_base_speed(void)
{
    if (g_difficulty == SHOOTER_DIFFICULTY_HARD)
    {
        return 0.0105f;
    }
    if (g_difficulty == SHOOTER_DIFFICULTY_NORMAL)
    {
        return 0.0080f;
    }
    return 0.0058f;
}

static uint32_t enemy_fire_interval(void)
{
    if (g_difficulty == SHOOTER_DIFFICULTY_HARD)
    {
        return 400U;
    }
    if (g_difficulty == SHOOTER_DIFFICULTY_NORMAL)
    {
        return 620U;
    }
    return 900U;
}

static uint32_t initial_spawn_interval(void)
{
    if (g_difficulty == SHOOTER_DIFFICULTY_HARD)
    {
        return 620U;
    }
    if (g_difficulty == SHOOTER_DIFFICULTY_NORMAL)
    {
        return 820U;
    }
    return 1080U;
}

static uint32_t minimum_spawn_interval(void)
{
    if (g_difficulty == SHOOTER_DIFFICULTY_HARD)
    {
        return 300U;
    }
    if (g_difficulty == SHOOTER_DIFFICULTY_NORMAL)
    {
        return 480U;
    }
    return 700U;
}

static float abs_float(float value)
{
    return (value < 0.0f) ? -value : value;
}

static uint32_t random_next(void)
{
    g_rng = g_rng * 1664525UL + 1013904223UL;
    return g_rng;
}

static float random_x(void)
{
    return -0.78f + (float)(random_next() % 157U) * 0.01f;
}

static void clear_objects(void)
{
    uint8_t i;

    for (i = 0U; i < MAX_PLAYER_SHOTS; i++)
    {
        g_player_shots[i].active = 0U;
    }
    for (i = 0U; i < MAX_ENEMY_SHOTS; i++)
    {
        g_enemy_shots[i].active = 0U;
    }
    for (i = 0U; i < MAX_ENEMIES; i++)
    {
        g_enemies[i].active = 0U;
    }
    for (i = 0U; i < MAX_EXPLOSIONS; i++)
    {
        g_explosions[i].ticks = 0U;
    }
}

static void add_explosion(float x, float y)
{
    uint8_t i;

    for (i = 0U; i < MAX_EXPLOSIONS; i++)
    {
        if (g_explosions[i].ticks == 0U)
        {
            g_explosions[i].x = x;
            g_explosions[i].y = y;
            g_explosions[i].ticks = 12U;
            return;
        }
    }
}

static void fire_player_shot(void)
{
    uint8_t i;

    for (i = 0U; i < MAX_PLAYER_SHOTS; i++)
    {
        if (g_player_shots[i].active == 0U)
        {
            g_player_shots[i].x = g_player_x;
            g_player_shots[i].y = g_player_y - PLAYER_HALF_HEIGHT;
            g_player_shots[i].active = 1U;
            return;
        }
    }
}

static void spawn_enemy(void)
{
    uint8_t i;

    for (i = 0U; i < MAX_ENEMIES; i++)
    {
        if (g_enemies[i].active == 0U)
        {
            int32_t direction = (int32_t)(random_next() % 3U) - 1;

            g_enemies[i].x = random_x();
            g_enemies[i].y = FIELD_TOP + 0.055f;
            g_enemies[i].vx = (float)direction * 0.0045f;
            g_enemies[i].active = 1U;
            return;
        }
    }
}

static void fire_enemy_shot(void)
{
    uint8_t start = (uint8_t)(random_next() % MAX_ENEMIES);
    uint8_t offset;

    for (offset = 0U; offset < MAX_ENEMIES; offset++)
    {
        uint8_t enemy_index =
            (uint8_t)((start + offset) % MAX_ENEMIES);

        if (g_enemies[enemy_index].active != 0U)
        {
            uint8_t i;

            for (i = 0U; i < MAX_ENEMY_SHOTS; i++)
            {
                if (g_enemy_shots[i].active == 0U)
                {
                    g_enemy_shots[i].x = g_enemies[enemy_index].x;
                    g_enemy_shots[i].y = g_enemies[enemy_index].y + 0.055f;
                    g_enemy_shots[i].active = 1U;
                    return;
                }
            }
        }
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

    add_explosion(g_player_x, g_player_y);
    g_invulnerable_ticks = 75U;

    if (g_lives == 0U)
    {
        g_game_over = 1U;
        g_restart_armed = 0U;
    }
}

static void use_bomb(void)
{
    uint8_t i;

    if (g_bombs == 0U)
    {
        return;
    }

    g_bombs--;
    g_blast_ticks = 18U;

    for (i = 0U; i < MAX_ENEMIES; i++)
    {
        if (g_enemies[i].active != 0U)
        {
            add_explosion(g_enemies[i].x, g_enemies[i].y);
            g_enemies[i].active = 0U;
            g_score = (uint16_t)(g_score + 5U);
        }
    }
    for (i = 0U; i < MAX_ENEMY_SHOTS; i++)
    {
        g_enemy_shots[i].active = 0U;
    }
}

static void update_player(void)
{
    if ((game_key_a_down() != 0U) ||
        (bluetooth_left_down() != 0U))
    {
        g_player_x -= PLAYER_SPEED;
    }
    if ((game_key_b_down() != 0U) ||
        (bluetooth_right_down() != 0U))
    {
        g_player_x += PLAYER_SPEED;
    }
    if (bluetooth_up_down() != 0U)
    {
        g_player_y -= PLAYER_SPEED;
    }
    if (bluetooth_down_down() != 0U)
    {
        g_player_y += PLAYER_SPEED;
    }

    if (g_player_x < FIELD_LEFT + PLAYER_HALF_WIDTH)
    {
        g_player_x = FIELD_LEFT + PLAYER_HALF_WIDTH;
    }
    if (g_player_x > FIELD_RIGHT - PLAYER_HALF_WIDTH)
    {
        g_player_x = FIELD_RIGHT - PLAYER_HALF_WIDTH;
    }
    if (g_player_y < 0.10f)
    {
        g_player_y = 0.10f;
    }
    if (g_player_y > FIELD_BOTTOM - PLAYER_HALF_HEIGHT)
    {
        g_player_y = FIELD_BOTTOM - PLAYER_HALF_HEIGHT;
    }
}

static void update_stars(void)
{
    uint8_t i;

    for (i = 0U; i < STAR_COUNT; i++)
    {
        g_stars[i].y += g_stars[i].speed;
        if (g_stars[i].y > FIELD_BOTTOM)
        {
            g_stars[i].y = FIELD_TOP;
            g_stars[i].x = random_x();
        }
    }
}

static void update_player_shots(void)
{
    uint8_t i;

    for (i = 0U; i < MAX_PLAYER_SHOTS; i++)
    {
        uint8_t e;

        if (g_player_shots[i].active == 0U)
        {
            continue;
        }

        g_player_shots[i].y -= 0.045f;
        if (g_player_shots[i].y < FIELD_TOP)
        {
            g_player_shots[i].active = 0U;
            continue;
        }

        for (e = 0U; e < MAX_ENEMIES; e++)
        {
            if ((g_enemies[e].active != 0U) &&
                (abs_float(g_player_shots[i].x - g_enemies[e].x) < 0.075f) &&
                (abs_float(g_player_shots[i].y - g_enemies[e].y) < 0.060f))
            {
                add_explosion(g_enemies[e].x, g_enemies[e].y);
                g_enemies[e].active = 0U;
                g_player_shots[i].active = 0U;
                g_score = (uint16_t)(g_score + 10U);
                break;
            }
        }
    }
}

static void update_enemies(void)
{
    uint8_t i;
    float base_speed = enemy_base_speed();
    float speed_bonus = (float)(g_score / 250U) * 0.0007f;

    if (speed_bonus > 0.006f)
    {
        speed_bonus = 0.006f;
    }

    for (i = 0U; i < MAX_ENEMIES; i++)
    {
        if (g_enemies[i].active == 0U)
        {
            continue;
        }

        g_enemies[i].x += g_enemies[i].vx;
        g_enemies[i].y += base_speed + speed_bonus;

        if ((g_enemies[i].x < FIELD_LEFT + 0.06f) ||
            (g_enemies[i].x > FIELD_RIGHT - 0.06f))
        {
            g_enemies[i].vx = -g_enemies[i].vx;
        }

        if ((g_invulnerable_ticks == 0U) &&
            (abs_float(g_enemies[i].x - g_player_x) < 0.105f) &&
            (abs_float(g_enemies[i].y - g_player_y) < 0.105f))
        {
            add_explosion(g_enemies[i].x, g_enemies[i].y);
            g_enemies[i].active = 0U;
            lose_life();
            continue;
        }

        if (g_enemies[i].y > FIELD_BOTTOM)
        {
            g_enemies[i].active = 0U;
            lose_life();
        }
    }
}

static void update_enemy_shots(void)
{
    uint8_t i;

    for (i = 0U; i < MAX_ENEMY_SHOTS; i++)
    {
        if (g_enemy_shots[i].active == 0U)
        {
            continue;
        }

        g_enemy_shots[i].y += 0.024f;
        if (g_enemy_shots[i].y > FIELD_BOTTOM)
        {
            g_enemy_shots[i].active = 0U;
            continue;
        }

        if ((g_invulnerable_ticks == 0U) &&
            (abs_float(g_enemy_shots[i].x - g_player_x) < 0.060f) &&
            (abs_float(g_enemy_shots[i].y - g_player_y) < 0.065f))
        {
            g_enemy_shots[i].active = 0U;
            lose_life();
        }
    }
}

static void update_explosions(void)
{
    uint8_t i;

    for (i = 0U; i < MAX_EXPLOSIONS; i++)
    {
        if (g_explosions[i].ticks > 0U)
        {
            g_explosions[i].ticks--;
        }
    }

    if (g_invulnerable_ticks > 0U)
    {
        g_invulnerable_ticks--;
    }
    if (g_blast_ticks > 0U)
    {
        g_blast_ticks--;
    }
}

static void simulation_step(void)
{
    update_player();
    update_stars();
    update_player_shots();
    update_enemies();
    update_enemy_shots();
    update_explosions();
}

void shooter_init(void)
{
    uint8_t i;
    uint32_t now = HAL_GetTick();

    clear_objects();

    g_player_x = 0.0f;
    g_player_y = PLAYER_START_Y;
    g_score = 0U;
    if (g_difficulty == SHOOTER_DIFFICULTY_EASY)
    {
        g_lives = 5U;
        g_bombs = 5U;
    }
    else if (g_difficulty == SHOOTER_DIFFICULTY_NORMAL)
    {
        g_lives = 4U;
        g_bombs = 3U;
    }
    else
    {
        g_lives = 3U;
        g_bombs = 2U;
    }
    g_game_over = 0U;
    g_restart_armed = 0U;
    g_invulnerable_ticks = 0U;
    g_blast_ticks = 0U;
    g_rng = now ^ 0x5A17C3E1UL;

    for (i = 0U; i < STAR_COUNT; i++)
    {
        g_stars[i].x = random_x();
        g_stars[i].y =
            FIELD_TOP +
            (FIELD_BOTTOM - FIELD_TOP) *
            (float)i / (float)STAR_COUNT;
        g_stars[i].speed = 0.005f + (float)(i % 3U) * 0.002f;
    }

    g_last_update = now;
    g_last_fire = now - NORMAL_FIRE_MS;
    g_last_enemy_fire = now;
    g_last_spawn = now - initial_spawn_interval();
}

void shooter_set_difficulty(ShooterDifficulty difficulty)
{
    if (difficulty >= SHOOTER_DIFFICULTY_COUNT)
    {
        difficulty = SHOOTER_DIFFICULTY_EASY;
    }
    g_difficulty = difficulty;
}

void shooter_update(void)
{
    uint32_t now = HAL_GetTick();
    uint32_t fire_interval =
        (bluetooth_action1_down() != 0U) ?
        RAPID_FIRE_MS :
        NORMAL_FIRE_MS;
    uint8_t steps = 0U;

    if (g_game_over != 0U)
    {
        uint8_t left = bluetooth_left_pressed();
        uint8_t right = bluetooth_right_pressed();
        uint8_t up = bluetooth_up_pressed();
        uint8_t down = bluetooth_down_pressed();
        uint8_t action1 = bluetooth_action1_pressed();
        uint8_t action2 = bluetooth_action2_pressed();
        uint8_t start = bluetooth_start_pressed();

        if (g_restart_armed == 0U)
        {
            (void)game_key_a_pressed();
            (void)game_key_b_pressed();

            if ((game_key_a_down() == 0U) &&
                (game_key_b_down() == 0U) &&
                (bluetooth_left_down() == 0U) &&
                (bluetooth_right_down() == 0U) &&
                (bluetooth_up_down() == 0U) &&
                (bluetooth_down_down() == 0U) &&
                (bluetooth_action1_down() == 0U) &&
                (bluetooth_action2_down() == 0U))
            {
                g_restart_armed = 1U;
            }
            return;
        }

        if ((game_key_a_pressed() != 0U) ||
            (game_key_b_pressed() != 0U) ||
            (left != 0U) || (right != 0U) ||
            (up != 0U) || (down != 0U) ||
            (action1 != 0U) || (action2 != 0U) ||
            (start != 0U))
        {
            shooter_init();
        }
        return;
    }

    if (bluetooth_action2_pressed() != 0U)
    {
        use_bomb();
    }

    if ((uint32_t)(now - g_last_fire) >= fire_interval)
    {
        g_last_fire = now;
        fire_player_shot();
    }

    if ((uint32_t)(now - g_last_enemy_fire) >= enemy_fire_interval())
    {
        g_last_enemy_fire = now;
        fire_enemy_shot();
    }

    {
        uint32_t initial_interval = initial_spawn_interval();
        uint32_t minimum_interval = minimum_spawn_interval();
        uint32_t spawn_interval = initial_interval;
        uint32_t reduction = (uint32_t)(g_score / 25U) * 12U;

        if (reduction + minimum_interval < initial_interval)
        {
            spawn_interval -= reduction;
        }
        else
        {
            spawn_interval = minimum_interval;
        }

        if ((uint32_t)(now - g_last_spawn) >= spawn_interval)
        {
            g_last_spawn = now;
            spawn_enemy();
        }
    }

    while (((uint32_t)(now - g_last_update) >= UPDATE_MS) &&
           (steps < MAX_CATCH_UP_STEPS))
    {
        g_last_update += UPDATE_MS;
        simulation_step();
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

static void draw_ship(float x, float y)
{
    vector_move_to(x, y - PLAYER_HALF_HEIGHT);
    vector_line_to(x + PLAYER_HALF_WIDTH, y + PLAYER_HALF_HEIGHT, 4U);
    vector_line_to(x + 0.022f, y + 0.035f, 3U);
    vector_line_to(x, y + 0.058f, 2U);
    vector_line_to(x - 0.022f, y + 0.035f, 2U);
    vector_line_to(x - PLAYER_HALF_WIDTH, y + PLAYER_HALF_HEIGHT, 3U);
    vector_line_to(x, y - PLAYER_HALF_HEIGHT, 4U);
}

static void draw_enemy(float x, float y)
{
    vector_move_to(x, y + 0.050f);
    vector_line_to(x + 0.060f, y - 0.040f, 3U);
    vector_line_to(x, y - 0.015f, 2U);
    vector_line_to(x - 0.060f, y - 0.040f, 3U);
    vector_line_to(x, y + 0.050f, 3U);
}

static void draw_explosion(const Explosion *explosion)
{
    float size = 0.025f + (float)explosion->ticks * 0.002f;

    vector_move_to(explosion->x - size, explosion->y - size);
    vector_line_to(explosion->x + size, explosion->y + size, 3U);
    vector_move_to(explosion->x + size, explosion->y - size);
    vector_line_to(explosion->x - size, explosion->y + size, 3U);
}

void shooter_render(void)
{
    uint8_t i;
    char score_text[16];
    char life_text[12];
    char bomb_text[12];

    vector_draw_border(FIELD_LEFT, FIELD_TOP, FIELD_RIGHT, FIELD_BOTTOM);

    for (i = 0U; i < STAR_COUNT; i++)
    {
        vector_move_to(g_stars[i].x, g_stars[i].y);
        vector_line_to(g_stars[i].x + 0.012f, g_stars[i].y, 2U);
    }

    for (i = 0U; i < MAX_ENEMIES; i++)
    {
        if (g_enemies[i].active != 0U)
        {
            draw_enemy(g_enemies[i].x, g_enemies[i].y);
        }
    }

    for (i = 0U; i < MAX_PLAYER_SHOTS; i++)
    {
        if (g_player_shots[i].active != 0U)
        {
            vector_move_to(g_player_shots[i].x, g_player_shots[i].y);
            vector_line_to(g_player_shots[i].x, g_player_shots[i].y - 0.045f, 3U);
        }
    }

    for (i = 0U; i < MAX_ENEMY_SHOTS; i++)
    {
        if (g_enemy_shots[i].active != 0U)
        {
            vector_move_to(g_enemy_shots[i].x, g_enemy_shots[i].y);
            vector_line_to(g_enemy_shots[i].x, g_enemy_shots[i].y + 0.035f, 3U);
        }
    }

    for (i = 0U; i < MAX_EXPLOSIONS; i++)
    {
        if (g_explosions[i].ticks != 0U)
        {
            draw_explosion(&g_explosions[i]);
        }
    }

    if (g_blast_ticks != 0U)
    {
        float size = 0.30f + (float)(18U - g_blast_ticks) * 0.025f;
        vector_draw_rect(0.0f, 0.0f, size * 2.0f, size * 1.45f);
    }

    draw_ship(g_player_x, g_player_y);

    if (g_invulnerable_ticks != 0U)
    {
        vector_draw_rect(g_player_x, g_player_y, 0.18f, 0.17f);
    }

    snprintf(score_text, sizeof(score_text), UI_TEXT_SCORE "%04u", (unsigned int)g_score);
    snprintf(life_text, sizeof(life_text), UI_TEXT_LIFE "%u", (unsigned int)g_lives);
    snprintf(bomb_text, sizeof(bomb_text), UI_TEXT_BOMB "%u", (unsigned int)g_bombs);

    vector_font_draw_text(score_text, -0.88f, -0.73f, 0.09f);
    vector_font_draw_text(life_text, 0.22f, -0.73f, 0.09f);
    vector_font_draw_text(bomb_text, 0.60f, -0.73f, 0.09f);

    if (g_game_over != 0U)
    {
        vector_font_draw_text_center(UI_TEXT_GAME_OVER, 0.0f, -0.06f, 0.20f);
        vector_font_draw_text_center(UI_TEXT_PRESS_TO_START, 0.0f, 0.21f, 0.12f);
    }

    vector_blank();
}
