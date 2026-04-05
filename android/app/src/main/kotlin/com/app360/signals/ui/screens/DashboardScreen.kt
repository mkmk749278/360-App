package com.app360.signals.ui.screens

import androidx.compose.animation.*
import androidx.compose.animation.core.*
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
import androidx.compose.ui.draw.scale
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
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
    val regime by viewModel.regime.collectAsStateWithLifecycle()
    val pausedPairs by viewModel.pausedPairs.collectAsStateWithLifecycle()
    var pausedExpanded by remember { mutableStateOf(false) }

    Scaffold(
        topBar = {
            Column {
                TopAppBar(
                    title = {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                "360°",
                                fontWeight = FontWeight.ExtraBold,
                                color = Teal,
                                fontSize = 20.sp,
                            )
                            Spacer(Modifier.width(10.dp))
                            PulsingConnectionDot(connectionState)
                            Spacer(Modifier.width(5.dp))
                            Text(
                                when (connectionState) {
                                    ConnectionState.CONNECTED -> "LIVE"
                                    ConnectionState.RECONNECTING -> "SYNCING"
                                    ConnectionState.DISCONNECTED -> "OFFLINE"
                                },
                                color = when (connectionState) {
                                    ConnectionState.CONNECTED -> Teal
                                    ConnectionState.RECONNECTING -> Gold
                                    ConnectionState.DISCONNECTED -> ShortRed
                                },
                                fontSize = 10.sp,
                                fontWeight = FontWeight.Bold,
                                letterSpacing = 1.sp,
                            )
                        }
                    },
                    colors = TopAppBarDefaults.topAppBarColors(containerColor = CardBackground),
                )
                AnimatedVisibility(visible = connectionState == ConnectionState.RECONNECTING) {
                    val pulseTransition = rememberInfiniteTransition(label = "reconnect")
                    val alpha by pulseTransition.animateFloat(
                        initialValue = 0.4f,
                        targetValue = 1f,
                        animationSpec = infiniteRepeatable(tween(700), RepeatMode.Reverse),
                        label = "reconnect_alpha",
                    )
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .background(Color(0xFF2A1800))
                            .padding(horizontal = 16.dp, vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Box(
                            Modifier
                                .size(6.dp)
                                .background(Gold.copy(alpha = alpha), RoundedCornerShape(3.dp)),
                        )
                        Spacer(Modifier.width(8.dp))
                        Text("Reconnecting to live feed…", color = Gold, fontSize = 12.sp)
                    }
                }
                AnimatedVisibility(visible = connectionState == ConnectionState.DISCONNECTED) {
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .background(Color(0xFF2A0010))
                            .padding(horizontal = 16.dp, vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Box(
                            Modifier
                                .size(6.dp)
                                .background(ShortRed, RoundedCornerShape(3.dp)),
                        )
                        Spacer(Modifier.width(8.dp))
                        Text("Disconnected from live feed", color = ShortRed, fontSize = 12.sp)
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
                        GradientFilterChip(
                            selected = filter == f,
                            label = f.name,
                            onClick = { viewModel.setFilter(f) },
                        )
                    }
                }
                // Regime pill banner
                if (regime.isNotBlank()) {
                    val (regimeColor, regimeBg) = when {
                        regime.startsWith("TRENDING") -> Pair(LongGreen, Color(0xFF0A2010))
                        regime == "RANGING" -> Pair(Color(0xFF4DA6FF), Color(0xFF0A1828))
                        regime == "VOLATILE" -> Pair(Gold, Color(0xFF2A1800))
                        else -> Pair(OnSurfaceDim, Color(0xFF151C2A))
                    }
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .background(regimeBg)
                            .padding(horizontal = 16.dp, vertical = 6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Box(
                            Modifier
                                .background(regimeColor, RoundedCornerShape(20.dp))
                                .padding(horizontal = 8.dp, vertical = 2.dp),
                        ) {
                            Text(
                                regime.replace("_", " "),
                                color = Color.Black,
                                fontSize = 10.sp,
                                fontWeight = FontWeight.Bold,
                            )
                        }
                        Text("Market Regime", color = regimeColor.copy(alpha = 0.8f), fontSize = 11.sp)
                    }
                }
                // Paused pairs banner
                val pausedCount = pausedPairs.count { it.value }
                AnimatedVisibility(visible = pausedCount > 0) {
                    Column(
                        Modifier
                            .fillMaxWidth()
                            .background(Color(0xFF2A0010))
                            .clickable { pausedExpanded = !pausedExpanded },
                    ) {
                        Row(
                            Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text("⚠", fontSize = 14.sp)
                            Spacer(Modifier.width(6.dp))
                            Text(
                                "$pausedCount pair${if (pausedCount > 1) "s" else ""} paused by circuit breaker",
                                color = ShortRed,
                                fontSize = 12.sp,
                                fontWeight = FontWeight.SemiBold,
                                modifier = Modifier.weight(1f),
                            )
                            Text(
                                if (pausedExpanded) "▲" else "▼",
                                color = ShortRed,
                                fontSize = 10.sp,
                            )
                        }
                        AnimatedVisibility(visible = pausedExpanded) {
                            Column(Modifier.padding(start = 36.dp, bottom = 8.dp, end = 16.dp)) {
                                pausedPairs.filter { it.value }.keys.forEach { sym ->
                                    Text(
                                        "• $sym",
                                        color = ShortRed.copy(alpha = 0.8f),
                                        fontSize = 11.sp,
                                    )
                                }
                            }
                        }
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
            if (isRefreshing && signals.isEmpty()) {
                LazyColumn(
                    Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(horizontal = 12.dp, vertical = 8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    items(3) { SkeletonCard() }
                }
            } else if (signals.isEmpty()) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    val emptyTransition = rememberInfiniteTransition(label = "empty")
                    val emptyScale by emptyTransition.animateFloat(
                        initialValue = 0.9f,
                        targetValue = 1.1f,
                        animationSpec = infiniteRepeatable(tween(1000), RepeatMode.Reverse),
                        label = "empty_scale",
                    )
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(
                            "📡",
                            fontSize = 48.sp,
                            modifier = Modifier.scale(emptyScale),
                        )
                        Spacer(Modifier.height(12.dp))
                        Text("Waiting for signals…", color = OnSurface, fontSize = 14.sp)
                        Spacer(Modifier.height(4.dp))
                        Text("Pull down to refresh", color = OnSurfaceDim, fontSize = 12.sp)
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
                            enter = slideInVertically(
                                animationSpec = spring(
                                    dampingRatio = Spring.DampingRatioMediumBouncy,
                                    stiffness = Spring.StiffnessLow,
                                ),
                                initialOffsetY = { it / 3 },
                            ) + fadeIn(animationSpec = tween(300)),
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
fun GradientFilterChip(selected: Boolean, label: String, onClick: () -> Unit) {
    val bgModifier = if (selected) {
        Modifier.background(
            Brush.linearGradient(listOf(GradientStart, GradientEnd)),
            RoundedCornerShape(20.dp),
        )
    } else {
        Modifier.background(Surface, RoundedCornerShape(20.dp))
    }
    Box(
        Modifier
            .clip(RoundedCornerShape(20.dp))
            .then(bgModifier)
            .clickable(onClick = onClick)
            .padding(horizontal = 10.dp, vertical = 5.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            label,
            color = if (selected) Color.Black else OnSurface,
            fontSize = 11.sp,
            fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
        )
    }
}

@Composable
fun SignalCard(signal: Signal, onClick: () -> Unit) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .border(
                width = 1.dp,
                brush = Brush.linearGradient(listOf(GradientStart, GradientEnd)),
                shape = RoundedCornerShape(16.dp),
            )
            .clickable(onClick = onClick),
        colors = CardDefaults.cardColors(containerColor = CardBackground),
        shape = RoundedCornerShape(16.dp),
        elevation = CardDefaults.cardElevation(defaultElevation = 0.dp),
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
                    Text(
                        signal.symbol,
                        fontWeight = FontWeight.Bold,
                        color = OnBackground,
                        fontSize = 18.sp,
                    )
                    DirectionBadge(signal.direction)
                    ChannelPill(signal.channel)
                }
                Column(horizontalAlignment = Alignment.End) {
                    QualityBadge(signal.qualityTier)
                    Spacer(Modifier.height(2.dp))
                    Text(timeAgo(signal.timestamp), color = OnSurfaceDim, fontSize = 10.sp)
                }
            }
            Spacer(Modifier.height(10.dp))
            HorizontalDivider(color = DividerColor, thickness = 0.5.dp)
            Spacer(Modifier.height(10.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                PriceItem("ENTRY", signal.entry, OnBackground)
                PriceItem("SL", signal.stopLoss, ShortRed)
                PriceItem("TP1", signal.tp1, ConfidenceHigh)
                if (signal.tp2 > 0) PriceItem("TP2", signal.tp2, ConfidenceHigh.copy(alpha = 0.7f))
            }
            Spacer(Modifier.height(10.dp))
            HorizontalDivider(color = DividerColor, thickness = 0.5.dp)
            Spacer(Modifier.height(10.dp))
            ConfidenceBar(signal.confidence)
            if (signal.setupClass.isNotBlank() || signal.riskLabel.isNotBlank()) {
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    if (signal.setupClass.isNotBlank()) SmallPill(signal.setupClass)
                    if (signal.riskLabel.isNotBlank()) SmallPill(signal.riskLabel)
                    if (signal.rrRatio > 0) SmallPill("1:${"%.1f".format(signal.rrRatio)} RR")
                }
            }
        }
    }
}

