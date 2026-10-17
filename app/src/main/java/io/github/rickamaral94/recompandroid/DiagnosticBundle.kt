// SPDX-License-Identifier: GPL-3.0-or-later
package io.github.rickamaral94.recompandroid

import java.io.OutputStream
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/**
 * The exportable diagnostic ZIP: report.json first, then readable logs. Pure JVM code so it is
 * unit-tested without a device. Never add game files, BIOS, firmware or keys here.
 */
object DiagnosticBundle {
    const val REPORT_ENTRY = "report.json"

    /** Logs larger than this are truncated from the front (the end of a log is what matters). */
    const val MAX_LOG_BYTES = 4 * 1024 * 1024

    fun write(out: OutputStream, reportJson: ByteArray, logs: Map<String, ByteArray>) {
        ZipOutputStream(out).use { zip ->
            zip.putNextEntry(ZipEntry(REPORT_ENTRY))
            zip.write(reportJson)
            zip.closeEntry()
            for ((name, bytes) in logs.toSortedMap()) {
                require(!name.startsWith("/") && !name.contains("..")) { "bad entry name: $name" }
                zip.putNextEntry(ZipEntry("logs/$name"))
                zip.write(tail(bytes))
                zip.closeEntry()
            }
        }
    }

    internal fun tail(bytes: ByteArray): ByteArray {
        if (bytes.size <= MAX_LOG_BYTES) return bytes
        val marker = "[... truncated ${bytes.size - MAX_LOG_BYTES} bytes ...]\n".toByteArray()
        return marker + bytes.copyOfRange(bytes.size - MAX_LOG_BYTES, bytes.size)
    }

    fun fileName(timestampCompact: String) = "recomp_android-diag-$timestampCompact.zip"
}
