package com.app360.signals.ui.screens

import androidx.compose.animation.core.*
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.app360.signals.ui.theme.*
import com.app360.signals.viewmodel.StatsViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun StatsScreen(viewModel: StatsViewModel = hiltViewModel()) {
    val stats by viewModel.stats.collectAsStateWithLifecycle()
    val isLoading by viewModel.isLoading.collectAsStateWithLifecycle()
    val circuitBreakerState by viewModel.circuitBreakerState.collectAsStateWithLifecycle()

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        "Performance",
                        fontWeight = FontWeight.Bold,
                        color = OnBackground,
                        fontSize = 18.sp,
                    )
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = CardBackground),
            )
        },
        containerColor = Background,
    ) { padding ->
        if (isLoading && stats == null) {
            Box(Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = Teal)
            }
        } else {
            Column(
                Modifier
                    .fillMaxSize()
                    .padding(padding)
                    .verticalScroll(rememberScrollState())
                    .padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                // Circuit Breaker status banner
                val isTripped = circuitBreakerState == "TRIPPED"
                Card(
                    modifier = Modifier
                        .fillMaxWidth()
                        .border(
                            width = 1.dp,
                            color = if (isTripped) ShortRed else LongGreen,
                            shape = RoundedCornerShape(12.dp),
                        ),
                    colors = CardDefaults.cardColors(
                        containerColor = if (isTripped) ShortRedBg else LongGreenBg,
                    ),
                    shape = RoundedCornerShape(12.dp),
                    elevation = CardDefaults.cardElevation(defaultElevation = 0.dp),
                ) {
                    Row(
                        Modifier.padding(horizontal = 16.dp, vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(if (isTripped) "🔴" else "🟢", fontSize = 16.sp)
                        Spacer(Modifier.width(8.dp))
                        Text(
                            if (isTripped) "Circuit Breaker: TRIPPED — Signals paused"
                            else "Circuit Breaker: OK — Engine active",
                            color = if (isTripped) ShortRed else LongGreen,
                            fontSize = 13.sp,
                            fontWeight = FontWeight.SemiBold,
                        )
                    }
                }
                stats?.let { s ->
                    // 2×2 metric grid
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Row(
                            Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            MetricCard(
                                label = "Win Rate",
                                value = "${s.winRate.toInt()}%",
                                valueColor = when {
                                    s.winRate >= 70 -> ConfidenceHigh
                                    s.winRate >= 50 -> ConfidenceMed
                                    else -> ConfidenceLow
                                },
                                icon = "🎯",
                                modifier = Modifier.weight(1f),
                            )
                            MetricCard(
                                label = "Avg PnL",
                                value = "${if (s.avgPnl >= 0) "+" else ""}${"%.2f".format(s.avgPnl)}%",
                                valueColor = if (s.avgPnl >= 0) LongGreen else ShortRed,
                                icon = if (s.avgPnl >= 0) "📈" else "📉",
                                modifier = Modifier.weight(1f),
                            )
                        }
                        Row(
                            Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            MetricCard(
                                label = "Total Signals",
                                value = "${s.total}",
                                valueColor = Teal,
                                icon = "📊",
                                modifier = Modifier.weight(1f),
                            )
                            MetricCard(
                                label = "W / L",
                                value = "${s.wins} / ${s.losses}",
                                valueColor = OnBackground,
                                icon = "⚔️",
                                modifier = Modifier.weight(1f),
                            )
                        }
                    }

                    // Wins vs Losses bar chart
                    if (s.total > 0) {
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
                                    "Wins vs Losses",
                                    color = OnSurface,
                                    fontSize = 12.sp,
                                    fontWeight = FontWeight.Bold,
                                )
                                Spacer(Modifier.height(16.dp))
                                AnimatedWinLossChart(wins = s.wins, losses = s.losses)
                            }
                        }
                    }
                } ?: run {
                    Box(
                        Modifier
                            .fillMaxWidth()
                            .padding(vertical = 32.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text("No stats available yet", color = OnSurface, fontSize = 14.sp)
                    }
                }

                Button(
                    onClick = viewModel::loadStats,
                    modifier = Modifier.fillMaxWidth(),
                    colors = ButtonDefaults.buttonColors(containerColor = Surface),
                    shape = RoundedCornerShape(12.dp),
                ) {
                    Text("Refresh Stats", color = Teal, fontWeight = FontWeight.SemiBold)
                }
            }
        }
    }
}

