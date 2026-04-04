package com.app360.signals.ui.screens

import androidx.compose.foundation.Canvas
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
import androidx.compose.ui.graphics.Color
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

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Performance Stats", color = OnBackground) },
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
                stats?.let { s ->
                    Card(
                        modifier = Modifier.fillMaxWidth(),
                        colors = CardDefaults.cardColors(containerColor = CardBackground),
                        shape = RoundedCornerShape(12.dp),
                    ) {
                        Column(Modifier.padding(16.dp)) {
                            Text(
                                "Today's Performance",
                                color = OnSurface, fontSize = 12.sp, fontWeight = FontWeight.Bold,
                            )
                            Spacer(Modifier.height(14.dp))
                            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
                                StatItem("Win Rate", "${s.winRate.toInt()}%", Teal)
                                StatItem("Wins", "${s.wins}", Color(0xFF00FF88))
                                StatItem("Losses", "${s.losses}", Color(0xFFFF4488))
                                StatItem("Total", "${s.total}", OnBackground)
                            }
                            Spacer(Modifier.height(12.dp))
                            HorizontalDivider(color = DividerColor)
                            Spacer(Modifier.height(12.dp))
                            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center) {
                                StatItem(
                                    "Avg PnL",
                                    "${if (s.avgPnl >= 0) "+" else ""}${"%.2f".format(s.avgPnl)}%",
                                    if (s.avgPnl >= 0) Color(0xFF51CF66) else Color(0xFFFF6B6B),
                                )
                            }
                        }
                    }

                    if (s.total > 0) {
                        Card(
                            modifier = Modifier.fillMaxWidth(),
                            colors = CardDefaults.cardColors(containerColor = CardBackground),
                            shape = RoundedCornerShape(12.dp),
                        ) {
                            Column(Modifier.padding(16.dp)) {
                                Text(
                                    "Wins vs Losses",
                                    color = OnSurface, fontSize = 12.sp, fontWeight = FontWeight.Bold,
                                )
                                Spacer(Modifier.height(16.dp))
                                WinLossBarChart(wins = s.wins, losses = s.losses)
                            }
                        }
                    }
                } ?: run {
                    Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                        Text("No stats available yet", color = OnSurface)
                    }
                }

                Button(
                    onClick = viewModel::loadStats,
                    modifier = Modifier.fillMaxWidth(),
                    colors = ButtonDefaults.buttonColors(containerColor = Surface),
                    shape = RoundedCornerShape(8.dp),
                ) {
                    Text("Refresh Stats", color = Teal)
                }
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
    val total = (wins + losses).coerceAtLeast(1)
    val winFraction = wins.toFloat() / total
    val lossFraction = losses.toFloat() / total

    Canvas(
        Modifier
            .fillMaxWidth()
            .height(120.dp),
    ) {
        val barWidth = size.width / 3f
        val maxHeight = size.height * 0.85f
        val winsHeight = maxHeight * winFraction
        val lossHeight = maxHeight * lossFraction
        val cornerRadius = CornerRadius(6f, 6f)
        val gap = size.width / 6f

        drawRoundRect(
            color = Color(0xFF00D4AA),
            topLeft = Offset(gap, size.height - winsHeight),
            size = Size(barWidth, winsHeight),
            cornerRadius = cornerRadius,
        )
        drawRoundRect(
            color = Color(0xFFFF4488),
            topLeft = Offset(gap * 2 + barWidth, size.height - lossHeight),
            size = Size(barWidth, lossHeight),
            cornerRadius = cornerRadius,
        )
    }
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
        Text("Wins ($wins)", color = Teal, fontSize = 11.sp)
        Text("Losses ($losses)", color = ShortRed, fontSize = 11.sp)
    }
}
