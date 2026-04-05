package com.app360.signals.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app360.signals.data.models.Stats
import com.app360.signals.data.repository.SignalRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class StatsViewModel @Inject constructor(
    private val repository: SignalRepository,
) : ViewModel() {

    private val _stats = MutableStateFlow<Stats?>(null)
    val stats: StateFlow<Stats?> = _stats

    private val _isLoading = MutableStateFlow(false)
    val isLoading: StateFlow<Boolean> = _isLoading

    private val _circuitBreakerState = MutableStateFlow("OK")
    val circuitBreakerState: StateFlow<String> = _circuitBreakerState

    init {
        loadStats()
        startStatusPolling()
    }

    fun loadStats() {
        viewModelScope.launch {
            _isLoading.value = true
            try { _stats.value = repository.fetchStats() }
            catch (e: Exception) { /* keep previous */ }
            finally { _isLoading.value = false }
        }
    }

    private fun startStatusPolling() {
        viewModelScope.launch {
            while (isActive) {
                try {
                    val status = repository.fetchStatus()
                    if (status != null) {
                        _circuitBreakerState.value = status.circuitBreakerState
                    }
                } catch (e: Exception) { /* ignore */ }
                delay(30_000L)
            }
        }
    }
}
