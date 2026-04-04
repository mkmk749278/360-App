package com.app360.signals.ui.theme

import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.datastore.preferences.core.stringPreferencesKey

val BACKEND_URL_KEY = stringPreferencesKey("backend_url")
const val DEFAULT_BACKEND_URL = "http://95.111.241.97:8080"

private val DarkColorScheme = darkColorScheme(
    primary = Teal,
    secondary = Purple,
    tertiary = Gold,
    background = Background,
    surface = Surface,
    surfaceVariant = SurfaceVariant,
    onBackground = OnBackground,
    onSurface = OnSurface,
    onPrimary = Color.Black,
    error = ShortRed,
)

@Composable
fun SignalsTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = DarkColorScheme,
        typography = Typography(),
        content = content,
    )
}
