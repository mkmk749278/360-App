package com.app360.signals.data.repository

import com.app360.signals.data.api.ApiService
import com.app360.signals.data.api.ConnectionState
import com.app360.signals.data.api.WebSocketClient
import com.app360.signals.data.models.Signal
import com.app360.signals.data.models.Stats
import kotlinx.coroutines.flow.StateFlow
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class SignalRepository @Inject constructor(
    private val apiService: ApiService,
    private val wsClient: WebSocketClient,
) {
    val signals: StateFlow<List<Signal>> = wsClient.signals
    val connectionState: StateFlow<ConnectionState> = wsClient.connectionState

    suspend fun fetchActiveSignals(): List<Signal> =
        try { apiService.getActiveSignals() } catch (e: Exception) { emptyList() }

    suspend fun fetchStats(): Stats =
        try { apiService.getStats() } catch (e: Exception) { Stats() }

    suspend fun testConnection(baseUrl: String): Boolean =
        try {
            apiService.getHealth()
            true
        } catch (e: Exception) { false }

    fun connectWebSocket(baseUrl: String) = wsClient.connect(baseUrl)
    fun disconnectWebSocket() = wsClient.disconnect()

    suspend fun refreshSignals(): List<Signal> {
        val serverSignals = fetchActiveSignals()
        wsClient.updateSignals(serverSignals)
        return wsClient.signals.value
    }
}
