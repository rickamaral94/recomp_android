// SPDX-License-Identifier: GPL-3.0-or-later
package io.github.rickamaral94.recompandroid

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.os.Process
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import java.io.File
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.concurrent.Executors

/**
 * M0 shell: shows the device/Vulkan summary and exports the diagnostic ZIP through the Storage
 * Access Framework (no root, no storage permission).
 */
class MainActivity : Activity() {
    private val worker = Executors.newSingleThreadExecutor()
    private lateinit var output: TextView
    private var pendingReport: ByteArray? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val logDir = File(getExternalFilesDir(null) ?: filesDir, "logs").apply { mkdirs() }
        NativeBridge.openLog(File(logDir, SESSION_LOG).path)
        NativeBridge.log(NativeBridge.LOG_INFO, "app", "start: commit ${BuildConfig.GIT_COMMIT} version ${BuildConfig.VERSION_NAME}")

        output = TextView(this).apply {
            setTextIsSelectable(true)
            setPadding(32, 32, 32, 32)
            text = getString(R.string.collecting)
        }
        val export = Button(this).apply {
            text = getString(R.string.export_diagnostics)
            setOnClickListener { startExport() }
        }
        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(export, ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
            addView(output)
        }
        setContentView(ScrollView(this).apply { addView(column) })

        worker.execute {
            val report = buildReport()
            runOnUiThread { output.text = report.toString(Charsets.UTF_8) }
        }
    }

    override fun onDestroy() {
        worker.shutdown()
        super.onDestroy()
    }

    private fun buildReport(): ByteArray {
        val device = DeviceInfo.current()
        val now = DateTimeFormatter.ISO_INSTANT.format(Instant.now().truncatedTo(java.time.temporal.ChronoUnit.SECONDS))
        return NativeBridge.buildReport(device.toNativeFields(), device.sdkInt, device.abis.toTypedArray(), now)
    }

    private fun startExport() {
        worker.execute {
            pendingReport = buildReport()
            val stamp = DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss").withZone(ZoneOffset.UTC).format(Instant.now())
            val intent = Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = "application/zip"
                putExtra(Intent.EXTRA_TITLE, DiagnosticBundle.fileName(stamp))
            }
            runOnUiThread {
                @Suppress("DEPRECATION")
                startActivityForResult(intent, REQUEST_EXPORT)
            }
        }
    }

    @Deprecated("Activity result API needs androidx; plain Activity keeps M0 dependency-free")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        @Suppress("DEPRECATION")
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != REQUEST_EXPORT) return
        val uri = data?.data
        val report = pendingReport
        if (resultCode != RESULT_OK || uri == null || report == null) return
        worker.execute {
            val result = runCatching {
                val logs = mutableMapOf<String, ByteArray>()
                val logDir = File(getExternalFilesDir(null) ?: filesDir, "logs")
                File(logDir, SESSION_LOG).takeIf { it.isFile }?.let { logs[SESSION_LOG] = it.readBytes() }
                ownLogcat()?.let { logs["logcat.txt"] = it }
                contentResolver.openOutputStream(uri)!!.use { DiagnosticBundle.write(it, report, logs) }
            }
            result.exceptionOrNull()?.let {
                NativeBridge.log(NativeBridge.LOG_ERROR, "export", "failed: $it")
            } ?: NativeBridge.log(NativeBridge.LOG_INFO, "export", "diagnostic ZIP written")
            runOnUiThread {
                val msg = if (result.isSuccess) R.string.export_done else R.string.export_failed
                Toast.makeText(this, msg, Toast.LENGTH_LONG).show()
            }
        }
    }

    /** This process's own logcat lines; readable without root. Null if logcat is unavailable. */
    private fun ownLogcat(): ByteArray? = runCatching {
        val p = ProcessBuilder("logcat", "-d", "-v", "threadtime", "--pid=${Process.myPid()}")
            .redirectErrorStream(true).start()
        val bytes = p.inputStream.use { it.readBytes() }
        p.waitFor()
        bytes
    }.getOrNull()

    private companion object {
        const val REQUEST_EXPORT = 1
        const val SESSION_LOG = "session.log"
    }
}
