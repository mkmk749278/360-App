package com.app360.signals.viewmodel

import com.app360.signals.data.models.PairStats
import com.app360.signals.data.models.Stats
import com.app360.signals.data.models.StatusResponse
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class StatsViewModelTest {

    @Test
    fun `Stats defaults are correct`() {
        val stats = Stats()
        assertEquals(0, stats.wins)
        assertEquals(0, stats.losses)
        assertEquals(0.0, stats.winRate, 0.001)
        assertEquals(0.0, stats.avgPnl, 0.001)
        assertEquals(0, stats.total)
        assertTrue(stats.perPair.isEmpty())
    }

    @Test
    fun `Stats with per-pair data stores correctly`() {
        val pairStats = listOf(
            PairStats(symbol = "BTCUSDT", winRate = 75.0, avgPnl = 1.2, total = 8),
            PairStats(symbol = "ETHUSDT", winRate = 60.0, avgPnl = 0.5, total = 5),
        )
        val stats = Stats(wins = 10, losses = 5, winRate = 66.7, avgPnl = 0.8, total = 15, perPair = pairStats)
        assertEquals(2, stats.perPair.size)
        assertEquals("BTCUSDT", stats.perPair[0].symbol)
        assertEquals(75.0, stats.perPair[0].winRate, 0.001)
    }

    @Test
    fun `PairStats defaults are correct`() {
        val ps = PairStats()
        assertEquals("", ps.symbol)
        assertEquals(0.0, ps.winRate, 0.001)
        assertEquals(0.0, ps.avgPnl, 0.001)
        assertEquals(0, ps.total)
    }

    @Test
    fun `StatusResponse includes perPairBreaker field`() {
        val status = StatusResponse(regime = "TRENDING_UP", perPairBreaker = mapOf("PEPEUSDT" to true))
        assertEquals(1, status.perPairBreaker.size)
        assertEquals(true, status.perPairBreaker["PEPEUSDT"])
        assertEquals("TRENDING_UP", status.regime)
    }

    @Test
    fun `StatusResponse defaults have empty breaker map`() {
        val status = StatusResponse()
        assertTrue(status.perPairBreaker.isEmpty())
        assertEquals("", status.regime)
        assertEquals("OK", status.circuitBreakerState)
    }
}
