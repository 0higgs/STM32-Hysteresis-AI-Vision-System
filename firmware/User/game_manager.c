#include "game_manager.h"

#include "menu_key.h"
#include "game_key.h"
#include "bluetooth_control.h"

#include "game_pong.h"
#include "game_snake.h"
#include "game_breakout.h"
#include "game_tetris.h"
#include "game_shooter.h"
#include "game_asteroids.h"
#include "game_doom.h"
#include "game_quake.h"
#include "game_dino.h"
#include "game_animation.h"

#include "vector_draw.h"
#include "vector_font.h"

#include "./SYSTEM/sys/sys.h"

#include <stdint.h>

typedef enum
{
    MENU_ITEM_PONG = 0,
    MENU_ITEM_SNAKE,
    MENU_ITEM_BREAKOUT,
    MENU_ITEM_TETRIS,
    MENU_ITEM_SHOOTER,
    MENU_ITEM_ASTEROIDS,
    MENU_ITEM_DOOM,
    MENU_ITEM_QUAKE,
    MENU_ITEM_DINO,
    MENU_ITEM_ANIMATION,
    MENU_ITEM_COUNT
} MenuItem;

#define MENU_ITEM_SPACING       0.27f
#define MENU_SCROLL_DURATION_MS 150U

static GameMode g_mode = GAME_MODE_MENU;
static MenuItem g_menu_item = MENU_ITEM_PONG;
static uint8_t g_paused = 0U;
static uint8_t g_pong_mode_menu = 0U;
static PongMode g_pong_mode = PONG_MODE_SINGLE_PLAYER;
static uint8_t g_shooter_difficulty_menu = 0U;
static ShooterDifficulty g_shooter_difficulty = SHOOTER_DIFFICULTY_EASY;
static float g_menu_scroll_start_offset = 0.0f;
static uint32_t g_menu_scroll_start_tick = 0U;

static float float_abs(float value)
{
    return (value < 0.0f) ? -value : value;
}

static float menu_scroll_offset(void)
{
    uint32_t elapsed = HAL_GetTick() - g_menu_scroll_start_tick;

    if (elapsed >= MENU_SCROLL_DURATION_MS)
    {
        return 0.0f;
    }

    return g_menu_scroll_start_offset *
           (1.0f - (float)elapsed / (float)MENU_SCROLL_DURATION_MS);
}

static void enter_menu(void)
{
    g_mode = GAME_MODE_MENU;
    g_paused = 0U;
    g_pong_mode_menu = 0U;
    g_shooter_difficulty_menu = 0U;
    g_menu_scroll_start_offset = 0.0f;
    g_menu_scroll_start_tick = HAL_GetTick();
    bluetooth_control_reset_inputs();

    vector_blank();

    /*
     * External menu keys are reset only when the menu becomes active.
     * They are not scanned at all while a game is running.
     */
    menu_key_reset();
}

static void start_selected_game(void)
{
    bluetooth_control_reset_inputs();
    game_key_reset();
    g_paused = 0U;

    switch (g_menu_item)
    {
        case MENU_ITEM_PONG:
            g_pong_mode_menu = 1U;
            g_menu_scroll_start_offset = 0.0f;
            g_menu_scroll_start_tick = HAL_GetTick();
            break;

        case MENU_ITEM_SNAKE:
            snake_init();
            g_mode = GAME_MODE_SNAKE;
            break;

        case MENU_ITEM_BREAKOUT:
            breakout_init();
            g_mode = GAME_MODE_BREAKOUT;
            break;

        case MENU_ITEM_TETRIS:
            tetris_init();
            g_mode = GAME_MODE_TETRIS;
            break;

        case MENU_ITEM_SHOOTER:
            g_shooter_difficulty_menu = 1U;
            g_menu_scroll_start_offset = 0.0f;
            g_menu_scroll_start_tick = HAL_GetTick();
            break;

        case MENU_ITEM_ASTEROIDS:
            asteroids_init();
            g_mode = GAME_MODE_ASTEROIDS;
            break;

        case MENU_ITEM_DOOM:
            doom_init();
            g_mode = GAME_MODE_DOOM;
            break;

        case MENU_ITEM_QUAKE:
            quake_init();
            g_mode = GAME_MODE_QUAKE;
            break;

        case MENU_ITEM_DINO:
            dino_init();
            g_mode = GAME_MODE_DINO;
            break;

        case MENU_ITEM_ANIMATION:
        default:
            animation_init();
            g_mode = GAME_MODE_ANIMATION;
            break;
    }
}

