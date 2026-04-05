package com.app360.signals.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Link
import androidx.compose.material.icons.rounded.Notifications
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.app360.signals.ui.theme.*
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    currentUrl: String,
    minConfidence: Int = 60,
    appVersion: String = "1.0",
    onUrlSaved: (String) -> Unit,
    onTestConnection: suspend (String) -> Boolean,
    onMinConfidenceSaved: (Int) -> Unit = {},
) {
    var urlInput by remember(currentUrl) { mutableStateOf(currentUrl) }
    var testResult by remember { mutableStateOf<String?>(null) }
    var isTesting by remember { mutableStateOf(false) }
    var confidenceThreshold by remember(minConfidence) { mutableIntStateOf(minConfidence) }
    val scope = rememberCoroutineScope()

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            "360°",
                            fontWeight = FontWeight.ExtraBold,
                            color = Teal,
                            fontSize = 22.sp,
                        )
                        Spacer(Modifier.width(8.dp))
                        Text(
                            "Settings",
                            fontWeight = FontWeight.Normal,
                            color = OnSurface,
                            fontSize = 16.sp,
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
            // Connection card
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
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(
                            Icons.Default.Link,
                            contentDescription = null,
                            tint = Teal,
                            modifier = Modifier.size(16.dp),
                        )
                        Spacer(Modifier.width(6.dp))
                        Text(
                            "Backend URL",
                            color = OnSurface,
                            fontSize = 12.sp,
                            fontWeight = FontWeight.Bold,
                        )
                    }
                    Spacer(Modifier.height(10.dp))
                    OutlinedTextField(
                        value = urlInput,
                        onValueChange = { urlInput = it; testResult = null },
                        modifier = Modifier.fillMaxWidth(),
                        placeholder = {
                            Text(DEFAULT_BACKEND_URL, color = OnSurfaceDim, fontSize = 13.sp)
                        },
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = Teal,
                            unfocusedBorderColor = DividerColor,
                            focusedTextColor = OnBackground,
                            unfocusedTextColor = OnBackground,
                            cursorColor = Teal,
                        ),
                        singleLine = true,
                        shape = RoundedCornerShape(10.dp),
                    )
                    Spacer(Modifier.height(12.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        // Save — gradient background
                        Box(
                            Modifier
                                .weight(1f)
                                .background(
                                    Brush.linearGradient(listOf(GradientStart, GradientEnd)),
                                    RoundedCornerShape(10.dp),
                                ),
                        ) {
                            Button(
                                onClick = { onUrlSaved(urlInput.trim().trimEnd('/')) },
                                modifier = Modifier.fillMaxWidth(),
                                colors = ButtonDefaults.buttonColors(
                                    containerColor = Color.Transparent,
                                    contentColor = Color.Black,
                                ),
                                elevation = ButtonDefaults.buttonElevation(defaultElevation = 0.dp),
                                shape = RoundedCornerShape(10.dp),
                            ) {
                                Text("Save", fontWeight = FontWeight.Bold, color = Color.Black)
                            }
                        }
                        // Test connection
                        OutlinedButton(
                            onClick = {
                                isTesting = true
                                testResult = null
                                scope.launch {
                                    val ok = onTestConnection(urlInput.trim().trimEnd('/'))
                                    testResult = if (ok) "✅ Connected!" else "❌ Unreachable"
                                    isTesting = false
                                }
                            },
                            enabled = !isTesting,
                            border = androidx.compose.foundation.BorderStroke(1.dp, Teal),
                            shape = RoundedCornerShape(10.dp),
                            modifier = Modifier.weight(1f),
                        ) {
                            if (isTesting) {
                                CircularProgressIndicator(
                                    modifier = Modifier.size(16.dp),
                                    color = Teal,
                                    strokeWidth = 2.dp,
                                )
                            } else {
                                Text("Test", color = Teal)
                            }
                        }
                    }
                    testResult?.let { result ->
                        Spacer(Modifier.height(8.dp))
                        Row(
                            Modifier
                                .fillMaxWidth()
                                .background(
                                    if (result.startsWith("✅")) LongGreenBg else ShortRedBg,
                                    RoundedCornerShape(8.dp),
                                )
                                .padding(horizontal = 12.dp, vertical = 8.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text(
                                result,
                                color = if (result.startsWith("✅")) LongGreen else ShortRed,
                                fontSize = 13.sp,
                                fontWeight = FontWeight.Medium,
                            )
                        }
                    }
                }
            }

            // Confidence threshold card
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
                    Row(
                        Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            "Min Confidence",
                            color = OnSurface,
                            fontSize = 12.sp,
                            fontWeight = FontWeight.Bold,
                        )
                        Box(
                            Modifier
                                .background(TealDim, RoundedCornerShape(20.dp))
                                .padding(horizontal = 10.dp, vertical = 3.dp),
                        ) {
                            Text(
                                "$confidenceThreshold%",
                                color = Teal,
                                fontSize = 13.sp,
                                fontWeight = FontWeight.Bold,
                            )
                        }
                    }
                    Spacer(Modifier.height(8.dp))
                    Slider(
                        value = confidenceThreshold.toFloat(),
                        onValueChange = { confidenceThreshold = it.toInt() },
                        onValueChangeFinished = { onMinConfidenceSaved(confidenceThreshold) },
                        valueRange = 0f..100f,
                        steps = 19, // 5% increments: (100 / 5) - 1 = 19 steps
                        colors = SliderDefaults.colors(
                            thumbColor = Teal,
                            activeTrackColor = Teal,
                            inactiveTrackColor = DividerColor,
                        ),
                    )
                    Text(
                        "Only show signals with confidence ≥ $confidenceThreshold%",
                        color = OnSurfaceDim,
                        fontSize = 11.sp,
                    )
                }
            }

            // Signal Limits card
            SignalLimitsCard()

            // Push Notifications card
            PushNotificationsCard()

            // App info card
            Card(
                modifier = Modifier
                    .fillMaxWidth()
                    .border(
                        width = 1.dp,
                        brush = Brush.linearGradient(
                            listOf(GradientStart.copy(alpha = 0.4f), GradientEnd.copy(alpha = 0.4f)),
                        ),
                        shape = RoundedCornerShape(16.dp),
                    ),
                colors = CardDefaults.cardColors(containerColor = CardBackground),
                shape = RoundedCornerShape(16.dp),
                elevation = CardDefaults.cardElevation(defaultElevation = 0.dp),
            ) {
                Column(Modifier.padding(16.dp)) {
                    Row(
                        Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column {
                            Text(
                                "360°",
                                color = Teal,
                                fontSize = 28.sp,
                                fontWeight = FontWeight.ExtraBold,
                            )
                            Text("Signals", color = OnBackground, fontSize = 14.sp)
                        }
                        Box(
                            Modifier
                                .background(TealDim, RoundedCornerShape(20.dp))
                                .padding(horizontal = 12.dp, vertical = 4.dp),
                        ) {
                            Text(
                                "v$appVersion",
                                color = Teal,
                                fontSize = 12.sp,
                                fontWeight = FontWeight.Bold,
                            )
                        }
                    }
                    Spacer(Modifier.height(12.dp))
                    HorizontalDivider(color = DividerColor, thickness = 0.5.dp)
                    Spacer(Modifier.height(10.dp))
                    Row(
                        Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text("Backend", color = OnSurfaceDim, fontSize = 12.sp)
                        Text(
                            currentUrl
                                .removePrefix("https://")
                                .removePrefix("http://"),
                            color = OnSurface,
                            fontSize = 12.sp,
                            fontFamily = FontFamily.Monospace,
                        )
                    }
                }
            }
        }
    }
}

