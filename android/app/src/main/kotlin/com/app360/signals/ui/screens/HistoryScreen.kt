package com.app360.signals.ui.screens

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.app360.signals.data.models.Signal
import com.app360.signals.ui.theme.*
import com.app360.signals.viewmodel.HistoryViewModel
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HistoryScreen(viewModel: HistoryViewModel = hiltViewModel()) {
    val history by viewModel.history.collectAsStateWithLifecycle()
    val isLoading by viewModel.isLoading.collectAsStateWithLifecycle()

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        "History",
                        fontWeight = FontWeight.Bold,
                        color = OnBackground,
                        fontSize = 18.sp,
                    )
                },
                actions = {
                    IconButton(onClick = viewModel::loadHistory) {
                        Icon(Icons.Rounded.Refresh, contentDescription = "Refresh", tint = Teal)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = CardBackground),
            )
        },
        containerColor = Background,
    ) { padding ->
        if (isLoading && history.isEmpty()) {
            Box(Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = Teal)
            }
        } else {
            LazyColumn(
                Modifier
                    .fillMaxSize()
                    .padding(padding),
                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                // Mini equity curve from last 30 signals
                if (history.size >= 2) {
                    item {
                        EquityCurveCard(signals = history.takeLast(30))
                    }
                }

                if (history.isEmpty()) {
                    item {
                        Box(
                            Modifier
                                .fillMaxWidth()
                                .padding(vertical = 48.dp),
                            contentAlignment = Alignment.Center,
                        ) {
                            Text("No history yet", color = OnSurface, fontSize = 14.sp)
                        }
                    }
                } else {
                    items(history, key = { it.effectiveId.ifBlank { it.timestamp } }) { signal ->
                        HistorySignalCard(signal = signal)
                    }
                }
            }
        }
    }
}

@Composable
fun EquityCurveCard(signals: List<Signal>) {
    // Compute mock cumulative PnL: +1 for completed TP hit, -1 for SL hit, 0 for open
    val cumulativePnl = run {
        var cum = 0.0
        val points = mutableListOf<Float>()
        points.add(0f)
        signals.forEach { s ->
            val delta = when {
                s.status.contains("TP", ignoreCase = true) -> 1.0
                s.status.contains("SL", ignoreCase = true) -> -1.0
                else -> 0.0
            }
            cum += delta
            points.add(cum.toFloat())
        }
        points
    }

    Card(
        modifier = Modifier
            .fillMaxWidth()
            .border(
                width = 1.dp,
                brush = Brush.linearGradient(listOf(GradientStart, GradientEnd)),
                shape = RoundedCornerShape(16.dp),
            ),
        colors = CardDefaults.cardColors(containerColor = CardBackground),
        shape = RoundedCornerShape(16.dp),
        elevation = CardDefaults.cardElevation(defaultElevation = 0.dp),
    ) {
        Column(Modifier.padding(16.dp)) {
            Text(
                "Equity Curve (last ${signals.size} signals)",
                color = OnSurface,
                fontSize = 12.sp,
                fontWeight = FontWeight.Bold,
            )
            Spacer(Modifier.height(12.dp))
            Canvas(
                Modifier
                    .fillMaxWidth()
                    .height(80.dp),
            ) {
                val pts = cumulativePnl
                if (pts.size < 2) return@Canvas
                val minV = pts.minOrNull() ?: 0f
                val maxV = pts.maxOrNull() ?: 1f
                val range = (maxV - minV).coerceAtLeast(0.01f)

                val stepX = size.width / (pts.size - 1).coerceAtLeast(1)
                val path = Path()
                pts.forEachIndexed { i, v ->
                    val x = i * stepX
                    val y = size.height - ((v - minV) / range) * size.height * 0.85f
                    if (i == 0) path.moveTo(x, y) else path.lineTo(x, y)
                }

                val lastY = size.height - ((pts.last() - minV) / range) * size.height * 0.85f
                val lineColor = if (pts.last() >= 0f) LongGreen else ShortRed
                drawPath(path, color = lineColor, style = Stroke(width = 2.dp.toPx(), cap = StrokeCap.Round))

                // Zero line
                val zeroY = size.height - ((0f - minV) / range) * size.height * 0.85f
                drawLine(
                    color = DividerColor,
                    start = Offset(0f, zeroY),
                    end = Offset(size.width, zeroY),
                    strokeWidth = 0.5.dp.toPx(),
                )
            }
        }
    }
}

