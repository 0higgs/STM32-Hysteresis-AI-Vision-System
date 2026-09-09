#ifndef __GAME_KEY_H
#define __GAME_KEY_H

#include <stdint.h>

/*
 * Board buttons only:
 * A = KEY0 / PA15
 * B = WKUP / PA0
 *
 * Game mappings:
 *   Pong:     A=UP, B=DOWN
 *   Snake:    A=TURN LEFT, B=TURN RIGHT
 *   Breakout: A=LEFT, B=RIGHT
 *   Tetris:   A=LEFT, B=RIGHT, PD13=ROTATE
 *
 * Bluetooth commands are merged with these physical controls.
 * Hold physical A+B together for about 0.9 s, or send X over Bluetooth,
 * to return to the game menu.
 */
void game_key_init(void);
void game_key_update(void);
void game_key_rotate_update(void);
void game_key_reset(void);

uint8_t game_key_a_down(void);
uint8_t game_key_b_down(void);
uint8_t game_key_rotate_down(void);

uint8_t game_key_a_pressed(void);
uint8_t game_key_b_pressed(void);
uint8_t game_key_rotate_pressed(void);

uint8_t game_key_exit_requested(void);

#endif
