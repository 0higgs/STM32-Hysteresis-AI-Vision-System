#ifndef __GAME_MANAGER_H
#define __GAME_MANAGER_H

typedef enum
{
    GAME_MODE_MENU = 0,
    GAME_MODE_PONG,
    GAME_MODE_SNAKE,
    GAME_MODE_BREAKOUT,
    GAME_MODE_TETRIS,
    GAME_MODE_SHOOTER,
    GAME_MODE_ASTEROIDS,
    GAME_MODE_DOOM,
    GAME_MODE_QUAKE,
    GAME_MODE_DINO,
    GAME_MODE_ANIMATION
} GameMode;

void game_manager_init(void);
void game_manager_update(void);
void game_manager_render(void);

GameMode game_manager_mode(void);

#endif
