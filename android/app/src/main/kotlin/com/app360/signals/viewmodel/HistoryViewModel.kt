package com.app360.signals.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app360.signals.data.models.Signal
import com.app360.signals.data.repository.SignalRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class HistoryViewModel @Inject constructor(
    private val repository: SignalRepository,
) : ViewModel() {

    private val _history = MutableStateFlow<List<Signal>>(emptyList())
    val history: StateFlow<List<Signal>> = _history

    private val _isLoading = MutableStateFlow(false)
    val isLoading: StateFlow<Boolean> = _isLoading

    init {
        loadHistory()
    }

    fun loadHistory() {
        viewModelScope.launch {
            _isLoading.value = true
            try {
                _history.value = repository.fetchHistory(limit = 50)
            } catch (_: Exception) { /* keep previous */ }
            finally {
                _isLoading.value = false
            }
        }
    }
}
