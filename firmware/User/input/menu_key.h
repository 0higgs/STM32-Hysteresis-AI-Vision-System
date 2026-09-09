#ifndef __MENU_KEY_H
#define __MENU_KEY_H

#include <stdint.h>

/*
 * External menu-only buttons, other terminal connected to GND:
 * PC6  -> menu up
 * PC7  -> menu down
 * PD13 -> enter
 *
 * Bluetooth U/D/E commands are merged with these physical controls.
 * This menu-key interface is ignored while a game is running.
 * Tetris reads PD13 separately through game_key as its rotate button.
 */
void menu_key_init(void);
void menu_key_update(void);
void menu_key_reset(void);

uint8_t menu_key_up_pressed(void);
uint8_t menu_key_down_pressed(void);
uint8_t menu_key_enter_pressed(void);

#endif
