#ifndef __GAME_PONG_H
#define __GAME_PONG_H

typedef enum
{
    PONG_MODE_SINGLE_PLAYER = 0,
    PONG_MODE_TWO_PLAYER,
    PONG_MODE_COUNT
} PongMode;

void pong_set_mode(PongMode mode);
void pong_init(void);
void pong_update(void);
void pong_render(void);

#endif
