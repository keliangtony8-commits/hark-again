package dev.assistant.assistant

import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.view.Display
import android.view.Surface
import android.view.SurfaceHolder
import android.view.SurfaceView
import android.view.View
import android.view.ViewGroup
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.util.WeakHashMap

// v3.5.2 高刷新率：Flyme/ColorOS/MIUI 对没声明的第三方 App 常默认给 60Hz（魅族 20 是 144Hz 屏），Flutter 引擎只跟系统给的 vsync 走。
// v3.5.4：真机自检（魅族 20）显示系统当前模式 60Hz、窗口请求 144Hz → Flyme 忽略了 preferredDisplayModeId。改成多管齐下，都做：
//   1) window.attributes.preferredDisplayModeId = 同分辨率最高刷的模式（API 23+）
//   2) window.attributes.preferredRefreshRate = 该最高 Hz（API 21+，部分 ROM 只认这个）
//   3) Flutter 的 SurfaceView 的 Surface.setFrameRate(maxHz, COMPATIBILITY_DEFAULT)（API 30+；API 31+ 用 CHANGE_FRAME_RATE_ALWAYS 重载）
// 时机：onCreate、onResume、onWindowFocusChanged(true)、Flutter SurfaceView 的 surfaceCreated / surfaceChanged 之后都重设
// （部分系统切后台 / 分屏 / 换 surface 后会把偏好重置）。系统仍可按省电策略降档，那是系统的决定。
// Flutter 3.47 引擎没有关于帧率的 AndroidManifest meta-data（io.flutter.embedding.android.* 里只有 Impeller / 调试类开关），所以不加。
class MainActivity : FlutterActivity() {
    /** 已挂过回调的 SurfaceView（弱引用，换 surface 后旧的自然释放）。 */
    private val hooked = WeakHashMap<SurfaceView, Boolean>()

    /** 最近一次 Surface.setFrameRate 的结果（自检读）。 */
    private var surfaceRateStatus = "未设"

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        requestHighestRefreshRate()
    }

    override fun onResume() {
        super.onResume()
        requestHighestRefreshRate()
        // FlutterSurfaceView 在 onStart/onResume 前后才挂上；下一帧再找一次
        window.decorView.post { requestHighestRefreshRate() }
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) requestHighestRefreshRate()
    }

    // v3.5.3 性能自检（lib/core/perf_probe.dart）：读系统当前显示模式、窗口请求的模式、Impeller 配置；
    // v3.5.4 加 refreshRate（滑动中每 200ms 采样系统当前刷新率）。只读，不改任何东西。
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "dev.assistant/perf").setMethodCallHandler { call, result ->
            when (call.method) {
                "display" -> try {
                    result.success(displayInfo())
                } catch (e: Exception) {
                    result.error("display", e.toString(), null)
                }
                "refreshRate" -> try {
                    val d = currentDisplay()
                    if (d == null) {
                        result.success(null)
                    } else {
                        val hz = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) d.mode.refreshRate else d.refreshRate
                        result.success(hz.toDouble())
                    }
                } catch (e: Exception) {
                    result.error("refreshRate", e.toString(), null)
                }
                else -> result.notImplemented()
            }
        }
    }

    @Suppress("DEPRECATION")
    private fun currentDisplay(): Display? =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) display else windowManager.defaultDisplay

    private fun displayInfo(): Map<String, Any?> {
        val m = HashMap<String, Any?>()
        val display = currentDisplay()
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
        val wantHz = window.attributes.preferredRefreshRate
        m["windowRefreshRate"] = if (wantHz > 0f) String.format("%.1f", wantHz) else "未设"
        m["surfaceFrameRate"] = surfaceRateStatus
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

    /** 同分辨率里刷新率最高的模式（API 23+）。 */
    private fun bestMode(): Display.Mode? {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return null
        val display = currentDisplay() ?: return null
        val current = display.mode
        return display.supportedModes
            .filter { it.physicalWidth == current.physicalWidth && it.physicalHeight == current.physicalHeight }
            .maxByOrNull { it.refreshRate }
    }

    private fun requestHighestRefreshRate() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return
        val best = try {
            bestMode()
        } catch (_: Exception) {
            null
        } ?: return // 拿不到显示模式（少数 ROM / 虚拟屏）就保持系统默认
        val maxHz = best.refreshRate
        // 招 1 + 招 2：窗口偏好（模式 id + 刷新率），有变化才写回，避免反复触发 relayout
        try {
            val attrs = window.attributes
            var changed = false
            if (attrs.preferredDisplayModeId != best.modeId) {
                attrs.preferredDisplayModeId = best.modeId
                changed = true
            }
            if (attrs.preferredRefreshRate != maxHz) {
                attrs.preferredRefreshRate = maxHz
                changed = true
            }
            if (changed) window.attributes = attrs
        } catch (_: Exception) {
        }
        // 招 3：Flutter 画面所在 Surface 的帧率投票
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            try {
                val sv = findSurfaceView(window.decorView)
                if (sv == null) {
                    surfaceRateStatus = "没找到 SurfaceView"
                } else {
                    hookSurface(sv)
                    applySurfaceFrameRate(sv.holder, maxHz)
                }
            } catch (e: Exception) {
                surfaceRateStatus = "失败：${e.javaClass.simpleName}"
            }
        } else {
            surfaceRateStatus = "系统低于 Android 11，不支持"
        }
    }

    /** 深度优先找第一个 SurfaceView（FlutterSurfaceView 继承自它）。 */
    private fun findSurfaceView(v: View): SurfaceView? {
        if (v is SurfaceView) return v
        if (v is ViewGroup) {
            for (i in 0 until v.childCount) {
                findSurfaceView(v.getChildAt(i))?.let { return it }
            }
        }
        return null
    }

    /** 在 surface 创建 / 变化之后重设（Flutter 自己的回调先注册，这里的在它之后跑）。 */
    private fun hookSurface(sv: SurfaceView) {
        if (hooked.containsKey(sv)) return
        hooked[sv] = true
        sv.holder.addCallback(object : SurfaceHolder.Callback {
            override fun surfaceCreated(holder: SurfaceHolder) {
                sv.post { requestHighestRefreshRate() }
            }

            override fun surfaceChanged(holder: SurfaceHolder, format: Int, width: Int, height: Int) {
                sv.post { requestHighestRefreshRate() }
            }

            override fun surfaceDestroyed(holder: SurfaceHolder) {}
        })
    }

    private fun applySurfaceFrameRate(holder: SurfaceHolder, hz: Float) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return
        val surface: Surface? = holder.surface
        if (surface == null || !surface.isValid) {
            surfaceRateStatus = "Surface 未就绪"
            return
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            surface.setFrameRate(hz, Surface.FRAME_RATE_COMPATIBILITY_DEFAULT, Surface.CHANGE_FRAME_RATE_ALWAYS)
            surfaceRateStatus = "${hz.toInt()}Hz（ALWAYS）"
        } else {
            surface.setFrameRate(hz, Surface.FRAME_RATE_COMPATIBILITY_DEFAULT)
            surfaceRateStatus = "${hz.toInt()}Hz"
        }
    }
}
