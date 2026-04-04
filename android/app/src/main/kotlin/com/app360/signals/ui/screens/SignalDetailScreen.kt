package com.app360.signals.ui.screens

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.app360.signals.data.models.Signal
import com.app360.signals.ui.theme.*
import kotlin.math.abs

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SignalDetailScreen(signal: Signal, onBack: () -> Unit) {
    val context = LocalContext.current
    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        signal.symbol,
                        fontWeight = FontWeight.Bold,
                        color = OnBackground,
                        fontSize = 18.sp,
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(
                            Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "Back",
                            tint = OnBackground,
                        )
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = CardBackground),
            )
        },
        containerColor = Background,
    ) { padding ->
        Column(
            Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            // Hero Card
            GradientBorderCard {
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column {
                        Text(
                            signal.symbol,
                            fontWeight = FontWeight.ExtraBold,
                            color = OnBackground,
                            fontSize = 28.sp,
                        )
                        Spacer(Modifier.height(6.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            DirectionBadge(signal.direction)
                            ChannelPill(signal.channel)
                        }
                    }
                    Column(horizontalAlignment = Alignment.End) {
                        ConfidenceRing(signal.confidence)
                        Spacer(Modifier.height(6.dp))
                        QualityBadge(signal.qualityTier)
                    }
                }
                if (signal.rrRatio > 0 && signal.tp1 > 0 && signal.stopLoss > 0) {
                    Spacer(Modifier.height(12.dp))
                    HorizontalDivider(color = DividerColor, thickness = 0.5.dp)
                    Spacer(Modifier.height(10.dp))
                    RRRatioBar(signal)
                }
            }

            // Price Levels Card
            GradientBorderCard {
                Text(
                    "Price Levels",
                    color = OnSurface,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.Bold,
                )
                Spacer(Modifier.height(8.dp))
                PriceLevelRow("Entry", signal.entry, OnBackground, null)
                HorizontalDivider(color = DividerColor.copy(alpha = 0.5f), thickness = 0.5.dp)
                PriceLevelRow("Stop Loss", signal.stopLoss, ShortRed, signal.entry)
                if (signal.tp1 > 0) {
                    HorizontalDivider(color = DividerColor.copy(alpha = 0.5f), thickness = 0.5.dp)
                    PriceLevelRow("Take Profit 1", signal.tp1, ConfidenceHigh, signal.entry)
                }
                if (signal.tp2 > 0) {
                    HorizontalDivider(color = DividerColor.copy(alpha = 0.5f), thickness = 0.5.dp)
                    PriceLevelRow("Take Profit 2", signal.tp2, ConfidenceHigh.copy(alpha = 0.7f), signal.entry)
                }
                signal.tp3?.let { tp3 ->
                    if (tp3 > 0) {
                        HorizontalDivider(color = DividerColor.copy(alpha = 0.5f), thickness = 0.5.dp)
                        PriceLevelRow("Take Profit 3", tp3, ConfidenceHigh.copy(alpha = 0.5f), signal.entry)
                    }
                }
            }

            // Signal Quality Card
            GradientBorderCard {
                Text(
                    "Signal Quality",
                    color = OnSurface,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.Bold,
                )
                Spacer(Modifier.height(10.dp))
                ConfidenceBar(signal.confidence)
                Spacer(Modifier.height(8.dp))
                if (signal.riskLabel.isNotBlank()) {
                    DetailRow("Risk Profile", signal.riskLabel, OnBackground)
                }
                if (signal.setupClass.isNotBlank()) {
                    DetailRow("Setup", signal.setupClass, OnBackground)
                }
                if (signal.marketPhase.isNotBlank()) {
                    DetailRow("Market Phase", signal.marketPhase, OnBackground)
                }
            }

            // Analysis Card
            if (signal.analystReason.isNotBlank() || signal.liquidityInfo.isNotBlank()) {
                GradientBorderCard {
                    Text(
                        "Analysis",
                        color = OnSurface,
                        fontSize = 12.sp,
                        fontWeight = FontWeight.Bold,
                    )
                    Spacer(Modifier.height(8.dp))
                    if (signal.liquidityInfo.isNotBlank()) {
                        Text("Liquidity", color = OnSurfaceDim, fontSize = 10.sp)
                        Spacer(Modifier.height(2.dp))
                        Text(signal.liquidityInfo, color = OnBackground, fontSize = 13.sp)
                        Spacer(Modifier.height(10.dp))
                    }
                    if (signal.analystReason.isNotBlank()) {
                        Text("Analyst View", color = OnSurfaceDim, fontSize = 10.sp)
                        Spacer(Modifier.height(2.dp))
                        Text(signal.analystReason, color = OnBackground, fontSize = 13.sp)
                    }
                }
            }

            // Copy Signal — gradient background button
            Button(
                onClick = { copySignal(context, signal) },
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.buttonColors(
                    containerColor = Color.Transparent,
                    contentColor = Color.Black,
                ),
                contentPadding = PaddingValues(0.dp),
                shape = RoundedCornerShape(12.dp),
                elevation = ButtonDefaults.buttonElevation(0.dp),
            ) {
                Box(
                    Modifier
                        .fillMaxWidth()
                        .background(
                            Brush.linearGradient(listOf(GradientStart, GradientEnd)),
                            RoundedCornerShape(12.dp),
                        )
                        .padding(vertical = 14.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Icon(
                            Icons.Default.ContentCopy,
                            contentDescription = null,
                            modifier = Modifier.size(16.dp),
                            tint = Color.Black,
                        )
                        Text(
                            "📋 Copy Signal",
                            fontWeight = FontWeight.Bold,
                            color = Color.Black,
                        )
                    }
                }
            }

            // Copy Cornix Format — outlined button
            OutlinedButton(
                onClick = { copyCornixFormat(context, signal) },
                modifier = Modifier.fillMaxWidth(),
                border = BorderStroke(
                    width = 1.dp,
                    brush = Brush.linearGradient(listOf(GradientStart, GradientEnd)),
                ),
                shape = RoundedCornerShape(12.dp),
                colors = ButtonDefaults.outlinedButtonColors(containerColor = Color.Transparent),
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text("📤", fontSize = 14.sp)
                    Text(
                        "Copy Cornix Format",
                        color = Teal,
                        fontWeight = FontWeight.SemiBold,
                    )
                }
            }

            Spacer(Modifier.height(8.dp))
        }
    }
}

