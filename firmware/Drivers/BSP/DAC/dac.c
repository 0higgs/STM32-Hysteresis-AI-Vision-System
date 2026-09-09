/**
 ****************************************************************************************************
 * @file        dac.c
 * @brief       双通道DAC同步DMA输出
 *
 * PA5 / DAC Channel2 -> X
 * PA4 / DAC Channel1 -> Y
 *
 * 两个DAC通道使用同一个TIM7 TRGO作为触发源。
 * 两路DMA在TIM7启动前全部进入工作状态，从而保证X/Y从同一触发时刻开始输出。
 ****************************************************************************************************
 */

#include "./BSP/DAC/dac.h"

/* DAC句柄 */
DAC_HandleTypeDef g_xy_dac_handle = {0};

/* 两路DMA句柄 */
DMA_HandleTypeDef g_xy_dma_y_handle = {0};
DMA_HandleTypeDef g_xy_dma_x_handle = {0};

/* TIM7句柄 */
TIM_HandleTypeDef g_xy_tim_handle = {0};

/* 两路磁滞回线缓冲区在hyst_model.c中生成 */
extern uint16_t g_hyst_buf_x[];
extern uint16_t g_hyst_buf_y[];

/**
 * @brief 初始化双通道DAC
 */
HAL_StatusTypeDef xy_dac_init(void)
{
    g_xy_dac_handle.Instance = XY_DAC;
    return HAL_DAC_Init(&g_xy_dac_handle);
}

/**
 * @brief HAL DAC MSP初始化
 */
