package com.app360.signals.ui.screens

import androidx.compose.animation.*
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.app360.signals.data.api.ConnectionState
import com.app360.signals.data.models.Signal
import com.app360.signals.ui.theme.*
import com.app360.signals.viewmodel.DashboardViewModel
import com.app360.signals.viewmodel.FilterOption
import java.time.Instant
import java.time.temporal.ChronoUnit

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DashboardScreen(
    onSignalClick: (Signal) -> Unit,
    viewModel: DashboardViewModel = hiltViewModel(),
) {
    val signals by viewModel.signals.collectAsStateWithLifecycle()
    val filter by viewModel.selectedFilter.collectAsStateWithLifecycle()
    val isRefreshing by viewModel.isRefreshing.collectAsStateWithLifecycle()
    val connectionState by viewModel.connectionState.collectAsStateWithLifecycle()

    Scaffold(
        topBar = {
            Column {
                TopAppBar(
                    title = {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text("360 Signals", fontWeight = FontWeight.Bold, color = OnBackground)
                            Spacer(Modifier.width(8.dp))
                            ConnectionDot(connectionState)
                        }
                    },
                    colors = TopAppBarDefaults.topAppBarColors(containerColor = CardBackground),
                )
                AnimatedVisibility(visible = connectionState != ConnectionState.CONNECTED) {
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .background(
                                if (connectionState == ConnectionState.RECONNECTING)
                                    Color(0xFF4A3000) else Color(0xFF3A0000)
                            )
                            .padding(horizontal = 16.dp, vertical = 6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            if (connectionState == ConnectionState.RECONNECTING)
                                "🔄 Reconnecting to live feed…" else "🔴 Disconnected",
                            color = Color(0xFFFFCC44),
                            fontSize = 12.sp,
                        )
                    }
                }
                LazyRow(
                    Modifier
                        .fillMaxWidth()
                        .background(CardBackground)
                        .padding(horizontal = 12.dp, vertical = 8.dp),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    items(FilterOption.values()) { f ->
                        FilterChip(
                            selected = filter == f,
                            onClick = { viewModel.setFilter(f) },
                            label = { Text(f.name, fontSize = 11.sp) },
                            colors = FilterChipDefaults.filterChipColors(
                                selectedContainerColor = Teal,
                                selectedLabelColor = Color.Black,
                                containerColor = Surface,
                                labelColor = OnSurface,
                            ),
                        )
                    }
                }
            }
        },
        containerColor = Background,
    ) { padding ->
        PullToRefreshBox(
            isRefreshing = isRefreshing,
            onRefresh = viewModel::refresh,
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
        ) {
            if (signals.isEmpty()) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text("📡", fontSize = 48.sp)
                        Spacer(Modifier.height(12.dp))
                        Text("Waiting for signals…", color = OnSurface, fontSize = 14.sp)
                    }
                }
            } else {
                LazyColumn(
                    Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(horizontal = 12.dp, vertical = 8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    items(signals, key = { it.effectiveId.ifBlank { it.timestamp } }) { signal ->
                        var visible by remember { mutableStateOf(false) }
                        LaunchedEffect(signal.effectiveId) { visible = true }
                        AnimatedVisibility(
                            visible = visible,
                            enter = slideInVertically(initialOffsetY = { -it / 2 }) + fadeIn(),
                        ) {
                            SignalCard(signal = signal, onClick = { onSignalClick(signal) })
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun SignalCard(signal: Signal, onClick: () -> Unit) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
        colors = CardDefaults.cardColors(containerColor = CardBackground),
        shape = RoundedCornerShape(12.dp),
        border = BorderStroke(0.5.dp, DividerColor),
    ) {
        Column(Modifier.padding(14.dp)) {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text(signal.symbol, fontWeight = FontWeight.Bold, color = OnBackground, fontSize = 16.sp)
                    DirectionBadge(signal.direction)
                    ChannelPill(signal.channel)
                }
                Column(horizontalAlignment = Alignment.End) {
                    QualityBadge(signal.qualityTier)
                    Spacer(Modifier.height(2.dp))
                    Text(timeAgo(signal.timestamp), color = OnSurface, fontSize = 10.sp)
                }
            }
            Spacer(Modifier.height(10.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                PriceItem("Entry", signal.entry)
                PriceItem("SL", signal.stopLoss, color = Color(0xFFFF6B6B))
                PriceItem("TP1", signal.tp1, color = Color(0xFF51CF66))
                if (signal.tp2 > 0) PriceItem("TP2", signal.tp2, color = Color(0xFF69DB7C))
            }
            Spacer(Modifier.height(10.dp))
            ConfidenceBar(signal.confidence)
            if (signal.riskLabel.isNotBlank()) {
                Spacer(Modifier.height(4.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    if (signal.setupClass.isNotBlank()) {
                        Text(
                            signal.setupClass, color = OnSurface, fontSize = 10.sp,
                            modifier = Modifier
                                .background(Surface, RoundedCornerShape(4.dp))
                                .padding(horizontal = 4.dp, vertical = 2.dp),
                        )
                    }
                    Text(
                        signal.riskLabel, color = OnSurface, fontSize = 10.sp,
                        modifier = Modifier
                            .background(Surface, RoundedCornerShape(4.dp))
                            .padding(horizontal = 4.dp, vertical = 2.dp),
                    )
                }
            }
        }
    }
}

@Composable
fun DirectionBadge(direction: String) {
    val isLong = direction.uppercase() == "LONG"
    Box(
        Modifier
            .background(if (isLong) LongGreenBg else ShortRedBg, RoundedCornerShape(4.dp))
            .padding(horizontal = 6.dp, vertical = 2.dp),
    ) {
        Text(
            direction.uppercase(),
            color = if (isLong) LongGreen else ShortRed,
            fontSize = 10.sp,
            fontWeight = FontWeight.Bold,
        )
    }
}

@Composable
fun ChannelPill(channel: String) {
    val short = channel.removePrefix("360_").take(8)
    Box(
        Modifier
            .background(Surface, RoundedCornerShape(10.dp))
            .padding(horizontal = 6.dp, vertical = 2.dp),
    ) {
        Text(short, color = Teal, fontSize = 9.sp, fontWeight = FontWeight.Medium)
    }
}

@Composable
fun QualityBadge(tier: String) {
    val color = when (tier) {
        "A+" -> Color(0xFF00D4AA)
        "A" -> Color(0xFF51CF66)
        "B+" -> Color(0xFFFFCC44)
        else -> Color(0xFF999999)
    }
    Box(
        Modifier
            .background(color.copy(alpha = 0.15f), RoundedCornerShape(4.dp))
            .padding(horizontal = 5.dp, vertical = 2.dp),
    ) {
        Text(tier, color = color, fontSize = 10.sp, fontWeight = FontWeight.Bold)
    }
}

@Composable
fun PriceItem(label: String, price: Double, color: Color = OnSurface) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(label, color = OnSurface.copy(alpha = 0.6f), fontSize = 9.sp)
        Text(formatPrice(price), color = color, fontSize = 12.sp, fontWeight = FontWeight.Medium)
    }
}

@Composable
fun ConfidenceBar(confidence: Double) {
    val pct = (confidence / 100.0).coerceIn(0.0, 1.0).toFloat()
    val barColor = when {
        confidence >= 80 -> ConfidenceHigh
        confidence >= 65 -> ConfidenceMed
        else -> ConfidenceLow
    }
    Column {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text("Confidence", color = OnSurface.copy(alpha = 0.6f), fontSize = 9.sp)
            Text("${confidence.toInt()}%", color = barColor, fontSize = 9.sp, fontWeight = FontWeight.Bold)
        }
        Spacer(Modifier.height(3.dp))
        Box(
            Modifier
                .fillMaxWidth()
                .height(4.dp)
                .background(Surface, RoundedCornerShape(2.dp)),
        ) {
            Box(
                Modifier
                    .fillMaxWidth(pct)
                    .height(4.dp)
                    .background(
                        Brush.horizontalGradient(listOf(barColor.copy(alpha = 0.6f), barColor)),
                        RoundedCornerShape(2.dp),
                    ),
            )
        }
    }
}

@Composable
fun ConnectionDot(state: ConnectionState) {
    val color = when (state) {
        ConnectionState.CONNECTED -> Color(0xFF00FF88)
        ConnectionState.RECONNECTING -> Color(0xFFFFCC44)
        ConnectionState.DISCONNECTED -> Color(0xFFFF4444)
    }
    Box(
        Modifier
            .size(8.dp)
            .background(color, RoundedCornerShape(4.dp)),
    )
}

internal fun formatPrice(price: Double): String = when {
    price >= 1000 -> "%.2f".format(price)
    price >= 1 -> "%.4f".format(price)
    else -> "%.6f".format(price)
}

private fun timeAgo(ts: String): String {
    return try {
        val instant = Instant.parse(if (ts.endsWith("Z")) ts else "${ts}Z")
        val now = Instant.now()
        val minutes = ChronoUnit.MINUTES.between(instant, now)
        when {
            minutes < 1 -> "just now"
            minutes < 60 -> "${minutes}m ago"
            minutes < 1440 -> "${minutes / 60}h ago"
            else -> "${minutes / 1440}d ago"
        }
    } catch (e: Exception) { "" }
}
