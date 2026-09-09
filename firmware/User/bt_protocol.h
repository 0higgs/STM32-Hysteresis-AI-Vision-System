#ifndef __BT_PROTOCOL_H
#define __BT_PROTOCOL_H

#include "hyst_model.h"
#include "./SYSTEM/sys/sys.h"

HAL_StatusTypeDef BT_ProtocolInit(uint32_t baudrate);
void BT_ProtocolPoll(void);
uint8_t BT_ProtocolTakeApply(HystParams *params);
void BT_ProtocolReportApplied(const HystParams *params);
void BT_ProtocolReportError(const char *reason);

#endif
