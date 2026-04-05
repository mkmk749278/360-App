package com.app360.signals.data.api

import com.app360.signals.ui.theme.DEFAULT_BACKEND_URL
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class ApiClientHolder @Inject constructor(
    private val okHttpClient: OkHttpClient,
    private val json: Json,
) {
    @Volatile private var currentBaseUrl: String = DEFAULT_BACKEND_URL
    @Volatile private var apiService: ApiService = buildService(currentBaseUrl)
    private val lock = Any()

    fun getApiService(baseUrl: String): ApiService {
        if (baseUrl != currentBaseUrl) {
            synchronized(lock) {
                if (baseUrl != currentBaseUrl) {
                    currentBaseUrl = baseUrl
                    apiService = buildService(baseUrl)
                }
            }
        }
        return apiService
    }

    fun getApiService(): ApiService = apiService

    private fun buildService(baseUrl: String): ApiService {
        val url = if (baseUrl.endsWith("/")) baseUrl else "$baseUrl/"
        return Retrofit.Builder()
            .baseUrl(url)
            .client(okHttpClient)
            .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
            .build()
            .create(ApiService::class.java)
    }
}