static void update_menu(void)
{
    uint8_t up_pressed;
    uint8_t down_pressed;
    uint8_t enter_pressed;

    menu_key_update();

    up_pressed =
        ((menu_key_up_pressed() != 0U) ||
         (bluetooth_menu_up_pressed() != 0U)) ? 1U : 0U;
    down_pressed =
        ((menu_key_down_pressed() != 0U) ||
         (bluetooth_menu_down_pressed() != 0U)) ? 1U : 0U;
    enter_pressed =
        ((menu_key_enter_pressed() != 0U) ||
         (bluetooth_menu_enter_pressed() != 0U)) ? 1U : 0U;

    if (g_pong_mode_menu != 0U)
    {
        if (bluetooth_exit_requested() != 0U)
        {
            g_pong_mode_menu = 0U;
            bluetooth_control_reset_inputs();
            return;
        }

        if ((up_pressed != 0U) &&
            (g_pong_mode != PONG_MODE_SINGLE_PLAYER))
        {
            g_menu_scroll_start_offset = -MENU_ITEM_SPACING;
            g_menu_scroll_start_tick = HAL_GetTick();
            g_pong_mode =
                (PongMode)((int)g_pong_mode - 1);
        }

        if ((down_pressed != 0U) &&
            (g_pong_mode != PONG_MODE_TWO_PLAYER))
        {
            g_menu_scroll_start_offset = MENU_ITEM_SPACING;
            g_menu_scroll_start_tick = HAL_GetTick();
            g_pong_mode =
                (PongMode)((int)g_pong_mode + 1);
        }

        if (enter_pressed != 0U)
        {
            pong_set_mode(g_pong_mode);
            bluetooth_control_reset_inputs();
            game_key_reset();
            pong_init();
            g_pong_mode_menu = 0U;
            g_mode = GAME_MODE_PONG;
        }
        return;
    }

    if (g_shooter_difficulty_menu != 0U)
    {
        if ((bluetooth_exit_requested() != 0U))
        {
            g_shooter_difficulty_menu = 0U;
            bluetooth_control_reset_inputs();
            return;
        }

        if ((up_pressed != 0U) ||
            (bluetooth_rotate_pressed() != 0U))
        {
            if (g_shooter_difficulty != SHOOTER_DIFFICULTY_EASY)
            {
                g_menu_scroll_start_offset = -MENU_ITEM_SPACING;
                g_menu_scroll_start_tick = HAL_GetTick();
                g_shooter_difficulty =
                    (ShooterDifficulty)((int)g_shooter_difficulty - 1);
            }
        }

        if ((down_pressed != 0U) ||
            (bluetooth_hard_drop_pressed() != 0U))
        {
            if (g_shooter_difficulty != SHOOTER_DIFFICULTY_HARD)
            {
                g_menu_scroll_start_offset = MENU_ITEM_SPACING;
                g_menu_scroll_start_tick = HAL_GetTick();
                g_shooter_difficulty =
                    (ShooterDifficulty)((int)g_shooter_difficulty + 1);
            }
        }

        if (enter_pressed != 0U)
        {
            shooter_set_difficulty(g_shooter_difficulty);
            shooter_init();
            g_shooter_difficulty_menu = 0U;
            g_mode = GAME_MODE_SHOOTER;
        }
        return;
    }

    if (up_pressed != 0U)
    {
        if (g_menu_item != MENU_ITEM_PONG)
        {
            g_menu_scroll_start_offset = -MENU_ITEM_SPACING;
            g_menu_scroll_start_tick = HAL_GetTick();
            g_menu_item = (MenuItem)((int)g_menu_item - 1);
        }
    }

    if (down_pressed != 0U)
    {
        if (g_menu_item != MENU_ITEM_ANIMATION)
        {
            g_menu_scroll_start_offset = MENU_ITEM_SPACING;
            g_menu_scroll_start_tick = HAL_GetTick();
            g_menu_item = (MenuItem)((int)g_menu_item + 1);
        }
    }

    if (enter_pressed != 0U)
    {
        start_selected_game();
    }
}

