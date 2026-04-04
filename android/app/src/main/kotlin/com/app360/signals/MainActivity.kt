package com.app360.signals

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.BarChart
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Wifi
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
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

    val dashboardVm: DashboardViewModel = hiltViewModel()

    LaunchedEffect(backendUrl) {
        dashboardVm.connect(backendUrl)
    }

    var detailSignal by remember { mutableStateOf<Signal?>(null) }

    val bottomNavItems = listOf(
        Triple("Signals", Screen.Dashboard.route, Icons.Default.Wifi),
        Triple("Stats", Screen.Stats.route, Icons.Default.BarChart),
        Triple("Settings", Screen.Settings.route, Icons.Default.Settings),
    )

    Scaffold(
        bottomBar = {
            NavigationBar(containerColor = CardBackground) {
                val navBackStackEntry by navController.currentBackStackEntryAsState()
                val currentRoute = navBackStackEntry?.destination?.route
                bottomNavItems.forEach { (label, route, icon) ->
                    NavigationBarItem(
                        selected = currentRoute == route,
                        onClick = {
                            navController.navigate(route) {
                                popUpTo(navController.graph.startDestinationId) { saveState = true }
                                launchSingleTop = true
                                restoreState = true
                            }
                        },
                        icon = { Icon(icon, contentDescription = label) },
                        label = { Text(label) },
                        colors = NavigationBarItemDefaults.colors(
                            selectedIconColor = Teal,
                            selectedTextColor = Teal,
                            indicatorColor = Surface,
                            unselectedIconColor = OnSurface,
                            unselectedTextColor = OnSurface,
                        ),
                    )
                }
            }
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
            composable(Screen.Settings.route) {
                SettingsScreen(
                    currentUrl = backendUrl,
                    onUrlSaved = { url ->
                        scope.launch {
                            context.dataStore.edit { it[BACKEND_URL_KEY] = url }
                            dashboardVm.disconnect()
                            dashboardVm.connect(url)
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
