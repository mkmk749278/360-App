package com.app360.signals.data.api

import com.app360.signals.data.models.HealthResponse
import com.app360.signals.data.models.Signal
import com.app360.signals.data.models.Stats
import com.app360.signals.data.models.StatusResponse
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Query

interface ApiService {
    @GET("signals/active")
    suspend fun getActiveSignals(): List<Signal>

    @GET("signals/history")
    suspend fun getSignalHistory(@Query("limit") limit: Int = 50): List<Signal>

    @GET("stats")
    suspend fun getStats(): Stats

    @GET("health")
    suspend fun getHealth(): HealthResponse

    @GET("status")
    suspend fun getStatus(): StatusResponse

    @POST("fcm/register")
    suspend fun registerFcmToken(@Body body: Map<String, String>): Response<Unit>

    @POST("settings/signal_limits")
    suspend fun updateSignalLimits(@Body limits: Map<String, Int>): Response<Unit>
}
