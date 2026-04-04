package com.app360.signals.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.datastore.preferences.core.stringPreferencesKey
import com.app360.signals.ui.theme.*
import kotlinx.coroutines.launch

const val DEFAULT_BACKEND_URL = "http://95.111.241.97:8080"
val BACKEND_URL_KEY = stringPreferencesKey("backend_url")

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    currentUrl: String,
    appVersion: String = "1.0",
    onUrlSaved: (String) -> Unit,
    onTestConnection: suspend (String) -> Boolean,
) {
    var urlInput by remember(currentUrl) { mutableStateOf(currentUrl) }
    var testResult by remember { mutableStateOf<String?>(null) }
    var isTesting by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Settings", color = OnBackground) },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = CardBackground),
            )
        },
        containerColor = Background,
    ) { padding ->
        Column(
            Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = CardBackground),
                shape = RoundedCornerShape(12.dp),
            ) {
                Column(Modifier.padding(16.dp)) {
                    Text("Backend URL", color = OnSurface, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = urlInput,
                        onValueChange = { urlInput = it; testResult = null },
                        modifier = Modifier.fillMaxWidth(),
                        placeholder = { Text(DEFAULT_BACKEND_URL, color = OnSurface.copy(alpha = 0.4f)) },
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = Teal,
                            unfocusedBorderColor = DividerColor,
                            focusedTextColor = OnBackground,
                            unfocusedTextColor = OnBackground,
                            cursorColor = Teal,
                        ),
                        singleLine = true,
                        shape = RoundedCornerShape(8.dp),
                    )
                    Spacer(Modifier.height(10.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(
                            onClick = { onUrlSaved(urlInput.trim().trimEnd('/')) },
                            colors = ButtonDefaults.buttonColors(containerColor = Teal, contentColor = Color.Black),
                            shape = RoundedCornerShape(8.dp),
                            modifier = Modifier.weight(1f),
                        ) { Text("Save", fontWeight = FontWeight.Bold) }
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
                            shape = RoundedCornerShape(8.dp),
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
                    testResult?.let {
                        Spacer(Modifier.height(6.dp))
                        Text(
                            it,
                            color = if (it.startsWith("✅")) Color(0xFF00FF88) else Color(0xFFFF4444),
                            fontSize = 12.sp,
                        )
                    }
                }
            }

            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = CardBackground),
                shape = RoundedCornerShape(12.dp),
            ) {
                Row(
                    Modifier
                        .fillMaxWidth()
                        .padding(16.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text("App Version", color = OnSurface, fontSize = 13.sp)
                    Text(appVersion, color = OnBackground, fontSize = 13.sp, fontWeight = FontWeight.Medium)
                }
            }
        }
    }
}
