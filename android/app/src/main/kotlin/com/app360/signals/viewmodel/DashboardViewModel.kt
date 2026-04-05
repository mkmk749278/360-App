package com.app360.signals.viewmodel

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app360.signals.data.api.ConnectionState
import com.app360.signals.data.models.Signal
import com.app360.signals.data.repository.SignalRepository
import com.app360.signals.ui.theme.DEFAULT_MIN_CONFIDENCE
import com.app360.signals.ui.theme.MIN_CONFIDENCE_KEY
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import javax.inject.Inject

enum class FilterOption { ALL, LONG, SHORT, SCALP, FVG, CVD, VWAP, OBI }

@HiltViewModel
class DashboardViewModel @Inject constructor(
    private val repository: SignalRepository,
    private val dataStore: DataStore<Preferences>,
) : ViewModel() {

    private val _selectedFilter = MutableStateFlow(FilterOption.ALL)
    val selectedFilter: StateFlow<FilterOption> = _selectedFilter

    private val _isRefreshing = MutableStateFlow(false)
    val isRefreshing: StateFlow<Boolean> = _isRefreshing

    val connectionState: StateFlow<ConnectionState> = repository.connectionState

    private val _regime = MutableStateFlow("")
    val regime: StateFlow<String> = _regime

    private val _pausedPairs = MutableStateFlow<Map<String, Boolean>>(emptyMap())
    val pausedPairs: StateFlow<Map<String, Boolean>> = _pausedPairs

    private val minConfidence: StateFlow<Int> = dataStore.data
        .map { prefs -> prefs[MIN_CONFIDENCE_KEY] ?: DEFAULT_MIN_CONFIDENCE }
        .stateIn(viewModelScope, SharingStarted.Eagerly, DEFAULT_MIN_CONFIDENCE)

    val signals: StateFlow<List<Signal>> = combine(
        repository.signals,
        _selectedFilter,
        minConfidence,
    ) { sigs, filter, minConf ->
        val filtered = sigs.filter { it.confidence >= minConf }
        when (filter) {
            FilterOption.ALL -> filtered
            FilterOption.LONG -> filtered.filter { it.direction.uppercase() == "LONG" }
            FilterOption.SHORT -> filtered.filter { it.direction.uppercase() == "SHORT" }
            FilterOption.SCALP -> filtered.filter { it.channel.contains("SCALP", ignoreCase = true) }
            FilterOption.FVG -> filtered.filter { it.channel.contains("FVG", ignoreCase = true) }
            FilterOption.CVD -> filtered.filter { it.channel.contains("CVD", ignoreCase = true) }
            FilterOption.VWAP -> filtered.filter { it.channel.contains("VWAP", ignoreCase = true) }
            FilterOption.OBI -> filtered.filter { it.channel.contains("OBI", ignoreCase = true) }
        }
    }.stateIn(viewModelScope, SharingStarted.Lazily, emptyList())

    init {
        startStatusPolling()
    }

    private fun startStatusPolling() {
        viewModelScope.launch {
            while (isActive) {
                try {
                    val status = repository.fetchStatus()
                    if (status != null) {
                        _regime.value = status.regime
                        _pausedPairs.value = status.perPairBreaker
                    }
                } catch (_: Exception) { /* keep previous values */ }
                delay(30_000L)
            }
        }
    }

    fun setFilter(filter: FilterOption) { _selectedFilter.value = filter }

    fun refresh() {
        viewModelScope.launch {
            _isRefreshing.value = true
            try { repository.refreshSignals() } catch (e: Exception) { /* ignore */ }
            finally { _isRefreshing.value = false }
        }
    }

    fun connect(baseUrl: String) = repository.connectWebSocket(baseUrl)
    fun disconnect() = repository.disconnectWebSocket()
}