@Composable
fun GradientBorderCard(content: @Composable ColumnScope.() -> Unit) {
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
        Column(Modifier.padding(16.dp), content = content)
    }
}

@Composable
fun ConfidenceRing(confidence: Double) {
    val barColor = when {
        confidence >= 80 -> ConfidenceHigh
        confidence >= 65 -> ConfidenceMed
        else -> ConfidenceLow
    }
    Box(
        modifier = Modifier.size(64.dp),
        contentAlignment = Alignment.Center,
    ) {
        Canvas(Modifier.fillMaxSize()) {
            val strokeWidth = 6.dp.toPx()
            val sweepAngle = 360f * (confidence.toFloat() / 100f)
            drawArc(
                color = SurfaceVariant,
                startAngle = -90f,
                sweepAngle = 360f,
                useCenter = false,
                style = Stroke(width = strokeWidth, cap = StrokeCap.Round),
            )
            drawArc(
                color = barColor,
                startAngle = -90f,
                sweepAngle = sweepAngle,
                useCenter = false,
                style = Stroke(width = strokeWidth, cap = StrokeCap.Round),
            )
        }
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(
                "${confidence.toInt()}",
                color = barColor,
                fontSize = 14.sp,
                fontWeight = FontWeight.Bold,
            )
            Text(
                "%",
                color = OnSurfaceDim,
                fontSize = 8.sp,
            )
        }
    }
}

@Composable
fun PriceLevelRow(label: String, price: Double, color: Color, entryPrice: Double?) {
    val pctText = if (entryPrice != null && entryPrice > 0 && label != "Entry") {
        val pct = (price - entryPrice) / entryPrice * 100
        "${if (pct >= 0) "+" else ""}${"%.2f".format(pct)}%"
    } else null

    Row(
        Modifier
            .fillMaxWidth()
            .padding(vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier
                .width(3.dp)
                .height(32.dp)
                .background(color, RoundedCornerShape(2.dp)),
        )
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(label, color = OnSurfaceDim, fontSize = 10.sp)
            Spacer(Modifier.height(2.dp))
            Text(
                formatPrice(price),
                color = color,
                fontSize = 15.sp,
                fontWeight = FontWeight.Bold,
                fontFamily = FontFamily.Monospace,
            )
        }
        pctText?.let {
            Text(
                it,
                color = color.copy(alpha = 0.7f),
                fontSize = 11.sp,
                fontWeight = FontWeight.Medium,
            )
        }
    }
}

