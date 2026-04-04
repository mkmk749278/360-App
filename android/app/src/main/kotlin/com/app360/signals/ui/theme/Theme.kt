package com.app360.signals.ui.theme

import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val DarkColorScheme = darkColorScheme(
    primary = Teal,
    onPrimary = Color.Black,
    secondary = TealDark,
    background = Background,
    surface = CardBackground,
    onBackground = OnBackground,
    onSurface = OnBackground,
    surfaceVariant = Surface,
    onSurfaceVariant = OnSurface,
    outline = DividerColor,
)

@Composable
fun SignalsTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = DarkColorScheme,
        typography = Typography(),
        content = content
    )
}
