#ifndef __GAME_SHOOTER_H
#define __GAME_SHOOTER_H

typedef enum
{
    SHOOTER_DIFFICULTY_EASY = 0,
    SHOOTER_DIFFICULTY_NORMAL,
    SHOOTER_DIFFICULTY_HARD,
    SHOOTER_DIFFICULTY_COUNT
} ShooterDifficulty;

void shooter_set_difficulty(ShooterDifficulty difficulty);
void shooter_init(void);
void shooter_update(void);
void shooter_render(void);

#endif
