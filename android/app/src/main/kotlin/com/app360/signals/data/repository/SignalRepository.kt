package com.app360.signals.data.repository

import com.app360.signals.data.api.ApiClientHolder
import com.app360.signals.data.api.ConnectionState
import com.app360.signals.data.api.WebSocketClient
import com.app360.signals.data.models.Signal
import com.app360.signals.data.models.Stats
import com.google.firebase.messaging.FirebaseMessaging
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class SignalRepository @Inject constructor(
    private val apiClientHolder: ApiClientHolder,
    private val wsClient: WebSocketClient,
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    val signals: StateFlow<List<Signal>> = wsClient.signals
    val connectionState: StateFlow<ConnectionState> = wsClient.connectionState

    suspend fun fetchActiveSignals(): List<Signal> =
        try { apiClientHolder.getApiService().getActiveSignals() } catch (e: Exception) { emptyList() }

    suspend fun fetchStats(): Stats =
        try { apiClientHolder.getApiService().getStats() } catch (e: Exception) { Stats() }

    suspend fun fetchStatus() =
        try { apiClientHolder.getApiService().getStatus() } catch (e: Exception) { null }

    suspend fun testConnection(baseUrl: String): Boolean =
        try {
            apiClientHolder.getApiService(baseUrl).getHealth()
            true
        } catch (e: Exception) { false }

    fun connectWebSocket(baseUrl: String) {
        apiClientHolder.getApiService(baseUrl)
        wsClient.connect(baseUrl)
        registerFcmToken(baseUrl)
    }

    fun disconnectWebSocket() = wsClient.disconnect()

    suspend fun fetchHistory(limit: Int = 50): List<Signal> =
        try { apiClientHolder.getApiService().getSignalHistory(limit) } catch (e: Exception) { emptyList() }

    suspend fun updateSignalLimits(limits: Map<String, Int>): Boolean =
        try {
            apiClientHolder.getApiService().updateSignalLimits(limits)
            true
        } catch (e: Exception) { false }

    suspend fun refreshSignals(): List<Signal> {
        val serverSignals = fetchActiveSignals()
        wsClient.updateSignals(serverSignals)
        return wsClient.signals.value
    }

    fun registerFcmToken(baseUrl: String) {
        try {
            FirebaseMessaging.getInstance().token.addOnSuccessListener { token ->
                scope.launch {
                    try {
                        apiClientHolder.getApiService(baseUrl).registerFcmToken(
                            mapOf("token" to token, "device_id" to android.os.Build.ID),
                        )
                    } catch (e: Exception) { /* silent fail */ }
                }
            }
        } catch (e: Exception) { /* Firebase not configured */ }
    }
}