static void update_game(void)
{
    game_key_update();

    /*
     * PC6/PC7 remain menu-only. PD13 is sampled separately only for
     * Tetris rotation. Hold the two board buttons together to return.
     */
    if (game_key_exit_requested() != 0U)
    {
        enter_menu();
        return;
    }

    if (bluetooth_pause_pressed() != 0U)
    {
        g_paused = (uint8_t)!g_paused;
        bluetooth_control_reset_inputs();
    }

    if (g_paused != 0U)
    {
        return;
    }

    if (g_mode == GAME_MODE_TETRIS)
    {
        game_key_rotate_update();
    }

    switch (g_mode)
    {
        case GAME_MODE_PONG:
            pong_update();
            break;

        case GAME_MODE_SNAKE:
            snake_update();
            break;

        case GAME_MODE_BREAKOUT:
            breakout_update();
            break;

        case GAME_MODE_TETRIS:
            tetris_update();
            break;

        case GAME_MODE_SHOOTER:
            shooter_update();
            break;

        case GAME_MODE_ASTEROIDS:
            asteroids_update();
            break;

        case GAME_MODE_DOOM:
            doom_update();
            break;

        case GAME_MODE_QUAKE:
            quake_update();
            break;

        case GAME_MODE_DINO:
            dino_update();
            break;

        case GAME_MODE_ANIMATION:
            animation_update();
            break;

        case GAME_MODE_MENU:
        default:
            break;
    }

    if (g_paused != 0U)
    {
        vector_font_draw_text_center(
            UI_TEXT_PAUSED,
            0.0f,
            0.0f,
            0.24f
        );
        vector_blank();
    }
}

void game_manager_init(void)
{
    g_menu_item = MENU_ITEM_PONG;
    g_pong_mode = PONG_MODE_SINGLE_PLAYER;
    g_shooter_difficulty = SHOOTER_DIFFICULTY_EASY;
    enter_menu();
}

void game_manager_update(void)
{
    bluetooth_control_update();

    if (g_mode == GAME_MODE_MENU)
    {
        update_menu();
    }
    else
    {
        update_game();
    }
}