void HAL_DAC_MspInit(DAC_HandleTypeDef *hdac)
{
    GPIO_InitTypeDef gpio_init_struct = {0};
    DAC_ChannelConfTypeDef dac_channel_conf_struct = {0};
    TIM_MasterConfigTypeDef tim_master_config_struct = {0};

    if (hdac->Instance == XY_DAC)
    {
        XY_DAC_CLK_ENABLE();
        XY_DAC_GPIO_CLK_ENABLE();
        XY_DAC_DMA_CLK_ENABLE();
        XY_DAC_TIM_CLK_ENABLE();

        /* PA4 + PA5 配置为模拟模式 */
        gpio_init_struct.Pin = XY_DAC_GPIO_PIN_Y | XY_DAC_GPIO_PIN_X;
        gpio_init_struct.Mode = GPIO_MODE_ANALOG;
        gpio_init_struct.Pull = GPIO_NOPULL;
        gpio_init_struct.Speed = GPIO_SPEED_FREQ_HIGH;
        HAL_GPIO_Init(XY_DAC_GPIO_PORT, &gpio_init_struct);

        /* 两个DAC通道都由TIM7 TRGO触发 */
        dac_channel_conf_struct.DAC_Trigger = DAC_TRIGGER_T7_TRGO;
        dac_channel_conf_struct.DAC_OutputBuffer = DAC_OUTPUTBUFFER_ENABLE;

        HAL_DAC_ConfigChannel(hdac, &dac_channel_conf_struct, XY_DAC_CH_Y);
        HAL_DAC_ConfigChannel(hdac, &dac_channel_conf_struct, XY_DAC_CH_X);

        /* ---------------- Y通道 DMA：DAC2 -> DMA1 Stream6 Channel7 ---------------- */
        g_xy_dma_y_handle.Instance = XY_DAC_DMA_Y_STREAM;
        g_xy_dma_y_handle.Init.Channel = XY_DAC_DMA_Y_CHANNEL;
        g_xy_dma_y_handle.Init.Direction = DMA_MEMORY_TO_PERIPH;
        g_xy_dma_y_handle.Init.PeriphInc = DMA_PINC_DISABLE;
        g_xy_dma_y_handle.Init.MemInc = DMA_MINC_ENABLE;
        g_xy_dma_y_handle.Init.PeriphDataAlignment = DMA_PDATAALIGN_HALFWORD;
        g_xy_dma_y_handle.Init.MemDataAlignment = DMA_MDATAALIGN_HALFWORD;
        g_xy_dma_y_handle.Init.Mode = DMA_CIRCULAR;
        g_xy_dma_y_handle.Init.Priority = DMA_PRIORITY_VERY_HIGH;
        g_xy_dma_y_handle.Init.FIFOMode = DMA_FIFOMODE_DISABLE;
        g_xy_dma_y_handle.Init.FIFOThreshold = DMA_FIFO_THRESHOLD_1QUARTERFULL;
        g_xy_dma_y_handle.Init.MemBurst = DMA_MBURST_SINGLE;
        g_xy_dma_y_handle.Init.PeriphBurst = DMA_PBURST_SINGLE;
        HAL_DMA_Init(&g_xy_dma_y_handle);

        __HAL_LINKDMA(hdac, DMA_Handle2, g_xy_dma_y_handle);

        HAL_NVIC_SetPriority(XY_DAC_DMA_Y_IRQn, 0, 0);
        HAL_NVIC_EnableIRQ(XY_DAC_DMA_Y_IRQn);

        /* ---------------- X通道 DMA：DAC1 -> DMA1 Stream5 Channel7 ---------------- */
        g_xy_dma_x_handle.Instance = XY_DAC_DMA_X_STREAM;
        g_xy_dma_x_handle.Init.Channel = XY_DAC_DMA_X_CHANNEL;
        g_xy_dma_x_handle.Init.Direction = DMA_MEMORY_TO_PERIPH;
        g_xy_dma_x_handle.Init.PeriphInc = DMA_PINC_DISABLE;
        g_xy_dma_x_handle.Init.MemInc = DMA_MINC_ENABLE;
        g_xy_dma_x_handle.Init.PeriphDataAlignment = DMA_PDATAALIGN_HALFWORD;
        g_xy_dma_x_handle.Init.MemDataAlignment = DMA_MDATAALIGN_HALFWORD;
        g_xy_dma_x_handle.Init.Mode = DMA_CIRCULAR;
        g_xy_dma_x_handle.Init.Priority = DMA_PRIORITY_VERY_HIGH;
        g_xy_dma_x_handle.Init.FIFOMode = DMA_FIFOMODE_DISABLE;
        g_xy_dma_x_handle.Init.FIFOThreshold = DMA_FIFO_THRESHOLD_1QUARTERFULL;
        g_xy_dma_x_handle.Init.MemBurst = DMA_MBURST_SINGLE;
        g_xy_dma_x_handle.Init.PeriphBurst = DMA_PBURST_SINGLE;
        HAL_DMA_Init(&g_xy_dma_x_handle);

        __HAL_LINKDMA(hdac, DMA_Handle1, g_xy_dma_x_handle);

        HAL_NVIC_SetPriority(XY_DAC_DMA_X_IRQn, 0, 0);
        HAL_NVIC_EnableIRQ(XY_DAC_DMA_X_IRQn);

        /* ---------------- TIM7 ---------------- */
        g_xy_tim_handle.Instance = XY_DAC_TIM;
        HAL_TIM_Base_Init(&g_xy_tim_handle);

        tim_master_config_struct.MasterOutputTrigger = TIM_TRGO_UPDATE;
        tim_master_config_struct.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
        HAL_TIMEx_MasterConfigSynchronization(&g_xy_tim_handle, &tim_master_config_struct);
    }
}

/**
 * @brief DAC Channel2 / Y DMA interrupt
 */
void XY_DAC_DMA_Y_IRQHandler(void)
{
    HAL_DMA_IRQHandler(&g_xy_dma_y_handle);
}

/**
 * @brief DAC Channel1 / X DMA interrupt
 */
void XY_DAC_DMA_X_IRQHandler(void)
{
    HAL_DMA_IRQHandler(&g_xy_dma_x_handle);
}

