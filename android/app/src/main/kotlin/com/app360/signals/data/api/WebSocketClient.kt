package com.app360.signals.data.api

import android.util.Log
import com.app360.signals.data.models.Signal
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.serialization.json.Json
import okhttp3.*
import javax.inject.Inject
import javax.inject.Singleton

enum class ConnectionState { CONNECTED, DISCONNECTED, RECONNECTING }

@Singleton
class WebSocketClient @Inject constructor(private val okHttpClient: OkHttpClient) {

    private val TAG = "WebSocketClient"
    private val _connectionState = MutableStateFlow(ConnectionState.DISCONNECTED)
    val connectionState: StateFlow<ConnectionState> = _connectionState

    private val _signals = MutableStateFlow<List<Signal>>(emptyList())
    val signals: StateFlow<List<Signal>> = _signals

    private var webSocket: WebSocket? = null
    private var baseUrl: String = "http://95.111.241.97:8080"
    private var reconnectJob: Job? = null
    private var reconnectDelay = 1000L
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    private val json = Json { ignoreUnknownKeys = true; coerceInputValues = true }

    fun connect(url: String) {
        baseUrl = url
        reconnectDelay = 1000L
        doConnect()
    }

    private fun doConnect() {
        val wsUrl = baseUrl.replace("http://", "ws://").replace("https://", "wss://") + "/ws/signals"
        val request = Request.Builder().url(wsUrl).build()
        webSocket = okHttpClient.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(ws: WebSocket, response: Response) {
                Log.i(TAG, "WebSocket connected")
                _connectionState.value = ConnectionState.CONNECTED
                reconnectDelay = 1000L
            }

            override fun onMessage(ws: WebSocket, text: String) {
                try {
                    if (text.contains("\"type\":\"heartbeat\"")) return
                    val signal = json.decodeFromString<Signal>(text)
                    val current = _signals.value.toMutableList()
                    current.removeAll { it.effectiveId == signal.effectiveId }
                    current.add(0, signal)
                    _signals.value = current.take(200)
                } catch (e: Exception) {
                    Log.w(TAG, "Failed to parse WS message: $text", e)
                }
            }

            override fun onClosing(ws: WebSocket, code: Int, reason: String) {
                ws.close(1000, null)
                scheduleReconnect()
            }

            override fun onFailure(ws: WebSocket, t: Throwable, response: Response?) {
                Log.w(TAG, "WebSocket failure: ${t.message}")
                scheduleReconnect()
            }
        })
    }

    private fun scheduleReconnect() {
        _connectionState.value = ConnectionState.RECONNECTING
        reconnectJob?.cancel()
        reconnectJob = scope.launch {
            delay(reconnectDelay)
            reconnectDelay = minOf(reconnectDelay * 2, 30_000L)
            doConnect()
        }
    }

    fun disconnect() {
        reconnectJob?.cancel()
        webSocket?.close(1000, "User disconnect")
        webSocket = null
        _connectionState.value = ConnectionState.DISCONNECTED
    }

    fun updateSignals(serverSignals: List<Signal>) {
        val wsSignals = _signals.value
        val merged = (wsSignals + serverSignals)
            .distinctBy { it.effectiveId }
            .sortedByDescending { it.timestamp }
        _signals.value = merged
    }
}
