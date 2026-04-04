package com.app360.signals.data.models

import kotlin.math.abs
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class Signal(
    val id: String = "",
    @SerialName("signal_id") val signalId: String = "",
    val symbol: String = "",
    val channel: String = "",
    val direction: String = "LONG",
    val entry: Double = 0.0,
    @SerialName("stop_loss") val stopLoss: Double = 0.0,
    val tp1: Double = 0.0,
    val tp2: Double = 0.0,
    val tp3: Double? = null,
    val confidence: Double = 0.0,
    @SerialName("quality_tier") val qualityTier: String = "B",
    @SerialName("risk_label") val riskLabel: String = "",
    @SerialName("setup_class") val setupClass: String = "",
    @SerialName("market_phase") val marketPhase: String = "",
    @SerialName("liquidity_info") val liquidityInfo: String = "",
    @SerialName("analyst_reason") val analystReason: String = "",
    val timestamp: String = "",
    val status: String = "ACTIVE",
) {
    val effectiveId: String get() = id.ifBlank { signalId }

    val rrRatio: Double
        get() {
            val risk = abs(entry - stopLoss)
            return if (risk > 0) abs(tp1 - entry) / risk else 0.0
        }
}