/**
 * @brief 启动同步X/Y波形输出
 * @param samples 每周期采样点数
 * @param arr     TIM7 ARR
 * @param psc     TIM7 PSC
 */
HAL_StatusTypeDef xy_dac_start(uint16_t samples, uint16_t arr, uint16_t psc)
{
    HAL_StatusTypeDef status;

    if (samples < 2U)
    {
        return HAL_ERROR;
    }

    /* 先停止旧输出 */
    HAL_TIM_Base_Stop(&g_xy_tim_handle);
    HAL_DAC_Stop_DMA(&g_xy_dac_handle, XY_DAC_CH_Y);
    HAL_DAC_Stop_DMA(&g_xy_dac_handle, XY_DAC_CH_X);

    /* 配置采样时钟 */
    g_xy_tim_handle.Init.Prescaler = psc;
    g_xy_tim_handle.Init.CounterMode = TIM_COUNTERMODE_UP;
    g_xy_tim_handle.Init.Period = arr;
    g_xy_tim_handle.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
    g_xy_tim_handle.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
    HAL_TIM_Base_Init(&g_xy_tim_handle);

    TIM_MasterConfigTypeDef tim_master_config_struct = {0};
    tim_master_config_struct.MasterOutputTrigger = TIM_TRGO_UPDATE;
    tim_master_config_struct.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
    HAL_TIMEx_MasterConfigSynchronization(&g_xy_tim_handle, &tim_master_config_struct);

    /* 先启动两路DMA，再启动TIM7。
     * 这样第一颗TIM7触发脉冲会同时驱动两个DAC通道。
     */
    status = HAL_DAC_Start_DMA(
        &g_xy_dac_handle,
        XY_DAC_CH_Y,
        (uint32_t *)g_hyst_buf_y,
        samples,
        DAC_ALIGN_12B_R
    );
    if (status != HAL_OK)
    {
        return status;
    }

    status = HAL_DAC_Start_DMA(
        &g_xy_dac_handle,
        XY_DAC_CH_X,
        (uint32_t *)g_hyst_buf_x,
        samples,
        DAC_ALIGN_12B_R
    );
    if (status != HAL_OK)
    {
        HAL_DAC_Stop_DMA(&g_xy_dac_handle, XY_DAC_CH_Y);
        return status;
    }

    __HAL_TIM_SET_COUNTER(&g_xy_tim_handle, 0);
    status = HAL_TIM_Base_Start(&g_xy_tim_handle);
    if (status != HAL_OK)
    {
        HAL_DAC_Stop_DMA(&g_xy_dac_handle, XY_DAC_CH_Y);
        HAL_DAC_Stop_DMA(&g_xy_dac_handle, XY_DAC_CH_X);
    }
    return status;
}

HAL_StatusTypeDef xy_dac_set_timer(uint16_t arr, uint16_t psc)
{
    if ((g_xy_tim_handle.Instance != XY_DAC_TIM) ||
        ((XY_DAC_TIM->CR1 & TIM_CR1_CEN) == 0U))
    {
        return HAL_ERROR;
    }

    /* Change the sample rate without stopping either circular DMA stream. */
    __HAL_TIM_SET_PRESCALER(&g_xy_tim_handle, psc);
    __HAL_TIM_SET_AUTORELOAD(&g_xy_tim_handle, arr);
    __HAL_TIM_SET_COUNTER(&g_xy_tim_handle, 0U);
    SET_BIT(XY_DAC_TIM->EGR, TIM_EGR_UG);
    return HAL_OK;
}

/**
 * @brief 停止X/Y输出
 */
void xy_dac_stop(void)
{
    HAL_TIM_Base_Stop(&g_xy_tim_handle);
    HAL_DAC_Stop_DMA(&g_xy_dac_handle, XY_DAC_CH_Y);
    HAL_DAC_Stop_DMA(&g_xy_dac_handle, XY_DAC_CH_X);
}