void game_manager_render(void)
{
    static const char *items[MENU_ITEM_COUNT] =
    {
        UI_TEXT_PONG,
        UI_TEXT_SNAKE,
        UI_TEXT_BREAKOUT,
        UI_TEXT_TETRIS,
        UI_TEXT_SHOOTER,
        UI_TEXT_ASTEROIDS,
        UI_TEXT_DOOM,
        UI_TEXT_QUAKE,
        UI_TEXT_DINO_RUN,
        UI_TEXT_CAT_WAVE
    };

    if (g_mode == GAME_MODE_MENU)
    {
        int relative;
        float offset = menu_scroll_offset();
        float scrollbar_top = -0.28f;
        float scrollbar_bottom = 0.28f;
        float thumb_height = 0.09f;
        float effective_item;
        float thumb_y;
        const char **visible_items = items;
        int visible_count = (int)MENU_ITEM_COUNT;
        int selected_item = (int)g_menu_item;
        static const char *difficulty_items[SHOOTER_DIFFICULTY_COUNT] =
        {
            UI_TEXT_EASY,
            UI_TEXT_NORMAL,
            UI_TEXT_HARD
        };
        static const char *pong_mode_items[PONG_MODE_COUNT] =
        {
            UI_TEXT_SINGLE_PLAYER,
            UI_TEXT_TWO_PLAYER
        };

        if (g_shooter_difficulty_menu != 0U)
        {
            visible_items = difficulty_items;
            visible_count = (int)SHOOTER_DIFFICULTY_COUNT;
            selected_item = (int)g_shooter_difficulty;
        }
        else if (g_pong_mode_menu != 0U)
        {
            visible_items = pong_mode_items;
            visible_count = (int)PONG_MODE_COUNT;
            selected_item = (int)g_pong_mode;
        }

        vector_font_draw_text_center(
            (g_shooter_difficulty_menu != 0U) ?
                UI_TEXT_DIFFICULTY :
                ((g_pong_mode_menu != 0U) ?
                    UI_TEXT_GAME_MODE :
                    UI_TEXT_SELECT_GAME),
            0.0f,
            -0.60f,
            0.18f
        );

        for (relative = -2; relative <= 2; relative++)
        {
            int item = selected_item + relative;
            float center_y = (float)relative * MENU_ITEM_SPACING + offset;
            float distance;
            float emphasis;
            float size;

            if ((item < 0) || (item >= visible_count))
            {
                continue;
            }

            if ((center_y < -0.36f) || (center_y > 0.36f))
            {
                continue;
            }

            distance = float_abs(center_y);
            emphasis = 1.0f - distance / MENU_ITEM_SPACING;
            if (emphasis < 0.0f)
            {
                emphasis = 0.0f;
            }

            size = 0.12f + emphasis * 0.05f;
            vector_font_draw_text_center(
                visible_items[item],
                0.0f,
                center_y - size * 0.5f,
                size
            );
        }

        vector_draw_rect(0.0f, 0.0f, 1.18f, 0.23f);

        vector_move_to(0.88f, scrollbar_top);
        vector_line_to(0.88f, scrollbar_bottom, 18U);

        effective_item =
            (float)selected_item - offset / MENU_ITEM_SPACING;
        if (effective_item < 0.0f)
        {
            effective_item = 0.0f;
        }
        if (effective_item > (float)(visible_count - 1))
        {
            effective_item = (float)(visible_count - 1);
        }

        thumb_y =
            scrollbar_top +
            thumb_height * 0.5f +
            effective_item /
            (float)(visible_count - 1) *
            (scrollbar_bottom - scrollbar_top - thumb_height);
        vector_draw_rect(0.88f, thumb_y, 0.075f, thumb_height);

        vector_font_draw_text_center(
            (g_shooter_difficulty_menu != 0U) ?
                UI_TEXT_LEFT_RIGHT_SELECT :
                ((g_pong_mode_menu != 0U) ?
                    UI_TEXT_LEFT_RIGHT_SELECT :
                    UI_TEXT_CONFIRM),
            0.0f,
            0.56f,
            0.11f
        );

        vector_blank();
        return;
    }

    switch (g_mode)
    {
        case GAME_MODE_PONG:
            pong_render();
            break;

        case GAME_MODE_SNAKE:
            snake_render();
            break;

        case GAME_MODE_BREAKOUT:
            breakout_render();
            break;

        case GAME_MODE_TETRIS:
            tetris_render();
            break;

        case GAME_MODE_SHOOTER:
            shooter_render();
            break;

        case GAME_MODE_ASTEROIDS:
            asteroids_render();
            break;

        case GAME_MODE_DOOM:
            doom_render();
            break;

        case GAME_MODE_QUAKE:
            quake_render();
            break;

        case GAME_MODE_DINO:
            dino_render();
            break;

        case GAME_MODE_ANIMATION:
            animation_render();
            break;

        case GAME_MODE_MENU:
        default:
            break;
    }
}

GameMode game_manager_mode(void)
{
    return g_mode;
}