data class SignalLimitConfig(val key: String, val label: String, val min: Int, val max: Int)

@Composable
fun SignalLimitsCard() {
    val limits = remember {
        listOf(
            SignalLimitConfig("MAX_SCALP_SIGNALS", "Scalp", 1, 10),
            SignalLimitConfig("MAX_SCALP_FVG_SIGNALS", "FVG", 1, 5),
            SignalLimitConfig("MAX_SCALP_CVD_SIGNALS", "CVD", 1, 5),
            SignalLimitConfig("MAX_SCALP_VWAP_SIGNALS", "VWAP", 1, 5),
            SignalLimitConfig("MAX_SCALP_OBI_SIGNALS", "OBI", 1, 5),
        )
    }
    val values = remember { limits.associate { it.key to it.min + 1 }.toMutableStateMap() }
    val defaults = mapOf(
        "MAX_SCALP_SIGNALS" to 5,
        "MAX_SCALP_FVG_SIGNALS" to 3,
        "MAX_SCALP_CVD_SIGNALS" to 3,
        "MAX_SCALP_VWAP_SIGNALS" to 3,
        "MAX_SCALP_OBI_SIGNALS" to 3,
    )
    // Initialize with defaults
    LaunchedEffect(Unit) {
        defaults.forEach { (k, v) -> values[k] = v }
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
                "Signal Limits",
                color = OnSurface,
                fontSize = 12.sp,
                fontWeight = FontWeight.Bold,
            )
            Spacer(Modifier.height(8.dp))
            limits.forEach { cfg ->
                val v = values[cfg.key] ?: cfg.min
                Row(
                    Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        cfg.label,
                        color = OnSurfaceDim,
                        fontSize = 11.sp,
                        modifier = Modifier.width(44.dp),
                    )
                    Slider(
                        value = v.toFloat(),
                        onValueChange = { values[cfg.key] = it.toInt() },
                        valueRange = cfg.min.toFloat()..cfg.max.toFloat(),
                        steps = cfg.max - cfg.min - 1,
                        colors = SliderDefaults.colors(
                            thumbColor = Teal,
                            activeTrackColor = Teal,
                            inactiveTrackColor = DividerColor,
                        ),
                        modifier = Modifier.weight(1f),
                    )
                    Box(
                        Modifier
                            .background(TealDim, RoundedCornerShape(20.dp))
                            .padding(horizontal = 8.dp, vertical = 2.dp),
                    ) {
                        Text("$v", color = Teal, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                    }
                }
            }
        }
    }
}

@Composable
fun PushNotificationsCard() {
    var pushEnabled by remember { mutableStateOf(true) }

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
        Row(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                Icons.Rounded.Notifications,
                contentDescription = null,
                tint = Teal,
                modifier = Modifier.size(16.dp),
            )
            Spacer(Modifier.width(8.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    "Push Notifications",
                    color = OnSurface,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.Bold,
                )
                Text(
                    "Receive alerts for new signals",
                    color = OnSurfaceDim,
                    fontSize = 11.sp,
                )
            }
            Switch(
                checked = pushEnabled,
                onCheckedChange = { pushEnabled = it },
                colors = SwitchDefaults.colors(
                    checkedThumbColor = Color.Black,
                    checkedTrackColor = Teal,
                    uncheckedThumbColor = OnSurfaceDim,
                    uncheckedTrackColor = Surface,
                ),
            )
        }
    }
}
