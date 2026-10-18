package dev.assistant.assistant

import android.os.Build
import android.os.Bundle
import io.flutter.embedding.android.FlutterActivity

// v3.5.2 高刷新率：Flyme/ColorOS/MIUI 对没声明的第三方 App 常默认给 60Hz（魅族 20 是 144Hz 屏），Flutter 引擎只跟系统给的 vsync 走。
// 这里在同分辨率的显示模式里挑刷新率最高的一个，设成窗口的 preferredDisplayModeId（API 23+，不引依赖）。
// 回前台再设一次：部分系统切后台 / 分屏后会把窗口偏好重置。系统仍可按省电策略降档，那是系统的决定。
class MainActivity : FlutterActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        requestHighestRefreshRate()
    }

    override fun onResume() {
        super.onResume()
        requestHighestRefreshRate()
    }

    private fun requestHighestRefreshRate() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return
        try {
            @Suppress("DEPRECATION")
            val display = (if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) display else windowManager.defaultDisplay) ?: return
            val current = display.mode
            val best = display.supportedModes
                .filter { it.physicalWidth == current.physicalWidth && it.physicalHeight == current.physicalHeight }
                .maxByOrNull { it.refreshRate } ?: return
            val attrs = window.attributes
            if (attrs.preferredDisplayModeId == best.modeId) return
            attrs.preferredDisplayModeId = best.modeId
            window.attributes = attrs
        } catch (_: Exception) {
            // 拿不到显示模式（少数 ROM / 虚拟屏）就保持系统默认
        }
    }
}
