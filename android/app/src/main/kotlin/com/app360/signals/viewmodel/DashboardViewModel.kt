package com.app360.signals.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app360.signals.data.api.ConnectionState
import com.app360.signals.data.models.Signal
import com.app360.signals.data.repository.SignalRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.*
import javax.inject.Inject

enum class FilterOption { ALL, LONG, SHORT, SCALP, FVG, CVD, VWAP, OBI }

@HiltViewModel
class DashboardViewModel @Inject constructor(
    private val repository: SignalRepository,
) : ViewModel() {

    private val _selectedFilter = MutableStateFlow(FilterOption.ALL)
    val selectedFilter: StateFlow<FilterOption> = _selectedFilter

    private val _isRefreshing = MutableStateFlow(false)
    val isRefreshing: StateFlow<Boolean> = _isRefreshing

    val connectionState: StateFlow<ConnectionState> = repository.connectionState

    val signals: StateFlow<List<Signal>> = combine(
        repository.signals,
        _selectedFilter,
    ) { sigs, filter ->
        when (filter) {
            FilterOption.ALL -> sigs
            FilterOption.LONG -> sigs.filter { it.direction.uppercase() == "LONG" }
            FilterOption.SHORT -> sigs.filter { it.direction.uppercase() == "SHORT" }
            FilterOption.SCALP -> sigs.filter { it.channel.contains("SCALP", ignoreCase = true) }
            FilterOption.FVG -> sigs.filter { it.channel.contains("FVG", ignoreCase = true) }
            FilterOption.CVD -> sigs.filter { it.channel.contains("CVD", ignoreCase = true) }
            FilterOption.VWAP -> sigs.filter { it.channel.contains("VWAP", ignoreCase = true) }
            FilterOption.OBI -> sigs.filter { it.channel.contains("OBI", ignoreCase = true) }
        }
    }.stateIn(viewModelScope, SharingStarted.Lazily, emptyList())

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
