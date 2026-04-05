package com.app360.signals

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.spring
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.BarChart
import androidx.compose.material.icons.rounded.History
import androidx.compose.material.icons.rounded.Settings
import androidx.compose.material.icons.rounded.Wifi
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.datastore.preferences.core.edit
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.compose.*
import com.app360.signals.data.models.Signal
import com.app360.signals.di.dataStore
import com.app360.signals.ui.screens.*
import com.app360.signals.ui.theme.*
import com.app360.signals.viewmodel.DashboardViewModel
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory

sealed class Screen(val route: String) {
    object Dashboard : Screen("dashboard")
    object Stats : Screen("stats")
    object History : Screen("history")
    object Settings : Screen("settings")
    object SignalDetail : Screen("signal_detail/{signalId}") {
        fun createRoute(id: String) = "signal_detail/$id"
    }
}

@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            SignalsTheme {
                App()
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun App() {
    val navController = rememberNavController()
    val scope = rememberCoroutineScope()
    val context = androidx.compose.ui.platform.LocalContext.current

    val backendUrl by remember {
        context.dataStore.data.map { prefs ->
            prefs[BACKEND_URL_KEY] ?: DEFAULT_BACKEND_URL
        }
    }.collectAsState(initial = DEFAULT_BACKEND_URL)

    val minConfidence by remember {
        context.dataStore.data.map { prefs ->
            prefs[MIN_CONFIDENCE_KEY] ?: DEFAULT_MIN_CONFIDENCE
        }
    }.collectAsState(initial = DEFAULT_MIN_CONFIDENCE)

    val dashboardVm: DashboardViewModel = hiltViewModel()

    LaunchedEffect(backendUrl) {
        dashboardVm.connect(backendUrl)
    }

    var detailSignal by remember { mutableStateOf<Signal?>(null) }

    val bottomNavItems = listOf(
        Triple("Signals", Screen.Dashboard.route, Icons.Rounded.Wifi),
        Triple("History", Screen.History.route, Icons.Rounded.History),
        Triple("Stats", Screen.Stats.route, Icons.Rounded.BarChart),
        Triple("Settings", Screen.Settings.route, Icons.Rounded.Settings),
    )

    Scaffold(
        bottomBar = {
            val navBackStackEntry by navController.currentBackStackEntryAsState()
            val currentRoute = navBackStackEntry?.destination?.route
            AnimatedBottomBar(
                items = bottomNavItems,
                selectedRoute = currentRoute,
                onSelect = { route ->
                    navController.navigate(route) {
                        popUpTo(navController.graph.startDestinationId) { saveState = true }
                        launchSingleTop = true
                        restoreState = true
                    }
                },
            )
        },
        containerColor = Background,
    ) { innerPadding ->
        NavHost(
            navController = navController,
            startDestination = Screen.Dashboard.route,
            modifier = Modifier.padding(innerPadding),
        ) {
            composable(Screen.Dashboard.route) {
                DashboardScreen(
                    onSignalClick = { signal ->
                        detailSignal = signal
                        navController.navigate(Screen.SignalDetail.createRoute(signal.effectiveId))
                    },
                    viewModel = dashboardVm,
                )
            }
            composable(Screen.Stats.route) {
                StatsScreen()
            }
            composable(Screen.History.route) {
                HistoryScreen()
            }
            composable(Screen.Settings.route) {
                SettingsScreen(
                    currentUrl = backendUrl,
                    minConfidence = minConfidence,
                    onUrlSaved = { url ->
                        scope.launch {
                            context.dataStore.edit { it[BACKEND_URL_KEY] = url }
                            dashboardVm.disconnect()
                            dashboardVm.connect(url)
                        }
                    },
                    onMinConfidenceSaved = { conf ->
                        scope.launch {
                            context.dataStore.edit { it[MIN_CONFIDENCE_KEY] = conf }
                        }
                    },
                    onTestConnection = { url ->
                        try {
                            val client = OkHttpClient()
                            val json = Json { ignoreUnknownKeys = true }
                            val retrofit = Retrofit.Builder()
                                .baseUrl("$url/")
                                .client(client)
                                .addConverterFactory(
                                    json.asConverterFactory("application/json".toMediaType()),
                                )
                                .build()
                            val api = retrofit.create(com.app360.signals.data.api.ApiService::class.java)
                            api.getHealth()
                            true
                        } catch (e: Exception) { false }
                    },
                )
            }
            composable(
                Screen.SignalDetail.route,
                arguments = listOf(
                    androidx.navigation.navArgument("signalId") {
                        type = androidx.navigation.NavType.StringType
                    },
                ),
            ) { backStackEntry ->
                val signalId = backStackEntry.arguments?.getString("signalId") ?: ""
                val signal = detailSignal?.takeIf { it.effectiveId == signalId }
                if (signal != null) {
                    SignalDetailScreen(signal = signal, onBack = { navController.popBackStack() })
                } else {
                    navController.popBackStack()
                }
            }
        }
    }
}

@Composable
fun AnimatedBottomBar(
    items: List<Triple<String, String, ImageVector>>,
    selectedRoute: String?,
    onSelect: (String) -> Unit,
) {
    val selectedIndex = items.indexOfFirst { it.second == selectedRoute }.coerceAtLeast(0)

    Column {
        HorizontalDivider(color = DividerColor, thickness = 0.5.dp)
        BoxWithConstraints(
            Modifier
                .fillMaxWidth()
                .background(CardBackground),
        ) {
            val tabWidth = maxWidth / items.size
            val indicatorOffset by animateDpAsState(
                targetValue = tabWidth * selectedIndex + (tabWidth - 48.dp) / 2,
                animationSpec = spring(dampingRatio = Spring.DampingRatioMediumBouncy),
                label = "nav_indicator",
            )

            Box(Modifier.fillMaxWidth()) {
                // Sliding teal pill at top
                Box(
                    Modifier
                        .offset(x = indicatorOffset)
                        .width(48.dp)
                        .height(2.dp)
                        .background(
                            Teal,
                            RoundedCornerShape(
                                topStart = 0.dp,
                                topEnd = 0.dp,
                                bottomStart = 2.dp,
                                bottomEnd = 2.dp,
                            ),
                        ),
                )

                // Tab row
                Row(Modifier.fillMaxWidth()) {
                    items.forEachIndexed { index, (label, route, icon) ->
                        val selected = selectedRoute == route
                        val iconColor by animateColorAsState(
                            targetValue = if (selected) Teal else OnSurfaceDim,
                            label = "icon_color_$index",
                        )
                        Column(
                            Modifier
                                .weight(1f)
                                .clickable { onSelect(route) }
                                .padding(vertical = 10.dp),
                            horizontalAlignment = Alignment.CenterHorizontally,
                        ) {
                            Icon(
                                icon,
                                contentDescription = label,
                                tint = iconColor,
                                modifier = Modifier.size(24.dp),
                            )
                            Spacer(Modifier.height(2.dp))
                            Text(
                                label,
                                color = iconColor,
                                fontSize = 10.sp,
                                fontWeight = if (selected) FontWeight.Bold else FontWeight.Normal,
                            )
                        }
                    }
                }
            }
        }
    }
}
