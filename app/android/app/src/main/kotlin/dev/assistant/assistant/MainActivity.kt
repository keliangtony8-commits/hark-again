package dev.assistant.assistant

import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

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

    // v3.5.3 性能自检（lib/core/perf_probe.dart perfDeviceInfo）：读系统当前显示模式、窗口请求的模式、Impeller 配置。只读，不改任何东西。
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "dev.assistant/perf").setMethodCallHandler { call, result ->
            if (call.method == "display") {
                try {
                    result.success(displayInfo())
                } catch (e: Exception) {
                    result.error("display", e.toString(), null)
                }
            } else {
                result.notImplemented()
            }
        }
    }

    private fun displayInfo(): Map<String, Any?> {
        val m = HashMap<String, Any?>()
        @Suppress("DEPRECATION")
        val display = (if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) display else windowManager.defaultDisplay)
        if (display != null && Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            val mode = display.mode
            m["modeId"] = mode.modeId
            m["modeRefreshRate"] = String.format("%.1f", mode.refreshRate)
            m["modeSize"] = "${mode.physicalWidth}x${mode.physicalHeight}"
            val pref = window.attributes.preferredDisplayModeId
            m["preferredModeId"] = pref
            m["preferredRefreshRate"] = display.supportedModes.firstOrNull { it.modeId == pref }?.let { String.format("%.1f", it.refreshRate) } ?: "未设"
            m["supported"] = display.supportedModes.joinToString(" ") { "${it.modeId}:${it.physicalWidth}x${it.physicalHeight}@${it.refreshRate.toInt()}" }
        }
        val meta = try {
            @Suppress("DEPRECATION")
            packageManager.getActivityInfo(componentName, PackageManager.GET_META_DATA).metaData
        } catch (_: Exception) {
            null
        }
        val app = applicationInfo.metaData
        fun metaOf(k: String): String? = (meta?.get(k) ?: app?.get(k))?.toString()
        m["enableImpeller"] = metaOf("io.flutter.embedding.android.EnableImpeller") ?: "未写（默认）"
        val vulkan = Build.VERSION.SDK_INT >= Build.VERSION_CODES.N &&
            packageManager.hasSystemFeature(PackageManager.FEATURE_VULKAN_HARDWARE_VERSION, 0x401000)
        m["impellerBackend"] = metaOf("io.flutter.embedding.android.ImpellerBackend")
            ?: (if (vulkan) "未写（设备支持 Vulkan 1.1，默认应为 Vulkan，推断）" else "未写（设备无 Vulkan 1.1，默认应为 OpenGLES，推断）")
        return m
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
