package com.app360.signals.fcm

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import com.app360.signals.MainActivity
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

class SignalMessagingService : FirebaseMessagingService() {
    companion object {
        const val CHANNEL_ID = "signals_channel"
        const val CHANNEL_NAME = "Trading Signals"
    }

    override fun onMessageReceived(remoteMessage: RemoteMessage) {
        super.onMessageReceived(remoteMessage)
        val title = remoteMessage.notification?.title
            ?: remoteMessage.data["symbol"]?.let { "$it Signal" }
            ?: "New Signal"
        val body = remoteMessage.notification?.body
            ?: remoteMessage.data["body"]
            ?: remoteMessage.data.let { d ->
                "${d["direction"] ?: ""} @ ${d["entry"] ?: ""} — Conf: ${d["confidence"] ?: ""}%"
            }

        val notificationManager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val channel = NotificationChannel(CHANNEL_ID, CHANNEL_NAME, NotificationManager.IMPORTANCE_HIGH).apply {
            enableVibration(true)
            setShowBadge(true)
        }
        notificationManager.createNotificationChannel(channel)

        val intent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        val pendingIntent = PendingIntent.getActivity(
            this, 0, intent,
            PendingIntent.FLAG_ONE_SHOT or PendingIntent.FLAG_IMMUTABLE,
        )

        val notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title)
            .setContentText(body)
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setContentIntent(pendingIntent)
            .build()

        notificationManager.notify(System.currentTimeMillis().toInt(), notification)
    }

    override fun onNewToken(token: String) {
        super.onNewToken(token)
        // Token is registered when the user connects to the backend
    }
}