@Composable
fun MetricCard(
    label: String,
    value: String,
    valueColor: Color,
    icon: String,
    modifier: Modifier = Modifier,
) {
    Card(
        modifier = modifier.border(
            width = 1.dp,
            brush = Brush.linearGradient(
                listOf(GradientStart.copy(alpha = 0.5f), GradientEnd.copy(alpha = 0.5f)),
            ),
            shape = RoundedCornerShape(16.dp),
        ),
        colors = CardDefaults.cardColors(containerColor = CardBackground),
        shape = RoundedCornerShape(16.dp),
        elevation = CardDefaults.cardElevation(defaultElevation = 0.dp),
    ) {
        Column(
            Modifier.padding(16.dp),
            horizontalAlignment = Alignment.Start,
        ) {
            Text(icon, fontSize = 18.sp)
            Spacer(Modifier.height(8.dp))
            Text(
                value,
                color = valueColor,
                fontWeight = FontWeight.ExtraBold,
                fontSize = 22.sp,
                fontFamily = FontFamily.Monospace,
            )
            Spacer(Modifier.height(4.dp))
            Text(label, color = OnSurfaceDim, fontSize = 11.sp)
        }
    }
}

@Composable
fun AnimatedWinLossChart(wins: Int, losses: Int) {
    val total = (wins + losses).coerceAtLeast(1)
    val winTargetFraction = wins.toFloat() / total
    val lossTargetFraction = losses.toFloat() / total

    val winFraction by animateFloatAsState(
        targetValue = winTargetFraction,
        animationSpec = tween(1000, easing = FastOutSlowInEasing),
        label = "win_fraction",
    )
    val lossFraction by animateFloatAsState(
        targetValue = lossTargetFraction,
        animationSpec = tween(1000, easing = FastOutSlowInEasing),
        label = "loss_fraction",
    )

    Box(
        Modifier
            .fillMaxWidth()
            .height(140.dp),
    ) {
        Canvas(Modifier.fillMaxSize()) {
            val maxHeight = size.height * 0.70f
            val barWidth = size.width * 0.25f
            val cornerRadius = CornerRadius(8f, 8f)
            val gridLineColor = Color(0xFF1E293B)

            // Horizontal grid lines at 25%, 50%, 75%
            for (i in 1..3) {
                val y = size.height - (maxHeight * i / 4) - 20f
                drawLine(
                    color = gridLineColor,
                    start = Offset(0f, y),
                    end = Offset(size.width, y),
                    strokeWidth = 0.5f,
                )
            }

            // Wins bar
            val winsHeight = maxHeight * winFraction
            if (winsHeight > 0) {
                drawRoundRect(
                    color = LongGreen,
                    topLeft = Offset(size.width * 0.15f, size.height - winsHeight - 20f),
                    size = Size(barWidth, winsHeight),
                    cornerRadius = cornerRadius,
                )
            }

            // Losses bar
            val lossHeight = maxHeight * lossFraction
            if (lossHeight > 0) {
                drawRoundRect(
                    color = ShortRed,
                    topLeft = Offset(size.width * 0.60f, size.height - lossHeight - 20f),
                    size = Size(barWidth, lossHeight),
                    cornerRadius = cornerRadius,
                )
            }
        }

        // Count labels above bars and axis labels below
        Row(
            Modifier
                .fillMaxWidth()
                .align(Alignment.BottomStart),
            horizontalArrangement = Arrangement.SpaceEvenly,
        ) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text("$wins", color = LongGreen, fontSize = 14.sp, fontWeight = FontWeight.Bold)
                Text("Wins", color = OnSurfaceDim, fontSize = 10.sp)
            }
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text("$losses", color = ShortRed, fontSize = 14.sp, fontWeight = FontWeight.Bold)
                Text("Losses", color = OnSurfaceDim, fontSize = 10.sp)
            }
        }
    }
}

@Composable
fun StatItem(label: String, value: String, valueColor: Color) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(value, color = valueColor, fontWeight = FontWeight.Bold, fontSize = 20.sp)
        Text(label, color = OnSurface.copy(alpha = 0.6f), fontSize = 11.sp)
    }
}

@Composable
fun WinLossBarChart(wins: Int, losses: Int) {
    AnimatedWinLossChart(wins = wins, losses = losses)
}
