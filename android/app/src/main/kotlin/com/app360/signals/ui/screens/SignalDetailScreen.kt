package com.app360.signals.ui.screens

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import androidx.compose.foundation.background
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.app360.signals.data.models.Signal
import com.app360.signals.ui.theme.*

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SignalDetailScreen(signal: Signal, onBack: () -> Unit) {
    val context = LocalContext.current
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("${signal.symbol} Detail", color = OnBackground) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back", tint = OnBackground)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = CardBackground),
                actions = {
                    IconButton(onClick = { copySignal(context, signal) }) {
                        Icon(Icons.Default.ContentCopy, contentDescription = "Copy", tint = Teal)
                    }
                },
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
            DetailCard {
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column {
                        Text(signal.symbol, fontWeight = FontWeight.Bold, color = OnBackground, fontSize = 22.sp)
                        Spacer(Modifier.height(4.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            DirectionBadge(signal.direction)
                            ChannelPill(signal.channel)
                        }
                    }
                    Column(horizontalAlignment = Alignment.End) {
                        QualityBadge(signal.qualityTier)
                        Spacer(Modifier.height(4.dp))
                        Text(
                            "R:R ${"%.2f".format(signal.rrRatio)}",
                            color = Teal, fontSize = 12.sp, fontWeight = FontWeight.Bold,
                        )
                    }
                }
            }

            DetailCard {
                Text("Price Levels", color = OnSurface, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(10.dp))
                DetailRow("Entry", formatPriceD(signal.entry), OnBackground)
                DetailRow("Stop Loss", formatPriceD(signal.stopLoss), Color(0xFFFF6B6B))
                DetailRow("Take Profit 1", formatPriceD(signal.tp1), Color(0xFF51CF66))
                if (signal.tp2 > 0) DetailRow("Take Profit 2", formatPriceD(signal.tp2), Color(0xFF69DB7C))
                signal.tp3?.let { if (it > 0) DetailRow("Take Profit 3", formatPriceD(it), Color(0xFF8CE99A)) }
            }

            DetailCard {
                Text("Signal Quality", color = OnSurface, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(10.dp))
                ConfidenceBar(signal.confidence)
                Spacer(Modifier.height(6.dp))
                if (signal.riskLabel.isNotBlank()) DetailRow("Risk", signal.riskLabel, OnBackground)
                if (signal.setupClass.isNotBlank()) DetailRow("Setup", signal.setupClass, OnBackground)
                if (signal.marketPhase.isNotBlank()) DetailRow("Market Phase", signal.marketPhase, OnBackground)
            }

            if (signal.analystReason.isNotBlank() || signal.liquidityInfo.isNotBlank()) {
                DetailCard {
                    Text("Analysis", color = OnSurface, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.height(8.dp))
                    if (signal.liquidityInfo.isNotBlank()) {
                        Text("Liquidity", color = OnSurface.copy(alpha = 0.6f), fontSize = 10.sp)
                        Text(signal.liquidityInfo, color = OnBackground, fontSize = 13.sp)
                        Spacer(Modifier.height(8.dp))
                    }
                    if (signal.analystReason.isNotBlank()) {
                        Text("Analyst View", color = OnSurface.copy(alpha = 0.6f), fontSize = 10.sp)
                        Text(signal.analystReason, color = OnBackground, fontSize = 13.sp)
                    }
                }
            }

            Button(
                onClick = { copySignal(context, signal) },
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.buttonColors(containerColor = Teal, contentColor = Color.Black),
                shape = RoundedCornerShape(8.dp),
            ) {
                Icon(Icons.Default.ContentCopy, contentDescription = null, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(8.dp))
                Text("Copy Signal", fontWeight = FontWeight.Bold)
            }
        }
    }
}

@Composable
fun DetailCard(content: @Composable ColumnScope.() -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = CardBackground),
        shape = RoundedCornerShape(12.dp),
    ) {
        Column(Modifier.padding(16.dp), content = content)
    }
}

@Composable
fun DetailRow(label: String, value: String, valueColor: Color = OnBackground) {
    Row(
        Modifier
            .fillMaxWidth()
            .padding(vertical = 3.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(label, color = OnSurface.copy(alpha = 0.6f), fontSize = 13.sp)
        Text(value, color = valueColor, fontSize = 13.sp, fontWeight = FontWeight.Medium)
    }
}

private fun formatPriceD(price: Double): String = formatPrice(price)

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
        if (signal.analystReason.isNotBlank()) appendLine("Reason: ${signal.analystReason}")
    }
    val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    clipboard.setPrimaryClip(ClipData.newPlainText("Signal", text))
}
