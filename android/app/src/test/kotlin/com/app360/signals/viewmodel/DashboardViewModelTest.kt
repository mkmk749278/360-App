package com.app360.signals.viewmodel

import org.junit.Assert.assertEquals
import org.junit.Test

class DashboardViewModelTest {

    @Test
    fun `FilterOption has all expected values`() {
        val expected = listOf("ALL", "LONG", "SHORT", "SCALP", "FVG", "CVD", "VWAP", "OBI")
        val actual = FilterOption.entries.map { it.name }
        assertEquals(expected, actual)
    }

    @Test
    fun `FilterOption ALL is first`() {
        assertEquals(FilterOption.ALL, FilterOption.entries.first())
    }

    @Test
    fun `FilterOption has eight values`() {
        assertEquals(8, FilterOption.entries.size)
    }
}