@Composable
fun SmallPill(text: String) {
    Box(
        Modifier
            .background(SurfaceVariant, RoundedCornerShape(4.dp))
            .padding(horizontal = 5.dp, vertical = 2.dp),
    ) {
        Text(text, color = OnSurface, fontSize = 9.sp)
    }
}

@Composable
fun DirectionBadge(direction: String) {
    val isLong = direction.uppercase() == "LONG"
    val prefix = if (isLong) "▲ " else "▼ "
    Box(
        Modifier
            .shadow(
                elevation = 4.dp,
                shape = RoundedCornerShape(6.dp),
                spotColor = if (isLong) LongGreen else ShortRed,
            )
            .background(
                if (isLong) LongGreenBg else ShortRedBg,
                RoundedCornerShape(6.dp),
            )
            .padding(horizontal = 8.dp, vertical = 3.dp),
    ) {
        Text(
            "$prefix${direction.uppercase()}",
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
            .background(TealDim, RoundedCornerShape(10.dp))
            .padding(horizontal = 6.dp, vertical = 2.dp),
    ) {
        Text(short, color = Teal, fontSize = 9.sp, fontWeight = FontWeight.Medium)
    }
}

@Composable
fun QualityBadge(tier: String) {
    val color = when (tier) {
        "A+" -> Teal
        "A" -> Color(0xFF51CF66)
        "B+" -> Gold
        else -> OnSurfaceDim
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
        Text(
            label,
            color = OnSurfaceDim,
            fontSize = 9.sp,
            fontWeight = FontWeight.Medium,
        )
        Spacer(Modifier.height(2.dp))
        Text(
            formatPrice(price),
            color = color,
            fontSize = 12.sp,
            fontWeight = FontWeight.Medium,
            fontFamily = FontFamily.Monospace,
        )
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
            Text("Confidence", color = OnSurfaceDim, fontSize = 9.sp)
            Text(
                "${confidence.toInt()}%",
                color = barColor,
                fontSize = 9.sp,
                fontWeight = FontWeight.Bold,
            )
        }
        Spacer(Modifier.height(4.dp))
        Box(
            Modifier
                .fillMaxWidth()
                .height(6.dp)
                .background(SurfaceVariant, RoundedCornerShape(3.dp)),
        ) {
            Box(
                Modifier
                    .fillMaxWidth(pct)
                    .height(6.dp)
                    .background(
                        Brush.horizontalGradient(
                            listOf(ConfidenceHigh.copy(alpha = 0.5f), barColor),
                        ),
                        RoundedCornerShape(3.dp),
                    ),
            )
        }
    }
}