@Composable
fun HistorySignalCard(signal: Signal) {
    val isLong = signal.direction.uppercase() == "LONG"
    val directionColor = if (isLong) LongGreen else ShortRed

    val (outcomeLabel, outcomeColor) = when {
        signal.status.contains("TP3", ignoreCase = true) -> "TP3" to LongGreen
        signal.status.contains("TP2", ignoreCase = true) -> "TP2" to LongGreen.copy(alpha = 0.8f)
        signal.status.contains("TP1", ignoreCase = true) -> "TP1" to LongGreen.copy(alpha = 0.6f)
        signal.status.contains("SL", ignoreCase = true) -> "SL" to ShortRed
        else -> "OPEN" to OnSurfaceDim
    }

    // Parse hold duration from timestamp
    val holdDuration = remember(signal.timestamp) {
        try {
            val start = Instant.parse(signal.timestamp)
            val now = Instant.now()
            val mins = java.time.Duration.between(start, now).toMinutes()
            when {
                mins < 60 -> "${mins}m"
                mins < 1440 -> "${mins / 60}h ${mins % 60}m"
                else -> "${mins / 1440}d ${(mins % 1440) / 60}h"
            }
        } catch (_: Exception) { "" }
    }

    Card(
        modifier = Modifier
            .fillMaxWidth()
            .border(
                width = 1.dp,
                color = directionColor.copy(alpha = 0.3f),
                shape = RoundedCornerShape(12.dp),
            ),
        colors = CardDefaults.cardColors(containerColor = CardBackground),
        shape = RoundedCornerShape(12.dp),
        elevation = CardDefaults.cardElevation(defaultElevation = 0.dp),
    ) {
        Row(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            // Symbol + direction
            Column(Modifier.weight(1f)) {
                Text(
                    signal.symbol.removeSuffix("USDT"),
                    color = OnBackground,
                    fontSize = 13.sp,
                    fontWeight = FontWeight.Bold,
                    fontFamily = FontFamily.Monospace,
                )
                Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    Box(
                        Modifier
                            .background(directionColor.copy(alpha = 0.2f), RoundedCornerShape(4.dp))
                            .padding(horizontal = 5.dp, vertical = 1.dp),
                    ) {
                        Text(
                            signal.direction.uppercase(),
                            color = directionColor,
                            fontSize = 9.sp,
                            fontWeight = FontWeight.Bold,
                        )
                    }
                    val channelLabel = signal.channel.removePrefix("360_")
                    Box(
                        Modifier
                            .background(TealDim, RoundedCornerShape(4.dp))
                            .padding(horizontal = 5.dp, vertical = 1.dp),
                    ) {
                        Text(channelLabel, color = Teal, fontSize = 9.sp)
                    }
                }
            }

            // Outcome badge
            Box(
                Modifier
                    .background(outcomeColor.copy(alpha = 0.15f), RoundedCornerShape(6.dp))
                    .padding(horizontal = 8.dp, vertical = 4.dp),
            ) {
                Text(
                    outcomeLabel,
                    color = outcomeColor,
                    fontSize = 11.sp,
                    fontWeight = FontWeight.Bold,
                )
            }

            Spacer(Modifier.width(8.dp))

            // Hold duration
            if (holdDuration.isNotBlank()) {
                Text(
                    holdDuration,
                    color = OnSurfaceDim,
                    fontSize = 10.sp,
                    modifier = Modifier.width(40.dp),
                )
            }

            // Entry price
            Text(
                "${"%.4f".format(signal.entry)}",
                color = OnSurface,
                fontSize = 10.sp,
                fontFamily = FontFamily.Monospace,
            )
        }
    }
}