@Composable
fun RRRatioBar(signal: Signal) {
    val riskDistance = abs(signal.entry - signal.stopLoss)
    val rewardDistance = abs(signal.tp1 - signal.entry)
    val total = (riskDistance + rewardDistance).coerceAtLeast(0.001)
    val riskFraction = (riskDistance / total).toFloat().coerceAtLeast(0.01f)
    val rewardFraction = (rewardDistance / total).toFloat().coerceAtLeast(0.01f)

    Column {
        Text(
            "Risk / Reward  ·  1 : ${"%.2f".format(signal.rrRatio)}",
            color = OnSurface,
            fontSize = 11.sp,
            fontWeight = FontWeight.Medium,
        )
        Spacer(Modifier.height(6.dp))
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                Modifier
                    .weight(riskFraction)
                    .height(8.dp)
                    .background(ShortRed.copy(alpha = 0.8f), RoundedCornerShape(4.dp)),
            )
            Box(
                Modifier
                    .weight(rewardFraction)
                    .height(8.dp)
                    .background(ConfidenceHigh.copy(alpha = 0.8f), RoundedCornerShape(4.dp)),
            )
        }
        Spacer(Modifier.height(4.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text("Risk", color = ShortRed.copy(alpha = 0.8f), fontSize = 9.sp)
            Text("Reward", color = ConfidenceHigh.copy(alpha = 0.8f), fontSize = 9.sp)
        }
    }
}

@Composable
fun DetailCard(content: @Composable ColumnScope.() -> Unit) {
    GradientBorderCard(content = content)
}

@Composable
fun DetailRow(label: String, value: String, valueColor: Color = OnBackground) {
    Row(
        Modifier
            .fillMaxWidth()
            .padding(vertical = 3.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(label, color = OnSurfaceDim, fontSize = 13.sp)
        Text(value, color = valueColor, fontSize = 13.sp, fontWeight = FontWeight.Medium)
    }
}

private fun copySignal(context: Context, signal: Signal) {
    val text = buildString {
        appendLine("📊 ${signal.symbol} ${signal.direction}")
        appendLine("Channel: ${signal.channel}")
        appendLine("Entry: ${formatPrice(signal.entry)}")
        appendLine("Stop Loss: ${formatPrice(signal.stopLoss)}")
        appendLine("TP1: ${formatPrice(signal.tp1)}")
        if (signal.tp2 > 0) appendLine("TP2: ${formatPrice(signal.tp2)}")
        signal.tp3?.let { if (it > 0) appendLine("TP3: ${formatPrice(it)}") }
        appendLine("Confidence: ${signal.confidence.toInt()}%")
        appendLine("Quality: ${signal.qualityTier}")
        if (signal.rrRatio > 0) appendLine("R:R  1:${"%.2f".format(signal.rrRatio)}")
        if (signal.analystReason.isNotBlank()) appendLine("Reason: ${signal.analystReason}")
    }
    val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    clipboard.setPrimaryClip(ClipData.newPlainText("Signal", text))
}

private fun copyCornixFormat(context: Context, signal: Signal) {
    val text = buildString {
        appendLine(signal.symbol)
        appendLine("Direction: ${signal.direction}")
        appendLine("Exchange: Binance Futures")
        appendLine("Leverage: Cross (5x)")
        appendLine()
        appendLine("Entry: ${formatPrice(signal.entry)}")
        appendLine()
        appendLine("Take Profit Targets:")
        appendLine("1) ${formatPrice(signal.tp1)}")
        if (signal.tp2 > 0) appendLine("2) ${formatPrice(signal.tp2)}")
        signal.tp3?.let { if (it > 0) appendLine("3) ${formatPrice(it)}") }
        appendLine()
        appendLine("Stop Loss: ${formatPrice(signal.stopLoss)}")
    }
    val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    clipboard.setPrimaryClip(ClipData.newPlainText("Cornix Signal", text))
}