@Composable
fun PulsingConnectionDot(state: ConnectionState) {
    val color = when (state) {
        ConnectionState.CONNECTED -> LongGreen
        ConnectionState.RECONNECTING -> Gold
        ConnectionState.DISCONNECTED -> ShortRed
    }
    if (state == ConnectionState.CONNECTED) {
        val dotTransition = rememberInfiniteTransition(label = "dot")
        val dotScale by dotTransition.animateFloat(
            initialValue = 0.6f,
            targetValue = 1.0f,
            animationSpec = infiniteRepeatable(tween(1000), RepeatMode.Reverse),
            label = "dot_scale",
        )
        Box(
            Modifier
                .size(8.dp)
                .scale(dotScale)
                .background(color, RoundedCornerShape(4.dp)),
        )
    } else {
        Box(
            Modifier
                .size(8.dp)
                .background(color, RoundedCornerShape(4.dp)),
        )
    }
}

@Composable
fun SkeletonCard() {
    val shimmerTransition = rememberInfiniteTransition(label = "shimmer")
    val shimmer by shimmerTransition.animateFloat(
        initialValue = 0.3f,
        targetValue = 0.7f,
        animationSpec = infiniteRepeatable(tween(1000), RepeatMode.Reverse),
        label = "shimmer_alpha",
    )
    Box(
        Modifier
            .fillMaxWidth()
            .background(CardBackground, RoundedCornerShape(16.dp))
            .border(
                width = 1.dp,
                brush = Brush.linearGradient(
                    listOf(
                        GradientStart.copy(alpha = shimmer * 0.4f),
                        GradientEnd.copy(alpha = shimmer * 0.4f),
                    ),
                ),
                shape = RoundedCornerShape(16.dp),
            )
            .padding(14.dp),
    ) {
        Column {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(
                    Modifier
                        .width(120.dp)
                        .height(18.dp)
                        .background(OnSurfaceDim.copy(alpha = shimmer), RoundedCornerShape(4.dp)),
                )
                Box(
                    Modifier
                        .width(40.dp)
                        .height(18.dp)
                        .background(OnSurfaceDim.copy(alpha = shimmer * 0.7f), RoundedCornerShape(4.dp)),
                )
            }
            Spacer(Modifier.height(12.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                repeat(4) {
                    Box(
                        Modifier
                            .width(60.dp)
                            .height(12.dp)
                            .background(OnSurfaceDim.copy(alpha = shimmer * 0.6f), RoundedCornerShape(4.dp)),
                    )
                }
            }
            Spacer(Modifier.height(12.dp))
            Box(
                Modifier
                    .fillMaxWidth()
                    .height(6.dp)
                    .background(OnSurfaceDim.copy(alpha = shimmer * 0.4f), RoundedCornerShape(3.dp)),
            )
        }
    }
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
