#ifndef __BLUETOOTH_CONTROL_H
#define __BLUETOOTH_CONTROL_H

#include <stdint.h>

#define BLUETOOTH_DEFAULT_BAUDRATE  9600U

/*
 * JDY-34 / HC-05D data link on USART2:
 *   PA2 / USART2_TX -> module RXD
 *   PA3 / USART2_RX <- module TXD
 *
 * Phone commands (ASCII, no line ending required):
 *   U/D/E : menu up / menu down / enter
 *   A/a   : hold / release game button A (left or up)
 *   B/b   : hold / release game button B (right or down)
 *   L/R   : short tap A / B
 *   T     : rotate
 *   X     : return to the game menu
 *   S     : release all held Bluetooth controls
 *   ?     : print command help to the Bluetooth link
 *
 * Extended gamepad packets are three paced ASCII bytes:
 *   !U1/!U0, !D1/!D0, !L1/!L0, !R1/!R0 : direction press/release
 *   !A1/!A0, !B1/!B0                   : action press/release
 *   !T1 rotate, !H1 hard drop, !P1 pause, !E1 start, !X1 back
 *   !S1 releases every Bluetooth-held control.
 *
 * Compact phone protocol (one byte per event, preferred):
 *   1/q, 2/w, 3/e, 4/r : direction press/release
 *   5/t, 6/y           : action press/release
 *   7 rotate, 8 hard drop, 9 pause, 0 start, x back, s release all
 *
 * PONG player 2 compact protocol:
 *   I/i : right paddle up press/release
 *   K/k : right paddle down press/release
 *   z   : release player 2 directions
 *
 * JDY-34 SPP multi-connection merges all phone data onto this UART.
 * Separate one-byte command sets let each phone select its own PONG side.
 */
void bluetooth_control_init(uint32_t baudrate);
void bluetooth_control_update(void);
void bluetooth_control_reset_inputs(void);

uint8_t bluetooth_menu_up_pressed(void);
uint8_t bluetooth_menu_down_pressed(void);
uint8_t bluetooth_menu_enter_pressed(void);

uint8_t bluetooth_a_down(void);
uint8_t bluetooth_b_down(void);
uint8_t bluetooth_rotate_down(void);

uint8_t bluetooth_a_pressed(void);
uint8_t bluetooth_b_pressed(void);
uint8_t bluetooth_rotate_pressed(void);
uint8_t bluetooth_exit_requested(void);

uint8_t bluetooth_up_down(void);
uint8_t bluetooth_down_down(void);
uint8_t bluetooth_left_down(void);
uint8_t bluetooth_right_down(void);
uint8_t bluetooth_action1_down(void);
uint8_t bluetooth_action2_down(void);

uint8_t bluetooth_up_pressed(void);
uint8_t bluetooth_down_pressed(void);
uint8_t bluetooth_left_pressed(void);
uint8_t bluetooth_right_pressed(void);
uint8_t bluetooth_action1_pressed(void);
uint8_t bluetooth_action2_pressed(void);
uint8_t bluetooth_hard_drop_pressed(void);
uint8_t bluetooth_pause_pressed(void);
uint8_t bluetooth_start_pressed(void);

uint8_t bluetooth_player2_up_down(void);
uint8_t bluetooth_player2_down_down(void);
uint8_t bluetooth_player2_up_pressed(void);
uint8_t bluetooth_player2_down_pressed(void);

#endif
