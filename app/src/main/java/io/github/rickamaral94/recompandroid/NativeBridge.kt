// SPDX-License-Identifier: GPL-3.0-or-later
package io.github.rickamaral94.recompandroid

/** JNI surface of librecompandroid.so (app/src/main/cpp/jni_bridge.cpp). */
object NativeBridge {
    init {
        System.loadLibrary("recompandroid")
    }

    const val LOG_DEBUG = 0
    const val LOG_INFO = 1
    const val LOG_WARN = 2
    const val LOG_ERROR = 3

    external fun openLog(path: String): Boolean

    external fun log(level: Int, tag: String, message: String)

    /**
     * report.json as UTF-8. [deviceFields] order: manufacturer, model, device, release,
     * socManufacturer, socModel, hardware (see [DeviceInfo.toNativeFields]).
     */
    external fun buildReport(
        deviceFields: Array<String>,
        sdkInt: Int,
        abis: Array<String>,
        generatedAt: String,
    ): ByteArray
}
