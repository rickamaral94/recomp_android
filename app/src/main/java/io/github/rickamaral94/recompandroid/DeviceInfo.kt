// SPDX-License-Identifier: GPL-3.0-or-later
package io.github.rickamaral94.recompandroid

import android.os.Build

/** Device identity for report.json. Unknown values are empty strings, reported as null. */
data class DeviceInfo(
    val manufacturer: String,
    val model: String,
    val device: String,
    val release: String,
    val sdkInt: Int,
    val socManufacturer: String,
    val socModel: String,
    val hardware: String,
    val abis: List<String>,
) {
    fun toNativeFields(): Array<String> =
        arrayOf(manufacturer, model, device, release, socManufacturer, socModel, hardware)

    companion object {
        fun current(): DeviceInfo = DeviceInfo(
            manufacturer = Build.MANUFACTURER.orEmpty(),
            model = Build.MODEL.orEmpty(),
            device = Build.DEVICE.orEmpty(),
            release = Build.VERSION.RELEASE.orEmpty(),
            sdkInt = Build.VERSION.SDK_INT,
            // minSdk is 31, where SOC_* exist. "unknown" is Android's own placeholder.
            socManufacturer = Build.SOC_MANUFACTURER.orEmpty().takeUnless { it == Build.UNKNOWN }.orEmpty(),
            socModel = Build.SOC_MODEL.orEmpty().takeUnless { it == Build.UNKNOWN }.orEmpty(),
            hardware = Build.HARDWARE.orEmpty(),
            abis = Build.SUPPORTED_ABIS.toList(),
        )
    }
}
