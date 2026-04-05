package com.app360.signals.data.models

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class Stats(
    val wins: Int = 0,
    val losses: Int = 0,
    @SerialName("win_rate") val winRate: Double = 0.0,
    @SerialName("avg_pnl") val avgPnl: Double = 0.0,
    val total: Int = 0,
)

@Serializable
data class HealthResponse(
    val status: String = "",
    @SerialName("uptime_seconds") val uptimeSeconds: Double = 0.0,
    @SerialName("engine_version") val engineVersion: String = "",
)

@Serializable
data class StatusResponse(
    @SerialName("pairs_count") val pairsCount: Int = 0,
    @SerialName("scan_interval") val scanInterval: Int = 0,
    @SerialName("circuit_breaker_tripped") val circuitBreakerTripped: Boolean = false,
    @SerialName("circuit_breaker_state") val circuitBreakerState: String = "OK",
    @SerialName("circuit_breaker_status") val circuitBreakerStatus: String = "",
    val regime: String = "",
    @SerialName("active_signals_count") val activeSignalsCount: Int = 0,
)
